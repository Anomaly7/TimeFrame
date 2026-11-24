"""The 14-point vibe-coded-app attack list (Sam, 2026-11-23): checks for the fixes made in that audit."""
from tests.test_endpoints import client, signup  # noqa: F401  (pytest fixture + helper)
from tests.test_billing import make_free


def test_malformed_busy_blocks_get_400_not_500(client):
    h = signup(client, "fuzz@example.com")
    for body in ([{"oops": 1}], [[{"start": "2031-01-01T10:00"}]], ["?"], [[["only-one"]]], [[[1, 2]]], [5]):
        r = client.post("/availability/merge", json=body, headers=h)
        assert r.status_code in (400, 422), (body, r.status_code)


def test_names_lose_control_and_invisible_characters(client):
    h = signup(client, "name@example.com")
    r = client.post("/auth/name", json={"name": "Sam‮exe.​evil\x00 <script>"}, headers=h)
    assert r.json()["name"] == "Samexe.evil <script>"  # shown as text by React, never run


def test_guessing_group_codes_is_rate_limited(client):
    h = signup(client, "hunter@example.com")
    make_free(client, "hunter@example.com")
    codes = [client.post(f"/groups/join?group_id=Gues{i:04d}", headers=h).status_code for i in range(35)]
    assert codes[0] == 200 and codes[1] == 402 and 429 in codes  # free accounts get 1 group


def test_coupon_once_per_account_cap_and_global_lock(client, monkeypatch):
    from app import billing
    monkeypatch.setenv("TIMEFRAME_COUPON", "FRIENDS2026")
    monkeypatch.setenv("TIMEFRAME_COUPON_MAX", "1")
    a = signup(client, "a1@example.com"); make_free(client, "a1@example.com")
    b = signup(client, "b1@example.com"); make_free(client, "b1@example.com")
    assert client.post("/billing/redeem", json={"code": "FRIENDS2026"}, headers=a).status_code == 200
    assert client.post("/billing/redeem", json={"code": "FRIENDS2026"}, headers=a).status_code == 200  # no-op repeat
    r = client.post("/billing/redeem", json={"code": "FRIENDS2026"}, headers=b)
    assert r.status_code == 400 and "used up" in r.json()["detail"]
    # Many accounts guessing: once 40 wrong codes pile up, even the right code is refused for a while.
    for _ in range(40):
        billing.coupon_wrong_total.record("all")
    monkeypatch.setenv("TIMEFRAME_COUPON_MAX", "0")
    assert client.post("/billing/redeem", json={"code": "FRIENDS2026"}, headers=b).status_code == 429


def test_security_headers_on_api_answers(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"


def test_signup_cannot_set_admin_or_pro(client):
    r = client.post("/auth/signup", json={"email": "sneaky@example.com", "password": "correct-horse-battery",
                                          "plan": "pro", "pro_source": "coupon", "is_admin": True, "role": "admin"})
    assert r.status_code == 200
    row = client.fake.execute("SELECT plan, pro_source FROM users WHERE id = 'sneaky@example.com'").fetchone()
    assert row[1] != "coupon"  # extra fields are ignored (the test schema's default is 'early')
