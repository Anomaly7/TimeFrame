"""Personal booking page (Pro, 2026-11-25): timeframecalender.com/<handle> lists your free times, anyone can pick
one with their name and email, and it lands in your Plan tab + bell (and counts as busy from then on).

Visitors only ever see open slots, never busy blocks or anything about your events. The booker gets an .ics /
"Add to Google Calendar" link on the confirmation screen (no email is sent: there's no email provider yet).
The page goes dark if the owner's Pro ends."""
import re
import time as _time
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from app.auth_utils import RateLimiter, clean_text, client_ip, get_current_user
from app.availability import is_all_day_block, merge_intervals
from app.db import conn
from app.schema import ensure_tables

router = APIRouter()
PST = ZoneInfo("America/Los_Angeles")
HANDLE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Paths the website already uses (or might), so nobody can claim them as a handle.
RESERVED = {"admin", "api", "app", "auth", "book", "booking", "bookings", "billing", "groups", "group", "guest", "help",
            "login", "logout", "privacy", "terms", "settings", "status", "health", "static", "assets", "support",
            "timeframe", "www", "about", "pricing", "pro", "signup", "signin", "account", "dashboard", "notion",
            "apple", "google", "extension", "u", "me", "polls", "notes", "sw", "manifest", "icons", "favicon"}
page_view_limiter = RateLimiter(max_attempts=120, window_seconds=600)
book_ip_limiter = RateLimiter(max_attempts=6, window_seconds=3600)
book_page_limiter = RateLimiter(max_attempts=30, window_seconds=86400)

ensure_tables([
    """CREATE TABLE IF NOT EXISTS booking_pages (user_id TEXT PRIMARY KEY, handle TEXT UNIQUE, enabled INTEGER DEFAULT 1,
        title TEXT, minutes INTEGER, day_start TEXT, day_end TEXT, weekdays TEXT, days_ahead INTEGER, notice_hours INTEGER,
        buffer INTEGER, timezone TEXT, created_at BIGINT)""",
], ["booking_pages"])

DEFAULTS = {"enabled": True, "title": "Meet with me", "minutes": 30, "day_start": "09:00", "day_end": "17:00",
            "weekdays": [0, 1, 2, 3, 4], "days_ahead": 14, "notice_hours": 12, "buffer": 0, "timezone": "America/Vancouver"}
COLS = ("user_id", "handle", "enabled", "title", "minutes", "day_start", "day_end", "weekdays", "days_ahead",
        "notice_hours", "buffer", "timezone", "created_at")


def _k(u) -> str:
    return (u or "").strip().lower()


def _page_by(field: str, value: str):
    row = conn.execute(f"SELECT {', '.join(COLS)} FROM booking_pages WHERE {field} = ?", (value,)).fetchone()
    if not row:
        return None
    p = dict(zip(COLS, row))
    p["enabled"] = bool(p["enabled"])
    p["weekdays"] = [int(x) for x in (p["weekdays"] or "").split(",") if x.strip().isdigit()]
    return p


def _clean(body: dict, current: dict | None) -> dict:
    base = {**DEFAULTS, **(current or {})}
    out = {}
    handle = str(body.get("handle", base.get("handle") or "")).strip().lower()
    if not HANDLE_RE.match(handle) or handle in RESERVED or handle.startswith("guest"):
        raise HTTPException(status_code=400, detail="Pick a link name of 3-30 letters, numbers or dashes (not a reserved word).")
    out["handle"] = handle
    out["enabled"] = bool(body.get("enabled", base["enabled"]))
    out["title"] = clean_text(body.get("title", base["title"]), 60) or DEFAULTS["title"]
    try:
        out["minutes"] = int(body.get("minutes", base["minutes"]))
        out["days_ahead"] = int(body.get("days_ahead", base["days_ahead"]))
        out["notice_hours"] = int(body.get("notice_hours", base["notice_hours"]))
        out["buffer"] = int(body.get("buffer", base["buffer"]))
        start = time.fromisoformat(str(body.get("day_start", base["day_start"])))
        end = time.fromisoformat(str(body.get("day_end", base["day_end"])))
        days = sorted({int(d) for d in body.get("weekdays", base["weekdays"])})
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Check the booking page settings.")
    if not 10 <= out["minutes"] <= 240 or not 1 <= out["days_ahead"] <= 60 or not 0 <= out["notice_hours"] <= 168 \
            or not 0 <= out["buffer"] <= 60 or end <= start or not days or any(not 0 <= d <= 6 for d in days):
        raise HTTPException(status_code=400, detail="Check the booking page settings.")
    out["day_start"], out["day_end"], out["weekdays"] = start.strftime("%H:%M"), end.strftime("%H:%M"), days
    tz = str(body.get("timezone", base["timezone"]))
    try:
        ZoneInfo(tz)
    except Exception:
        raise HTTPException(status_code=400, detail="Unknown time zone.")
    out["timezone"] = tz
    return out


def _public_settings(p: dict) -> dict:
    return {k: p[k] for k in ("handle", "enabled", "title", "minutes", "day_start", "day_end", "weekdays", "days_ahead",
                              "notice_hours", "buffer", "timezone")}


@router.get("/booking-page")
def get_my_page(user_id: str = Depends(get_current_user)):
    from app.billing import is_pro
    p = _page_by("user_id", _k(user_id))
    return {"page": _public_settings(p) if p else None, "pro": is_pro(user_id)}


@router.post("/booking-page")
def save_my_page(body: dict = Body(...), user_id: str = Depends(get_current_user)):
    from app.billing import require_pro
    from app.guests import require_account
    require_account(user_id, "A booking page")
    require_pro(user_id, "A booking page")
    current = _page_by("user_id", _k(user_id))
    p = _clean(body, current)
    taken = _page_by("handle", p["handle"])
    if taken and taken["user_id"] != _k(user_id):
        raise HTTPException(status_code=409, detail="That link name is taken. Try another.")
    values = (p["handle"], int(p["enabled"]), p["title"], p["minutes"], p["day_start"], p["day_end"],
              ",".join(map(str, p["weekdays"])), p["days_ahead"], p["notice_hours"], p["buffer"], p["timezone"])
    if current:
        conn.execute("UPDATE booking_pages SET handle = ?, enabled = ?, title = ?, minutes = ?, day_start = ?, day_end = ?, "
                     "weekdays = ?, days_ahead = ?, notice_hours = ?, buffer = ?, timezone = ? WHERE user_id = ?",
                     values + (_k(user_id),))
    else:
        conn.execute("INSERT INTO booking_pages (handle, enabled, title, minutes, day_start, day_end, weekdays, days_ahead, "
                     "notice_hours, buffer, timezone, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     values + (_k(user_id), int(_time.time())))
    conn.commit()
    return {"page": _public_settings(_page_by("user_id", _k(user_id)))}


def _host_page(handle: str) -> dict:
    from app.billing import is_pro
    p = _page_by("handle", (handle or "").strip().lower())
    if not p or not p["enabled"] or not is_pro(p["user_id"]):
        raise HTTPException(status_code=404, detail="This booking page isn't available.")
    return p


def _open_slots(p: dict) -> list[tuple[datetime, datetime]]:
    from app.bookings import bookings_for_user
    tz = ZoneInfo(p["timezone"])
    now = datetime.now(tz)
    earliest = now + timedelta(hours=p["notice_hours"])
    today = now.date()
    horizon = datetime.combine(today + timedelta(days=p["days_ahead"] + 1), time.min, tzinfo=tz)
    pad = timedelta(minutes=p["buffer"])
    busy = []
    for start, end, source in conn.execute("SELECT start, end_time, source FROM busy_times WHERE LOWER(TRIM(user_id)) = ?",
                                           (p["user_id"],)).fetchall():
        if source != "manual" and is_all_day_block(start, end):
            continue
        s, e = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if s.tzinfo is None:
            s, e = s.replace(tzinfo=tz), e.replace(tzinfo=tz)
        if s < horizon and e > now:
            busy.append((s - pad, e + pad))
    for b in bookings_for_user(p["user_id"]):
        busy.append((datetime.fromisoformat(b["start"]) - pad, datetime.fromisoformat(b["end"]) + pad))
    merged = merge_intervals(busy)
    length = timedelta(minutes=p["minutes"])
    step = timedelta(minutes=30 if p["minutes"] >= 30 else 15)
    slots = []
    for offset in range(p["days_ahead"] + 1):
        day = today + timedelta(days=offset)
        if day.weekday() not in p["weekdays"]:
            continue
        t = datetime.combine(day, time.fromisoformat(p["day_start"]), tzinfo=tz)
        last = datetime.combine(day, time.fromisoformat(p["day_end"]), tzinfo=tz) - length
        while t <= last:
            if t >= earliest and not any(s < t + length and e > t for s, e in merged):
                slots.append((t, t + length))
            t += step
    return slots


@router.get("/book/{handle}")
def view_page(handle: str, request: Request):
    page_view_limiter.check("ip:" + client_ip(request))
    p = _host_page(handle)
    from app.bookings import display_name
    return {"name": display_name(p["user_id"]), "title": p["title"], "minutes": p["minutes"], "timezone": p["timezone"],
            "slots": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in _open_slots(p)]}


@router.post("/book/{handle}")
def book_on_page(handle: str, request: Request, body: dict = Body(...)):
    from app.bookings import create_booking, public
    p = _host_page(handle)
    name = clean_text(body.get("name"), 60)
    email = str(body.get("email") or "").strip().lower()
    note = clean_text(body.get("note"), 300) or None
    if not name:
        raise HTTPException(status_code=400, detail="Add your name.")
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Add a valid email so they can reach you.")
    try:
        start = datetime.fromisoformat(str(body.get("start")))
    except ValueError:
        raise HTTPException(status_code=400, detail="Pick a time.")
    book_ip_limiter.check("ip:" + client_ip(request))
    book_page_limiter.check("page:" + p["handle"])
    match = next(((s, e) for s, e in _open_slots(p) if s == start), None)
    if not match:
        raise HTTPException(status_code=409, detail="That time was just taken or isn't available. Pick another.")
    b = create_booking(None, f"{p['title']} with {name}", match[0], match[1], None, host=p["user_id"],
                       guest_name=name, guest_email=email, note=note)
    from app.notifications import notify_user
    notify_user(p["user_id"], "booking_page", f"{name} booked \"{p['title']}\" ({email})",
                {"booking": b["id"], "start": b["start"]})
    out = public(b, "")
    return {"booking": {k: out[k] for k in ("id", "title", "start", "end")}}
