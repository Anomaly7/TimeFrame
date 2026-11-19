"""Apple Calendar (iCloud CalDAV) and Notion connections (Sam's request, 2026-11-18).
Apple's and Notion's servers are faked; nothing here touches the network."""
from datetime import date, timedelta

from tests.test_endpoints import client, signup  # noqa: F401  (client is a pytest fixture)

DAY = (date.today() + timedelta(days=3)).strftime("%Y%m%d")


def _vevent(uid, hour, extra=""):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:test\r\nBEGIN:VEVENT\r\n"
            f"UID:{uid}\r\nDTSTART:{DAY}T{hour:02d}0000Z\r\nDURATION:PT1H\r\n{extra}SUMMARY:x\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


def _fake_icloud(calls):
    principal = b"""<d:multistatus xmlns:d="DAV:"><d:response><d:href>/</d:href><d:propstat><d:prop>
        <d:current-user-principal><d:href>/123/principal/</d:href></d:current-user-principal></d:prop></d:propstat></d:response></d:multistatus>"""
    home = b"""<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>/123/principal/</d:href>
        <d:propstat><d:prop><c:calendar-home-set><d:href>https://p42-caldav.icloud.com/123/calendars/</d:href></c:calendar-home-set>
        </d:prop></d:propstat></d:response></d:multistatus>"""
    listing = b"""<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
        <d:response><d:href>/123/calendars/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>
        <d:response><d:href>/123/calendars/home/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
          <c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set></d:prop></d:propstat></d:response>
        <d:response><d:href>/123/calendars/work/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
          </d:prop></d:propstat></d:response>
        <d:response><d:href>/123/calendars/tasks/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
          <c:supported-calendar-component-set><c:comp name="VTODO"/></c:supported-calendar-component-set></d:prop></d:propstat></d:response>
        </d:multistatus>"""

    def report(events):
        body = "".join(f"<d:response><d:href>/e{i}.ics</d:href><d:propstat><d:prop><c:calendar-data>{e}</c:calendar-data>"
                       "</d:prop></d:propstat></d:response>" for i, e in enumerate(events))
        return f'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">{body}</d:multistatus>'.encode()

    def fake(method, url, auth, body, depth):
        import app.apple_calendar as ac
        assert ac._allowed(url)
        calls.append((method, url))
        if method == "PROPFIND" and url == "https://caldav.icloud.com/":
            return url, principal
        if method == "PROPFIND" and url.endswith("/principal/"):
            return url, home
        if method == "PROPFIND":
            return url, listing
        if url.endswith("/home/"):
            return url, report([_vevent("a", 15), _vevent("free", 17, "TRANSP:TRANSPARENT\r\n")])
        if url.endswith("/work/"):
            return url, report([_vevent("b", 19), _vevent("dup", 15)])  # 15:00 also on home: counted once
        raise AssertionError("reminders list must not be read: " + url)
    return fake


def test_apple_connect_imports_busy_times(client, monkeypatch):
    import app.apple_calendar as ac
    calls = []
    monkeypatch.setattr(ac, "_request", _fake_icloud(calls))
    h = signup(client, "apple@example.com")
    assert client.get("/apple/status", headers=h).json() == {"connected": False}

    r = client.post("/apple/connect", json={"apple_id": "sam@icloud.com", "app_password": "abcd-efgh-ijkl-mnop"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"imported": 2}  # the "Free" event and the duplicate are skipped
    assert not any(u.endswith("/tasks/") for _, u in calls)
    assert client.get("/apple/status", headers=h).json() == {"connected": True}

    # Never stored: no column anywhere holds the password.
    dump = "\n".join(str(r) for r in client.fake.db.iterdump())
    assert "abcd-efgh" not in dump and "abcdefgh" not in dump

    assert client.post("/apple/disconnect", headers=h).status_code == 200
    assert client.get("/apple/status", headers=h).json() == {"connected": False}
    assert client.fake.execute("SELECT COUNT(*) FROM busy_times WHERE source = 'apple'").fetchone()[0] == 0


def test_apple_wrong_password_and_sign_in_required(client, monkeypatch):
    import app.apple_calendar as ac

    def reject(*a):
        raise ac.AppleAuthError()
    monkeypatch.setattr(ac, "_request", reject)
    assert client.post("/apple/connect", json={"apple_id": "a@b.c", "app_password": "x"}).status_code == 401  # not signed in
    h = signup(client, "apple2@example.com")
    r = client.post("/apple/connect", json={"apple_id": "a@b.c", "app_password": "wrong"}, headers=h)
    assert r.status_code == 401 and "app-specific" in r.json()["detail"]
    assert client.post("/apple/connect", json={"apple_id": "", "app_password": ""}, headers=h).status_code == 400


def test_apple_credentials_only_go_to_icloud(client):
    import app.apple_calendar as ac
    assert ac._allowed("https://p42-caldav.icloud.com:443/1/calendars/")
    assert not ac._allowed("http://caldav.icloud.com/")
    assert not ac._allowed("https://icloud.com.evil.example/")
    assert not ac._allowed("https://evil.example/?x=.icloud.com")


# ---------------- Notion ----------------
def _fake_notion(email="notion@example.com"):
    d = (date.today() + timedelta(days=3)).isoformat()
    pages = [
        {"properties": {"When": {"date": {"start": f"{d}T10:00:00.000-08:00", "end": f"{d}T11:30:00.000-08:00"}}}},
        {"properties": {"When": {"date": {"start": f"{d}T14:00:00.000-08:00", "end": None}}}},  # no end: 1 h
        {"properties": {"When": {"date": {"start": f"{d}T09:00:00", "time_zone": "America/Los_Angeles"}}}},
        {"properties": {"When": {"date": {"start": d}}}},  # date only (a deadline): not busy
        {"properties": {"When": {"date": None}}},
    ]

    def post(token, path, body):
        assert token == "secret-token"
        if path == "/search":
            return {"results": [{"id": "db1", "properties": {"When": {"type": "date"}, "Name": {"type": "title"}}}],
                    "has_more": False}
        assert path == "/databases/db1/query"
        return {"results": pages, "has_more": False}

    def exchange(code):
        assert code == "good-code"
        owner = {"type": "user", "user": {"person": {"email": email}}} if email else {"type": "workspace"}
        return {"access_token": "secret-token", "owner": owner}
    return post, exchange


def _notion_env(monkeypatch, email="notion@example.com"):
    import app.notion_auth as na
    monkeypatch.setenv("NOTION_CLIENT_ID", "cid")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("NOTION_REDIRECT_URI", "https://api.example/notion/callback")
    post, exchange = _fake_notion(email)
    monkeypatch.setattr(na, "notion_post", post)
    monkeypatch.setattr(na, "exchange_code", exchange)
    return na


def _start(client, ticket=None):
    from urllib.parse import parse_qs, urlparse
    r = client.get("/notion/login" + (f"?ticket={ticket}" if ticket else ""), follow_redirects=False)
    assert r.status_code in (302, 307), r.text
    loc = r.headers["location"]
    assert loc.startswith("https://api.notion.com/v1/oauth/authorize?")
    return parse_qs(urlparse(loc).query)["state"][0], r.cookies.get("notion_nonce")


def _finish(client, state, nonce, code="good-code"):
    client.cookies.set("notion_nonce", nonce or "", path="/notion")
    r = client.get(f"/notion/callback?state={state}&code={code}", follow_redirects=False)
    client.cookies.clear()
    return r.headers["location"]


def test_sign_in_with_notion_imports_timed_entries(client, monkeypatch):
    _notion_env(monkeypatch)
    state, nonce = _start(client)
    loc = _finish(client, state, nonce)
    assert "#user=notion%40example.com" in loc and "&token=" in loc and loc.endswith("&notion=3")
    rows = client.fake.execute("SELECT start, end_time FROM busy_times WHERE source = 'notion' ORDER BY start").fetchall()
    assert len(rows) == 3
    assert rows[0][0].endswith("T09:00:00-08:00") and rows[0][1].endswith("T10:00:00-08:00")
    assert rows[2][0].endswith("T14:00:00-08:00") and rows[2][1].endswith("T15:00:00-08:00")
    token = loc.split("&token=")[1].split("&")[0]
    h = {"Authorization": "Bearer " + token}
    assert client.get("/notion/status", headers=h).json() == {"connected": True, "available": True}
    assert "secret-token" not in "\n".join(client.fake.db.iterdump())


def test_connect_notion_to_existing_account(client, monkeypatch):
    _notion_env(monkeypatch, email="someone-else@example.com")
    h = signup(client, "me@example.com")
    ticket = client.post("/notion/link-ticket", headers=h).json()["ticket"]
    state, nonce = _start(client, ticket)
    loc = _finish(client, state, nonce)
    assert "#user=me%40example.com" in loc  # stays on the signed-in account, whatever Notion's email is
    assert client.fake.execute("SELECT COUNT(*) FROM busy_times WHERE user_id = 'me@example.com' AND source = 'notion'").fetchone()[0] == 3
    # A session token is not a ticket, and a ticket is not a session.
    assert client.get("/notion/status", headers={"Authorization": "Bearer " + ticket}).status_code == 401
    assert "auth_error" in client.get("/notion/login?ticket=" + h["Authorization"][7:], follow_redirects=False).headers["location"]


def test_notion_refuses_replay_and_unverified_password_accounts(client, monkeypatch):
    _notion_env(monkeypatch)
    state, _ = _start(client)
    assert "auth_error" in _finish(client, state, "wrong-nonce")  # started in another browser
    # Someone made a password account with the Notion email: don't merge into it.
    signup(client, "notion@example.com")
    state, nonce = _start(client)
    assert "auth_error" in _finish(client, state, nonce)
    assert client.fake.execute("SELECT COUNT(*) FROM busy_times WHERE source = 'notion'").fetchone()[0] == 0


def test_notion_without_email_or_config(client, monkeypatch):
    _notion_env(monkeypatch, email=None)
    state, nonce = _start(client)
    assert "auth_error" in _finish(client, state, nonce)
    monkeypatch.delenv("NOTION_CLIENT_ID")
    r = client.get("/notion/login", follow_redirects=False)
    assert "auth_error" in r.headers["location"]


def test_notion_available_tracks_server_config(client, monkeypatch):
    for k in ("NOTION_CLIENT_ID", "NOTION_CLIENT_SECRET", "NOTION_REDIRECT_URI"):
        monkeypatch.delenv(k, raising=False)
    assert client.get("/notion/available").json() == {"available": False}
    monkeypatch.setenv("NOTION_CLIENT_ID", "id")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "secret")
    monkeypatch.setenv("NOTION_REDIRECT_URI", "https://api.example/notion/callback")
    assert client.get("/notion/available").json() == {"available": True}


def test_apple_sign_in_from_the_sign_in_page(client, monkeypatch):
    import app.apple_calendar as ac
    monkeypatch.setattr(ac, "_request", _fake_icloud([]))

    # New person: signing in with Apple creates the account (the Apple ID email) and imports their calendars.
    r = client.post("/apple/login", json={"apple_id": "New.Person@iCloud.com", "app_password": "abcd-efgh-ijkl-mnop"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["email"] == "new.person@icloud.com" and out["imported"] == 2 and out["token"]
    h = {"Authorization": "Bearer " + out["token"]}
    assert client.get("/apple/status", headers=h).json() == {"connected": True}
    dump = "\n".join(str(row) for row in client.fake.db.iterdump())
    assert "abcd-efgh" not in dump and "abcdefgh" not in dump  # the password is never stored

    # Someone already made an unverified password account with that email: don't hand it over.
    signup(client, "taken@icloud.com")
    r = client.post("/apple/login", json={"apple_id": "taken@icloud.com", "app_password": "abcd-efgh-ijkl-mnop"})
    assert r.status_code == 409

    # Apple says no: no account, no session.
    def reject(*a):
        raise ac.AppleAuthError()
    monkeypatch.setattr(ac, "_request", reject)
    r = client.post("/apple/login", json={"apple_id": "nobody@icloud.com", "app_password": "wrong"})
    assert r.status_code == 401
    assert client.fake.execute("SELECT COUNT(*) FROM users WHERE id = 'nobody@icloud.com'").fetchone()[0] == 0
    assert client.post("/apple/login", json={"apple_id": "not-an-email", "app_password": "x"}).status_code == 400
