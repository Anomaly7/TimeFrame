"""Group polls, When2meet style: someone picks candidate dates and hours,
shares a link, and everyone paints the half-hours they're free. Anyone with
the link can respond with just a name (no account needed); signed-in users
can also fill their grid from their saved calendar."""
import hashlib
import json
import re
import secrets
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request

from app.auth_utils import RateLimiter, client_ip, get_current_user
from app.db import conn

router = APIRouter()

POLL_ID_RE = re.compile(r"^[A-Za-z0-9]{8,16}$")
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
SLOT_CHOICES = (15, 30, 60)
MAX_DATES = 31
MAX_RESPONSES = 100

respond_limiter = RateLimiter(max_attempts=60, window_seconds=300)
create_limiter = RateLimiter(max_attempts=20, window_seconds=3600)

conn.execute("""
CREATE TABLE IF NOT EXISTS polls (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_by TEXT,
    dates TEXT,
    start_min INTEGER,
    end_min INTEGER,
    slot_min INTEGER,
    timezone TEXT,
    created_at TEXT
)
""")
conn.execute("""
CREATE TABLE IF NOT EXISTS poll_responses (
    poll_id TEXT,
    participant TEXT,
    name TEXT,
    slots TEXT,
    edit_hash TEXT,
    updated_at TEXT,
    PRIMARY KEY (poll_id, participant)
)
""")
conn.commit()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _optional_user(authorization: str = Header(None)):
    """The signed-in user if a valid session came with the request, else None
    (poll responses don't require an account)."""
    if not authorization:
        return None
    try:
        return get_current_user(authorization)
    except HTTPException:
        return None


def _to_minutes(hhmm: str) -> int:
    try:
        t = time.fromisoformat(hhmm)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Times must look like 09:00.")
    return t.hour * 60 + t.minute


def _cells(poll) -> list:
    """Every cell key in the poll's grid, e.g. '2026-11-02T09:30', in the
    poll's own timezone."""
    out = []
    for d in poll["dates"]:
        m = poll["start_min"]
        while m + poll["slot_min"] <= poll["end_min"]:
            out.append(f"{d}T{m // 60:02d}:{m % 60:02d}")
            m += poll["slot_min"]
    return out


def _load(poll_id: str):
    if not POLL_ID_RE.match(poll_id):
        raise HTTPException(status_code=404, detail="Poll not found.")
    row = conn.execute(
        "SELECT id, title, dates, start_min, end_min, slot_min, timezone FROM polls WHERE id = ?",
        (poll_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Poll not found.")
    return {
        "id": row[0], "title": row[1], "dates": json.loads(row[2]),
        "start_min": row[3], "end_min": row[4], "slot_min": row[5], "timezone": row[6],
    }


@router.post("/polls")
def create_poll(request: Request, body: dict = Body(...), user_id: str = Depends(get_current_user)):
    create_limiter.check("poll-create:" + user_id, "poll-create-ip:" + client_ip(request))

    title = str(body.get("title") or "").strip()[:100] or "Group meeting"
    try:
        tz_name = str(body.get("timezone") or "America/Vancouver")
        ZoneInfo(tz_name)
    except Exception:
        raise HTTPException(status_code=400, detail="Unknown timezone.")

    raw_dates = body.get("dates") or []
    if not isinstance(raw_dates, list) or not raw_dates:
        raise HTTPException(status_code=400, detail="Pick at least one date.")
    try:
        dates = sorted({date.fromisoformat(str(d)).isoformat() for d in raw_dates})
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must look like 2026-11-02.")
    if len(dates) > MAX_DATES:
        raise HTTPException(status_code=400, detail=f"Pick at most {MAX_DATES} dates.")

    start_min = _to_minutes(body.get("start") or "09:00")
    end_raw = body.get("end") or "17:00"
    end_min = 24 * 60 if end_raw in ("24:00", "00:00") else _to_minutes(end_raw)
    slot_min = int(body.get("slot_minutes") or 30)
    if slot_min not in SLOT_CHOICES:
        raise HTTPException(status_code=400, detail="Slot length must be 15, 30 or 60 minutes.")
    if end_min - start_min < slot_min:
        raise HTTPException(status_code=400, detail="The end time must be after the start time.")

    poll_id = "".join(secrets.choice(ALPHABET) for _ in range(10))
    conn.execute(
        "INSERT INTO polls (id, title, created_by, dates, start_min, end_min, slot_min, timezone, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (poll_id, title, user_id, json.dumps(dates), start_min, end_min, slot_min, tz_name,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return {"id": poll_id}


@router.get("/polls/{poll_id}")
def get_poll(poll_id: str):
    poll = _load(poll_id)
    rows = conn.execute(
        "SELECT participant, name, slots FROM poll_responses WHERE poll_id = ? ORDER BY updated_at",
        (poll_id,),
    ).fetchall()
    # Participant ids are opaque (never an email), so the link only reveals
    # the names people chose and the times they marked.
    responses = [{"id": p, "name": n, "slots": json.loads(s)} for p, n, s in rows]
    return {**poll, "cells": _cells(poll), "responses": responses}


@router.post("/polls/{poll_id}/respond")
def respond(
    poll_id: str,
    request: Request,
    body: dict = Body(...),
    user_id=Depends(_optional_user),
):
    respond_limiter.check("poll-respond:" + client_ip(request))
    poll = _load(poll_id)

    name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()[:40]
    if not name:
        raise HTTPException(status_code=400, detail="Enter your name.")

    valid = set(_cells(poll))
    slots = body.get("slots") or []
    if not isinstance(slots, list):
        raise HTTPException(status_code=400, detail="Slots must be a list.")
    slots = sorted({str(s) for s in slots} & valid)

    edit_token = body.get("edit_token")
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT participant, name, edit_hash FROM poll_responses WHERE poll_id = ?", (poll_id,)
    ).fetchall()

    if user_id:
        # Signed-in: one response per account, keyed by a hash so the account
        # email never appears in the poll.
        participant = "u" + _hash(user_id.strip().lower())[:15]
        new_token = None
        # Answered as a guest in this browser before signing in: that answer
        # becomes the account's (otherwise it would clash with itself).
        if edit_token:
            h = _hash(str(edit_token))
            guest = next((p for p, _, eh in existing if eh and secrets.compare_digest(eh, h)), None)
            if guest:
                if participant in {p for p, _, _ in existing}:
                    conn.execute("DELETE FROM poll_responses WHERE poll_id = ? AND participant = ?", (poll_id, guest))
                else:
                    conn.execute(
                        "UPDATE poll_responses SET participant = ?, edit_hash = NULL WHERE poll_id = ? AND participant = ?",
                        (participant, poll_id, guest),
                    )
                existing = conn.execute(
                    "SELECT participant, name, edit_hash FROM poll_responses WHERE poll_id = ?", (poll_id,)
                ).fetchall()
    else:
        participant, new_token = None, None
        if edit_token:
            h = _hash(str(edit_token))
            participant = next((p for p, _, eh in existing if eh and secrets.compare_digest(eh, h)), None)
        if participant is None:
            participant = "a" + secrets.token_hex(8)
            new_token = secrets.token_urlsafe(24)

    # Two different people can't share a name in one poll (it would be
    # impossible to tell their rows apart).
    for p, n, _ in existing:
        if p != participant and n.lower() == name.lower():
            raise HTTPException(status_code=409, detail=f'Someone already answered as "{name}". Pick another name.')

    is_new = participant not in {p for p, _, _ in existing}
    if is_new and len(existing) >= MAX_RESPONSES:
        raise HTTPException(status_code=400, detail="This poll is full.")

    if is_new:
        conn.execute(
            "INSERT INTO poll_responses (poll_id, participant, name, slots, edit_hash, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (poll_id, participant, name, json.dumps(slots), _hash(new_token) if new_token else None, now),
        )
    else:
        conn.execute(
            "UPDATE poll_responses SET name = ?, slots = ?, updated_at = ? WHERE poll_id = ? AND participant = ?",
            (name, json.dumps(slots), now, poll_id, participant),
        )
    conn.commit()
    return {"id": participant, "edit_token": new_token, "slots": slots}


@router.get("/polls/{poll_id}/autofill")
def autofill(poll_id: str, user_id: str = Depends(get_current_user)):
    """The cells in this poll where the signed-in user's saved calendar
    (Google, .ics and manual busy times) has nothing booked."""
    poll = _load(poll_id)
    tz = ZoneInfo(poll["timezone"])
    busy = []
    for start, end in conn.execute(
        "SELECT start, end_time FROM busy_times WHERE user_id = ?", (user_id,)
    ).fetchall():
        try:
            busy.append((datetime.fromisoformat(start), datetime.fromisoformat(end)))
        except (TypeError, ValueError):
            continue
    busy = [(s if s.tzinfo else s.replace(tzinfo=tz), e if e.tzinfo else e.replace(tzinfo=tz)) for s, e in busy]

    free = []
    step = timedelta(minutes=poll["slot_min"])
    for cell in _cells(poll):
        lo = datetime.fromisoformat(cell).replace(tzinfo=tz)
        hi = lo + step
        if not any(s < hi and e > lo for s, e in busy):
            free.append(cell)
    return {"slots": free}
