"""Polls / propose times (2026-11-25): the admin puts 2-5 times up for a vote, members (guests too) tap the ones
that work, and closing the poll books the winner for the group (bookings.py). Works for people who never connect
a calendar."""
import json
import secrets
import time as _time

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.auth_utils import clean_text, get_current_user
from app.db import conn
from app.schema import ensure_tables

router = APIRouter()
MAX_OPEN = 20

ensure_tables([
    """CREATE TABLE IF NOT EXISTS tf_polls (id TEXT PRIMARY KEY, group_id TEXT, title TEXT, options TEXT, created_by TEXT,
        created_at BIGINT, closed INTEGER DEFAULT 0, winner INTEGER, booking_id TEXT)""",
    "CREATE INDEX IF NOT EXISTS tf_polls_group ON tf_polls (group_id)",
    "CREATE TABLE IF NOT EXISTS tf_poll_votes (poll_id TEXT, user_id TEXT, option INTEGER)",
    "CREATE INDEX IF NOT EXISTS tf_poll_votes_poll ON tf_poll_votes (poll_id)",
], ["tf_polls", "tf_poll_votes"])


def _k(u) -> str:
    return (u or "").strip().lower()


def _can_run(group_id: str, user_id: str) -> bool:
    """The admin runs polls; in a group with no admin yet, any member can."""
    from app.group_availability import group_row, same_user
    info = group_row(group_id)
    return bool(info) and (info[1] is None or same_user(info[1], user_id))


def _poll(pid: str):
    row = conn.execute("SELECT id, group_id, title, options, created_by, created_at, closed, winner, booking_id FROM tf_polls WHERE id = ?",
                       (pid,)).fetchone()
    if not row:
        return None
    keys = ("id", "group_id", "title", "options", "created_by", "created_at", "closed", "winner", "booking_id")
    p = dict(zip(keys, row))
    p["options"] = json.loads(p["options"] or "[]")
    p["closed"] = bool(p["closed"])
    return p


def _member_poll(pid: str, user_id: str):
    from app.bookings import _require_member
    p = _poll(pid)
    if not p:
        raise HTTPException(status_code=404, detail="That poll doesn't exist.")
    _require_member(p["group_id"], user_id)
    return p


def _view(p: dict, viewer: str) -> dict:
    from app.bookings import display_name
    votes = conn.execute("SELECT user_id, option FROM tf_poll_votes WHERE poll_id = ?", (p["id"],)).fetchall()
    options = []
    for i, opt in enumerate(p["options"]):
        voters = sorted({uid for uid, o in votes if o == i}, key=_k)
        options.append({**opt, "votes": len(voters), "voters": [display_name(u) for u in voters],
                        "mine": any(_k(u) == _k(viewer) for u in voters)})
    return {"id": p["id"], "title": p["title"], "options": options, "closed": p["closed"], "winner": p["winner"],
            "booking_id": p["booking_id"], "created_by_name": display_name(p["created_by"]), "created_at": p["created_at"],
            "voters": len({_k(u) for u, _ in votes}), "can_manage": _k(p["created_by"]) == _k(viewer) or _can_run(p["group_id"], viewer)}


@router.post("/groups/polls")
def create_poll(group_id: str = Query(...), body: dict = Body(...), user_id: str = Depends(get_current_user)):
    from app.bookings import _require_member, parse_span
    _require_member(group_id, user_id)
    if not _can_run(group_id, user_id):
        raise HTTPException(status_code=403, detail="Only the group's admin can start a poll.")
    raw = body.get("options")
    if not isinstance(raw, list) or not 2 <= len(raw) <= 5:
        raise HTTPException(status_code=400, detail="Pick 2 to 5 times to vote on.")
    options = []
    for o in raw:
        if not isinstance(o, dict):
            raise HTTPException(status_code=400, detail="Each option needs a start and an end.")
        s, e = parse_span(o.get("start"), o.get("end"))
        options.append({"start": s.isoformat(), "end": e.isoformat()})
    open_count = conn.execute("SELECT COUNT(*) FROM tf_polls WHERE group_id = ? AND closed = 0", (group_id,)).fetchone()[0]
    if open_count >= MAX_OPEN:
        raise HTTPException(status_code=400, detail="This group has too many open polls. Close some first.")
    title = clean_text(body.get("title"), 80) or "Group meeting"
    pid = secrets.token_urlsafe(9)
    conn.execute("INSERT INTO tf_polls (id, group_id, title, options, created_by, created_at, closed) VALUES (?, ?, ?, ?, ?, ?, 0)",
                 (pid, group_id, title, json.dumps(options), user_id, int(_time.time())))
    conn.commit()
    from app.bookings import display_name
    from app.notifications import notify_group
    notify_group(group_id, "poll", f"{display_name(user_id)} wants to know when works for \"{title}\". Vote now.",
                 exclude=user_id, data={"poll": pid})
    return {"poll": _view(_poll(pid), user_id)}


@router.get("/groups/polls")
def list_polls(group_id: str = Query(...), user_id: str = Depends(get_current_user)):
    """Open polls, plus ones closed in the last 3 days."""
    from app.bookings import _require_member
    _require_member(group_id, user_id)
    cutoff = int(_time.time()) - 3 * 86400
    rows = conn.execute("SELECT id FROM tf_polls WHERE group_id = ? AND (closed = 0 OR created_at > ?) ORDER BY created_at DESC",
                        (group_id, cutoff)).fetchall()
    return {"polls": [_view(_poll(r[0]), user_id) for r in rows]}


@router.post("/polls/vote")
def vote(id: str = Query(...), body: dict = Body(...), user_id: str = Depends(get_current_user)):
    """Your yes-votes on this poll (every option that works for you); replaces your earlier votes."""
    p = _member_poll(id, user_id)
    if p["closed"]:
        raise HTTPException(status_code=400, detail="This poll is closed.")
    picks = body.get("options")
    if not isinstance(picks, list) or any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(p["options"]) for i in picks):
        raise HTTPException(status_code=400, detail="Pick options from the poll.")
    conn.execute("DELETE FROM tf_poll_votes WHERE poll_id = ? AND LOWER(TRIM(user_id)) = ?", (id, _k(user_id)))
    for i in sorted(set(picks)):
        conn.execute("INSERT INTO tf_poll_votes (poll_id, user_id, option) VALUES (?, ?, ?)", (id, user_id, i))
    conn.commit()
    return {"poll": _view(_poll(id), user_id)}


@router.post("/polls/close")
def close_poll(id: str = Query(...), body: dict = Body(default={}), user_id: str = Depends(get_current_user)):
    """Ends the vote and books the winner (most votes; a tie goes to the earliest time), or the option given."""
    from datetime import datetime
    from app.bookings import create_booking, display_name
    p = _member_poll(id, user_id)
    view = _view(p, user_id)
    if not view["can_manage"]:
        raise HTTPException(status_code=403, detail="Only whoever started the poll, or the admin, can close it.")
    if p["closed"]:
        raise HTTPException(status_code=400, detail="This poll is already closed.")
    pick = body.get("option")
    if pick is None:
        pick = max(range(len(view["options"])), key=lambda i: (view["options"][i]["votes"], -datetime.fromisoformat(view["options"][i]["start"]).timestamp()))
    elif not isinstance(pick, int) or isinstance(pick, bool) or not 0 <= pick < len(p["options"]):
        raise HTTPException(status_code=400, detail="Pick an option from the poll.")
    opt = p["options"][pick]
    b = create_booking(p["group_id"], p["title"], datetime.fromisoformat(opt["start"]), datetime.fromisoformat(opt["end"]), user_id)
    conn.execute("UPDATE tf_polls SET closed = 1, winner = ?, booking_id = ? WHERE id = ?", (pick, b["id"], id))
    conn.commit()
    from app.notifications import notify_group
    notify_group(p["group_id"], "booked", f"The poll is closed: \"{p['title']}\" is booked", exclude=user_id,
                 data={"booking": b["id"], "start": b["start"]})
    return {"poll": _view(_poll(id), user_id), "booking_id": b["id"], "booked_by": display_name(user_id)}


@router.post("/polls/delete")
def delete_poll(id: str = Query(...), user_id: str = Depends(get_current_user)):
    p = _member_poll(id, user_id)
    if not _view(p, user_id)["can_manage"]:
        raise HTTPException(status_code=403, detail="Only whoever started the poll, or the admin, can delete it.")
    conn.execute("DELETE FROM tf_poll_votes WHERE poll_id = ?", (id,))
    conn.execute("DELETE FROM tf_polls WHERE id = ?", (id,))
    conn.commit()
    return {"deleted": True}
