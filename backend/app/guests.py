"""Guest links (2026-11-25): someone opens a group link, types their name, paints when they're busy. No account.

A guest is a real (password-less) TimeFrame user with an id like guest-abc123@guest.timeframecalender.com and a
session on that one browser. Guests can join the group whose link they opened, add busy times, vote in polls and
read the group's notes; they can't create groups, buy Pro or have a booking page. The group's admin can turn guest
joining off. Guest accounts have no email, so they can't sign in elsewhere: clearing the browser ends them.
"""
import secrets
import time as _time

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from app.auth_utils import REMEMBER_TTL_SECONDS, RateLimiter, clean_text, client_ip, create_session_token, get_current_user
from app.db import conn
from app.schema import ensure_tables

router = APIRouter()
GUEST_DOMAIN = "@guest.timeframecalender.com"
guest_ip_limiter = RateLimiter(max_attempts=10, window_seconds=3600)
guest_site_limiter = RateLimiter(max_attempts=300, window_seconds=3600)

ensure_tables([
    "CREATE TABLE IF NOT EXISTS group_prefs (group_id TEXT PRIMARY KEY, allow_guests INTEGER DEFAULT 1, pinned_note TEXT)",
], ["group_prefs"])


def is_guest(user_id: str) -> bool:
    return (user_id or "").strip().lower().endswith(GUEST_DOMAIN)


def require_account(user_id: str, what: str = "That") -> None:
    if is_guest(user_id):
        raise HTTPException(status_code=403, detail=f"{what} needs a free TimeFrame account. Guests can't do it.")


def guests_allowed(group_id: str) -> bool:
    row = conn.execute("SELECT allow_guests FROM group_prefs WHERE group_id = ?", (group_id,)).fetchone()
    return row is None or row[0] is None or bool(row[0])


def _open_group(group_id: str):
    from app.group_availability import GROUP_ID_RE, group_row
    if not GROUP_ID_RE.match(group_id or ""):
        raise HTTPException(status_code=400, detail="That group link isn't valid.")
    if conn.execute("SELECT 1 FROM deleted_groups WHERE id = ?", (group_id,)).fetchone():
        raise HTTPException(status_code=410, detail="This group was deleted by its admin.")
    info = group_row(group_id)
    if not info:
        raise HTTPException(status_code=404, detail="That group doesn't exist (yet). Ask for a new link.")
    return info


@router.get("/guest/group")
def guest_group_info(request: Request, group_id: str = Query(...)):
    """What the sign-in page shows someone who opened a group link: its name and whether guests can join."""
    from app.group_availability import join_limiter
    join_limiter.check("ip:" + client_ip(request))
    name, _owner, _settings = _open_group(group_id)
    members = conn.execute("SELECT COUNT(DISTINCT LOWER(TRIM(user_id))) FROM group_members WHERE group_id = ?",
                           (group_id,)).fetchone()[0]
    return {"name": name, "members": members, "guests_allowed": guests_allowed(group_id)}


@router.post("/guest/join")
def guest_join(request: Request, body: dict = Body(...)):
    from app.group_availability import join_limiter
    group_id = str(body.get("group_id") or "")
    name = clean_text(body.get("name"), 40)
    if not name:
        raise HTTPException(status_code=400, detail="Type your name so the group knows who you are.")
    ip = client_ip(request)
    join_limiter.check("ip:" + ip)
    _open_group(group_id)
    if not guests_allowed(group_id):
        raise HTTPException(status_code=403, detail="This group's admin has turned off guest access. Sign in to join.")
    guest_ip_limiter.check("guest-ip:" + ip)
    guest_site_limiter.check("guest-all")
    user_id = "guest-" + secrets.token_hex(6) + GUEST_DOMAIN
    conn.execute("INSERT INTO users (id, email, email_verified, display_name) VALUES (?, ?, FALSE, ?)",
                 (user_id, user_id, name))
    conn.execute("INSERT INTO group_members (group_id, user_id) VALUES (?, ?)", (group_id, user_id))
    conn.commit()
    from app.notifications import notify_group
    notify_group(group_id, "joined", f"{name} joined as a guest", exclude=user_id)
    return {"token": create_session_token(user_id, REMEMBER_TTL_SECONDS), "user": user_id, "name": name}


@router.post("/groups/guests")
def set_guest_access(group_id: str = Query(...), allow: bool = Query(...), user_id: str = Depends(get_current_user)):
    """Admin only: let people join this group's link as guests (on by default)."""
    from app.group_availability import require_admin
    require_admin(group_id, user_id)
    conn.execute("INSERT INTO group_prefs (group_id, allow_guests) VALUES (?, ?) "
                 "ON CONFLICT (group_id) DO UPDATE SET allow_guests = excluded.allow_guests", (group_id, int(allow)))
    conn.commit()
    return {"guests_allowed": allow}
