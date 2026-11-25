import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from app.google_auth import router as google_router
from dotenv import load_dotenv
from app.group_availability import router as group_router
from app.calendar_import import router as import_router
from app.email_auth import router as email_auth_router
from app.apple_calendar import router as apple_router
from app.notion_auth import router as notion_router
from app.billing import router as billing_router
from app.admin import router as admin_router
from app.google_sync import router as sync_router, start_background_loop
from app.bookings import router as bookings_router
from app.guests import router as guests_router
from app.polls import router as polls_router
import app.maintenance as maintenance
from fastapi.middleware.cors import CORSMiddleware
from app.auth_utils import _secret
from app.db import conn, current_request

load_dotenv()
_secret()  # fail at startup, not on the first sign-in, if SESSION_SECRET is missing/weak

app = FastAPI(
    title="Calendar Availability API",
    version="1.0.0"
)

# Only the real frontend (plus local dev) may call the API from a browser.
# Auth is a Bearer token, not cookies, so credentials aren't needed.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv(
    "FRONTEND_ORIGINS",
    "https://www.timeframecalender.com,https://timeframecalender.com,https://calender-app-one-xi.vercel.app,http://localhost:5173"
).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


def _maintenance_response(request: Request):
    """The app is switched off for maintenance (admin page). Browsers opening an API address directly (a sign-in
    link, say) go to the website, which shows the maintenance screen; everything else gets a 503 the site reads."""
    site = next((o for o in ALLOWED_ORIGINS if o.startswith("https://")), ALLOWED_ORIGINS[0])
    if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(site + "/", status_code=302)
    response = JSONResponse(
        {"detail": "TimeFrame is down for maintenance. Please try again soon.", **maintenance.public()},
        status_code=503, headers={"Retry-After": "120", "Cache-Control": "no-store"})
    # This answer skips the CORS layer, so add its header here, or the website couldn't read why the call failed.
    origin = request.headers.get("origin")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


@app.middleware("http")
async def mark_request(request: Request, call_next):
    # Lets the database layer drop anything a previous request left unfinished.
    token = current_request.set(object())
    try:
        if maintenance.blocks(request.url.path, request.method):
            response = _maintenance_response(request)
        else:
            response = await call_next(request)
    finally:
        current_request.reset(token)
    # Safe defaults on every answer (the admin page sets stricter ones of its own): browsers must not guess file
    # types, nothing may show the API inside a frame, and links out never carry the address.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response

app.include_router(group_router)
app.include_router(google_router)
app.include_router(import_router)
app.include_router(email_auth_router)
app.include_router(apple_router)
app.include_router(notion_router)
app.include_router(billing_router)
app.include_router(maintenance.router)  # public GET /status (maintenance mode on/off)
app.include_router(sync_router)  # Google auto-sync / "Sync now"
app.include_router(bookings_router)  # booked meetings
app.include_router(guests_router)  # guest links
app.include_router(polls_router)  # polls / propose times
app.include_router(admin_router)  # owner-only /admin (off until ADMIN_PASSWORD + ADMIN_TOTP_SECRET are set)

# Background jobs (Google auto-sync; off unless its key is set, and in tests via DISABLE_BACKGROUND_JOBS).
start_background_loop()


@app.get("/")
def root():
    return {"status": "API running"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/health/db")
def health_db():
    # Runs a real query, so a daily ping keeps the free Supabase project
    # from pausing for inactivity (and shows whether the database is up).
    conn.execute("SELECT 1").fetchone()
    return {"status": "healthy", "database": "ok"}

