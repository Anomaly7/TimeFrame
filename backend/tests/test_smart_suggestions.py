"""Smarter suggestions (2026-11-25): everyone-but-one, travel buffer, weekly finder."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tests.test_endpoints import client, signup  # noqa: F401

UTC = ZoneInfo("UTC")


def _day(n=2):
    return datetime.now(UTC).date() + timedelta(days=n)


def _busy(client, who, blocks):
    client.post("/availability/merge?timezone=UTC", json=[[{"start": s, "end": e} for s, e in blocks]], headers=who)


def test_when_nothing_fits_everyone_it_suggests_times_missing_one_person(client):
    a, b, c = (signup(client, f"{n}@example.com") for n in ("ana", "ben", "cy"))
    for who in (a, b, c):
        client.post("/groups/join?group_id=Most2345", headers=who)
    d = _day()
    # ana and ben busy all day except 12-13; cy busy 12-13 -> no full slot that day
    _busy(client, a, [(f"{d}T08:00", f"{d}T12:00"), (f"{d}T13:00", f"{d}T22:00")])
    _busy(client, b, [(f"{d}T08:00", f"{d}T12:00"), (f"{d}T13:00", f"{d}T22:00")])
    _busy(client, c, [(f"{d}T12:00", f"{d}T13:00")])
    m = client.post("/availability/merge?timezone=UTC&days=1&start_offset=2&group=Most2345&keep_manual=1", json=[], headers=a).json()
    assert m["ranked_free_time"] == []
    assert m["almost_free"] and all(x["missing"] == "cy" for x in m["almost_free"])
    assert m["almost_free"][0]["start"].startswith(f"{d}T12:")


def test_travel_buffer_keeps_time_free_around_events(client):
    sam = signup(client, "sam@example.com")  # test accounts are Pro (see FakeConn)
    d = _day()
    _busy(client, sam, [(f"{d}T08:00", f"{d}T12:00"), (f"{d}T12:40", f"{d}T22:00")])
    base = "/availability/merge?timezone=UTC&days=1&start_offset=2&keep_manual=1&min_minutes=30"
    assert len(client.post(base, json=[], headers=sam).json()["ranked_free_time"]) == 1
    assert client.post(base + "&buffer=15", json=[], headers=sam).json()["ranked_free_time"] == []
    client.post("/groups/join?group_id=Buff2345", headers=sam)
    r = client.post("/groups/settings?group_id=Buff2345", json={"bufferMinutes": 15}, headers=sam)
    assert r.json()["settings"]["bufferMinutes"] == 15
    assert client.post("/groups/settings?group_id=Buff2345", json={"bufferMinutes": 90}, headers=sam).status_code == 400


def test_weekly_finder_prefers_the_time_free_most_weeks(client):
    sam = signup(client, "sam@example.com")
    # Busy every day 08:00-22:00 for 4 weeks except 15:00-16:00 on one weekday
    blocks = []
    start = _day(1)
    for i in range(28):
        d = start + timedelta(days=i)
        if i % 7 == 2:
            blocks += [(f"{d}T08:00", f"{d}T15:00"), (f"{d}T16:00", f"{d}T22:00")]
        else:
            blocks.append((f"{d}T08:00", f"{d}T22:00"))
    _busy(client, sam, blocks)
    r = client.get("/availability/recurring?timezone=UTC&weeks=4&length=60", headers=sam).json()
    best = r["slots"][0]
    assert best["weekday"] == (start + timedelta(days=2)).strftime("%A") and best["time"] == "15:00"
    assert best["free_weeks"] == 4 and r["minutes"] == 60
