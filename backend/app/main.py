import os

from fastapi import FastAPI, Request
from app.google_auth import router as google_router
from dotenv import load_dotenv
from app.group_availability import router as group_router
from app.calendar_import import router as import_router
from app.email_auth import router as email_auth_router
from fastapi.middleware.cors import CORSMiddleware
from app.auth_utils import _secret
from app.db import current_request

load_dotenv()
_secret()  # fail at startup, not on the first sign-in, if SESSION_SECRET is missing/weak

app = FastAPI(
    title="Calendar Availability API",
    version="1.0.0"
)

# Only the real frontend (plus local dev) may call the API from a browser.
# Auth is a Bearer token, not cookies, so credentials aren't needed.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv(
    "FRONTEND_ORIGINS", "https://calender-app-one-xi.vercel.app,http://localhost:5173"
).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def mark_request(request: Request, call_next):
    # Lets the database layer drop anything a previous request left unfinished.
    token = current_request.set(object())
    try:
        return await call_next(request)
    finally:
        current_request.reset(token)

app.include_router(group_router)
app.include_router(google_router)
app.include_router(import_router)
app.include_router(email_auth_router)

@app.get("/")
def root():
    return {"status": "API running"}

@app.get("/health")
def health():
    return {"status": "healthy"}

