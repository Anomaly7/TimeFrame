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
