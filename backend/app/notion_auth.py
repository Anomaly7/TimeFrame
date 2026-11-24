"""Notion: sign in with Notion, or connect it to an existing TimeFrame account,
and import busy times from the Notion databases the user shares with TimeFrame.

Notion has no calendar API (Notion Calendar is Google/Outlook underneath), so
"busy" here means pages in a shared database with a *timed* date property
(e.g. a schedule, meetings or a planner database). Date-only entries
(deadlines, to-dos) don't block time and are skipped.

Like the Google import this is a one-shot sync: the Notion access token is
used during the callback and never stored. "Reconnect" re-imports.

Setup (Notion side): notion.so/profile/integrations > New integration >
type Public, capabilities "Read content" + "Read user information including
email addresses", redirect URI https://<api-host>/notion/callback. Then set
NOTION_CLIENT_ID, NOTION_CLIENT_SECRET and NOTION_REDIRECT_URI on the API.
"""
import base64
import json
import os
import secrets
import time as _time
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import RedirectResponse

from app.auth_utils import ALGORITHM, _secret, create_session_token, get_current_user, is_banned, BANNED_DETAIL
from app.busy_store import insert_busy_rows, is_linked, mark_linked, unlink
from app.calendar_import import PST
from app.db import conn

router = APIRouter()

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://www.timeframecalender.com").rstrip("/")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
STATE_COOKIE = "notion_nonce"
STATE_TTL = 600
TICKET_TTL = 120
MAX_DATABASES = 50
MAX_PAGES = 5000
DEFAULT_MINUTES = 60  # a timed entry with no end time
TIMEOUT = 20


def _config():
    cid, secret, redirect = (os.getenv("NOTION_CLIENT_ID"), os.getenv("NOTION_CLIENT_SECRET"),
                             (os.getenv("NOTION_REDIRECT_URI") or os.getenv("NOTION_REDIRECT_URL")))
    if not (cid and secret and redirect):
        return None
    return cid, secret, redirect


def _error(message: str) -> RedirectResponse:
    response = RedirectResponse(f"{FRONTEND_URL}/#auth_error=" + quote(message))
    response.delete_cookie(STATE_COOKIE, path="/notion")
    return response


# ---- Linking to an account that's already signed in ----
# A browser redirect can't carry the Bearer token, and a session token must
# never go in a URL (it would land in server logs). So the signed-in page asks
# for a short-lived ticket that can do one thing only: start a Notion link
# for that user.
# Public: lets the page hide the Notion buttons until NOTION_CLIENT_ID / _SECRET / _REDIRECT_URI are set.
@router.get("/notion/available")
def notion_available():
    return {"available": _config() is not None}


@router.post("/notion/link-ticket")
def link_ticket(user_id: str = Depends(get_current_user)):
    ticket = jwt.encode({"sub": user_id, "exp": int(_time.time()) + TICKET_TTL, "typ": "notion_ticket"},
                        _secret(), algorithm=ALGORITHM)
    return {"ticket": ticket}


def _ticket_user(ticket: str | None) -> str | None:
    if not ticket:
        return None
    try:
        payload = jwt.decode(ticket, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload.get("sub") if payload.get("typ") == "notion_ticket" else None


@router.get("/notion/login")
def notion_login(ticket: str | None = None):
    cfg = _config()
    if not cfg:
        return _error("Notion sign-in isn't set up on this server yet.")
    client_id, _, redirect_uri = cfg
    link_user = _ticket_user(ticket)
    if ticket and not link_user:
        return _error("That Notion link expired. Please try again.")

    nonce = secrets.token_urlsafe(16)
    state = jwt.encode({"nonce": nonce, "link": link_user, "exp": int(_time.time()) + STATE_TTL,
                        "typ": "notion_state"}, _secret(), algorithm=ALGORITHM)
    url = "https://api.notion.com/v1/oauth/authorize?" + urlencode({
        "client_id": client_id, "response_type": "code", "owner": "user",
        "redirect_uri": redirect_uri, "state": state,
    })
    response = RedirectResponse(url)
    # Only this browser can finish the sign-in it started (stops login CSRF).
    response.set_cookie(STATE_COOKIE, nonce, max_age=STATE_TTL, httponly=True, secure=True,
                        samesite="lax", path="/notion")
    return response


def _state(state: str | None, cookie_nonce: str | None):
    """The verified state payload, or None."""
    if not state or not cookie_nonce:
        return None
    try:
        payload = jwt.decode(state, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "notion_state" or not secrets.compare_digest(payload.get("nonce", ""), cookie_nonce):
        return None
    return payload


# ---- Notion API ----
def _http(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        raise NotionError(e.code)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise NotionError(0)


class NotionError(Exception):
    def __init__(self, status: int):
        self.status = status


def exchange_code(code: str) -> dict:
    client_id, client_secret, redirect_uri = _config()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return _http(f"{NOTION_API}/oauth/token",
                 {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
                 {"Authorization": "Basic " + basic})


def notion_post(token: str, path: str, body: dict) -> dict:
    return _http(f"{NOTION_API}{path}", body,
                 {"Authorization": "Bearer " + token, "Notion-Version": NOTION_VERSION})


def _paged(token: str, path: str, body: dict, limit: int):
    cursor, count = None, 0
    while True:
        res = notion_post(token, path, {**body, "page_size": 100, **({"start_cursor": cursor} if cursor else {})})
        for item in res.get("results", []):
            yield item
            count += 1
            if count >= limit:
                return
        cursor = res.get("next_cursor")
        if not res.get("has_more") or not cursor:
            return


def _parse(value: str, tz_name: str | None):
    """A Notion date string -> aware datetime, or None for a date-only value."""
    if not value or "T" not in value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tz_name) if tz_name else PST)
        except Exception:
            dt = dt.replace(tzinfo=PST)
    return dt.astimezone(PST)


def notion_busy(token: str, window_start: date, window_end: date) -> list:
    """(start, end) datetimes from every timed date in the shared databases."""
    busy, pages = [], 0
    databases = _paged(token, "/search", {"filter": {"property": "object", "value": "database"}}, MAX_DATABASES)
    for db in databases:
        date_props = [name for name, prop in (db.get("properties") or {}).items() if prop.get("type") == "date"]
        for prop in date_props:
            query = {"filter": {"and": [
                {"property": prop, "date": {"on_or_after": window_start.isoformat()}},
                {"property": prop, "date": {"on_or_before": window_end.isoformat()}},
            ]}}
            try:
                results = list(_paged(token, f"/databases/{db['id']}/query", query, MAX_PAGES - pages))
            except NotionError:
                continue  # one database we can't query must not stop the others
            pages += len(results)
            for page in results:
                value = ((page.get("properties") or {}).get(prop) or {}).get("date") or {}
                start = _parse(value.get("start"), value.get("time_zone"))
                if start is None:
                    continue
                end = _parse(value.get("end"), value.get("time_zone")) or start + timedelta(minutes=DEFAULT_MINUTES)
                if end > start:
                    busy.append((start, end))
            if pages >= MAX_PAGES:
                return busy
    return busy


def notion_email(token_response: dict) -> str | None:
    owner = token_response.get("owner") or {}
    user = owner.get("user") or {}
    email = ((user.get("person") or {}).get("email") or "").strip().lower()
    return email or None


@router.get("/notion/callback")
def notion_callback(request: Request):
    state = _state(request.query_params.get("state"), request.cookies.get(STATE_COOKIE))
    if not state:
        return _error("Sign-in expired or was started elsewhere. Please try again.")
    if request.query_params.get("error") or not request.query_params.get("code"):
        return _error("Notion sign-in was cancelled.")
    if not _config():
        return _error("Notion sign-in isn't set up on this server yet.")

    try:
        token_response = exchange_code(request.query_params["code"])
    except NotionError:
        return _error("Notion sign-in failed. Please try again.")
    token = token_response.get("access_token")
    if not token:
        return _error("Notion sign-in failed. Please try again.")

    user_id = state.get("link")
    if not user_id:
        # Signing in with Notion: the account is the Notion email.
        email = notion_email(token_response)
        if not email:
            return _error("Notion didn't share your email. Sign in another way, then connect Notion.")
        if is_banned(email):
            return _error(BANNED_DETAIL)
        row = conn.execute("SELECT password_hash, email_verified FROM users WHERE id = ?", (email,)).fetchone()
        if row and row[0] and not row[1]:
            # Someone made a password account with this email that was never
            # verified. Don't merge into it (whoever set that password could
            # then read this person's Notion schedule).
            return _error("An account with this email already uses a password. Sign in with it, then connect Notion.")
        if not row:
            conn.execute("INSERT INTO users (id, email, email_verified) VALUES (?, ?, FALSE)", (email, email))
        user_id = email

    today = datetime.now(PST).date()
    try:
        busy = notion_busy(token, today - timedelta(days=7), today + timedelta(days=366))
    except NotionError:
        return _error("Couldn't read your Notion databases. Please try again.")

    seen, rows = set(), []
    for start, end in busy:
        key = (start.isoformat(), end.isoformat())
        if key not in seen:
            seen.add(key)
            rows.append((user_id, key[0], key[1], "notion", str(PST), None))

    conn.execute("DELETE FROM busy_times WHERE user_id = ? AND source = 'notion'", (user_id,))
    insert_busy_rows(rows)
    mark_linked(user_id, "notion")
    conn.commit()

    session = create_session_token(user_id)
    response = RedirectResponse(f"{FRONTEND_URL}/#user={quote(user_id)}&token={quote(session)}&notion={len(rows)}")
    response.delete_cookie(STATE_COOKIE, path="/notion")
    return response


@router.get("/notion/status")
def notion_status(user_id: str = Depends(get_current_user)):
    return {"connected": is_linked(user_id, "notion"), "available": _config() is not None}


@router.post("/notion/disconnect")
def disconnect_notion(user_id: str = Depends(get_current_user)):
    conn.execute("DELETE FROM busy_times WHERE user_id = ? AND source = 'notion'", (user_id,))
    unlink(user_id, "notion")
    conn.commit()
    return {"disconnected": True}
