from tests.test_endpoints import client, signup  # noqa: F401  (client is a pytest fixture)


def test_batched_insert_keeps_every_row_across_chunks(client):
    from app.busy_store import insert_busy_rows, CHUNK
    n = CHUNK * 2 + 37  # three statements, the last one partial
    rows = [("u@example.com", f"2031-01-01T{i % 24:02d}:00:00-08:00", f"2031-01-01T{i % 24:02d}:30:00-08:00",
             "google", "America/Vancouver", f"Event {i}") for i in range(n)]
    insert_busy_rows(rows)
    insert_busy_rows([])  # nothing to save is fine
    saved = client.fake.execute("SELECT title FROM busy_times WHERE user_id = 'u@example.com' ORDER BY id").fetchall()
    assert [t for (t,) in saved] == [f"Event {i}" for i in range(n)]


def test_manual_blocks_still_round_trip_through_merge(client):
    alice = signup(client, "alice@example.com")
    blocks = [[{"start": f"2031-01-0{d}T10:00", "end": f"2031-01-0{d}T11:00", "title": f"Block {d}"} for d in range(1, 6)]]
    url = "/availability/merge?days=7&start_offset=0&timezone=America/Vancouver"
    client.post(url, json=blocks, headers=alice)
    client.post(url, json=blocks, headers=alice)  # saving again replaces, never duplicates
    rows = client.fake.execute("SELECT title FROM busy_times WHERE user_id = 'alice@example.com' AND source = 'manual'").fetchall()
    assert sorted(t for (t,) in rows) == [f"Block {d}" for d in range(1, 6)]


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
    assert all(c["fields"] == "nextPageToken,items(start,end,summary)" for c in calls)
    (count,) = client.fake.execute("SELECT COUNT(*) FROM busy_times WHERE user_id = 'gal@example.com' AND source = 'google'").fetchone()
    assert count == 1350

    # Signing in again replaces the synced events instead of duplicating them.
    client.get("/auth/callback?state=x&code=y", follow_redirects=False)
    (count,) = client.fake.execute("SELECT COUNT(*) FROM busy_times WHERE user_id = 'gal@example.com' AND source = 'google'").fetchone()
    assert count == 1350
