"""Google auto-sync (2026-11-25): tokens only kept when the server has a key, encrypted, deleted on Disconnect."""
from cryptography.fernet import Fernet

from tests.test_endpoints import client, signup  # noqa: F401


def test_without_a_key_nothing_is_stored_and_sync_now_asks_to_reconnect(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_TOKEN_KEY", raising=False)
    from app.google_sync import save_refresh_token
    sam = signup(client, "sam@example.com")
    save_refresh_token("sam@example.com", "1//secret-refresh")
    assert client.fake.execute("SELECT COUNT(*) FROM google_tokens").fetchone()[0] == 0
    assert client.post("/sync/google", headers=sam).json() == {"synced": False, "reconnect": True}
    s = client.get("/auth/status", headers=sam).json()
    assert s["auto_sync"] is False and s["auto_sync_available"] is False


def test_with_a_key_the_token_is_encrypted_and_disconnect_deletes_it(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_TOKEN_KEY", Fernet.generate_key().decode())
    from app import google_sync
    monkeypatch.setattr(google_sync.urllib.request, "urlopen", lambda *a, **k: None)  # no real revoke call
    sam = signup(client, "sam@example.com")
    google_sync.save_refresh_token("Sam@Example.com", "1//secret-refresh")
    client.fake.commit()
    stored = client.fake.execute("SELECT token FROM google_tokens").fetchone()[0]
    assert "secret-refresh" not in stored
    assert google_sync._refresh_token("sam@example.com") == "1//secret-refresh"
    assert client.get("/auth/status", headers=sam).json()["auto_sync"] is True
    client.post("/auth/disconnect", headers=sam)
    assert client.fake.execute("SELECT COUNT(*) FROM google_tokens").fetchone()[0] == 0


def test_resync_uses_the_stored_token_and_records_the_time(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_TOKEN_KEY", Fernet.generate_key().decode())
    from app import google_auth, google_sync
    calls = []

    def fake_import(creds, expect_user=None):
        calls.append((creds.refresh_token, expect_user))
        google_sync.mark_synced(expect_user, "google")
        return expect_user
    monkeypatch.setattr(google_auth, "import_google_events", fake_import)
    sam = signup(client, "sam@example.com")
    google_sync.save_refresh_token("sam@example.com", "1//tok")
    client.fake.commit()
    r = client.post("/sync/google", headers=sam).json()
    assert r["synced"] is True and r["synced_at"]
    assert calls == [("1//tok", "sam@example.com")]
    # fresh now, so the background pass skips it
    assert google_sync.sync_stale_users() == 0


def test_a_revoked_token_is_dropped_with_a_reconnect_message(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_TOKEN_KEY", Fernet.generate_key().decode())
    from google.auth.exceptions import RefreshError
    from app import google_auth, google_sync

    def boom(creds, expect_user=None):
        raise RefreshError("invalid_grant")
    monkeypatch.setattr(google_auth, "import_google_events", boom)
    sam = signup(client, "sam@example.com")
    google_sync.save_refresh_token("sam@example.com", "1//tok")
    client.fake.commit()
    assert client.post("/sync/google", headers=sam).status_code == 502
    assert client.fake.execute("SELECT COUNT(*) FROM google_tokens").fetchone()[0] == 0
    assert "Reconnect" in client.get("/auth/status", headers=sam).json()["sync_error"]
