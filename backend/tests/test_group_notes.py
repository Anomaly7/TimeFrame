"""Group notes + pinned note (2026-11-25)."""
from tests.test_bookings import _group
from tests.test_endpoints import client, signup  # noqa: F401


def test_members_post_notes_admin_pins_and_moderates(client):
    sam, priya, eve = _group(client)
    assert client.post("/groups/notes?group_id=Book2345", json={"text": "Bring laptops"}, headers=priya).status_code == 200
    assert client.post("/groups/notes?group_id=Book2345", json={"text": "x"}, headers=eve).status_code == 404
    assert client.get("/groups/notes?group_id=Book2345", headers=eve).status_code == 404
    got = client.get("/groups/notes?group_id=Book2345", headers=sam).json()
    assert got["notes"][0]["text"] == "Bring laptops" and got["notes"][0]["author"] == "priya" and got["can_pin"]
    assert any("Bring laptops" in n["text"] for n in client.get("/notifications", headers=sam).json()["notifications"])
    assert client.post("/groups/pin?group_id=Book2345", json={"text": "Room 204"}, headers=priya).status_code == 403
    assert client.post("/groups/pin?group_id=Book2345", json={"text": "Room 204"}, headers=sam).json() == {"pinned": "Room 204"}
    assert client.get("/groups/notes?group_id=Book2345", headers=priya).json()["pinned"] == "Room 204"
    nid = got["notes"][0]["id"]
    sam_note = client.post("/groups/notes?group_id=Book2345", json={"text": "ok"}, headers=sam).json()["id"]
    assert client.post(f"/groups/notes/delete?id={sam_note}", headers=priya).status_code == 403
    assert client.post(f"/groups/notes/delete?id={nid}", headers=sam).json() == {"deleted": True}  # admin
    assert client.post("/groups/notes?group_id=Book2345", json={"text": "   "}, headers=sam).status_code == 400
    long = client.post("/groups/notes?group_id=Book2345", json={"text": "a" * 500}, headers=sam)
    assert long.status_code == 200
    assert 280 in [len(n["text"]) for n in client.get("/groups/notes?group_id=Book2345", headers=sam).json()["notes"]]
