"""Importing more than one kind of event (Sam's bug report, 2026-11-18): every Google calendar the user has
turned on, and several .ics files at once, must all end up as busy time."""
from datetime import date, timedelta

from tests.test_endpoints import client, signup  # noqa: F401  (client is a pytest fixture)


def _ics(uid, day, hour):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:test\r\n"
            f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTART:{day}T{hour:02d}0000Z\r\nDURATION:PT1H\r\nSUMMARY:x\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n")


def test_several_ics_files_import_together(client):
    h = signup(client, "multi@example.com")
    d = (date.today() + timedelta(days=3)).strftime("%Y%m%d")
    files = [
        ("files", ("classes.ics", _ics("a", d, 15), "text/calendar")),
        ("files", ("work.ics", _ics("b", d, 18), "text/calendar")),
        ("files", ("copy.ics", _ics("c", d, 15), "text/calendar")),  # same time as classes: counted once
    ]
    r = client.post("/import/ics", files=files, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"imported": 2, "files": 3}
    rows = client.fake.execute("SELECT COUNT(*) FROM busy_times WHERE user_id = 'multi@example.com' AND source = 'ics'").fetchone()
    assert rows[0] == 2

    # The old single-file form still works (cached pages), and a bad file stops the import before anything changes.
    assert client.post("/import/ics", files={"file": ("one.ics", _ics("d", d, 20), "text/calendar")}, headers=h).json()["imported"] == 1
    bad = [("files", ("ok.ics", _ics("e", d, 9), "text/calendar")), ("files", ("bad.ics", "not a calendar", "text/calendar"))]
    assert client.post("/import/ics", files=bad, headers=h).status_code == 400
    rows = client.fake.execute("SELECT COUNT(*) FROM busy_times WHERE user_id = 'multi@example.com' AND source = 'ics'").fetchone()
    assert rows[0] == 1


def test_google_imports_every_shown_calendar(client, monkeypatch):
    import app.google_auth as ga

    class FakeFlow:
        credentials = object()
        redirect_uri = None
        def fetch_token(self, **kw): pass

    class Req:
        def __init__(self, result): self.result = result
        def execute(self): return self.result

    def ev(hour):
        return {"start": {"dateTime": f"2031-03-03T{hour:02d}:00:00-08:00"}, "end": {"dateTime": f"2031-03-03T{hour:02d}:30:00-08:00"}}

    per_calendar = {
        "primary": [ev(9)],
        "classes@group.calendar.google.com": [ev(11), ev(9)],   # ev(9) is a copy of the primary one
        "work@group.calendar.google.com": [ev(14)],
        "hidden@group.calendar.google.com": [ev(16)],           # not shown in Google Calendar: skipped
        "en.canadian#holiday@group.v.calendar.google.com": [ev(8)],
        "shared-busy@group.calendar.google.com": None,          # can't be read: skipped, others still import
    }
    asked = []

    class Events:
        def list(self, **kw):
            asked.append(kw["calendarId"])
            items = per_calendar[kw["calendarId"]]
            if items is None:
                raise RuntimeError("403 forbidden")
            return Req({"items": items})

    class CalList:
        def get(self, calendarId): return Req({"id": "cal@example.com"})
        def list(self, **kw):
            return Req({"items": [
                {"id": "cal@example.com", "primary": True, "selected": True},
                {"id": "classes@group.calendar.google.com", "selected": True},
                {"id": "work@group.calendar.google.com", "selected": True},
                {"id": "hidden@group.calendar.google.com", "selected": False},
                {"id": "en.canadian#holiday@group.v.calendar.google.com", "selected": True},
                {"id": "shared-busy@group.calendar.google.com", "selected": True},
            ]})

    class Service:
        def events(self): return Events()
        def calendarList(self): return CalList()

    monkeypatch.setattr(ga, "get_flow", lambda: FakeFlow())
    monkeypatch.setattr(ga, "build", lambda *a, **k: Service())
    monkeypatch.setattr(ga, "IMPORT_IN_BACKGROUND", False)
    monkeypatch.setattr(ga, "verify_oauth_state", lambda s, c: True)

    r = client.get("/auth/callback?state=x&code=y", follow_redirects=False)
    assert r.status_code == 307
    assert "hidden@group.calendar.google.com" not in asked and not any("#holiday" in a for a in asked)
    rows = client.fake.execute("SELECT start FROM busy_times WHERE user_id = 'cal@example.com' AND source = 'google' ORDER BY start").fetchall()
    assert [s[11:13] for (s,) in rows] == ["09", "11", "14"]
