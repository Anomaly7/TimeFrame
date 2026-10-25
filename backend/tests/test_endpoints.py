"""Endpoint tests against an in-memory SQLite stand-in for Postgres (same
sqlite3-style API the app uses), so they run without a database server."""
import sqlite3
import sys
import types

import pytest


class FakeConn:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT, password_hash TEXT, email_verified BOOLEAN DEFAULT FALSE, display_name TEXT);
            CREATE TABLE busy_times (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, start TEXT, end_time TEXT,
                                     source TEXT, raw_timezone TEXT, title TEXT);
            CREATE TABLE groups (id TEXT PRIMARY KEY, name TEXT);
            CREATE TABLE group_members (group_id TEXT, user_id TEXT);
        """)

    def execute(self, sql, params=()):
        return self.db.execute(sql, params)

    def commit(self):
        self.db.commit()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "y" * 40)
    import contextvars
    fake_db = types.ModuleType("app.db")
    fake_db.conn = FakeConn()
    fake_db.current_request = contextvars.ContextVar("current_request", default=None)
    for name in [m for m in sys.modules if m == "app.db" or m.startswith("app.") and m != "app.availability" and m != "app.auth_utils"]:
        del sys.modules[name]
    monkeypatch.setitem(sys.modules, "app.db", fake_db)
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    c.fake = fake_db.conn
    yield c
    for name in [m for m in sys.modules if m.startswith("app.") and m not in ("app.availability", "app.auth_utils")]:
        del sys.modules[name]


def signup(client, email):
    r = client.post("/auth/signup", json={"email": email, "password": "correct-horse-battery"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


MERGE = "/availability/merge?days=7&start_offset=1&timezone=America/Vancouver"


def test_non_members_cannot_read_a_groups_calendars(client):
    alice = signup(client, "alice@example.com")
    mallory = signup(client, "mallory@example.com")
    assert client.post("/groups/join?group_id=Abc23456", headers=alice).status_code == 200
    block = [[{"start": "2031-01-01T10:00", "end": "2031-01-01T11:00", "title": "Secret meeting"}]]
    client.post("/availability/merge?days=1&start_offset=0", json=block, headers=alice)
    client.fake.execute("INSERT INTO busy_times (user_id, start, end_time, source, raw_timezone, title) VALUES "
                        "('alice@example.com', datetime('now', '+2 days'), datetime('now', '+2 days', '+1 hour'), 'manual', 'UTC', 'Secret meeting')")
    r = client.post(MERGE + "&group=Abc23456", json=[], headers=mallory)
    assert r.status_code == 200
    assert all(b["owner"] == "mallory@example.com" for b in r.json()["busy_times"])
    # once joined, the member does see the group
    client.post("/groups/join?group_id=Abc23456", headers=mallory)
    r = client.post(MERGE + "&group=Abc23456", json=[], headers=mallory)
    assert any(b["owner"] == "alice@example.com" for b in r.json()["busy_times"])


def test_bad_inputs_get_400s_not_500s(client):
    h = signup(client, "bob@example.com")
    assert client.post("/availability/merge?day_start=nope", json=[], headers=h).status_code == 400
    assert client.post("/availability/merge?day_start=18:00&day_end=09:00", json=[], headers=h).status_code == 400
    assert client.post("/availability/merge?days=100000", json=[], headers=h).status_code == 422
    assert client.post("/availability/merge", json=[[["garbage", "x"]]], headers=h).status_code == 400
    assert client.post("/groups/join?group_id=../../etc", headers=h).status_code == 400


def test_signup_login_and_password_rules(client):
    assert client.post("/auth/signup", json={"email": "c@example.com", "password": "short"}).status_code == 400
    assert client.post("/auth/signup", json={"email": "c@example.com", "password": "p" * 100}).status_code == 400
    signup(client, "c@example.com")
    assert client.post("/auth/login", json={"email": "c@example.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/auth/login", json={"email": "c@example.com", "password": "correct-horse-battery"}).status_code == 200


def test_login_is_rate_limited(client):
    signup(client, "d@example.com")
    codes = [client.post("/auth/login", json={"email": "d@example.com", "password": "nope-nope-nope"}).status_code
             for _ in range(12)]
    assert codes[-1] == 429


def test_google_callback_rejects_missing_state(client):
    r = client.get("/auth/callback?code=abc", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "#auth_error=" in r.headers["location"] and "token=" not in r.headers["location"]


def test_ics_without_dtend_is_imported_not_a_crash(client):
    h = signup(client, "e@example.com")
    from datetime import date, timedelta
    d = (date.today() + timedelta(days=3)).strftime("%Y%m%d")
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:test\r\n"
           f"BEGIN:VEVENT\r\nUID:1\r\nDTSTART;VALUE=DATE:{d}\r\nSUMMARY:All day\r\nEND:VEVENT\r\n"
           f"BEGIN:VEVENT\r\nUID:2\r\nDTSTART:{d}T150000Z\r\nDURATION:PT1H\r\nSUMMARY:One hour\r\nEND:VEVENT\r\n"
           "END:VCALENDAR\r\n")
    r = client.post("/import/ics", files={"file": ("cal.ics", ics, "text/calendar")}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2


def test_cors_only_allows_the_real_frontend(client):
    ok = client.options("/health", headers={"Origin": "https://calender-app-one-xi.vercel.app", "Access-Control-Request-Method": "GET"})
    bad = client.options("/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "https://calender-app-one-xi.vercel.app"
    assert "access-control-allow-origin" not in bad.headers


def test_health_db_runs_a_query(client):
    r = client.get("/health/db")
    assert r.status_code == 200 and r.json()["database"] == "ok"
