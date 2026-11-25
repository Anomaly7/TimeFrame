"""Group chat-lite (2026-11-25): short notes on a group ("Bring laptops") and one note the admin pins at the top.
The pinned next meeting is the group's next booking (Plan tab)."""
import secrets
import time as _time

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.auth_utils import RateLimiter, clean_text, get_current_user
from app.db import conn
from app.schema import ensure_tables

router = APIRouter()
MAX_LEN = 280
KEEP = 200
note_limiter = RateLimiter(max_attempts=20, window_seconds=600)

ensure_tables([
    "CREATE TABLE IF NOT EXISTS group_notes (id TEXT PRIMARY KEY, group_id TEXT, user_id TEXT, text TEXT, created_at BIGINT)",
    "CREATE INDEX IF NOT EXISTS group_notes_group ON group_notes (group_id)",
], ["group_notes"])


def _k(u) -> str:
    return (u or "").strip().lower()


def _member(group_id: str, user_id: str):
    from app.bookings import _require_member
    _require_member(group_id, user_id)


def _pinned(group_id: str):
    row = conn.execute("SELECT pinned_note FROM group_prefs WHERE group_id = ?", (group_id,)).fetchone()
    return row[0] if row and row[0] else None


@router.get("/groups/notes")
def list_notes(group_id: str = Query(...), user_id: str = Depends(get_current_user)):
    from app.bookings import _is_admin, display_name
    _member(group_id, user_id)
    admin = _is_admin(group_id, user_id)
    rows = conn.execute("SELECT id, user_id, text, created_at FROM group_notes WHERE group_id = ? ORDER BY created_at DESC LIMIT 50",
                        (group_id,)).fetchall()
    notes = [{"id": nid, "author": "You" if _k(uid) == _k(user_id) else display_name(uid), "text": text, "created_at": at,
              "mine": _k(uid) == _k(user_id), "can_delete": admin or _k(uid) == _k(user_id)} for nid, uid, text, at in rows]
    return {"pinned": _pinned(group_id), "notes": notes, "can_pin": admin}


@router.post("/groups/notes")
def add_note(group_id: str = Query(...), body: dict = Body(...), user_id: str = Depends(get_current_user)):
    from app.bookings import display_name
    _member(group_id, user_id)
    text = clean_text(body.get("text"), MAX_LEN)
    if not text:
        raise HTTPException(status_code=400, detail="Write something first.")
    note_limiter.check("user:" + _k(user_id))
    nid = secrets.token_urlsafe(9)
    conn.execute("INSERT INTO group_notes (id, group_id, user_id, text, created_at) VALUES (?, ?, ?, ?, ?)",
                 (nid, group_id, user_id, text, int(_time.time())))
    # Keep the newest KEEP notes per group.
    old = conn.execute("SELECT id FROM group_notes WHERE group_id = ? ORDER BY created_at DESC", (group_id,)).fetchall()[KEEP:]
    for (oid,) in old:
        conn.execute("DELETE FROM group_notes WHERE id = ?", (oid,))
    conn.commit()
    from app.notifications import notify_group
    notify_group(group_id, "note", f"{display_name(user_id)}: {text[:120]}", exclude=user_id)
    return {"id": nid}


@router.post("/groups/notes/delete")
def delete_note(id: str = Query(...), user_id: str = Depends(get_current_user)):
    from app.bookings import _is_admin
    row = conn.execute("SELECT group_id, user_id FROM group_notes WHERE id = ?", (id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="That note doesn't exist.")
    _member(row[0], user_id)
    if _k(row[1]) != _k(user_id) and not _is_admin(row[0], user_id):
        raise HTTPException(status_code=403, detail="Only whoever wrote it, or the admin, can delete it.")
    conn.execute("DELETE FROM group_notes WHERE id = ?", (id,))
    conn.commit()
    return {"deleted": True}


@router.post("/groups/pin")
def pin_note(group_id: str = Query(...), body: dict = Body(...), user_id: str = Depends(get_current_user)):
    """Admin only; blank unpins."""
    from app.group_availability import require_admin
    require_admin(group_id, user_id)
    text = clean_text(body.get("text"), MAX_LEN) or None
    conn.execute("INSERT INTO group_prefs (group_id, pinned_note) VALUES (?, ?) "
                 "ON CONFLICT (group_id) DO UPDATE SET pinned_note = excluded.pinned_note", (group_id, text))
    conn.commit()
    return {"pinned": text}
