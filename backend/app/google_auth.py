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
def login(app_redirect: str | None = None):
    flow = get_flow()
    flow.redirect_uri = os.getenv("REDIRECT_URI")

    # From the phone app: hand the finished sign-in back to the app (see safe_app_redirect).
    app_target = safe_app_redirect(app_redirect)
    if app_redirect and not app_target:
        raise HTTPException(status_code=400, detail="That app address isn't allowed.")
    state, nonce = create_oauth_state(app_target)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=state,
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

    service = build("calendar", "v3", credentials=credentials)

    # A full year out (plus a week back) so Month view has real data
    # whenever the user navigates within the synced range, not just the
    # current week.
    today = datetime.now(PST).date()
    now = datetime.combine(today - timedelta(days=7), time.min, tzinfo=PST).isoformat()
    end = datetime.combine(today + timedelta(days=366), time.max, tzinfo=PST).isoformat()

    # Use calendar account email as user identity
    calendar = build("calendar", "v3", credentials=credentials)

    calendar_info = calendar.calendarList().get(calendarId="primary").execute()
    email = calendar_info["id"]   # usually the email
    user_id = email               # simple + stable
    if is_banned(email):
        return RedirectResponse(f"{back_to}#auth_error=" + quote(BANNED_DETAIL))


    # Google has just proven this person owns the address. If someone else
    # had already signed up with it by email/password (never verified),
    # remove that password so they can't sign in and read this calendar.
    conn.execute(
        """INSERT INTO users (id, email, email_verified) VALUES (?, ?, TRUE)
           ON CONFLICT (id) DO UPDATE SET
             password_hash = CASE WHEN users.email_verified THEN users.password_hash ELSE NULL END,
             email_verified = TRUE""",
        (user_id, email)
    )
    conn.commit()

    # Every calendar the user has turned on in Google Calendar (classes, work,
    # gym...), not just the main one - each is a different "type" of event.
    events, seen_elsewhere = [], set()
    for calendar_id in calendars_to_import(service):
        try:
            cal_events = list_calendar_events(service, calendar_id, now, end)
        except Exception:
            # One calendar we can't read (e.g. shared as free/busy only) must not
            # stop the others from importing.
            if calendar_id == "primary":
                raise
            continue
        # The same event can sit on two calendars (e.g. an invite copied to a shared
        # calendar): skip copies of events already taken from another calendar.
        events.extend(e for e in cal_events if event_key(e) not in seen_elsewhere)
        seen_elsewhere.update(event_key(e) for e in cal_events)

    busy = [parse_event(e) for e in events if blocks_time(e)]

    # Store Google Calendar busy times for later merging
    conn.execute(
        "DELETE FROM busy_times WHERE user_id = ? AND source = 'google'",
        (user_id,)
    )

    insert_busy_rows(
        (user_id, start.isoformat(), end.isoformat(), "google", raw_timezone, None)
        for start, end, raw_timezone, _title in busy
    )

    conn.commit()


    token = create_session_token(user_id)
    # In the #fragment, not the ?query: fragments are never sent to servers,
    # so the token doesn't land in Vercel's logs or Referer headers.
    response = RedirectResponse(f"{back_to}#user={quote(user_id)}&token={quote(token)}")
    response.delete_cookie(STATE_COOKIE, path="/auth")
    return response

@router.get("/auth/status")
def google_status(user_id: str = Depends(get_current_user)):
    row = conn.execute(
        "SELECT 1 FROM busy_times WHERE user_id = ? AND source = 'google' LIMIT 1",
        (user_id,)
    ).fetchone()

    return {"connected": row is not None}

@router.post("/auth/disconnect")
def disconnect_google(user_id: str = Depends(get_current_user)):
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
    conn.execute(
        "DELETE FROM busy_times WHERE user_id = ? AND source = 'google'",
        (user_id,)
    )
    conn.commit()

    return {"logged_out": True}
