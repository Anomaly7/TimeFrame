import re

import bcrypt
from fastapi import APIRouter, Body, HTTPException, Request

from app.auth_utils import RateLimiter, client_ip, create_session_token
from app.db import conn

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# 10 tries per 10 minutes per IP and per email address.
auth_limiter = RateLimiter(max_attempts=10, window_seconds=600)


def _check_password_rules(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    # bcrypt only uses the first 72 bytes (newer versions refuse longer ones).
    if len(password.encode()) > 72:
        raise HTTPException(status_code=400, detail="Password must be at most 72 characters.")


@router.post("/auth/signup")
def signup(request: Request, body: dict = Body(...)):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    auth_limiter.check("ip:" + client_ip(request), "email:" + email)

    if len(email) > 254 or not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    _check_password_rules(password)

    existing = conn.execute("SELECT id FROM users WHERE id = ?", (email,)).fetchone()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="An account with this email already exists - try signing in instead."
        )

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    conn.execute(
        "INSERT INTO users (id, email, password_hash, email_verified) VALUES (?, ?, ?, FALSE)",
        (email, email, password_hash)
    )
    conn.commit()

    token = create_session_token(email)
    return {"token": token, "email": email}


@router.post("/auth/login")
def login(request: Request, body: dict = Body(...)):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    auth_limiter.check("ip:" + client_ip(request), "email:" + email)

    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (email,)).fetchone()

    if not row or not row[0] or len(password.encode()) > 72:
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    if not bcrypt.checkpw(password.encode(), row[0].encode()):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    token = create_session_token(email)
    return {"token": token, "email": email}
