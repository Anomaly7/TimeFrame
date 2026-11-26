import os

# Plain-http OAuth callbacks are only allowed when explicitly running locally.
if os.getenv("ALLOW_INSECURE_OAUTH") == "1":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

from urllib.parse import quote
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from starlette.responses import RedirectResponse
from app.availability import parse_event, find_free_time, PST
from app.auth_utils import (REMEMBER_TTL_SECONDS, SHORT_TTL_SECONDS, create_oauth_state, clean_text, create_session_token, is_banned, BANNED_DETAIL,
                            get_current_user, oauth_state_app_redirect, safe_app_redirect, verify_oauth_state)
from datetime import datetime, time, timedelta
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from app.db import conn
from app.busy_store import insert_busy_rows


router = APIRouter()

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://www.timeframecalender.com").rstrip("/")
STATE_COOKIE = "oauth_nonce"

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

def get_flow():
    return Flow.from_client_config(
        {
            "web": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [os.getenv("REDIRECT_URI")]
            }
        },
        scopes=SCOPES,
        # /auth/login and /auth/callback are separate requests, each building
        # a fresh Flow, so there's no way to carry a PKCE code_verifier
        # between them. This is a confidential client (has a client_secret),
        # so PKCE isn't required — disable it rather than losing the verifier.
        autogenerate_code_verifier=False
    )

def blocks_time(event) -> bool:
    """Whether a Google event really makes you busy. Skips events shown as
    "Free" (transparent - e.g. reminders, holidays, all-day notes), Google's
    all-day "Working location" markers, and invitations you declined."""
    if event.get("transparency") == "transparent":
        return False
    if event.get("eventType") == "workingLocation":
        return False
    # All-day events (no time of day) don't block time (Sam, 2026-11-20).
    if "dateTime" not in (event.get("start") or {}):
        return False
    for attendee in event.get("attendees") or []:
        if attendee.get("self") and attendee.get("responseStatus") == "declined":
            return False
    return True


# Google's built-in "Holidays in ..." and "Birthdays" calendars never make you busy.
SKIP_CALENDAR_SUFFIXES = ("#holiday@group.v.calendar.google.com", "#contacts@group.v.calendar.google.com")


def calendars_to_import(service) -> list:
    """IDs of the calendars to import: every calendar shown (checked) in the user's
    Google Calendar, plus the main one. Falls back to just the main calendar if the
    list can't be read."""
    ids, page_token = [], None
    try:
        while True:
            res = service.calendarList().list(
                pageToken=page_token, minAccessRole="reader",
                fields="nextPageToken,items(id,primary,selected,hidden)",
            ).execute()
            for cal in res.get("items", []):
                cid = cal.get("id", "")
                if cal.get("primary"):
                    continue  # added first below, as "primary"
                if cal.get("hidden") or not cal.get("selected") or cid.endswith(SKIP_CALENDAR_SUFFIXES):
                    continue
                ids.append(cid)
            page_token = res.get("nextPageToken")
            if not page_token:
                break
    except Exception:
        ids = []
    return ["primary"] + ids


def list_calendar_events(service, calendar_id, time_min, time_max) -> list:
    # A year of (singleEvents-expanded) events can span many pages - Google caps
    # each page at maxResults, so keep following nextPageToken until it's exhausted.
    events, page_token = [], None
    while True:
        res = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=2500,
            pageToken=page_token,
            # Only the times plus what's needed to tell if the time is really
            # busy - never titles, descriptions, other attendees or links
            # (busy blocks only show whose they are). attendees(self,
            # responseStatus) returns only *your* RSVP, no one else's email.
            fields="nextPageToken,items(start,end,transparency,eventType,attendees(self,responseStatus))",
        ).execute()
        events.extend(res.get("items", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            return events


def event_key(event) -> tuple:
    start, end = event.get("start") or {}, event.get("end") or {}
    return (start.get("dateTime") or start.get("date"), end.get("dateTime") or end.get("date"))


@router.get("/auth/login")
def login(app_redirect: str | None = None, consent: bool = False):
    flow = get_flow()
    flow.redirect_uri = os.getenv("REDIRECT_URI")

    # From the phone app: hand the finished sign-in back to the app (see safe_app_redirect).
    app_target = safe_app_redirect(app_redirect)
    if app_redirect and not app_target:
        raise HTTPException(status_code=400, detail="That app address isn't allowed.")
    state, nonce = create_oauth_state(app_target)
    # Always show Google's account chooser, so after signing out you can pick a different Google account
    # (without it Google silently reuses the last one; Sam, 2026-11-26). "Turn on auto-sync" also needs the
    # consent screen, since Google only hands out a refresh token there.
    extra = {"prompt": "select_account consent" if consent else "select_account"}
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=state,
        **extra,
    )

    response = RedirectResponse(auth_url)
    # Only this browser can finish the sign-in it started (see verify_oauth_state).
    response.set_cookie(STATE_COOKIE, nonce, max_age=600, httponly=True, secure=True, samesite="lax", path="/auth")
    return response

@router.get("/auth/callback")
def callback(request: Request):
    state = request.query_params.get("state")
    if not verify_oauth_state(state, request.cookies.get(STATE_COOKIE)):
        return RedirectResponse(f"{FRONTEND_URL}/#auth_error=" + quote("Sign-in expired or was started elsewhere. Please try again."))
    # Where the result goes: the website, or the phone app that started the sign-in.
    back_to = oauth_state_app_redirect(state) or f"{FRONTEND_URL}/"
    if request.query_params.get("error"):
        return RedirectResponse(f"{back_to}#auth_error=" + quote("Google sign-in was cancelled."))

    flow = get_flow()
    flow.redirect_uri = os.getenv("REDIRECT_URI")

    # Behind Render's proxy the app sees http://; Google redirected to https://.
    callback_url = str(request.url)
    if request.headers.get("x-forwarded-proto") == "https" and callback_url.startswith("http://"):
        callback_url = "https://" + callback_url[len("http://"):]
    try:
        flow.fetch_token(authorization_response=callback_url)
    except Exception:
        return RedirectResponse(f"{back_to}#auth_error=" + quote("Google sign-in failed. Please try again."))
    credentials = flow.credentials

    # Speed (Sam, 2026-11-26): only confirm who this is here, then send the browser straight back to the app's loading
    # screen. The calendar import runs in the background (next 5 weeks first, then the rest of the year) and the
    # site polls /auth/import-status, instead of the person staring at Google's page while a year of events loads.
    try:
        user_id = _sign_in_google(credentials)
    except _Banned:
        return RedirectResponse(f"{back_to}#auth_error=" + quote(BANNED_DETAIL))
    except Exception:
        return RedirectResponse(f"{back_to}#auth_error=" + quote("Couldn't read your Google Calendar. Please try again."))
    start_import(user_id, credentials)

    token = create_session_token(user_id)
    # In the #fragment, not the ?query: fragments are never sent to servers,
    # so the token doesn't land in Vercel's logs or Referer headers.
    response = RedirectResponse(f"{back_to}#user={quote(user_id)}&token={quote(token)}&importing=1")
    response.delete_cookie(STATE_COOKIE, path="/auth")
    return response


class _Banned(Exception):
    pass


def _sign_in_google(credentials) -> str:
    """Who this is (one Google call), saved as a verified account, plus the refresh token for auto-sync."""
    from app.google_sync import save_refresh_token
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    email = service.calendarList().get(calendarId="primary").execute()["id"]
    if is_banned(email):
        raise _Banned()
    _save_user(email)
    save_refresh_token(email, getattr(credentials, "refresh_token", None))
    conn.commit()
    return email


def _save_user(email: str) -> None:
    # Google has just proven this person owns the address. If someone else
    # had already signed up with it by email/password (never verified),
    # remove that password so they can't sign in and read this calendar.
    conn.execute(
        """INSERT INTO users (id, email, email_verified) VALUES (?, ?, TRUE)
           ON CONFLICT (id) DO UPDATE SET
             password_hash = CASE WHEN users.email_verified THEN users.password_hash ELSE NULL END,
             email_verified = TRUE""",
        (email, email)
    )
    conn.commit()


# ---- background import + status (kept in memory: one server) ----
IMPORTS: dict = {}
IMPORT_IN_BACKGROUND = True  # the tests turn this off so they can check the result straight away
_imports_lock = threading.Lock()


def _set_import(user_id: str, **state) -> None:
    key = user_id.strip().lower()
    with _imports_lock:
        IMPORTS[key] = {**IMPORTS.get(key, {}), **state, "at": _time.time()}


def start_import(user_id: str, credentials, background: bool | None = None) -> None:
    background = IMPORT_IN_BACKGROUND if background is None else background
    _set_import(user_id, state="running", ready=False, imported=0, error=None)

    def run():
        try:
            today = datetime.now(PST).date()
            first = (today - timedelta(days=7), today + timedelta(days=35))
            n = _write_google(user_id, fetch_google_busy(credentials, *first), *first)
            _set_import(user_id, ready=True, imported=n)  # the app can open now
            full = (today - timedelta(days=7), today + timedelta(days=366))
            busy = fetch_google_busy(credentials, *full)
            # The full pass replaces everything from Google (same as a re-sync), so nothing is ever doubled up.
            conn.execute("DELETE FROM busy_times WHERE user_id = ? AND source = 'google'", (user_id,))
            n = _write_google(user_id, busy, *full)
            from app.google_sync import mark_synced
            mark_synced(user_id, "google")
            conn.commit()
            _set_import(user_id, state="done", ready=True, imported=n)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"Google import failed for a user: {type(e).__name__}", flush=True)
            _set_import(user_id, state="error", ready=True, error="Couldn't read your Google Calendar. Try Sync now.")

    if background:
        threading.Thread(target=run, daemon=True).start()
    else:
        run()


@router.get("/auth/import-status")
def import_status(user_id: str = Depends(get_current_user)):
    with _imports_lock:
        st = dict(IMPORTS.get(user_id.strip().lower()) or {})
    if not st:
        return {"state": "none", "ready": True}
    return {"state": st["state"], "ready": st.get("ready", True), "imported": st.get("imported", 0), "error": st.get("error")}


def fetch_google_busy(credentials, day_from, day_to) -> list:
    """Busy blocks from every calendar the person has turned on, read in parallel (one API client per thread:
    Google's client isn't thread-safe)."""
    time_min = datetime.combine(day_from, time.min, tzinfo=PST).isoformat()
    time_max = datetime.combine(day_to, time.max, tzinfo=PST).isoformat()
    ids = calendars_to_import(build("calendar", "v3", credentials=credentials, cache_discovery=False))

    def one(calendar_id):
        svc = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        try:
            return calendar_id, list_calendar_events(svc, calendar_id, time_min, time_max)
        except Exception:
            if calendar_id == "primary":
                raise
            return calendar_id, []  # a calendar we can't read (shared as free/busy only) must not stop the rest

    with ThreadPoolExecutor(max_workers=min(6, len(ids) or 1)) as pool:
        results = dict(pool.map(one, ids))
    # The same event can sit on two calendars (an invite copied to a shared calendar): keep one copy.
    events, seen_elsewhere = [], set()
    for calendar_id in ids:
        cal_events = results.get(calendar_id, [])
        events.extend(e for e in cal_events if event_key(e) not in seen_elsewhere)
        seen_elsewhere.update(event_key(e) for e in cal_events)
    return [parse_event(e) for e in events if blocks_time(e)]


def _write_google(user_id: str, busy: list, day_from, day_to) -> int:
    """Replaces this person's Google busy times overlapping [day_from, day_to] (text dates) with what Google just
    returned for that range (Google returns every event overlapping it)."""
    lo, hi = day_from.isoformat(), day_to.isoformat()
    conn.execute(
        "DELETE FROM busy_times WHERE user_id = ? AND source = 'google' AND substr(end_time, 1, 10) >= ? AND substr(start, 1, 10) <= ?",
        (user_id, lo, hi))
    rows = [(user_id, a.isoformat(), b.isoformat(), "google", tz, None) for a, b, tz, _t in busy]
    insert_busy_rows(rows)
    conn.commit()
    return len(rows)


def import_google_events(credentials, expect_user=None) -> str:
    """Full re-sync (auto-sync / Sync now): saves the user and a year of their Google busy times; returns their id.
    expect_user: the account the stored token belongs to; anything else is refused rather than written elsewhere."""
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    email = service.calendarList().get(calendarId="primary").execute()["id"]
    if expect_user is not None and email.strip().lower() != expect_user.strip().lower():
        raise RuntimeError("Stored Google token belongs to a different account")
    if is_banned(email):
        raise _Banned()
    _save_user(email)
    today = datetime.now(PST).date()
    days = (today - timedelta(days=7), today + timedelta(days=366))
    busy = fetch_google_busy(credentials, *days)
    conn.execute("DELETE FROM busy_times WHERE user_id = ? AND source = 'google'", (email,))
    _write_google(email, busy, *days)
    from app.google_sync import mark_synced
    mark_synced(email, "google")
    conn.commit()
    return email


@router.get("/auth/status")
def google_status(user_id: str = Depends(get_current_user)):
    row = conn.execute(
        "SELECT 1 FROM busy_times WHERE user_id = ? AND source = 'google' LIMIT 1",
        (user_id,)
    ).fetchone()
    from app.google_sync import auto_sync_available, has_token, resync_in_background, stale, sync_info
    auto = has_token(user_id)
    # Opening the app re-syncs stale Google data in the background (the server sleeps between visits).
    if row is not None and auto and stale(user_id):
        resync_in_background(user_id)
    return {"connected": row is not None, "auto_sync": auto, "auto_sync_available": auto_sync_available(),
            **sync_info(user_id, "google")}

@router.post("/auth/disconnect")
def disconnect_google(user_id: str = Depends(get_current_user)):
    from app.google_sync import forget_token
    forget_token(user_id)
    conn.execute("DELETE FROM calendar_sync WHERE user_id = ? AND source = 'google'", (user_id.strip().lower(),))
    conn.execute(
        "DELETE FROM busy_times WHERE user_id = ? AND source = 'google'",
        (user_id,)
    )
    conn.commit()

    return {"disconnected": True}

def default_name(user_id: str) -> str:
    return user_id.split("@")[0]


@router.post("/auth/refresh")
def refresh_session(remember: bool = True, user_id: str = Depends(get_current_user)):
    """Swap a still-valid session token for a fresh one. With "Remember me" on the
    app calls this on every visit, so someone who keeps using TimeFrame (or the
    extension) stays signed in; only 90 days of not opening it signs them out."""
    ttl = REMEMBER_TTL_SECONDS if remember else SHORT_TTL_SECONDS
    return {"token": create_session_token(user_id, ttl), "expires_in": ttl}


@router.get("/auth/me")
def me(user_id: str = Depends(get_current_user)):
    row = conn.execute(
        "SELECT email, display_name FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    return {
        "email": row[0] if row else None,
        "name": (row[1] if row else None) or default_name(user_id),
        "custom_name": bool(row and row[1]),
        "guest": user_id.strip().lower().endswith("@guest.timeframecalender.com"),
    }


@router.post("/auth/name")
def set_name(body: dict = Body(...), user_id: str = Depends(get_current_user)):
    """The name group members see on your blocks. Blank = back to the
    default (the part of your email before the @)."""
    name = clean_text(body.get("name"), 40)
    conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (name or None, user_id))
    conn.commit()
    return {"name": name or default_name(user_id), "custom_name": bool(name)}

@router.post("/auth/logout")
def logout(user_id: str = Depends(get_current_user)):
    """Signing out of one device keeps your calendar: it used to delete your Google busy times, so signing out
    on a phone made you look free to every group until you signed in with Google again (fixed 2026-11-25).
    Removing Google data is "Disconnect" (/auth/disconnect); deleting everything is account deletion."""
    return {"logged_out": True}
