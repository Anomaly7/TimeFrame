"""Personal booking page (Pro, 2026-11-25)."""
from tests.test_endpoints import client, signup  # noqa: F401

PAGE = {"handle": "sam", "title": "Office hours", "minutes": 30, "day_start": "09:00", "day_end": "17:00",
        "weekdays": [0, 1, 2, 3, 4, 5, 6], "days_ahead": 7, "notice_hours": 0, "timezone": "UTC"}


def test_owner_sets_a_page_visitors_book_and_the_slot_disappears(client):
    sam = signup(client, "sam@example.com")  # test accounts are Pro
    r = client.post("/booking-page", json=PAGE, headers=sam)
    assert r.status_code == 200, r.text
    view = client.get("/book/sam").json()
    assert view["name"] == "sam" and view["title"] == "Office hours" and view["slots"]
    assert "busy" not in str(view).lower()
    slot = view["slots"][3]
    bad = client.post("/book/sam", json={"start": slot["start"], "name": "Kim", "email": "nope"})
    assert bad.status_code == 400
    ok = client.post("/book/sam", json={"start": slot["start"], "name": "Kim", "email": "kim@example.com", "note": "Re: lab"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["booking"]["title"] == "Office hours with Kim"
    assert slot["start"] not in [s["start"] for s in client.get("/book/sam").json()["slots"]]
    again = client.post("/book/sam", json={"start": slot["start"], "name": "Lee", "email": "lee@example.com"})
    assert again.status_code == 409
    mine = client.get("/bookings/mine", headers=sam).json()["bookings"]
    assert mine[0]["guest_email"] == "kim@example.com" and mine[0]["booking_page"] and mine[0]["can_cancel"]
    bell = client.get("/notifications", headers=sam).json()["notifications"]
    assert bell[0]["kind"] == "booking_page" and "Kim" in bell[0]["text"]


def test_handles_are_checked_and_free_accounts_cannot_have_a_page(client):
    sam = signup(client, "sam@example.com")
    priya = signup(client, "priya@example.com")
    client.post("/booking-page", json=PAGE, headers=sam)
    assert client.post("/booking-page", json=PAGE, headers=priya).status_code == 409  # taken
    for handle in ("admin", "ab", "Bad Name", "-dash", "privacy"):
        assert client.post("/booking-page", json={**PAGE, "handle": handle}, headers=priya).status_code == 400
    client.fake.execute("UPDATE users SET plan = NULL WHERE id = 'sam@example.com'")
    client.fake.commit()
    assert client.get("/book/sam").status_code == 404  # Pro ended: page goes dark
    assert client.post("/booking-page", json=PAGE, headers=sam).status_code == 402
    assert client.get("/book/nobody").status_code == 404


def test_busy_times_and_disabled_pages(client):
    sam = signup(client, "sam@example.com")
    client.post("/booking-page", json={**PAGE, "enabled": False}, headers=sam)
    assert client.get("/book/sam").status_code == 404
    client.post("/booking-page", json={**PAGE, "enabled": True}, headers=sam)
    slots = client.get("/book/sam").json()["slots"]
    first = slots[0]
    client.post("/availability/merge?timezone=UTC", json=[[{"start": first["start"], "end": first["end"]}]], headers=sam)
    assert first["start"] not in [s["start"] for s in client.get("/book/sam").json()["slots"]]
