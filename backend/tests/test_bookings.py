"""Book the slot (2026-11-25)."""
from datetime import datetime, timedelta, timezone

from tests.test_endpoints import client, signup  # noqa: F401


def _span(days=2, hour=17, minutes=60):
    start = (datetime.now(timezone.utc) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return start.isoformat(), (start + timedelta(minutes=minutes)).isoformat()


def _group(client):
    sam, priya, eve = (signup(client, e) for e in ("sam@example.com", "priya@example.com", "eve@example.com"))
    client.post("/groups/join?group_id=Book2345&name=Team", headers=sam)
    client.post("/groups/join?group_id=Book2345", headers=priya)
    return sam, priya, eve


def test_members_book_and_everyone_sees_it_as_booked(client):
    sam, priya, eve = _group(client)
    s, e = _span()
    r = client.post("/groups/book?group_id=Book2345", json={"title": "Study session", "start": s, "end": e}, headers=priya)
    assert r.status_code == 200, r.text
    listed = client.get("/groups/bookings?group_id=Book2345", headers=sam).json()["bookings"]
    assert [b["title"] for b in listed] == ["Study session"]
    assert listed[0]["created_by_name"] == "priya" and listed[0]["can_cancel"]  # sam is admin
    # outsiders can't book or read
    assert client.post("/groups/book?group_id=Book2345", json={"start": s, "end": e}, headers=eve).status_code == 404
    assert client.get("/groups/bookings?group_id=Book2345", headers=eve).status_code == 404
    # in the merged calendar it's a booking, and that time isn't free
    m = client.post("/availability/merge?timezone=UTC&days=4&start_offset=0&group=Book2345&keep_manual=1&day_start=00:00&day_end=23:59",
                    json=[], headers=sam).json()
    assert [b["title"] for b in m["bookings"]] == ["Study session"]
    for f in m["ranked_free_time"]:
        assert not (f["start"] < e and f["end"] > s)


def test_a_booking_makes_members_busy_in_their_other_groups_without_its_title(client):
    sam, priya, eve = _group(client)
    client.post("/groups/join?group_id=Othr2345", headers=eve)
    client.post("/groups/join?group_id=Othr2345", headers=priya)
    s, e = _span()
    client.post("/groups/book?group_id=Book2345", json={"title": "Secret plan", "start": s, "end": e}, headers=sam)
    m = client.post("/availability/merge?timezone=UTC&days=4&start_offset=0&group=Othr2345&keep_manual=1",
                    json=[], headers=eve).json()
    assert m["bookings"] == []
    blocks = [b for b in m["busy_times"] if b["label"] == "(booked)"]
    assert [b["owner"] for b in blocks] == ["priya@example.com"] and blocks[0]["title"] is None


def test_cancel_rules_and_bad_input(client):
    sam, priya, eve = _group(client)
    s, e = _span()
    bid = client.post("/groups/book?group_id=Book2345", json={"start": s, "end": e}, headers=sam).json()["booking"]["id"]
    assert client.post(f"/bookings/cancel?id={bid}", headers=priya).status_code == 403  # not hers, not admin
    assert client.post(f"/bookings/cancel?id={bid}", headers=sam).json() == {"cancelled": True}
    assert client.get("/groups/bookings?group_id=Book2345", headers=sam).json()["bookings"] == []
    assert client.post("/groups/book?group_id=Book2345", json={"start": e, "end": s}, headers=sam).status_code == 400
    assert client.post("/groups/book?group_id=Book2345", json={"start": "2030-01-01T10:00", "end": "2030-01-01T11:00"},
                       headers=sam).status_code == 400  # no time zone
    s2, e2 = _span(minutes=13 * 60)
    assert client.post("/groups/book?group_id=Book2345", json={"start": s2, "end": e2}, headers=sam).status_code == 400


def test_my_bookings_lists_across_groups(client):
    sam, priya, eve = _group(client)
    s, e = _span()
    client.post("/groups/book?group_id=Book2345", json={"title": "Sync", "start": s, "end": e}, headers=sam)
    mine = client.get("/bookings/mine", headers=priya).json()["bookings"]
    assert mine[0]["title"] == "Sync" and mine[0]["group_name"] == "Team"
    assert client.get("/bookings/mine", headers=eve).json()["bookings"] == []
