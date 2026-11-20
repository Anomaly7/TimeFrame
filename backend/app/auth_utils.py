from __future__ import annotations

import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque

import jwt
from fastapi import Header, HTTPException, Request

ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days: what a fresh sign-in gets
REMEMBER_TTL_SECONDS = 60 * 60 * 24 * 90  # "Remember me": renewed on every visit, so active users never get signed out
SHORT_TTL_SECONDS = 60 * 60 * 12  # "Remember me" off: half a day at most (the browser also forgets it on close)
OAUTH_STATE_TTL_SECONDS = 600


def _secret() -> str:
    secret = os.getenv("SESSION_SECRET")
    # A missing or short secret would let anyone forge a session token for
    # any user, so refuse to issue or accept tokens at all without one.
    if not secret or len(secret) < 32:
        raise RuntimeError("SESSION_SECRET must be set to a random string of at least 32 characters")
    return secret


def create_session_token(user_id: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + ttl_seconds, "typ": "session"}
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def get_current_user(authorization: str = Header(None)) -> str:
    """FastAPI dependency: the caller's identity, proven by a signed session
    token - never trust a client-supplied user_id query param for this, or
    anyone can read/overwrite anyone else's schedule just by guessing or
    typing in their email."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not signed in")

    token = authorization[len("Bearer "):]

    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Session expired, please sign in again")

    # Tokens issued before "typ" existed are still session tokens; anything
    # else (e.g. an OAuth state token) must not work as a login.
    if payload.get("typ", "session") != "session" or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Session expired, please sign in again")

    return payload["sub"]


# ---- OAuth state (stops login CSRF: someone else's Google callback being
# replayed into your browser and signing you into their account) ----
def create_oauth_state(app_redirect: str | None = None) -> tuple[str, str]:
    """Returns (state, nonce). The nonce goes in a cookie on the API domain;
    the callback only accepts a state whose nonce matches that cookie.
    app_redirect (already checked with safe_app_redirect) sends the finished
    sign-in back to the phone app instead of the website."""
    nonce = secrets.token_urlsafe(16)
    payload = {"nonce": nonce, "exp": int(time.time()) + OAUTH_STATE_TTL_SECONDS, "typ": "oauth_state"}
    if app_redirect:
        payload["app"] = app_redirect
    state = jwt.encode(payload, _secret(), algorithm=ALGORITHM)
    return state, nonce


def oauth_state_app_redirect(state: str | None) -> str | None:
    """The phone-app address stored in a (signature-checked) state, if any."""
    try:
        payload = jwt.decode(state or "", _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return safe_app_redirect(payload.get("app"))


_PRIVATE_HOST = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$"
)


def _extension_ids() -> set[str]:
    ids = {"mekfgkblklbedejkkcocmpgpgdmlgfde", "aejjnpicjnicnoekejbgekioiifjanck"}
    ids.update(x.strip() for x in os.getenv("EXTENSION_IDS", "").split(",") if x.strip())
    return ids


def safe_app_redirect(url: str | None) -> str | None:
    """Only the TimeFrame app itself (timeframe://...) or Expo Go on a phone on
    the same home network (exp://<private address>/...) may receive a session
    token. Anything else - another app's scheme, a website, an Expo tunnel on
    the internet - is refused, so a crafted sign-in link can't send someone's
    token to a stranger."""
    if not url or len(url) > 300 or "#" in url:
        return None
    if url.startswith("timeframe://"):
        return url
    # The TimeFrame Chrome extension (chrome.identity.launchWebAuthFlow). Only our own extension IDs:
    # the Web Store copy, Sam's unpacked dev copy, plus any listed in EXTENSION_IDS.
    m = re.match(r"^https://([a-p]{32})\.chromiumapp\.org/[A-Za-z0-9_/-]*$", url)
    if m and m.group(1) in _extension_ids():
        return url
    m = re.match(r"^exp://([^/]+)(/.*)?$", url)
    if m and _PRIVATE_HOST.match(m.group(1)):
        return url
    return None


def verify_oauth_state(state: str | None, cookie_nonce: str | None) -> bool:
    if not state or not cookie_nonce:
        return False
    try:
        payload = jwt.decode(state, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return False
    return payload.get("typ") == "oauth_state" and secrets.compare_digest(payload.get("nonce", ""), cookie_nonce)


# ---- rate limiting for sign-in / sign-up (in memory, per server process) ----
class RateLimiter:
    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, *keys: str) -> None:
        now = time.time()
        with self._lock:
            for key in keys:
                hits = self._hits[key]
                while hits and hits[0] < now - self.window:
                    hits.popleft()
                if len(hits) >= self.max_attempts:
                    raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes and try again.")
            for key in keys:
                self._hits[key].append(now)


def client_ip(request: Request) -> str:
    # Render (like most hosts) sits behind a proxy; the original client is the
    # first address in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
