"""Owner admin page: off by default, password + authenticator code, lockouts, cookie safety, cross-site refusal,
headers, and the Pro actions."""
import time

import pytest
from fastapi.testclient import TestClient

from tests.test_endpoints import client, signup  # noqa: F401  (pytest fixture + helper)

PW = "a-very-long-admin-password-123"
TOTP = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
H = {"X-TF-Admin": "1"}


def code(offset=0):
    import base64
    from app.admin import _code_at
    return _code_at(base64.b32decode(TOTP), int(time.time()) // 30 + offset)


@pytest.fixture()
def admin(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", PW)
    monkeypatch.setenv("ADMIN_TOTP_SECRET", TOTP)
    monkeypatch.setattr("time.sleep", lambda s: None)
    import app.admin as a
    a._used_codes.clear()
    a._flood._hits.clear()
    c = TestClient(client.app, base_url="https://testserver")
    c.fake = client.fake
    return c


def login(c, pw=PW, offset=0):
    return c.post("/admin/api/login", json={"password": pw, "code": code(offset)}, headers=H)


def test_admin_does_not_exist_until_both_secrets_are_set(client, monkeypatch):
    assert client.get("/admin").status_code == 404
    monkeypatch.setenv("ADMIN_PASSWORD", PW)
    assert client.get("/admin").status_code == 404  # no authenticator secret yet
    monkeypatch.setenv("ADMIN_TOTP_SECRET", TOTP)
    monkeypatch.setenv("ADMIN_PASSWORD", "short-password")
    assert client.get("/admin").status_code == 404  # password under 16 characters
    assert client.post("/admin/api/login", json={}, headers=H).status_code == 404
    assert "/admin" not in client.get("/openapi.json").text


def test_page_is_served_with_strict_headers(admin):
    r = admin.get("/admin")
    assert r.status_code == 200 and "TimeFrame admin" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store" and r.headers["x-frame-options"] == "DENY"
    assert admin.get("/admin/app.js").status_code == 200


def test_needs_password_and_code_and_sets_a_locked_down_cookie(admin):
    assert login(admin, pw="wrong-password-wrong").status_code == 401
    bad = admin.post("/admin/api/login", json={"password": PW, "code": "000000"}, headers=H)
    assert bad.status_code == 401
    assert admin.get("/admin/api/overview", headers=H).status_code == 401
    r = login(admin)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "__Host-tfadmin=" in cookie and "HttpOnly" in cookie and "Secure" in cookie and "samesite=strict" in cookie.lower()
    d = admin.get("/admin/api/overview", headers=H).json()
    assert "users" in d and d["health"]["database"] is True


def test_a_code_works_only_once(admin):
    assert login(admin).status_code == 200
    admin.cookies.clear()
    assert login(admin).status_code == 401  # same 30-second code replayed


def test_cross_site_and_headerless_requests_are_refused(admin):
    assert login(admin).status_code == 200
    assert admin.get("/admin/api/overview").status_code == 403  # no X-TF-Admin header
    assert admin.get("/admin/api/overview", headers={**H, "Origin": "https://evil.example"}).status_code == 403
    assert admin.get("/admin/api/overview", headers={**H, "Origin": "https://testserver"}).status_code == 200
    # the website address (Vercel forwards www.timeframecalender.com/admin here), but only over https
    assert admin.get("/admin/api/overview", headers={**H, "Origin": "https://www.timeframecalender.com"}).status_code == 200
    assert admin.get("/admin/api/overview", headers={**H, "Origin": "http://www.timeframecalender.com"}).status_code == 403
    assert admin.get("/admin/api/overview", headers={**H, "Origin": "https://www.timeframecalender.com.evil.example"}).status_code == 403


def test_lockout_per_address_then_for_everyone(admin):
    for _ in range(5):
        assert login(admin, pw="nope-nope-nope-nope").status_code == 401
    r = login(admin)  # even the right password is refused while locked
    assert r.status_code == 429
    # 10 wrong tries from anywhere in an hour closes sign-in for everyone
    for i in range(5):
        admin.post("/admin/api/login", json={"password": "x" * 20, "code": "1"}, headers={**H, "X-Forwarded-For": f"10.0.0.{i}"})
    r = admin.post("/admin/api/login", json={"password": PW, "code": code()}, headers={**H, "X-Forwarded-For": "10.9.9.9"})
    assert r.status_code == 429 and "hour" in r.json()["detail"]


def test_changing_the_password_signs_everyone_out(admin, monkeypatch):
    assert login(admin).status_code == 200
    assert admin.get("/admin/api/overview", headers=H).status_code == 200
    monkeypatch.setenv("ADMIN_PASSWORD", PW + "-new")
    assert admin.get("/admin/api/overview", headers=H).status_code == 401


def test_a_regular_user_token_is_not_an_admin_session(admin, client):
    h = signup(client, "user@example.com")
    assert admin.get("/admin/api/users", headers={**H, **h}).status_code == 401
    admin.cookies.set("__Host-tfadmin", h["Authorization"][7:])
    assert admin.get("/admin/api/users", headers=H).status_code == 401


def test_list_search_grant_and_remove_pro(admin, client):
    signup(client, "free@example.com")
    signup(client, "paying@example.com")
    client.fake.execute("UPDATE users SET plan = NULL, pro_source = NULL WHERE id = 'free@example.com'")
    client.fake.execute("UPDATE users SET pro_source = 'stripe', stripe_sub = 'sub_1', pro_until = ? WHERE id = 'paying@example.com'",
                        (int(time.time()) + 86400 * 20,))
    client.fake.commit()
    assert login(admin).status_code == 200
    users = admin.get("/admin/api/users?q=FREE", headers=H).json()["users"]
    assert [u["email"] for u in users] == ["free@example.com"] and users[0]["plan"] == "free"
    assert admin.get("/admin/api/users?q=%25", headers=H).json()["users"] == []  # wildcards are literal

    r = admin.post("/admin/api/users/pro", json={"id": "free@example.com", "action": "grant"}, headers=H)
    assert r.status_code == 200
    assert client.get("/billing/status", headers=signup_login(client, "free@example.com")).json()["source"] == "manual"
    assert admin.post("/admin/api/users/pro", json={"id": "free@example.com", "action": "revoke"}, headers=H).status_code == 200
    # someone paying through Stripe can't be switched off here (they'd keep being charged)
    r = admin.post("/admin/api/users/pro", json={"id": "paying@example.com", "action": "revoke"}, headers=H)
    assert r.status_code == 409
    events = [e["action"] for e in admin.get("/admin/api/audit", headers=H).json()["events"]]
    assert "grant_pro" in events and "revoke_pro" in events and "login" in events


def signup_login(client, email):
    r = client.post("/auth/login", json={"email": email, "password": "correct-horse-battery"})
    return {"Authorization": "Bearer " + r.json()["token"]}
