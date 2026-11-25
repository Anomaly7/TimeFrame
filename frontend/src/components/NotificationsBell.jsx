import { useEffect, useState } from "react";
import { API_URL } from "../config";
import { ago } from "../util";

const ICONS = { joined: "👋", booked: "📅", cancelled: "✖️", poll: "🗳️", reminder: "⏰", booking_page: "📥" };

function keyBytes(base64url) {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

// The bell in the top bar: who joined, what got booked, polls, reminders. Also turns on push for this device.
export default function NotificationsBell({ authHeaders, onActivity, notify }) {
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [pushKey, setPushKey] = useState(null);
  const [pushOn, setPushOn] = useState(false);

  async function load() {
    try {
      const res = await fetch(`${API_URL}/notifications`, { headers: authHeaders() });
      if (!res.ok) return;
      const data = await res.json();
      setItems(data.notifications);
      setUnread((prev) => {
        if (data.unread > prev) onActivity?.();
        return data.unread;
      });
    } catch { /* offline */ }
  }

  useEffect(() => {
    load();
    const timer = setInterval(() => document.visibilityState === "visible" && load(), 60000);
    fetch(`${API_URL}/push/key`).then((r) => (r.ok ? r.json() : {})).then((d) => d.available && setPushKey(d.key)).catch(() => {});
    navigator.serviceWorker?.ready
      .then((reg) => reg.pushManager?.getSubscription())
      .then((sub) => setPushOn(!!sub))
      .catch(() => {});
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && unread > 0) {
      setUnread(0);
      fetch(`${API_URL}/notifications/read`, { method: "POST", headers: authHeaders() }).catch(() => {});
    }
  }

  async function enablePush() {
    try {
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        throw new Error(/iPhone|iPad/.test(navigator.userAgent)
          ? "On iPhone, add TimeFrame to your Home Screen first (Share > Add to Home Screen), then turn this on there."
          : "This browser can't show notifications.");
      }
      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error("Notifications are blocked for this site in your browser settings.");
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(pushKey) });
      const res = await fetch(`${API_URL}/push/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(sub.toJSON()),
      });
      if (!res.ok) throw new Error("Couldn't turn on notifications.");
      setPushOn(true);
      notify?.("Notifications are on for this device.");
    } catch (err) {
      notify?.(err.message, "error");
    }
  }

  async function disablePush() {
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await fetch(`${API_URL}/push/unsubscribe`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({ endpoint: sub.endpoint }),
        }).catch(() => {});
        await sub.unsubscribe();
      }
      setPushOn(false);
    } catch { /* ignore */ }
  }

  return (
    <div className="bell">
      <button type="button" className="icon-btn bell-btn" onClick={toggle} aria-label={`Notifications${unread ? ` (${unread} new)` : ""}`} aria-expanded={open}>
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15L6 16z" />
          <path fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" d="M10 20.5a2.2 2.2 0 0 0 4 0" />
        </svg>
        {unread > 0 && <span className="bell-dot">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <>
          <div className="dash-menu-backdrop" onClick={() => setOpen(false)} />
          <div className="bell-menu" role="dialog" aria-label="Notifications">
            <div className="bell-head">
              <strong>Notifications</strong>
              {pushKey && (pushOn
                ? <button className="link-btn muted" onClick={disablePush}>Push on · turn off</button>
                : <button className="link-btn" onClick={enablePush}>Turn on push</button>)}
            </div>
            {items.length === 0 && <p className="muted-line bell-empty">Nothing yet. You'll hear when someone joins, books a time or starts a poll.</p>}
            <ul>
              {items.map((n) => (
                <li key={n.id} className={n.read ? "" : "unread"}>
                  <span className="bell-icon" aria-hidden="true">{ICONS[n.kind] || "•"}</span>
                  <span className="bell-text">{n.text}<small>{ago(n.created_at)}</small></span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
