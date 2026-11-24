"""TimeFrame Pro: early supporters, the coupon, Stripe checkout and the group-creation gate (Stripe is faked)."""
import time

from tests.test_endpoints import client, signup  # noqa: F401  (pytest fixture + helper)


def make_free(client, email):
    client.fake.execute("UPDATE users SET plan = NULL, pro_source = NULL WHERE id = ?", (email,))
    client.fake.commit()


def test_early_supporters_keep_pro_and_new_free_users_cannot_create_groups(client):
    early = signup(client, "early@example.com")  # the test schema defaults to 'early' Pro, like a migrated account
    assert client.get("/billing/status", headers=early).json()["pro"] is True
    assert client.post("/groups/join?group_id=Abcd2345", headers=early).status_code == 200

    free = signup(client, "free@example.com")
    make_free(client, "free@example.com")
    st = client.get("/billing/status", headers=free).json()
    assert st["pro"] is False and st["prices"] == {"month": "$4.47", "year": "$30.40"}
    # Free accounts can create 1 group; the second needs Pro.
    assert client.post("/groups/join?group_id=Wxyz2345", headers=free).status_code == 200
    r = client.post("/groups/join?group_id=Wxyz3456", headers=free)
    assert r.status_code == 402 and "Pro" in r.json()["detail"]
    # Leaving your group frees the slot.
    client.post("/groups/leave?group_id=Wxyz2345", headers=free)
    assert client.post("/groups/join?group_id=Wxyz3456", headers=free).status_code == 200
    # ...but joining someone else's group is free.
    assert client.post("/groups/join?group_id=Abcd2345", headers=free).status_code == 200


def test_the_one_coupon_gives_pro_for_free(client, monkeypatch):
    h = signup(client, "c@example.com")
    make_free(client, "c@example.com")
    assert client.post("/billing/redeem", json={"code": "ANYTHING"}, headers=h).status_code == 400  # no coupon set
    monkeypatch.setenv("TIMEFRAME_COUPON", "FRIENDS2026")
    assert client.post("/billing/redeem", json={"code": "wrong"}, headers=h).status_code == 400
    r = client.post("/billing/redeem", json={"code": " friends2026 "}, headers=h)
    assert r.status_code == 200 and r.json()["pro"] is True
    st = client.get("/billing/status", headers=h).json()
    assert st["pro"] is True and st["source"] == "coupon"
    assert client.post("/groups/join?group_id=Coup2345", headers=h).status_code == 200


def test_coupon_guessing_is_rate_limited(client, monkeypatch):
    monkeypatch.setenv("TIMEFRAME_COUPON", "FRIENDS2026")
    h = signup(client, "g@example.com")
    codes = [client.post("/billing/redeem", json={"code": f"guess{i}"}, headers=h).status_code for i in range(10)]
    assert 429 in codes


def test_stripe_checkout_confirm_and_lapse(client, monkeypatch):
    from app import billing
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    calls = []
    state = {"status": "trialing"}

    def fake(method, path, data=None):
        calls.append((method, path, data))
        if path == "checkout/sessions":
            return {"url": "https://checkout.stripe.com/c/pay/cs_test_1"}
        if path.startswith("checkout/sessions/"):
            return {"client_reference_id": "s@example.com", "status": "complete", "customer": "cus_1",
                    "subscription": {"id": "sub_1", "status": "trialing", "trial_end": int(time.time()) + 7 * 86400}}
        if path.startswith("subscriptions/"):
            return {"id": "sub_1", "status": state["status"], "items": {"data": [{"current_period_end": int(time.time()) - 10 * 86400}]}}
        raise AssertionError(path)

    monkeypatch.setattr(billing, "stripe", fake)
    h = signup(client, "s@example.com")
    make_free(client, "s@example.com")
    r = client.post("/billing/checkout", json={"interval": "year"}, headers=h)
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.com/")
    sent = calls[0][2]
    assert sent["line_items"][0]["price_data"]["unit_amount"] == 3040
    assert sent["subscription_data"]["trial_period_days"] == 7 and sent["client_reference_id"] == "s@example.com"
    # Someone else's checkout can't be claimed.
    other = signup(client, "o@example.com")
    assert client.post("/billing/confirm", json={"session_id": "cs_test_1"}, headers=other).status_code == 403
    r = client.post("/billing/confirm", json={"session_id": "cs_test_1"}, headers=h)
    assert r.status_code == 200 and r.json() == {"pro": True, "trial": True}
    assert client.get("/billing/status", headers=h).json()["pro"] is True
    # Paid-through date passes and Stripe says it was cancelled: back to free.
    client.fake.execute("UPDATE users SET pro_until = ? WHERE id = 's@example.com'", (int(time.time()) - 3 * 86400,))
    state["status"] = "canceled"
    assert client.get("/billing/status", headers=h).json()["pro"] is False


def test_checkout_without_stripe_keys_says_so(client, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    h = signup(client, "n@example.com")
    make_free(client, "n@example.com")
    r = client.post("/billing/checkout", json={}, headers=h)
    assert r.status_code == 503 and "set up" in r.json()["detail"]


def test_tax_is_added_on_top_when_switched_on(client, monkeypatch):
    from app import billing
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    sent = []
    monkeypatch.setattr(billing, "stripe", lambda m, p, d=None: sent.append(d) or {"url": "https://checkout.stripe.com/x"})
    h = signup(client, "tax@example.com")
    make_free(client, "tax@example.com")
    client.post("/billing/checkout", json={"interval": "month"}, headers=h)
    item = sent[-1]["line_items"][0]["price_data"]
    assert item["tax_behavior"] == "exclusive" and item["unit_amount"] == 447  # price never lowered
    assert "automatic_tax" not in sent[-1]  # off until registered
    monkeypatch.setattr(billing, "COLLECT_TAX", True)
    client.post("/billing/checkout", json={"interval": "month"}, headers=h)
    assert sent[-1]["automatic_tax"] == {"enabled": True}
    assert sent[-1]["line_items"][0]["price_data"]["unit_amount"] == 447


def test_settings_are_pro_only(client):
    free = signup(client, "set@example.com")
    make_free(client, "set@example.com")
    assert client.post("/groups/join?group_id=Sett2345", headers=free).status_code == 200
    rules = {"dayStart": "09:00", "dayEnd": "17:00", "meetingLength": 60, "excludeWeekends": True, "timePrefs": ["morning"]}
    r = client.post("/groups/settings?group_id=Sett2345", json=rules, headers=free)
    assert r.status_code == 402 and "Pro" in r.json()["detail"]
    # A free account's own view always uses the defaults, whatever the browser asks for.
    url = "/availability/merge?days=1&start_offset=0&timezone=America/Vancouver&keep_manual=1&min_minutes=240&day_start=11:00&day_end=12:00"
    free_slots = client.post(url, json=[], headers=free).json()
    pro = signup(client, "setpro@example.com")  # test schema defaults to Pro
    pro_slots = client.post(url, json=[], headers=pro).json()
    assert free_slots != pro_slots
