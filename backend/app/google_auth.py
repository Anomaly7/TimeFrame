import os

# Plain-http OAuth callbacks are only allowed when explicitly running locally.
if os.getenv("ALLOW_INSECURE_OAUTH") == "1":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from starlette.responses import RedirectResponse
from app.availability import parse_event, find_free_time, PST
from app.auth_utils import create_oauth_state, create_session_token, get_current_user, verify_oauth_state
from datetime import datetime, time, timedelta
from app.db import conn
from app.busy_store import insert_busy_rows


router = APIRouter()

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://calender-app-one-xi.vercel.app").rstrip("/")
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

@router.get("/auth/login")
def login():
    flow = get_flow()
    flow.redirect_uri = os.getenv("REDIRECT_URI")

    state, nonce = create_oauth_state()
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
    if not verify_oauth_state(request.query_params.get("state"), request.cookies.get(STATE_COOKIE)):
        return RedirectResponse(f"{FRONTEND_URL}/#auth_error=" + quote("Sign-in expired or was started elsewhere. Please try again."))
    if request.query_params.get("error"):
        return RedirectResponse(f"{FRONTEND_URL}/#auth_error=" + quote("Google sign-in was cancelled."))

    flow = get_flow()
    flow.redirect_uri = os.getenv("REDIRECT_URI")

    # Behind Render's proxy the app sees http://; Google redirected to https://.
    callback_url = str(request.url)
    if request.headers.get("x-forwarded-proto") == "https" and callback_url.startswith("http://"):
        callback_url = "https://" + callback_url[len("http://"):]
    try:
        flow.fetch_token(authorization_response=callback_url)
    except Exception:
        return RedirectResponse(f"{FRONTEND_URL}/#auth_error=" + quote("Google sign-in failed. Please try again."))
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

    # A year of (singleEvents-expanded) events can span many pages -
    # Google caps each page at maxResults, so keep following nextPageToken
    # until it's exhausted.
    events = []
    page_token = None
    while True:
        events_result = service.events().list(
            calendarId="primary",
            timeMin=now,
            timeMax=end,
            singleEvents=True,
            orderBy="startTime",
            maxResults=2500,
            pageToken=page_token,
            # Only the times - never titles, descriptions, attendees or links
            # (busy blocks only show whose they are). Also a much smaller response.
            fields="nextPageToken,items(start,end)"
        ).execute()
        events.extend(events_result.get("items", []))
        page_token = events_result.get("nextPageToken")
        if not page_token:
            break

    busy = [parse_event(e) for e in events]

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
    response = RedirectResponse(f"{FRONTEND_URL}/#user={quote(user_id)}&token={quote(token)}")
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

@router.get("/auth/me")
def me(user_id: str = Depends(get_current_user)):
    row = conn.execute(
        "SELECT email FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    return {"email": row[0] if row else None}

@router.post("/auth/logout")
def logout(user_id: str = Depends(get_current_user)):
    conn.execute(
        "DELETE FROM busy_times WHERE user_id = ? AND source = 'google'",
        (user_id,)
    )
    conn.commit()

    return {"logged_out": True}
