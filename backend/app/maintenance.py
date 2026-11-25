"""Maintenance mode (Sam, 2026-11-25): the owner can switch the app off from the admin page.

While it's on, every app request gets a 503 with {"maintenance": true, ...} (the website shows its maintenance screen),
and a browser opening an API address directly (e.g. a Google sign-in link) is sent to the website instead.
Always open: /admin (so it can be switched back on), /health*, /status, and CORS preflights.
The switch is kept in the database, so a restart or redeploy doesn't turn it off.
"""
import json
import time

from fastapi import APIRouter

from app.db import conn

router = APIRouter()

conn.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
conn.commit()

KEY = "maintenance"
CACHE_SECONDS = 5  # every request checks the switch; read the database at most once per 5 s
OPEN_PREFIXES = ("/admin", "/health", "/status")
MAX_MESSAGE = 300

_cache = {"at": 0.0, "state": None}


def _default() -> dict:
    return {"on": False, "message": "", "until": None, "since": None}


def state(fresh: bool = False) -> dict:
    now = time.monotonic()
    if not fresh and _cache["state"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["state"]
    s = _default()
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (KEY,)).fetchone()
        if row and row[0]:
            s.update({k: v for k, v in json.loads(row[0]).items() if k in s})
    except Exception:
        # Can't read the switch (database hiccup): keep the last known state rather than flipping the app on or off.
        if _cache["state"] is not None:
            return _cache["state"]
    _cache.update(at=now, state=s)
    return s


def set_state(on: bool, message: str = "", until: int | None = None) -> dict:
    prev = state(fresh=True)
    s = {
        "on": bool(on),
        "message": str(message or "").strip()[:MAX_MESSAGE] if on else "",
        "until": int(until) if on and until else None,
        "since": (prev["since"] if prev["on"] and prev["since"] else int(time.time())) if on else None,
    }
    conn.execute("DELETE FROM app_settings WHERE key = ?", (KEY,))
    conn.execute("INSERT INTO app_settings (key, value) VALUES (?, ?)", (KEY, json.dumps(s)))
    conn.commit()
    _cache.update(at=time.monotonic(), state=s)
    return s


def public(s: dict | None = None) -> dict:
    s = s or state()
    return {"maintenance": s["on"], "message": s["message"], "until": s["until"], "since": s["since"]}


def blocks(path: str, method: str) -> bool:
    """True when this request must be turned away because the app is in maintenance."""
    if method == "OPTIONS" or path == "/" or path.startswith(OPEN_PREFIXES):
        return False
    return state()["on"]


@router.get("/status")
def status():
    """Public: is the app up? The website checks this when it opens and while showing the maintenance screen."""
    return public()
