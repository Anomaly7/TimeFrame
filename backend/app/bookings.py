"""Book the slot ("Lock it in", 2026-11-25): a group member picks a free time and names it. Everyone in the group
sees it as Booked (calendar + the Plan tab's "Next meeting"), can add it to Google Calendar or download an .ics,
and it counts as busy for each of them from then on, so other groups won't suggest that time.
No new Google permission: the app builds the "Add to Google Calendar" link and the .ics file itself.
Bookings from someone's personal booking page (booking_page.py) live here too, with group_id NULL and host set."""
import secrets
import time as _time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.auth_utils import clean_text, get_current_user
from app.db import conn
from app.schema import ensure_tables

router = APIRouter()
MAX_UPCOMING = 200

ensure_tables([
    """CREATE TABLE IF NOT EXISTS bookings (
        id TEXT PRIMARY KEY, group_id TEXT, title TEXT, start TEXT, end_time TEXT, created_by TEXT,
        created_at BIGINT, cancelled INTEGER DEFAULT 0, host TEXT, guest_name TEXT, guest_email TEXT, note TEXT)""",
    "CREATE INDEX IF NOT EXISTS bookings_group ON bookings (group_id)",
    "CREATE INDEX IF NOT EXISTS bookings_host ON bookings (host)",
], ["bookings"])


def _k(user_id) -> str:
    return (user_id or "").strip().lower()


def parse_span(start, end, max_hours: int = 12) -> tuple[datetime, datetime]:
    try:
        s = datetime.fromisoformat(str(start))
        e = datetime.fromisoformat(str(end))
    except ValueError:
        raise HTTPException(status_code=400, detail="Start and end must be ISO date-times.")
    if s.tzinfo is None or e.tzinfo is None:
        raise HTTPException(status_code=400, detail="Start and end need a time zone.")
    if e <= s:
        raise HTTPException(status_code=400, detail="The end must be after the start.")
    if e - s > timedelta(hours=max_hours):
        raise HTTPException(status_code=400, detail=f"A booking can be at most {max_hours} hours.")
    now = datetime.now(timezone.utc)
    if e < now - timedelta(hours=1) or s > now + timedelta(days=400):
        raise HTTPException(status_code=400, detail="Pick a time between now and next year.")
    return s, e


def create_booking(group_id, title, start: datetime, end: datetime, created_by, host=None,
                   guest_name=None, guest_email=None, note=None) -> dict:
    """The caller has checked permissions. Commits."""
    bid = secrets.token_urlsafe(9)
    conn.execute(
        "INSERT INTO bookings (id, group_id, title, start, end_time, created_by, created_at, cancelled, host, guest_name, guest_email, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
        (bid, group_id, title, start.isoformat(), end.isoformat(), created_by, int(_time.time()), host, guest_name, guest_email, note))
    conn.commit()
    return booking(bid)


def _row_to_dict(row) -> dict:
    bid, gid, title, start, end, created_by, created_at, cancelled, host, guest_name, guest_email, note = row
    return {"id": bid, "group_id": gid, "title": title, "start": start, "end": end, "created_by": created_by,
            "created_at": created_at, "cancelled": bool(cancelled), "host": host, "guest_name": guest_name,
            "guest_email": guest_email, "note": note}


COLS = "id, group_id, title, start, end_time, created_by, created_at, cancelled, host, guest_name, guest_email, note"


def booking(bid: str) -> dict | None:
    row = conn.execute(f"SELECT {COLS} FROM bookings WHERE id = ?", (bid,)).fetchone()
    return _row_to_dict(row) if row else None


def _upcoming(rows) -> list[dict]:
    now = datetime.now(timezone.utc)
    out = [_row_to_dict(r) for r in rows]
    out = [b for b in out if not b["cancelled"] and datetime.fromisoformat(b["end"]) > now]
    out.sort(key=lambda b: datetime.fromisoformat(b["start"]))
    return out


def group_bookings(group_id: str) -> list[dict]:
    return _upcoming(conn.execute(f"SELECT {COLS} FROM bookings WHERE group_id = ?", (group_id,)).fetchall())


def user_groups(user_id: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT group_id FROM group_members WHERE LOWER(TRIM(user_id)) = ?", (_k(user_id),)).fetchall()]


def bookings_for_user(user_id: str) -> list[dict]:
    """Every upcoming booking that makes this person busy: their groups' bookings and their booking page's."""
    out = []
    for gid in user_groups(user_id):
        out.extend(group_bookings(gid))
    out.extend(_upcoming(conn.execute(f"SELECT {COLS} FROM bookings WHERE LOWER(TRIM(host)) = ?", (_k(user_id),)).fetchall()))
    return out


def public(b: dict, viewer: str) -> dict:
    """What a member sees: the booker's contact details only for the host of a booking-page booking."""
    out = {k: b[k] for k in ("id", "group_id", "title", "start", "end", "created_at", "note")}
    out["created_by_name"] = display_name(b["created_by"]) if b["created_by"] else (b["guest_name"] or "Guest")
    out["can_cancel"] = _k(b["created_by"]) == _k(viewer) or _k(b["host"]) == _k(viewer) or (
        b["group_id"] and _is_admin(b["group_id"], viewer))
    if b["host"] and _k(b["host"]) == _k(viewer):
        out["guest_name"], out["guest_email"] = b["guest_name"], b["guest_email"]
        out["booking_page"] = True
    return out


def display_name(user_id: str) -> str:
    row = conn.execute("SELECT display_name FROM users WHERE id = ?", (user_id,)).fetchone()
    return (row[0] if row else None) or (user_id or "").split("@")[0]


def _is_admin(group_id: str, user_id: str) -> bool:
    from app.group_availability import group_row, same_user
    info = group_row(group_id)
    return bool(info) and same_user(info[1], user_id)


def _require_member(group_id: str, user_id: str):
    from app.group_availability import GROUP_ID_RE, is_member
    if not GROUP_ID_RE.match(group_id or "") or not is_member(group_id, user_id):
        raise HTTPException(status_code=404, detail="You're not in that group.")


@router.post("/groups/book")
def book_slot(group_id: str = Query(...), body: dict = Body(...), user_id: str = Depends(get_current_user)):
    """Any member can book a time for the group (the admin, or whoever booked it, can cancel)."""
    _require_member(group_id, user_id)
    start, end = parse_span(body.get("start"), body.get("end"))
    title = clean_text(body.get("title"), 80) or "Group meeting"
    if len(group_bookings(group_id)) >= MAX_UPCOMING:
        raise HTTPException(status_code=400, detail="This group has too many upcoming bookings.")
    b = create_booking(group_id, title, start, end, user_id)
    from app.notifications import notify_group
    notify_group(group_id, "booked", f"{display_name(user_id)} booked \"{title}\"", exclude=user_id,
                 data={"booking": b["id"], "start": b["start"]})
    return {"booking": public(b, user_id)}


@router.get("/groups/bookings")
def list_group_bookings(group_id: str = Query(...), user_id: str = Depends(get_current_user)):
    _require_member(group_id, user_id)
    return {"bookings": [public(b, user_id) for b in group_bookings(group_id)]}


@router.get("/bookings/mine")
def my_bookings(user_id: str = Depends(get_current_user)):
    """Everything upcoming you're part of, across groups and your booking page (for "Next meeting")."""
    from app.group_availability import group_row
    out = []
    for b in bookings_for_user(user_id):
        p = public(b, user_id)
        p["group_name"] = (group_row(b["group_id"]) or (None,))[0] if b["group_id"] else None
        out.append(p)
    return {"bookings": out}


@router.post("/bookings/cancel")
def cancel_booking(id: str = Query(...), user_id: str = Depends(get_current_user)):
    b = booking(id)
    if not b or b["cancelled"]:
        raise HTTPException(status_code=404, detail="That booking doesn't exist.")
    if b["group_id"]:
        _require_member(b["group_id"], user_id)
    if not public(b, user_id)["can_cancel"]:
        raise HTTPException(status_code=403, detail="Only whoever booked it, or the group's admin, can cancel it.")
    conn.execute("UPDATE bookings SET cancelled = 1 WHERE id = ?", (id,))
    conn.commit()
    if b["group_id"]:
        from app.notifications import notify_group
        notify_group(b["group_id"], "cancelled", f"\"{b['title']}\" was cancelled", exclude=user_id,
                     data={"booking": id, "start": b["start"]})
    return {"cancelled": True}
