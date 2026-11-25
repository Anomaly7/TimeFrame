"""Auto-sync for Google Calendar (2026-11-25).

Google busy times used to be a snapshot from sign-in, so a group's free times drifted out of date. Now:
- Every import records when it happened (calendar_sync), so the app can show "Updated 2 h ago".
- If GOOGLE_TOKEN_KEY is set on the server (a Fernet key: `python backend/sync_setup.py`), the Google refresh token
  from sign-in is kept, encrypted with that key, and busy times re-sync every few hours plus on "Sync now".
  Without the key nothing is stored and "Sync now" sends you through Google sign-in again (same result, one click).
- Disconnect (or account deletion) deletes the token and revokes it at Google.

Read-only scope only (calendar.readonly), same as before: no new Google permission.
"""
import os
import threading
import time as _time
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, HTTPException

from app.auth_utils import RateLimiter, get_current_user
from app.db import conn
from app.schema import ensure_tables

router = APIRouter()

STALE_SECONDS = 3 * 60 * 60  # re-sync anything older than this
LOOP_SECONDS = 20 * 60
sync_limiter = RateLimiter(max_attempts=4, window_seconds=300)

ensure_tables([
    "CREATE TABLE IF NOT EXISTS calendar_sync (user_id TEXT, source TEXT, synced_at BIGINT, error TEXT, PRIMARY KEY (user_id, source))",
    "CREATE TABLE IF NOT EXISTS google_tokens (user_id TEXT PRIMARY KEY, token TEXT, updated_at BIGINT)",
], ["calendar_sync", "google_tokens"])


def _fernet():
    key = os.getenv("GOOGLE_TOKEN_KEY")
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode())
    except Exception:
        print("GOOGLE_TOKEN_KEY is set but isn't a valid key: auto-sync stays off.")
        return None


def auto_sync_available() -> bool:
    return _fernet() is not None


def _key(user_id: str) -> str:
    return (user_id or "").strip().lower()


def mark_synced(user_id: str, source: str, error: str | None = None) -> None:
    """Records an import (or a failed re-sync). The caller commits."""
    now = int(_time.time())
    if error:
        conn.execute(
            "INSERT INTO calendar_sync (user_id, source, synced_at, error) VALUES (?, ?, NULL, ?) "
            "ON CONFLICT (user_id, source) DO UPDATE SET error = excluded.error", (_key(user_id), source, error))
    else:
        conn.execute(
            "INSERT INTO calendar_sync (user_id, source, synced_at, error) VALUES (?, ?, ?, NULL) "
            "ON CONFLICT (user_id, source) DO UPDATE SET synced_at = excluded.synced_at, error = NULL",
            (_key(user_id), source, now))


def sync_info(user_id: str, source: str) -> dict:
    row = conn.execute("SELECT synced_at, error FROM calendar_sync WHERE user_id = ? AND source = ?",
                       (_key(user_id), source)).fetchone()
    return {"synced_at": row[0] if row else None, "sync_error": row[1] if row else None}


def save_refresh_token(user_id: str, refresh_token: str | None) -> None:
    f = _fernet()
    if not f or not refresh_token:
        return
    conn.execute(
        "INSERT INTO google_tokens (user_id, token, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT (user_id) DO UPDATE SET token = excluded.token, updated_at = excluded.updated_at",
        (_key(user_id), f.encrypt(refresh_token.encode()).decode(), int(_time.time())))


def _refresh_token(user_id: str) -> str | None:
    f = _fernet()
    if not f:
        return None
    row = conn.execute("SELECT token FROM google_tokens WHERE user_id = ?", (_key(user_id),)).fetchone()
    if not row:
        return None
    try:
        return f.decrypt(row[0].encode()).decode()
    except Exception:
        return None  # key was rotated: they reconnect once


def has_token(user_id: str) -> bool:
    return auto_sync_available() and conn.execute(
        "SELECT 1 FROM google_tokens WHERE user_id = ?", (_key(user_id),)).fetchone() is not None


def forget_token(user_id: str, revoke: bool = True) -> None:
    """Deletes the stored token (Disconnect, account deletion) and revokes it at Google. The caller commits."""
    token = _refresh_token(user_id) if revoke else None
    conn.execute("DELETE FROM google_tokens WHERE user_id = ?", (_key(user_id),))
    if token:
        try:
            data = urllib.parse.urlencode({"token": token}).encode()
            urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/revoke", data=data), timeout=10)
        except Exception:
            pass  # already revoked at Google, or Google is down: it's gone from TimeFrame either way


def _credentials(refresh_token: str):
    from google.oauth2.credentials import Credentials
    from app.google_auth import SCOPES
    return Credentials(token=None, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token",
                       client_id=os.getenv("GOOGLE_CLIENT_ID"), client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
                       scopes=SCOPES)


def resync(user_id: str) -> bool:
    """Re-imports one person's Google busy times with their stored token. False if there's no usable token."""
    token = _refresh_token(user_id)
    if not token:
        return False
    from app.google_auth import import_google_events
    try:
        import_google_events(_credentials(token), expect_user=user_id)
        return True
    except Exception as e:
        from google.auth.exceptions import RefreshError
        if isinstance(e, RefreshError):
            # They removed TimeFrame's access in their Google account: stop trying, ask them to reconnect.
            forget_token(user_id, revoke=False)
            mark_synced(user_id, "google", "Google access was removed. Reconnect Google Calendar to keep syncing.")
        else:
            mark_synced(user_id, "google", "Couldn't reach Google Calendar. Trying again soon.")
        conn.commit()
        return False


_running = set()
_running_lock = threading.Lock()


def resync_in_background(user_id: str) -> None:
    key = _key(user_id)
    with _running_lock:
        if key in _running:
            return
        _running.add(key)

    def run():
        try:
            resync(user_id)
        except Exception as e:
            print(f"Background Google sync failed: {e}")
        finally:
            with _running_lock:
                _running.discard(key)
    threading.Thread(target=run, daemon=True).start()


def stale(user_id: str) -> bool:
    info = sync_info(user_id, "google")
    return not info["synced_at"] or _time.time() - info["synced_at"] > STALE_SECONDS


def sync_stale_users() -> int:
    """One pass of the background loop: re-syncs everyone with a token whose data is older than STALE_SECONDS."""
    cutoff = int(_time.time()) - STALE_SECONDS
    rows = conn.execute(
        "SELECT t.user_id FROM google_tokens t LEFT JOIN calendar_sync s ON s.user_id = t.user_id AND s.source = 'google' "
        "WHERE s.synced_at IS NULL OR s.synced_at < ?", (cutoff,)).fetchall()
    done = 0
    for (uid,) in rows:
        if resync(uid):
            done += 1
    return done


def start_background_loop() -> None:
    """Runs while the server is awake (Render's free plan sleeps; opening the app also triggers a sync)."""
    if not auto_sync_available() or os.getenv("DISABLE_BACKGROUND_JOBS") == "1":
        return

    def loop():
        while True:
            _time.sleep(LOOP_SECONDS)
            try:
                n = sync_stale_users()
                if n:
                    print(f"Auto-sync: refreshed {n} Google calendar(s)")
            except Exception as e:
                print(f"Auto-sync pass failed: {e}")
    threading.Thread(target=loop, daemon=True, name="google-auto-sync").start()


@router.post("/sync/google")
def sync_now(user_id: str = Depends(get_current_user)):
    """"Sync now". With a stored token it re-imports right away; without one the app sends you through Google
    sign-in (reconnect: true)."""
    sync_limiter.check("user:" + _key(user_id))
    if not has_token(user_id):
        return {"synced": False, "reconnect": True}
    if not resync(user_id):
        info = sync_info(user_id, "google")
        raise HTTPException(status_code=502, detail=info["sync_error"] or "Couldn't sync Google Calendar.")
    return {"synced": True, **sync_info(user_id, "google")}
