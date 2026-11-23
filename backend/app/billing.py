"""TimeFrame Pro (2026-11-20).

Free: your own calendar (every source) and joining groups.
Pro: creating groups and the Chrome extension.

Ways to get Pro:
- "early": every account that existed when Pro launched keeps it, free, for good (set once in db.py).
- "coupon": the one coupon code in TIMEFRAME_COUPON (Render > Environment) gives Pro for free, no card.
- "stripe": a Stripe subscription ($4.47/month or $30.40/year CAD by default, 7-day free trial).

Stripe is called over plain HTTPS (no SDK). There is no webhook to set up: a subscription's paid-through
date is saved, and once it passes, the next status check asks Stripe whether it's still active.
"""
import base64
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.auth_utils import RateLimiter, client_ip, get_current_user
from app.db import conn

router = APIRouter()

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://www.timeframecalender.com").rstrip("/")
CURRENCY = os.getenv("PRO_CURRENCY", "cad").lower()
# $4.47/month (Sam, 2026-11-20): after Stripe's Canadian fees (2.9% + $0.30 card, 0.7% Billing) he keeps about $4.00; $30.40/year nets about $29.00.
PRICES = {  # cents
    "month": int(os.getenv("PRO_PRICE_MONTH_CENTS", "447")),
    "year": int(os.getenv("PRO_PRICE_YEAR_CENTS", "3040")),
}
TRIAL_DAYS = int(os.getenv("PRO_TRIAL_DAYS", "7"))
# Stripe tax category. Required when the Stripe account uses Managed Payments (Stripe handles sales tax):
# txcd_10103000 = Software as a Service (SaaS), personal use.
TAX_CODE = os.getenv("PRO_TAX_CODE", "txcd_10103000").strip()
# Sales tax goes ON TOP of the advertised price, paid by the customer (Sam, 2026-11-20: he keeps the full price).
# Stripe Tax works out the right GST/HST/PST from the customer's address. Only switch on (PRO_COLLECT_TAX=1 in Render)
# once registered for GST/HST and Stripe Tax is set up (Stripe > Settings > Tax), since unregistered sellers may not charge it.
COLLECT_TAX = os.getenv("PRO_COLLECT_TAX", "").strip().lower() in ("1", "true", "yes", "on")
GRACE_SECONDS = 24 * 3600  # don't drop someone the minute a renewal is due
ACTIVE = {"active", "trialing", "past_due"}

coupon_limiter = RateLimiter(max_attempts=8, window_seconds=3600)  # per account and per address
# Across ALL accounts: someone making lots of accounts to guess the code. 40 wrong codes in an hour closes coupon
# redemption for everyone for the rest of that hour, and Sam's phone is alerted once.
coupon_wrong_total = RateLimiter(max_attempts=40, window_seconds=3600)
_coupon_lock_alerted = {"at": 0.0}


def _alert_owner(message: str):
    try:
        from app.admin import alert
        alert(message)
    except Exception:
        pass


def _coupon_cap() -> int:
    """Optional cap on how many accounts can use the coupon (TIMEFRAME_COUPON_MAX in Render; unset or 0 = no cap)."""
    try:
        return max(0, int(os.getenv("TIMEFRAME_COUPON_MAX", "0") or 0))
    except ValueError:
        return 0


class StripeError(Exception):
    pass


def _key() -> str:
    return os.getenv("STRIPE_SECRET_KEY", "").strip()


def _flatten(data, prefix=""):
    """Stripe's form encoding: {"a": {"b": 1}} -> a[b]=1, lists -> a[0]=..."""
    out = []
    items = data.items() if isinstance(data, dict) else enumerate(data)
    for k, v in items:
        name = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, (dict, list)):
            out.extend(_flatten(v, name))
        elif isinstance(v, bool):
            out.append((name, "true" if v else "false"))
        elif v is not None:
            out.append((name, str(v)))
    return out


def stripe(method: str, path: str, data=None) -> dict:
    key = _key()
    if not key:
        raise StripeError("Payments aren't set up yet.")
    body = urllib.parse.urlencode(_flatten(data or {})).encode() if data else None
    url = f"https://api.stripe.com/v1/{path}"
    if method == "GET" and data:
        url += "?" + body.decode()
        body = None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": "Basic " + base64.b64encode(f"{key}:".encode()).decode(),
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise StripeError(msg or f"Stripe answered {e.code}.")
    except urllib.error.URLError:
        raise StripeError("Couldn't reach Stripe.")


def _row(user_id: str):
    return conn.execute(
        "SELECT plan, pro_source, stripe_customer, stripe_sub, pro_until, email FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def _set(user_id: str, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE users SET {cols} WHERE id = ?", (*fields.values(), user_id))
    conn.commit()


def _period_end(sub: dict) -> int:
    """Paid-through time of a subscription (top level on older API versions, per item on newer ones)."""
    end = sub.get("current_period_end")
    if not end:
        items = (sub.get("items") or {}).get("data") or []
        end = max((i.get("current_period_end") or 0) for i in items) if items else 0
    return int(end or sub.get("trial_end") or 0)


def is_pro(user_id: str) -> bool:
    row = _row(user_id)
    if not row or row[0] != "pro":
        return False
    source, sub_id, until = row[1], row[3], row[4]
    if source != "stripe":
        return True  # early supporters, the coupon, or set by hand
    if until and time.time() < int(until) + GRACE_SECONDS:
        return True
    # Paid-through date passed: ask Stripe once whether it renewed.
    try:
        sub = stripe("GET", f"subscriptions/{sub_id}")
    except StripeError:
        return bool(until and time.time() < int(until) + 7 * GRACE_SECONDS)  # Stripe down: a week's grace
    if sub.get("status") in ACTIVE:
        _set(user_id, pro_until=_period_end(sub))
        return True
    _set(user_id, plan=None)
    return False


def require_pro(user_id: str, what: str = "This"):
    if not is_pro(user_id):
        raise HTTPException(status_code=402, detail=f"{what} is part of TimeFrame Pro.")


def _money(cents: int) -> str:
    return f"${cents / 100:.2f}".replace(".00", "")


@router.get("/billing/status")
def billing_status(user_id: str = Depends(get_current_user)):
    pro = is_pro(user_id)
    row = _row(user_id)
    source = row[1] if row and pro else None
    trial = False
    if pro and source == "stripe" and row[3]:
        try:
            trial = stripe("GET", f"subscriptions/{row[3]}").get("status") == "trialing"
        except StripeError:
            pass
    return {
        "pro": pro,
        "source": source,
        "trial": trial,
        "pro_until": int(row[4]) if pro and source == "stripe" and row[4] else None,
        "can_manage": bool(row and row[2] and _key()),
        "checkout_available": bool(_key()),
        "coupons": bool(os.getenv("TIMEFRAME_COUPON", "").strip()),
        "currency": CURRENCY.upper(),
        "prices": {k: _money(v) for k, v in PRICES.items()},
        "trial_days": TRIAL_DAYS,
        "tax_added": COLLECT_TAX,
    }


@router.post("/billing/redeem")
def redeem_coupon(request: Request, body: dict = Body(...), user_id: str = Depends(get_current_user)):
    """The one coupon: Pro for free, no card. Using it again on the same account changes nothing."""
    if coupon_wrong_total.over("all"):
        raise HTTPException(status_code=429, detail="Coupon codes are paused for a while. Try again later.")
    coupon_limiter.check("coupon:" + user_id, "ip:" + client_ip(request))
    code = str(body.get("code") or "").strip().upper()
    real = os.getenv("TIMEFRAME_COUPON", "").strip().upper()
    if not real or not code or not hmac.compare_digest(code.encode(), real.encode()):
        if real and code and coupon_wrong_total.record("all") >= coupon_wrong_total.max_attempts                 and time.time() - _coupon_lock_alerted["at"] > 3600:
            _coupon_lock_alerted["at"] = time.time()
            _alert_owner("TimeFrame: 40 wrong coupon codes in an hour. Coupon redemption is paused for an hour.")
        raise HTTPException(status_code=400, detail="That coupon code isn't valid.")
    row = _row(user_id)
    if row and row[0] == "pro" and row[1] == "coupon":
        return {"pro": True, "source": "coupon", "still_paying": False}  # already redeemed: nothing to do
    cap = _coupon_cap()
    if cap and conn.execute("SELECT COUNT(*) FROM users WHERE pro_source = 'coupon'").fetchone()[0] >= cap:
        raise HTTPException(status_code=400, detail="That coupon has been used up.")
    still_paying = bool(row and row[1] == "stripe" and row[3] and is_pro(user_id))
    _set(user_id, plan="pro", pro_source="coupon")
    _alert_owner(f"TimeFrame: coupon redeemed by {user_id}.")
    return {"pro": True, "source": "coupon", "still_paying": still_paying}


@router.post("/billing/checkout")
def start_checkout(body: dict = Body(default={}), user_id: str = Depends(get_current_user)):
    interval = "year" if body.get("interval") == "year" else "month"
    if is_pro(user_id):
        raise HTTPException(status_code=400, detail="You already have TimeFrame Pro.")
    row = _row(user_id)
    params = {
        "mode": "subscription",
        "client_reference_id": user_id,
        "metadata": {"user_id": user_id},
        "line_items": [{
            "quantity": 1,
            "price_data": {
                "currency": CURRENCY,
                "unit_amount": PRICES[interval],
                "recurring": {"interval": interval},
                "tax_behavior": "exclusive",  # tax is added on top, never taken out of the price
                "product_data": {"name": "TimeFrame Pro", **({"tax_code": TAX_CODE} if TAX_CODE else {})},
            },
        }],
        "allow_promotion_codes": True,
        **({"automatic_tax": {"enabled": True}, "billing_address_collection": "required"} if COLLECT_TAX else {}),
        "success_url": f"{FRONTEND_URL}/?billing=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{FRONTEND_URL}/?billing=cancelled",
    }
    if row and row[2]:
        params["customer"] = row[2]
        if COLLECT_TAX:  # save the address Checkout collects on the existing customer, for the tax calculation
            params["customer_update"] = {"address": "auto"}
    else:
        email = (row[5] if row else None) or (user_id if "@" in user_id else None)
        if email:
            params["customer_email"] = email
        if TRIAL_DAYS > 0:  # one free trial per account: only before they've ever subscribed
            params["subscription_data"] = {"trial_period_days": TRIAL_DAYS}
    try:
        session = stripe("POST", "checkout/sessions", params)
    except StripeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"url": session["url"]}


@router.post("/billing/confirm")
def confirm_checkout(body: dict = Body(...), user_id: str = Depends(get_current_user)):
    """Called when Stripe sends the user back; turns Pro on without needing a webhook."""
    session_id = str(body.get("session_id") or "")
    if not session_id.startswith("cs_"):
        raise HTTPException(status_code=400, detail="That checkout link isn't valid.")
    try:
        session = stripe("GET", f"checkout/sessions/{session_id}", {"expand": ["subscription"]})
    except StripeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if session.get("client_reference_id") != user_id:
        raise HTTPException(status_code=403, detail="That checkout belongs to a different account.")
    sub = session.get("subscription") or {}
    if session.get("status") != "complete" or sub.get("status") not in ACTIVE:
        raise HTTPException(status_code=402, detail="The payment didn't go through.")
    _set(user_id, plan="pro", pro_source="stripe", stripe_customer=session.get("customer"),
         stripe_sub=sub.get("id"), pro_until=_period_end(sub))
    return {"pro": True, "trial": sub.get("status") == "trialing"}


@router.post("/billing/portal")
def billing_portal(user_id: str = Depends(get_current_user)):
    """Stripe's own page to change card, switch monthly/yearly, see invoices or cancel."""
    row = _row(user_id)
    if not row or not row[2]:
        raise HTTPException(status_code=400, detail="There's no subscription on this account.")
    try:
        portal = stripe("POST", "billing_portal/sessions", {"customer": row[2], "return_url": f"{FRONTEND_URL}/"})
    except StripeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"url": portal["url"]}
