"""Guest links (2026-11-25)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tests.test_endpoints import client, signup  # noqa: F401


def _guest(client, group="Gst23456", name="Jordan"):
    r = client.post("/guest/join", json={"group_id": group, "name": name})
    return r


def test_a_guest_joins_with_just_a_name_and_their_busy_times_count(client):
    sam = signup(client, "sam@example.com")
    client.post("/groups/join?group_id=Gst23456&name=Climbing", headers=sam)
    info = client.get("/guest/group?group_id=Gst23456").json()
    assert info == {"name": "Climbing", "members": 1, "guests_allowed": True}
    r = _guest(client)
    assert r.status_code == 200, r.text
    guest = {"Authorization": "Bearer " + r.json()["token"]}
    me = client.get("/auth/me", headers=guest).json()
    assert me["guest"] is True and me["name"] == "Jordan"
    day = datetime.now(ZoneInfo("UTC")).date() + timedelta(days=2)
    client.post("/availability/merge?timezone=UTC", json=[[{"start": f"{day}T10:00", "end": f"{day}T11:00"}]], headers=guest)
    m = client.post("/availability/merge?timezone=UTC&days=1&start_offset=2&group=Gst23456&keep_manual=1", json=[], headers=sam).json()
    assert [b["owner_name"] for b in m["busy_times"]] == ["Jordan"]
    g = client.get("/groups", headers=sam).json()["groups"][0]
    assert any(mem["guest"] and mem["name"] == "Jordan" for mem in g["members"])


def test_guests_cannot_create_groups_buy_pro_or_join_closed_groups(client):
    sam = signup(client, "sam@example.com")
    client.post("/groups/join?group_id=Gst23456", headers=sam)
    guest = {"Authorization": "Bearer " + _guest(client).json()["token"]}
    assert client.post("/groups/join?group_id=Brandnew1", headers=guest).status_code == 403
    assert client.post("/billing/checkout", json={}, headers=guest).status_code == 403
    assert client.post("/billing/redeem", json={"code": "X"}, headers=guest).status_code == 403
    # admin turns guests off
    assert client.post("/groups/guests?group_id=Gst23456&allow=false", headers=sam).json() == {"guests_allowed": False}
    assert _guest(client, name="Late").status_code == 403
    assert client.post("/groups/guests?group_id=Gst23456&allow=true", headers=guest).status_code == 403  # not admin


def test_guest_join_validation(client):
    assert _guest(client, group="Nope2345").status_code == 404
    assert _guest(client, group="bad id!").status_code == 400
    sam = signup(client, "sam@example.com")
    client.post("/groups/join?group_id=Gst23456", headers=sam)
    assert _guest(client, name="   ").status_code == 400
    assert client.post("/auth/signup", json={"email": "x@guest.timeframecalender.com", "password": "correct-horse-battery"}).status_code == 400
