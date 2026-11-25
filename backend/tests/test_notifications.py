"""Notifications (2026-11-25): the bell, push subscriptions, reminders."""
import base64
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric import ec

from tests.test_bookings import _group, _span
from tests.test_endpoints import client, signup  # noqa: F401


def _bell(client, who):
    return client.get("/notifications", headers=who).json()


def test_joining_booking_and_polls_ring_the_others(client):
    sam, priya, eve = _group(client)  # priya joining notifies sam
    assert [n["kind"] for n in _bell(client, sam)["notifications"]] == ["joined"]
    s, e = _span()
    client.post("/groups/book?group_id=Book2345", json={"title": "Standup", "start": s, "end": e}, headers=sam)
    bell = _bell(client, priya)
    assert bell["unread"] == 1 and "Standup" in bell["notifications"][0]["text"] and "Team" in bell["notifications"][0]["text"]
    assert _bell(client, eve)["notifications"] == []  # not in the group
    assert all(n["kind"] != "booked" for n in _bell(client, sam)["notifications"])  # not told about your own booking
    client.post("/notifications/read", headers=priya)
    assert _bell(client, priya)["unread"] == 0


def test_a_reminder_goes_out_once_an_hour_before(client):
    from app import notifications
    sam, priya, eve = _group(client)
    start = datetime.now(timezone.utc) + timedelta(minutes=30)
    client.post("/groups/book?group_id=Book2345", headers=sam,
                json={"title": "Soon", "start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat()})
    later = datetime.now(timezone.utc) + timedelta(days=3)
    client.post("/groups/book?group_id=Book2345", headers=sam,
                json={"title": "Later", "start": later.isoformat(), "end": (later + timedelta(hours=1)).isoformat()})
    assert notifications.send_due_reminders() == 1
    assert notifications.send_due_reminders() == 0
    reminders = [n for n in _bell(client, sam)["notifications"] if n["kind"] == "reminder"]
    assert len(reminders) == 1 and "Soon" in reminders[0]["text"]


def test_push_is_off_without_a_key_and_subscriptions_are_checked(client, monkeypatch):
    sam = signup(client, "sam@example.com")
    sub = {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "x" * 80, "auth": "y" * 20}}
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    assert client.get("/push/key").json() == {"available": False, "key": None}
    assert client.post("/push/subscribe", json=sub, headers=sam).status_code == 503
    raw = ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value.to_bytes(32, "big")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", base64.urlsafe_b64encode(raw).decode().rstrip("="))
    key = client.get("/push/key").json()
    assert key["available"] and len(base64.urlsafe_b64decode(key["key"] + "==")) == 65
    assert client.post("/push/subscribe", json={**sub, "endpoint": "http://insecure"}, headers=sam).status_code == 400
    assert client.post("/push/subscribe", json=sub, headers=sam).json() == {"subscribed": True}
    sent = []
    import pywebpush
    monkeypatch.setattr(pywebpush, "webpush", lambda info, data, **kw: sent.append(info["endpoint"]))
    from app import notifications
    monkeypatch.setattr(notifications.threading, "Thread", lambda target, daemon=None, **kw: type("T", (), {"start": lambda self: target()})())
    notifications.notify_user("sam@example.com", "test", "Hello")
    assert sent == ["https://push.example.com/abc"]
