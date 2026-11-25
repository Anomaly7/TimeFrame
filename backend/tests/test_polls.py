"""Polls / propose times (2026-11-25)."""
from tests.test_bookings import _group, _span
from tests.test_endpoints import client, signup  # noqa: F401


def _opts(n=3):
    return [dict(zip(("start", "end"), _span(days=2 + i))) for i in range(n)]


def test_admin_polls_members_and_guests_vote_and_closing_books_the_winner(client):
    sam, priya, eve = _group(client)
    guest = {"Authorization": "Bearer " + client.post("/guest/join", json={"group_id": "Book2345", "name": "Jo"}).json()["token"]}
    assert client.post("/groups/polls?group_id=Book2345", json={"options": _opts()}, headers=priya).status_code == 403  # not admin
    poll = client.post("/groups/polls?group_id=Book2345", json={"title": "Dinner", "options": _opts()}, headers=sam).json()["poll"]
    pid = poll["id"]
    client.post(f"/polls/vote?id={pid}", json={"options": [0, 2]}, headers=priya)
    r = client.post(f"/polls/vote?id={pid}", json={"options": [2]}, headers=guest).json()["poll"]
    assert [o["votes"] for o in r["options"]] == [1, 0, 2] and r["options"][2]["mine"]
    assert r["options"][2]["voters"] == ["Jo", "priya"]
    # changing your mind replaces your votes
    r = client.post(f"/polls/vote?id={pid}", json={"options": [0]}, headers=guest).json()["poll"]
    assert [o["votes"] for o in r["options"]] == [2, 0, 1]
    # outsiders can't see or vote
    assert client.get("/groups/polls?group_id=Book2345", headers=eve).status_code == 404
    assert client.post(f"/polls/vote?id={pid}", json={"options": [0]}, headers=eve).status_code == 404
    assert client.post(f"/polls/close?id={pid}", headers=priya).status_code == 403
    closed = client.post(f"/polls/close?id={pid}", headers=sam).json()
    assert closed["poll"]["closed"] and closed["poll"]["winner"] == 0
    booked = client.get("/groups/bookings?group_id=Book2345", headers=priya).json()["bookings"]
    assert [b["title"] for b in booked] == ["Dinner"] and booked[0]["start"] == poll["options"][0]["start"]
    assert client.post(f"/polls/vote?id={pid}", json={"options": [1]}, headers=priya).status_code == 400


def test_poll_validation(client):
    sam, priya, eve = _group(client)
    assert client.post("/groups/polls?group_id=Book2345", json={"options": _opts(1)}, headers=sam).status_code == 400
    assert client.post("/groups/polls?group_id=Book2345", json={"options": _opts(6)}, headers=sam).status_code == 400
    pid = client.post("/groups/polls?group_id=Book2345", json={"options": _opts(2)}, headers=sam).json()["poll"]["id"]
    assert client.post(f"/polls/vote?id={pid}", json={"options": [5]}, headers=priya).status_code == 400
    assert client.post(f"/polls/vote?id={pid}", json={"options": [True]}, headers=priya).status_code == 400
    assert client.post(f"/polls/close?id={pid}", json={"option": 1}, headers=sam).json()["poll"]["winner"] == 1
    assert client.post(f"/polls/delete?id={pid}", headers=sam).json() == {"deleted": True}
    assert client.get("/groups/polls?group_id=Book2345", headers=sam).json()["polls"] == []
