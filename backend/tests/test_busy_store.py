from tests.test_endpoints import client, signup  # noqa: F401  (client is a pytest fixture)


def test_batched_insert_keeps_every_row_across_chunks(client):
    from app.busy_store import insert_busy_rows, CHUNK
    n = CHUNK * 2 + 37  # three statements, the last one partial
    rows = [("u@example.com", f"2031-01-01T{i % 24:02d}:00:00-08:00", f"2031-01-01T{i % 24:02d}:30:00-08:00",
             "google", "America/Vancouver", f"Event {i}") for i in range(n)]
    insert_busy_rows(rows)
    insert_busy_rows([])  # nothing to save is fine
    saved = client.fake.execute("SELECT start, title FROM busy_times WHERE user_id = 'u@example.com' ORDER BY id").fetchall()
    assert [s for s, _ in saved] == [r[1] for r in rows]
    assert all(t is None for _, t in saved)  # titles are never stored


def test_manual_blocks_still_round_trip_through_merge(client):
    alice = signup(client, "alice@example.com")
    blocks = [[{"start": f"2031-01-0{d}T10:00", "end": f"2031-01-0{d}T11:00", "title": f"Block {d}"} for d in range(1, 6)]]
    url = "/availability/merge?days=7&start_offset=0&timezone=America/Vancouver"
    client.post(url, json=blocks, headers=alice)
    client.post(url, json=blocks, headers=alice)  # saving again replaces, never duplicates
    rows = client.fake.execute("SELECT start, title FROM busy_times WHERE user_id = 'alice@example.com' AND source = 'manual'").fetchall()
    assert len(rows) == 5 and all(t is None for _, t in rows)


def test_google_callback_saves_every_event_page(client, monkeypatch):
    import app.google_auth as ga

    class FakeFlow:
        credentials = object()
        redirect_uri = None
        def fetch_token(self, **kw): pass

    pages = {None: ("p2", 700), "p2": (None, 650)}  # two pages, 1350 events
    calls = []

    class Req:
        def __init__(self, result): self.result = result
        def execute(self): return self.result

    class Events:
        def list(self, **kw):
            calls.append(kw)
            nxt, n = pages[kw.get("pageToken")]
            items = [{"start": {"dateTime": f"2031-02-01T09:{i % 60:02d}:00-08:00", "timeZone": "America/Vancouver"},
                      "end": {"dateTime": f"2031-02-01T10:{i % 60:02d}:00-08:00"}, "summary": f"E{kw.get('pageToken')}-{i}"}
                     for i in range(n)]
            return Req({"items": items, **({"nextPageToken": nxt} if nxt else {})})

    class CalList:
        def get(self, calendarId): return Req({"id": "gal@example.com"})

    class Service:
        def events(self): return Events()
        def calendarList(self): return CalList()

    monkeypatch.setattr(ga, "get_flow", lambda: FakeFlow())
    monkeypatch.setattr(ga, "build", lambda *a, **k: Service())
    monkeypatch.setattr(ga, "verify_oauth_state", lambda s, c: True)

    r = client.get("/auth/callback?state=x&code=y", follow_redirects=False)
    assert r.status_code == 307 and "#user=gal%40example.com&token=" in r.headers["location"]
    assert all("summary" not in c["fields"] and "description" not in c["fields"] for c in calls)  # titles never requested
    (count,) = client.fake.execute("SELECT COUNT(*) FROM busy_times WHERE user_id = 'gal@example.com' AND source = 'google'").fetchone()
    assert count == 1350

    # Signing in again replaces the synced events instead of duplicating them.
    client.get("/auth/callback?state=x&code=y", follow_redirects=False)
    (count,) = client.fake.execute("SELECT COUNT(*) FROM busy_times WHERE user_id = 'gal@example.com' AND source = 'google'").fetchone()
    assert count == 1350


def test_blocks_only_say_whose_they_are(client):
    alice = signup(client, "alice@example.com")
    bob = signup(client, "bob@example.com")
    client.post("/groups/join?group_id=Abc23456", headers=alice)
    client.post("/groups/join?group_id=Abc23456", headers=bob)
    url = "/availability/merge?days=7&start_offset=0&timezone=America/Vancouver&group=Abc23456"
    client.post(url, json=[[{"start": "2031-01-01T10:00", "end": "2031-01-01T11:00", "title": "Doctor"}]], headers=alice)
    # A title saved before this change must not leak either.
    client.fake.execute("INSERT INTO busy_times (user_id, start, end_time, source, raw_timezone, title) VALUES "
                        "('alice@example.com', datetime('now', '+1 day'), datetime('now', '+1 day', '+1 hour'), 'google', 'UTC', 'Therapy')")
    r = client.post(url, json=[], headers=bob)
    body = r.text
    assert "Doctor" not in body and "Therapy" not in body
    assert all(b["title"] is None for b in r.json()["busy_times"])
    assert any(b["owner"] == "alice@example.com" for b in r.json()["busy_times"])


def test_free_declined_and_working_location_events_dont_block_time(client):
    from app.google_auth import blocks_time
    assert blocks_time({"start": {}, "end": {}})
    assert not blocks_time({"transparency": "transparent"})
    assert not blocks_time({"eventType": "workingLocation"})
    assert not blocks_time({"attendees": [{"self": True, "responseStatus": "declined"}]})
    assert blocks_time({"attendees": [{"responseStatus": "declined"}, {"self": True, "responseStatus": "accepted"}]})
    assert blocks_time({"eventType": "focusTime", "transparency": "opaque"})


def test_a_plain_refresh_never_wipes_saved_manual_blocks(client):
    alice = signup(client, "alice@example.com")
    url = "/availability/merge?days=7&start_offset=0&timezone=America/Vancouver"
    client.post(url, json=[[{"start": "2031-01-01T10:00", "end": "2031-01-01T11:00"}]], headers=alice)
    # A second device with nothing stored locally just refreshes...
    client.post(url + "&keep_manual=1", json=[], headers=alice)
    saved = client.get("/availability/manual", headers=alice).json()["blocks"]
    assert len(saved) == 1 and saved[0]["start"].startswith("2031-01-01T10:00")
    # ...while an explicit save of an empty list (Clear) still clears them.
    client.post(url, json=[], headers=alice)
    assert client.get("/availability/manual", headers=alice).json()["blocks"] == []


def test_members_see_each_others_chosen_names(client):
    alice = signup(client, "alice.smith@example.com")
    bob = signup(client, "bob@example.com")
    assert client.get("/auth/me", headers=alice).json()["name"] == "alice.smith"  # default
    r = client.post("/auth/name", json={"name": "  Alice   S  "}, headers=alice)
    assert r.json() == {"name": "Alice S", "custom_name": True}
    for h in (alice, bob):
        client.post("/groups/join?group_id=Abc23456", headers=h)
    url = "/availability/merge?days=7&start_offset=0&timezone=America/Vancouver&group=Abc23456"
    client.post(url, json=[[{"start": "2031-01-01T10:00", "end": "2031-01-01T11:00"}]], headers=alice)
    client.fake.execute("INSERT INTO busy_times (user_id, start, end_time, source, raw_timezone, title) VALUES "
                        "('alice.smith@example.com', datetime('now', '+1 day'), datetime('now', '+1 day', '+1 hour'), 'manual', 'UTC', NULL)")
    blocks = client.post(url + "&keep_manual=1", json=[], headers=bob).json()["busy_times"]
    assert any(b["owner_name"] == "Alice S" for b in blocks)
    # Blank resets to the email default.
    assert client.post("/auth/name", json={"name": ""}, headers=alice).json() == {"name": "alice.smith", "custom_name": False}
    assert client.post("/auth/name", json={"name": "x"}).status_code == 401


def test_named_groups_list_rename_and_leave(client):
    sam = signup(client, "sam@example.com")
    priya = signup(client, "priya@example.com")
    client.post("/auth/name", json={"name": "Priya K"}, headers=priya)
    client.post("/groups/join?group_id=Robo2345&name=Robotics%20team", headers=sam)
    client.post("/groups/join?group_id=Gym23456", headers=sam)
    # Joining someone's link never renames their group.
    client.post("/groups/join?group_id=Robo2345&name=Hijack", headers=priya)

    groups = {g["id"]: g for g in client.get("/groups", headers=sam).json()["groups"]}
    assert groups["Robo2345"]["name"] == "Robotics team" and groups["Gym23456"]["name"] is None
    assert sorted(m["name"] for m in groups["Robo2345"]["members"]) == ["Priya K", "You"]

    assert client.post("/groups/rename?group_id=Gym23456&name=Gym%20crew", headers=sam).json()["name"] == "Gym crew"
    # Only members can rename (and only the admin, see the admin test).
    assert client.post("/groups/rename?group_id=Gym23456&name=x", headers=priya).status_code == 404

    client.post("/groups/leave?group_id=Robo2345", headers=sam)
    assert [g["id"] for g in client.get("/groups", headers=sam).json()["groups"]] == ["Gym23456"]
    # The link still works for the people still in it.
    assert [[m["name"] for m in g["members"]] for g in client.get("/groups", headers=priya).json()["groups"]] == [["You"]]


def test_group_admin_controls_settings_and_can_remove_people(client):
    sam = signup(client, "sam@example.com")
    priya = signup(client, "priya@example.com")
    client.post("/groups/join?group_id=Team2345&name=Team", headers=sam)
    client.post("/groups/join?group_id=Team2345", headers=priya)

    g = client.get("/groups", headers=sam).json()["groups"][0]
    assert g["is_admin"] and not g["claimable"]
    assert [m["admin"] for m in g["members"] if m["you"]] == [True]
    assert not client.get("/groups", headers=priya).json()["groups"][0]["is_admin"]

    rules = {"dayStart": "09:00", "dayEnd": "17:00", "meetingLength": 60,
             "excludeWeekends": True, "timePrefs": ["morning"]}
    # Members can't change the group's settings or name; the admin can.
    assert client.post("/groups/settings?group_id=Team2345", json=rules, headers=priya).status_code == 403
    assert client.post("/groups/rename?group_id=Team2345&name=x", headers=priya).status_code == 403
    saved = client.post("/groups/settings?group_id=Team2345", json=rules, headers=sam).json()["settings"]
    assert saved["timePrefs"] == ["morning", "afternoon", "evening"] and saved["meetingLength"] == 60
    assert client.post("/groups/settings?group_id=Team2345", json={**rules, "dayEnd": "08:00"}, headers=sam).status_code == 400

    # Whatever a member's browser asks for, the group's settings are used.
    url = "/availability/merge?days=14&start_offset=0&timezone=America/Vancouver&group=Team2345&keep_manual=1&min_minutes=15&day_start=06:00&day_end=23:00&prefer=evening"
    r = client.post(url, json=[], headers=priya).json()
    assert r["group_settings"]["meetingLength"] == 60
    from datetime import date
    assert all(f["duration_minutes"] == 60 for f in r["ranked_free_time"])
    assert all(date.fromisoformat(f["date"]).weekday() < 5 for f in r["ranked_free_time"])
    assert all("09:00" <= f["start"][11:16] and f["end"][11:16] <= "17:00" for f in r["ranked_free_time"])

    # Removing someone: only the admin, not themselves, and no rejoining.
    assert client.post("/groups/kick?group_id=Team2345&member=sam@example.com", headers=priya).status_code == 403
    assert client.post("/groups/kick?group_id=Team2345&member=sam@example.com", headers=sam).status_code == 400
    assert client.post("/groups/kick?group_id=Team2345&member=priya@example.com", headers=sam).json() == {"removed": True}
    assert client.get("/groups", headers=priya).json()["groups"] == []
    assert client.post("/groups/join?group_id=Team2345", headers=priya).status_code == 403


def test_older_groups_without_an_admin_can_be_claimed_once(client):
    sam = signup(client, "sam@example.com")
    priya = signup(client, "priya@example.com")
    for h in (sam, priya):
        client.post("/groups/join?group_id=Old23456", headers=h)
    client.fake.execute("UPDATE groups SET owner = NULL WHERE id = 'Old23456'")  # made before admins existed
    assert client.get("/groups", headers=priya).json()["groups"][0]["claimable"]
    assert client.post("/groups/claim?group_id=Old23456", headers=priya).json() == {"is_admin": True}
    assert client.post("/groups/claim?group_id=Old23456", headers=sam).status_code == 409
    assert client.get("/groups", headers=priya).json()["groups"][0]["is_admin"]
