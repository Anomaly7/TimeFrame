"""Notifications (2026-11-25): someone joins your group, a time is booked or cancelled, a poll opens, and a
reminder an hour before a booked meeting.

- In the app: the bell in the top bar (stored here, newest first, kept 30 days).
- Push: phones and browsers that turned on notifications (Web Push; on iPhone only once TimeFrame is added to the
  home screen). Needs VAPID_PRIVATE_KEY on the server (`python backend/keys_setup.py`); without it push is off.
- Email: not built yet. It needs an email provider account (Sam's decision), then a send function here.

Render's free plan sleeps when nobody is using the app, so the reminder loop also runs whenever someone opens the
bell; a reminder can be late if the server was asleep, never sent twice.
"""
import base64
import json
import os
import secrets
import threading
import time as _time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException

from app.auth_utils import get_current_user
from app.db import conn
from app.schema import ensure_tables

router = APIRouter()
KEEP_SECONDS = 30 * 86400
REMIND_BEFORE = timedelta(minutes=60)
MAX_SUBS_PER_USER = 10

ensure_tables([
    """CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, user_id TEXT, kind TEXT, text TEXT, data TEXT,
        created_at BIGINT, is_read INTEGER DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS notifications_user ON notifications (user_id)",
    "CREATE TABLE IF NOT EXISTS push_subs (endpoint TEXT PRIMARY KEY, user_id TEXT, p256dh TEXT, auth TEXT, created_at BIGINT)",
    "CREATE TABLE IF NOT EXISTS booking_reminders (booking_id TEXT PRIMARY KEY, at BIGINT)",
], ["notifications", "push_subs", "booking_reminders"])


def _k(u) -> str:
    return (u or "").strip().lower()


# ---------- Web Push ----------
def _vapid_private():
    return (os.getenv("VAPID_PRIVATE_KEY") or "").strip() or None


def vapid_public_key() -> str | None:
    """The browser-side key (uncompressed P-256 point, base64url), worked out from the private key."""
    priv = _vapid_private()
    if not priv:
        return None
    try:
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid
        raw = Vapid.from_string(priv).public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    except Exception:
        print("VAPID_PRIVATE_KEY is set but isn't a valid key: push stays off.")
        return None


def _send_push(user_id: str, payload: dict) -> None:
    priv = _vapid_private()
    if not priv:
        return
    subs = conn.execute("SELECT endpoint, p256dh, auth FROM push_subs WHERE user_id = ?", (_k(user_id),)).fetchall()
    if not subs:
        return

    def run():
        try:
            from pywebpush import WebPushException, webpush
        except ImportError:
            return
        claims = {"sub": os.getenv("VAPID_SUBJECT", "mailto:sam.esebor@gmail.com")}
        for endpoint, p256dh, auth in subs:
            try:
                webpush({"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}, json.dumps(payload),
                        vapid_private_key=priv, vapid_claims=dict(claims), ttl=3600, timeout=10)
            except WebPushException as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status in (404, 410):  # that browser unsubscribed or the subscription expired
                    try:
                        conn.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))
                        conn.commit()
                    except Exception:
                        pass
            except Exception as e:
                print(f"Push failed: {e}")
    threading.Thread(target=run, daemon=True).start()


# ---------- Sending ----------
def notify_user(user_id, kind, text, data=None) -> None:
    now = int(_time.time())
    conn.execute("INSERT INTO notifications (id, user_id, kind, text, data, created_at, is_read) VALUES (?, ?, ?, ?, ?, ?, 0)",
                 (secrets.token_urlsafe(9), _k(user_id), kind, text[:300], json.dumps(data or {}), now))
    conn.execute("DELETE FROM notifications WHERE user_id = ? AND created_at < ?", (_k(user_id), now - KEEP_SECONDS))
    conn.commit()
    _send_push(user_id, {"title": "TimeFrame", "body": text[:300], "kind": kind, "data": data or {}})


def group_member_ids(group_id: str) -> list[str]:
    seen, out = set(), []
    for (uid,) in conn.execute("SELECT user_id FROM group_members WHERE group_id = ?", (group_id,)).fetchall():
        if _k(uid) not in seen:
            seen.add(_k(uid))
            out.append(uid)
    return out


def notify_group(group_id, kind, text, exclude=None, data=None) -> None:
    from app.group_availability import group_row
    name = (group_row(group_id) or (None,))[0]
    full = f"{name}: {text}" if name else text
    for uid in group_member_ids(group_id):
        if exclude and _k(uid) == _k(exclude):
            continue
        try:
            notify_user(uid, kind, full, {**(data or {}), "group": group_id})
        except Exception as e:
            print(f"Notification failed: {e}")


# ---------- Reminders ----------
def send_due_reminders() -> int:
    """Booked meetings starting within the next hour that haven't had their reminder. Each is sent once."""
    from app.bookings import COLS, _row_to_dict
    now = datetime.now(timezone.utc)
    sent = 0
    for row in conn.execute(f"SELECT {COLS} FROM bookings WHERE cancelled = 0").fetchall():
        b = _row_to_dict(row)
        start = datetime.fromisoformat(b["start"])
        if not (now <= start <= now + REMIND_BEFORE):
            continue
        if conn.execute("SELECT 1 FROM booking_reminders WHERE booking_id = ?", (b["id"],)).fetchone():
            continue
        conn.execute("INSERT INTO booking_reminders (booking_id, at) VALUES (?, ?)", (b["id"], int(_time.time())))
        conn.commit()
        mins = max(1, round((start - now).total_seconds() / 60))
        text = f"Reminder: \"{b['title']}\" starts in {mins} min"
        people = group_member_ids(b["group_id"]) if b["group_id"] else [b["host"]]
        for uid in people:
            if uid:
                notify_user(uid, "reminder", text, {"booking": b["id"], "start": b["start"], "group": b["group_id"]})
        sent += 1
    return sent


_last_check = {"at": 0.0}
_check_lock = threading.Lock()


def maybe_send_reminders() -> None:
    """At most once a minute, whoever triggers it."""
    with _check_lock:
        if _time.time() - _last_check["at"] < 60:
            return
        _last_check["at"] = _time.time()
    try:
        send_due_reminders()
    except Exception as e:
        print(f"Reminder pass failed: {e}")


def start_reminder_loop() -> None:
    if os.getenv("DISABLE_BACKGROUND_JOBS") == "1":
        return

    def loop():
        while True:
            _time.sleep(300)
            maybe_send_reminders()
    threading.Thread(target=loop, daemon=True, name="booking-reminders").start()


# ---------- API ----------
@router.get("/notifications")
def list_notifications(user_id: str = Depends(get_current_user)):
    maybe_send_reminders()
    rows = conn.execute("SELECT id, kind, text, data, created_at, is_read FROM notifications WHERE user_id = ? "
                        "ORDER BY created_at DESC LIMIT 40", (_k(user_id),)).fetchall()
    items = [{"id": r[0], "kind": r[1], "text": r[2], "data": json.loads(r[3] or "{}"), "created_at": r[4], "read": bool(r[5])}
             for r in rows]
    return {"notifications": items, "unread": sum(1 for i in items if not i["read"])}


@router.post("/notifications/read")
def mark_read(user_id: str = Depends(get_current_user)):
    conn.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (_k(user_id),))
    conn.commit()
    return {"read": True}


@router.get("/push/key")
def push_key():
    key = vapid_public_key()
    return {"available": bool(key), "key": key}


@router.post("/push/subscribe")
def push_subscribe(body: dict = Body(...), user_id: str = Depends(get_current_user)):
    endpoint = body.get("endpoint")
    keys = body.get("keys") or {}
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > 1000 \
            or not isinstance(keys.get("p256dh"), str) or not isinstance(keys.get("auth"), str) \
            or len(keys["p256dh"]) > 200 or len(keys["auth"]) > 100:
        raise HTTPException(status_code=400, detail="That isn't a push subscription.")
    if not vapid_public_key():
        raise HTTPException(status_code=503, detail="Push notifications aren't switched on yet.")
    conn.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))
    conn.execute("INSERT INTO push_subs (endpoint, user_id, p256dh, auth, created_at) VALUES (?, ?, ?, ?, ?)",
                 (endpoint, _k(user_id), keys["p256dh"], keys["auth"], int(_time.time())))
    # Oldest devices beyond the limit drop off.
    rows = conn.execute("SELECT endpoint FROM push_subs WHERE user_id = ? ORDER BY created_at DESC", (_k(user_id),)).fetchall()
    for (old,) in rows[MAX_SUBS_PER_USER:]:
        conn.execute("DELETE FROM push_subs WHERE endpoint = ?", (old,))
    conn.commit()
    return {"subscribed": True}


@router.post("/push/unsubscribe")
def push_unsubscribe(body: dict = Body(...), user_id: str = Depends(get_current_user)):
    conn.execute("DELETE FROM push_subs WHERE endpoint = ? AND user_id = ?", (str(body.get("endpoint") or ""), _k(user_id)))
    conn.commit()
    return {"subscribed": False}
