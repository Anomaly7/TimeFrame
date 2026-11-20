"""Owner-only admin page (Sam, 2026-11-20): accounts, Pro status, and app health.

Lives on the API server. Open it at https://www.timeframecalender.com/admin: Vercel forwards that address here
(frontend/vercel.json), so the browser only ever talks to the website's own domain. The Render address works too.

Security, layer by layer:
- OFF unless ADMIN_PASSWORD (16+ characters) AND ADMIN_TOTP_SECRET (authenticator app) are set in Render.
  Until then every /admin address answers 404, as if it didn't exist.
- Sign-in needs both the password and a 6-digit authenticator code (each code works once).
- Lockouts, counted in the database so a restart doesn't reset them: 5 failures from one address in 15 minutes
  locks that address; 10 failures from anywhere in an hour closes the admin sign-in for everyone for an hour.
- Sam's phone is alerted (OWNER_NTFY_TOPIC) on every successful sign-in and on every lockout.
- The session is an HttpOnly, Secure, SameSite=Strict cookie (__Host- prefix) that lasts 2 hours. It is signed with a
  key derived from SESSION_SECRET + ADMIN_PASSWORD + ADMIN_TOTP_SECRET, so changing either admin secret in Render
  signs out every admin session at once.
- Every admin API call needs the X-TF-Admin header and, if the browser sends one, an Origin of this same server, so
  other sites can't make the browser act for you (on top of SameSite=Strict).
- Strict headers on every admin response: no caching, no framing, no outside scripts (CSP), no referrer, no indexing.
- Not in the public API docs (/docs).
- Shows accounts, plans and counts only: never anyone's calendar events.
- Everything done here is written to admin_audit and shown on the page.
"""
import base64
import hashlib
import hmac
import json
import os
import struct
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import jwt
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from app import billing
from app.auth_utils import ALGORITHM, RateLimiter, client_ip
from app.db import conn

router = APIRouter(include_in_schema=False)

STATIC = Path(__file__).parent / "admin_static"
COOKIE = "__Host-tfadmin"
SESSION_SECONDS = 2 * 3600
IP_MAX, IP_WINDOW = 5, 15 * 60
ALL_MAX, ALL_WINDOW = 10, 3600
MIN_PASSWORD = 16
STARTED = int(time.time())

# A cheap first line before the database is touched at all.
_flood = RateLimiter(max_attempts=20, window_seconds=15 * 60)
_used_codes: dict[int, float] = {}  # TOTP time-steps already used (no replaying a code someone saw)
_used_lock = threading.Lock()

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Strict-Transport-Security": "max-age=31536000",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}


# ---- configuration ----------------------------------------------------------
def _password() -> str:
    return os.getenv("ADMIN_PASSWORD", "")


def _totp_secret() -> bytes | None:
    raw = os.getenv("ADMIN_TOTP_SECRET", "").strip().replace(" ", "").upper()
    if not raw:
        return None
    try:
        key = base64.b32decode(raw + "=" * (-len(raw) % 8))
    except Exception:
        return None
    return key if len(key) >= 10 else None  # 80+ bits


def enabled() -> bool:
    return len(_password()) >= MIN_PASSWORD and _totp_secret() is not None


def _not_found():
    raise HTTPException(status_code=404, detail="Not Found")


def _signing_key() -> str:
    material = "|".join([os.getenv("SESSION_SECRET", ""), _password(), os.getenv("ADMIN_TOTP_SECRET", "")])
    return hmac.new(b"timeframe-admin-v1", material.encode(), hashlib.sha256).hexdigest()


# ---- authenticator codes (RFC 6238, the standard 6-digit / 30-second kind) ----
def _code_at(key: bytes, step: int) -> str:
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def _check_code(code: str) -> bool:
    key = _totp_secret()
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if not key or len(code) != 6:
        return False
    now_step = int(time.time()) // 30
    for step in (now_step - 1, now_step, now_step + 1):  # allow 30 s of clock drift either way
        if hmac.compare_digest(_code_at(key, step), code):
            with _used_lock:
                for s in [s for s, t in _used_codes.items() if t < time.time() - 300]:
                    del _used_codes[s]
                if step in _used_codes:
                    return False
                _used_codes[step] = time.time()
            return True
    return False


def _check_password(given: str) -> bool:
    real = _password()
    # Compare fixed-length hashes so the time taken says nothing about the length or the matching prefix.
    return bool(real) and hmac.compare_digest(
        hashlib.sha256(str(given or "").encode()).digest(), hashlib.sha256(real.encode()).digest())


# ---- audit log + phone alerts --------------------------------------------------
def audit(ip: str, action: str, detail: str = ""):
    conn.execute("INSERT INTO admin_audit (at, ip, action, detail) VALUES (?, ?, ?, ?)",
                 (int(time.time()), ip[:64], action[:40], detail[:300]))
    conn.commit()


def _count(action: str, since: int, ip: str | None = None) -> int:
    if ip is None:
        row = conn.execute("SELECT COUNT(*) FROM admin_audit WHERE action = ? AND at > ?", (action, since)).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM admin_audit WHERE action = ? AND at > ? AND ip = ?",
                           (action, since, ip)).fetchone()
    return int(row[0] or 0)


def alert(message: str):
    topic = os.getenv("OWNER_NTFY_TOPIC", "").strip()
    if not topic:
        return

    def send():
        try:
            req = urllib.request.Request(
                "https://ntfy.sh/" + urllib.parse.quote(topic, safe=""), data=message.encode(), method="POST",
                headers={"Title": "TimeFrame admin", "Priority": "high", "Tags": "lock"})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass

    threading.Thread(target=send, daemon=True).start()


# ---- sessions -------------------------------------------------------------------
def _issue(response: Response, ip: str):
    token = jwt.encode({"typ": "admin", "sub": "owner", "ip": ip, "iat": int(time.time()),
                        "exp": int(time.time()) + SESSION_SECONDS}, _signing_key(), algorithm=ALGORITHM)
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, path="/", secure=True, httponly=True, samesite="strict")


def _site_hosts() -> set[str]:
    """The page is also reached at https://www.timeframecalender.com/admin: Vercel forwards /admin there to this
    server (frontend/vercel.json), so to the browser it is the website's own address."""
    raw = os.getenv("ADMIN_SITE_HOSTS", "www.timeframecalender.com,timeframecalender.com")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True  # same-origin GETs often omit it; the custom header below still has to be there
    parts = urllib.parse.urlsplit(origin)
    if parts.scheme != "https" and parts.hostname not in ("localhost", "127.0.0.1", "testserver"):
        return False
    host = parts.netloc.lower()
    return host == (request.headers.get("host") or "").lower() or host in _site_hosts()


def _guard_api(request: Request):
    """Every /admin/api call: admin on, our own page, no cross-site."""
    if not enabled():
        _not_found()
    if request.headers.get("x-tf-admin") != "1" or not _same_origin(request):
        raise HTTPException(status_code=403, detail="Forbidden")


def require_admin(request: Request) -> str:
    _guard_api(request)
    token = request.cookies.get(COOKIE, "")
    try:
        payload = jwt.decode(token, _signing_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Signed out. Sign in again.")
    if payload.get("typ") != "admin" or payload.get("sub") != "owner":
        raise HTTPException(status_code=401, detail="Signed out. Sign in again.")
    return client_ip(request)


def _secure(response: Response) -> Response:
    for k, v in SECURITY_HEADERS.items():
        response.headers[k] = v
    return response


# ---- the page itself ---------------------------------------------------------------
_FILES = {"admin": ("admin.html", "text/html; charset=utf-8"),
          "admin/app.js": ("admin.js", "text/javascript; charset=utf-8"),
          "admin/app.css": ("admin.css", "text/css; charset=utf-8")}


@router.get("/admin")
@router.get("/admin/app.js")
@router.get("/admin/app.css")
def admin_file(request: Request):
    if not enabled():
        _not_found()
    name, media = _FILES[request.url.path.strip("/")]
    return _secure(FileResponse(STATIC / name, media_type=media))


# ---- sign in / out -----------------------------------------------------------------
@router.post("/admin/api/login")
def login(request: Request, body: dict = Body(...)):
    _guard_api(request)
    ip = client_ip(request)
    _flood.check("admin:" + ip)
    now = int(time.time())
    if _count("login_failed", now - ALL_WINDOW) >= ALL_MAX:
        raise HTTPException(status_code=429, detail="Admin sign-in is closed for an hour after too many wrong tries.")
    if _count("login_failed", now - IP_WINDOW, ip) >= IP_MAX:
        raise HTTPException(status_code=429, detail="Too many wrong tries from here. Wait 15 minutes.")

    pw_ok = _check_password(body.get("password"))
    code_ok = pw_ok and _check_code(body.get("code"))  # a code is only "spent" with the right password
    if not (pw_ok and code_ok):
        audit(ip, "login_failed", "wrong password" if not pw_ok else "wrong or reused code")
        if _count("login_failed", now - ALL_WINDOW) >= ALL_MAX:
            alert(f"TimeFrame admin sign-in LOCKED for an hour: {ALL_MAX} wrong tries (latest from {ip}).")
        elif _count("login_failed", now - IP_WINDOW, ip) >= IP_MAX:
            alert(f"TimeFrame admin: {IP_MAX} wrong sign-in tries from {ip}; that address is locked for 15 minutes.")
        time.sleep(1)  # slows guessing a little more
        raise HTTPException(status_code=401, detail="Wrong password or code.")

    audit(ip, "login", request.headers.get("user-agent", "")[:200])
    alert(f"Someone signed in to the TimeFrame admin page from {ip}. If that wasn't you, change ADMIN_PASSWORD "
          "and ADMIN_TOTP_SECRET in Render now (that signs everyone out).")
    response = _secure(Response(content=json.dumps({"ok": True}), media_type="application/json"))
    _issue(response, ip)
    return response


@router.post("/admin/api/logout")
def logout(request: Request):
    _guard_api(request)
    response = _secure(Response(content=json.dumps({"ok": True}), media_type="application/json"))
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return response


def _json(data) -> Response:
    return _secure(Response(content=json.dumps(data), media_type="application/json"))


# ---- what the page shows ------------------------------------------------------------
@router.get("/admin/api/overview")
def overview(ip: str = Depends(require_admin)):
    one = lambda sql, p=(): int((conn.execute(sql, p).fetchone() or [0])[0] or 0)  # noqa: E731
    now = int(time.time())
    db_ok = True
    try:
        one("SELECT 1")
    except Exception:
        db_ok = False
    pro = {src or "other": n for src, n in conn.execute(
        "SELECT pro_source, COUNT(*) FROM users WHERE plan = 'pro' GROUP BY pro_source").fetchall()}
    sources = {s: n for s, n in conn.execute(
        "SELECT source, COUNT(DISTINCT user_id) FROM ("
        " SELECT user_id, source FROM busy_times UNION SELECT user_id, source FROM calendar_links) x GROUP BY source").fetchall()}
    key = billing._key()
    stripe_mode = "off" if not key else "live" if "_live_" in key else "test"
    return _json({
        "users": one("SELECT COUNT(*) FROM users"),
        "new7": one("SELECT COUNT(*) FROM users WHERE created_at > ?", (now - 7 * 86400,)),
        "new30": one("SELECT COUNT(*) FROM users WHERE created_at > ?", (now - 30 * 86400,)),
        "unknownJoin": one("SELECT COUNT(*) FROM users WHERE created_at IS NULL"),
        "pro": pro,
        "groups": one("SELECT COUNT(*) FROM groups"),
        "groupsUsed": one("SELECT COUNT(DISTINCT group_id) FROM group_members"),
        "members": one("SELECT COUNT(*) FROM group_members"),
        "calendars": sources,
        "health": {
            "database": db_ok, "stripe": stripe_mode, "coupon": bool(os.getenv("TIMEFRAME_COUPON", "").strip()),
            "tax": billing.COLLECT_TAX, "trialDays": billing.TRIAL_DAYS,
            "prices": {k: billing._money(v) for k, v in billing.PRICES.items()}, "currency": billing.CURRENCY.upper(),
            "alerts": bool(os.getenv("OWNER_NTFY_TOPIC", "").strip()), "upSince": STARTED,
        },
        "you": ip,
    })


def _like(q: str) -> str:
    q = q.strip().lower()[:100]
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/admin/api/users")
def users(q: str = "", page: int = 0, ip: str = Depends(require_admin)):
    page = max(0, min(int(page), 1000))
    rows = conn.execute(
        "SELECT id, email, display_name, password_hash IS NOT NULL, email_verified, plan, pro_source, pro_until, created_at, "
        " stripe_sub IS NOT NULL FROM users WHERE LOWER(COALESCE(email, id)) LIKE ? ESCAPE '\\' "
        "ORDER BY created_at DESC NULLS LAST, id LIMIT 51 OFFSET ?", (_like(q), page * 50)).fetchall()
    ids = [r[0] for r in rows[:50]]
    cal, member, owner = {}, {}, {}
    if ids:
        marks = ",".join("?" for _ in ids)
        for uid, src in conn.execute(
                f"SELECT DISTINCT user_id, source FROM busy_times WHERE user_id IN ({marks}) "
                f"UNION SELECT user_id, source FROM calendar_links WHERE user_id IN ({marks})", (*ids, *ids)).fetchall():
            cal.setdefault(uid, set()).add(src)
        member = dict(conn.execute(f"SELECT user_id, COUNT(*) FROM group_members WHERE user_id IN ({marks}) GROUP BY user_id", ids).fetchall())
        owner = dict(conn.execute(f"SELECT owner, COUNT(*) FROM groups WHERE owner IN ({marks}) GROUP BY owner", ids).fetchall())
    out = []
    for r in rows[:50]:
        uid = r[0]
        out.append({
            "id": uid, "email": r[1] or uid, "name": r[2] or "",
            "password": bool(r[3]), "googleVerified": bool(r[4]),
            "calendars": sorted(c for c in cal.get(uid, set()) if c),
            "plan": "pro" if r[5] == "pro" else "free", "source": r[6] if r[5] == "pro" else None,
            "proUntil": int(r[7]) if r[7] else None, "joined": int(r[8]) if r[8] else None, "hasSub": bool(r[9]),
            "groups": int(member.get(uid, 0)), "owns": int(owner.get(uid, 0)),
        })
    return _json({"users": out, "more": len(rows) > 50, "page": page})


@router.post("/admin/api/users/pro")
def change_pro(body: dict = Body(...), ip: str = Depends(require_admin)):
    uid = str(body.get("id") or "")[:320]
    action = body.get("action")
    row = billing._row(uid) if uid else None
    if not row:
        raise HTTPException(status_code=404, detail="No account with that email.")
    plan, source, _customer, sub_id, _until, _email = row
    if action == "grant":
        if plan == "pro" and source == "stripe" and billing.is_pro(uid):
            raise HTTPException(status_code=409, detail="They already pay for Pro. Cancel it in Stripe first if you want to give it free.")
        billing._set(uid, plan="pro", pro_source="manual")
        audit(ip, "grant_pro", uid)
        return _json({"ok": True, "message": f"{uid} now has Pro (given by you)."})
    if action == "revoke":
        if plan != "pro":
            return _json({"ok": True, "message": f"{uid} is already on Free."})
        if source == "stripe" and sub_id:
            raise HTTPException(status_code=409, detail="They pay through Stripe. Cancel the subscription in Stripe instead, or they'd keep being charged.")
        billing._set(uid, plan=None, pro_source=None)
        audit(ip, "revoke_pro", f"{uid} (was {source})")
        return _json({"ok": True, "message": f"{uid} is back on Free."})
    if action == "recheck":
        if not sub_id:
            raise HTTPException(status_code=400, detail="This account has no Stripe subscription to check.")
        try:
            sub = billing.stripe("GET", f"subscriptions/{sub_id}")
        except billing.StripeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        status = sub.get("status")
        if status in billing.ACTIVE:
            billing._set(uid, plan="pro", pro_source="stripe", pro_until=billing._period_end(sub))
        elif source == "stripe":
            billing._set(uid, plan=None)
        audit(ip, "recheck_stripe", f"{uid}: {status}")
        return _json({"ok": True, "message": f"Stripe says the subscription is {status}."})
    raise HTTPException(status_code=400, detail="Unknown action.")


@router.get("/admin/api/audit")
def audit_log(ip: str = Depends(require_admin)):
    rows = conn.execute("SELECT at, ip, action, detail FROM admin_audit ORDER BY at DESC LIMIT 40").fetchall()
    return _json({"events": [{"at": int(a), "ip": b, "action": c, "detail": d or ""} for a, b, c, d in rows]})
