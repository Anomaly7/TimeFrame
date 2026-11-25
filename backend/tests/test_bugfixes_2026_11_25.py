"""Bugs fixed in the 2026-11-25 sweep."""
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from app.availability import find_free_time
from tests.test_endpoints import client, signup  # noqa: F401  (fixture + helper)


def test_two_members_busy_at_the_same_time_both_show(client):
    sam = signup(client, "sam@example.com")
    priya = signup(client, "priya@example.com")
    client.post("/groups/join?group_id=Same2345", headers=sam)
    client.post("/groups/join?group_id=Same2345", headers=priya)
    day = datetime.now(ZoneInfo("UTC")).date() + timedelta(days=3)
    block = [[{"start": f"{day}T10:00:00", "end": f"{day}T11:00:00"}]]
    for who in (sam, priya):
        client.post("/availability/merge?timezone=UTC", json=block, headers=who)
    offset = 3
    res = client.post(f"/availability/merge?timezone=UTC&days=1&start_offset={offset}&group=Same2345&keep_manual=1",
                      json=[], headers=sam).json()
    owners = sorted(b["owner"] for b in res["busy_times"])
    assert owners == ["priya@example.com", "sam@example.com"]
    assert res["in_group"] is True


def test_admin_leaving_makes_the_group_claimable(client):
    sam = signup(client, "sam@example.com")
    priya = signup(client, "priya@example.com")
    client.post("/groups/join?group_id=Lead2345&name=Team", headers=sam)
    client.post("/groups/join?group_id=Lead2345", headers=priya)
    client.post("/groups/leave?group_id=Lead2345", headers=sam)
    g = client.get("/groups", headers=priya).json()["groups"][0]
    assert g["claimable"] and not g["is_admin"]
    assert client.post("/groups/claim?group_id=Lead2345", headers=priya).json() == {"is_admin": True}


def test_merge_says_when_you_are_not_in_the_group(client):
    sam = signup(client, "sam@example.com")
    res = client.post("/availability/merge?group=Nope2345&keep_manual=1", json=[], headers=sam).json()
    assert res["in_group"] is False
    assert client.post("/availability/merge?keep_manual=1", json=[], headers=sam).json()["in_group"] is None


def test_malformed_sign_in_is_a_400_not_a_crash(client):
    assert client.post("/auth/signup", json={"email": 123, "password": "longenough"}).status_code == 400
    assert client.post("/auth/login", json={"email": "a@b.co", "password": ["x"]}).status_code == 400


def test_todays_free_slots_start_on_a_five_minute_mark():
    tz = ZoneInfo("America/Los_Angeles")
    today = datetime.now(tz).date()
    slots = find_free_time([], today, time(0, 0), time(23, 59), min_minutes=5, tz=tz)
    for start, _end in slots:
        assert start.second == 0 and start.microsecond == 0 and start.minute % 5 == 0


def test_signing_out_keeps_your_calendar(client):
    from app.db import conn
    sam = signup(client, "sam@example.com")
    conn.execute("INSERT INTO busy_times (user_id, start, end_time, source, raw_timezone, title) VALUES "
                 "('sam@example.com', '2030-01-01T10:00:00+00:00', '2030-01-01T11:00:00+00:00', 'google', 'UTC', NULL)")
    conn.commit()
    assert client.post("/auth/logout", headers=sam).json() == {"logged_out": True}
    assert client.get("/auth/status", headers=sam).json() == {"connected": True}


def test_rate_limits_use_cloudflares_address_not_a_typed_one():
    from starlette.requests import Request
    from app.auth_utils import client_ip

    def req(headers):
        return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                        "client": ("10.0.0.1", 1234)})

    # Behind Cloudflare: a made-up X-Forwarded-For is ignored.
    assert client_ip(req({"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "1.2.3.4, 203.0.113.7"})) == "203.0.113.7"
    assert client_ip(req({"X-Forwarded-For": "1.2.3.4"})) == "1.2.3.4"  # local/tests only
    assert client_ip(req({})) == "10.0.0.1"
