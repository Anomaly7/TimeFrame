"""Apple Calendar (iCloud) via CalDAV.

Apple has no OAuth for calendars: third-party apps sign in to iCloud's CalDAV
server with the Apple ID email plus an *app-specific password* (made at
account.apple.com > Sign-In and Security > App-Specific Passwords). It can only
read/write calendars and contacts, never the Apple account itself, and the user
can revoke it there at any time.

Like the Google import, this is a one-shot sync: the password is used for this
one request to read busy times and is never stored. "Reconnect" re-imports.
"""
import base64
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urljoin, urlparse

import icalendar
import recurring_ical_events
from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.auth_utils import RateLimiter, check_not_banned, client_ip, create_session_token, get_current_user
from app.busy_store import insert_busy_rows, is_linked, mark_linked, unlink
from app.calendar_import import MAX_EVENTS, PST, event_rows
from app.db import conn

router = APIRouter()

ICLOUD_CALDAV = "https://caldav.icloud.com/"
MAX_CALENDARS = 30
TIMEOUT = 20
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}

# Each attempt is a sign-in to Apple through our server: keep guessing slow.
apple_limiter = RateLimiter(max_attempts=5, window_seconds=600)


class AppleAuthError(Exception):
    pass


def _allowed(url: str) -> bool:
    """Credentials only ever go to Apple's own CalDAV servers over https
    (the calendar home can live on e.g. p42-caldav.icloud.com)."""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host == "icloud.com" or host.endswith(".icloud.com"))


def _request(method: str, url: str, auth: str, body: str, depth: str):
    """One CalDAV request -> (final url, response bytes). Follows redirects
    by hand (urllib won't for PROPFIND/REPORT), only within icloud.com."""
    for _ in range(4):
        if not _allowed(url):
            raise HTTPException(status_code=502, detail="Apple Calendar answered from an unexpected address.")
        req = urllib.request.Request(url, data=body.encode(), method=method, headers={
            "Authorization": "Basic " + auth,
            "Depth": depth,
            "Content-Type": "application/xml; charset=utf-8",
            "User-Agent": "TimeFrame/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
                return url, res.read()
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 307, 308) and e.headers.get("Location"):
                url = urljoin(url, e.headers["Location"])
                continue
            if e.code in (401, 403):
                raise AppleAuthError()
            raise HTTPException(status_code=502, detail="Apple Calendar didn't answer. Try again in a minute.")
        except (urllib.error.URLError, TimeoutError, OSError):
            raise HTTPException(status_code=502, detail="Couldn't reach Apple Calendar. Try again in a minute.")
    raise HTTPException(status_code=502, detail="Apple Calendar redirected too many times.")


def _xml(data: bytes):
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise HTTPException(status_code=502, detail="Apple Calendar sent a reply TimeFrame couldn't read.")


def _href(root, path: str):
    el = root.find(path, NS)
    return el.text.strip() if el is not None and el.text else None


def find_calendars(auth: str) -> list:
    """URLs of the user's event calendars (not reminders/to-do lists)."""
    url, data = _request("PROPFIND", ICLOUD_CALDAV, auth, (
        '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>'), "0")
    principal = _href(_xml(data), ".//d:current-user-principal/d:href")
    if not principal:
        raise HTTPException(status_code=502, detail="Apple Calendar didn't say where your calendars are.")

    url, data = _request("PROPFIND", urljoin(url, principal), auth, (
        '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        '<d:prop><c:calendar-home-set/></d:prop></d:propfind>'), "0")
    home = _href(_xml(data), ".//c:calendar-home-set/d:href")
    if not home:
        raise HTTPException(status_code=502, detail="Apple Calendar didn't say where your calendars are.")

    url, data = _request("PROPFIND", urljoin(url, home), auth, (
        '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        '<d:prop><d:resourcetype/><c:supported-calendar-component-set/></d:prop></d:propfind>'), "1")
    calendars = []
    for resp in _xml(data).findall("d:response", NS):
        href = _href(resp, "d:href")
        if not href or resp.find(".//d:resourcetype/c:calendar", NS) is None:
            continue
        comps = {c.get("name") for c in resp.findall(".//c:supported-calendar-component-set/c:comp", NS)}
        if comps and "VEVENT" not in comps:
            continue  # a Reminders list, not a calendar
        calendars.append(urljoin(url, href))
    return calendars[:MAX_CALENDARS]


def calendar_events(auth: str, cal_url: str, window_start: datetime, window_end: datetime) -> list:
    """Expanded VEVENTs from one calendar that overlap the window."""
    fmt = "%Y%m%dT%H%M%SZ"
    start_utc = window_start.astimezone(timezone.utc).strftime(fmt)
    end_utc = window_end.astimezone(timezone.utc).strftime(fmt)
    _, data = _request("REPORT", cal_url, auth, (
        '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        '<d:prop><c:calendar-data/></d:prop>'
        '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
        f'<c:time-range start="{start_utc}" end="{end_utc}"/>'
        '</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>'), "1")
    events = []
    for el in _xml(data).findall(".//c:calendar-data", NS):
        if not el.text:
            continue
        try:
            cal = icalendar.Calendar.from_ical(el.text)
            events.extend(recurring_ical_events.of(cal).between(window_start, window_end))
        except Exception:
            continue  # one unreadable event must not stop the rest
        if len(events) >= MAX_EVENTS:
            break
    return events


def _credentials(body: dict):
    apple_id = str(body.get("apple_id") or "").strip()
    # Apple shows app-specific passwords as xxxx-xxxx-xxxx-xxxx; spaces are a common paste slip.
    password = str(body.get("app_password") or "").strip().replace(" ", "")
    if not apple_id or len(apple_id) > 254 or not password or len(password) > 64:
        raise HTTPException(status_code=400, detail="Enter your Apple ID email and an app-specific password.")
    return apple_id, password


def _read_apple(apple_id: str, password: str) -> list:
    """Every event in the user's iCloud calendars for the sync window. Raises 401 if Apple rejects the login."""
    auth = base64.b64encode(f"{apple_id}:{password}".encode()).decode()
    today = datetime.now(PST).date()
    window_start = datetime.combine(today - timedelta(days=7), time.min, tzinfo=PST)
    window_end = datetime.combine(today + timedelta(days=366), time.max, tzinfo=PST)
    try:
        events = []
        for cal_url in find_calendars(auth):
            try:
                events.extend(calendar_events(auth, cal_url, window_start, window_end))
            except HTTPException:
                continue  # e.g. a shared calendar we can't read: import the others
        return events
    except AppleAuthError:
        raise HTTPException(status_code=401, detail=(
            "Apple didn't accept that. Use your Apple ID email and an app-specific password "
            "(not your normal Apple ID password)."))


def _save_apple(user_id: str, events: list) -> int:
    rows, seen = [], set()
    for row in event_rows(events, user_id, "apple", skip_free=True):
        if (row[1], row[2]) not in seen:  # the same event on two calendars counts once
            seen.add((row[1], row[2]))
            rows.append(row)
    conn.execute("DELETE FROM busy_times WHERE user_id = ? AND source = 'apple'", (user_id,))
    insert_busy_rows(rows)
    mark_linked(user_id, "apple")
    conn.commit()
    return len(rows)


@router.post("/apple/connect")
def connect_apple(request: Request, body: dict = Body(...), user_id: str = Depends(get_current_user)):
    apple_id, password = _credentials(body)
    apple_limiter.check("ip:" + client_ip(request), "user:" + user_id)
    return {"imported": _save_apple(user_id, _read_apple(apple_id, password))}


# Signing in with Apple (from the sign-in page). If iCloud accepts the Apple ID + app-specific password, that
# proves the person controls that Apple account, the same proof a Google sign-in gives, so the account is the
# Apple ID email. Same rule as Notion sign-in: never merge into a password account whose email was never verified.
@router.post("/apple/login")
def login_apple(request: Request, body: dict = Body(...)):
    apple_id, password = _credentials(body)
    email = apple_id.lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Use the email address of your Apple ID.")
    apple_limiter.check("ip:" + client_ip(request), "user:" + email)
    check_not_banned(email)
    events = _read_apple(apple_id, password)

    row = conn.execute("SELECT password_hash, email_verified FROM users WHERE id = ?", (email,)).fetchone()
    if row and row[0] and not row[1]:
        raise HTTPException(status_code=409, detail=(
            "An account with this email already uses a password. Sign in with it, then connect Apple Calendar."))
    if not row:
        conn.execute("INSERT INTO users (id, email, email_verified) VALUES (?, ?, FALSE)", (email, email))
    imported = _save_apple(email, events)
    return {"token": create_session_token(email), "email": email, "imported": imported}


@router.get("/apple/status")
def apple_status(user_id: str = Depends(get_current_user)):
    return {"connected": is_linked(user_id, "apple")}


@router.post("/apple/disconnect")
def disconnect_apple(user_id: str = Depends(get_current_user)):
    conn.execute("DELETE FROM busy_times WHERE user_id = ? AND source = 'apple'", (user_id,))
    unlink(user_id, "apple")
    conn.commit()
    return {"disconnected": True}
