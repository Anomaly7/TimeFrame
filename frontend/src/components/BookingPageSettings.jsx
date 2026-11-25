import { useEffect, useState } from "react";
import { API_URL } from "../config";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; // Python weekday() order
const MY_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

function suggestHandle(name) {
  return (name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30) || "me";
}

// Owner settings for the Pro booking page (from the account menu).
export default function BookingPageSettings({ authHeaders, myName, onClose, onNeedPro, notify }) {
  const [page, setPage] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/booking-page`, { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => {
        if (!d.pro) return onNeedPro();
        setSaved(!!d.page);
        setPage(d.page || {
          handle: suggestHandle(myName), enabled: true, title: "Meet with me", minutes: 30, day_start: "09:00",
          day_end: "17:00", weekdays: [0, 1, 2, 3, 4], days_ahead: 14, notice_hours: 12, buffer: 0, timezone: MY_TZ,
        });
      })
      .catch(() => setError("Couldn't load your booking page."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!page) {
    return (
      <div className="modal-backdrop" onClick={onClose}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>{error || "Loading…"}</div>
      </div>
    );
  }

  const set = (patch) => setPage({ ...page, ...patch });
  const link = `${window.location.origin}/${page.handle}`;

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/booking-page`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(page),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Couldn't save.");
      setPage(data.page);
      setSaved(true);
      notify?.("Booking page saved.");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal bp-settings" role="dialog" aria-modal="true" aria-label="Booking page" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        <h2>Your booking page</h2>
        <p className="muted-line">People pick one of your free times; it shows up in your Plan tab and bell. They never see your events.</p>
        {saved && page.enabled && (
          <div className="bp-link">
            <a href={link} target="_blank" rel="noopener noreferrer">{link.replace(/^https?:\/\//, "")}</a>
            <button type="button" className="link-btn" onClick={() => navigator.clipboard?.writeText(link).then(() => setCopied(true))}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        )}
        <form onSubmit={save}>
          <label className="settings-checkbox bp-enabled">
            <input type="checkbox" checked={page.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> Page is on
          </label>
          <label className="field"><span>Link</span>
            <div className="bp-handle"><em>{window.location.host}/</em>
              <input value={page.handle} maxLength={30} onChange={(e) => set({ handle: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") })} />
            </div>
          </label>
          <label className="field"><span>Title</span>
            <input value={page.title} maxLength={60} onChange={(e) => set({ title: e.target.value })} />
          </label>
          <div className="field-row">
            <label className="field"><span>Length</span>
              <select value={page.minutes} onChange={(e) => set({ minutes: Number(e.target.value) })}>
                {[15, 20, 30, 45, 60, 90, 120].map((m) => <option key={m} value={m}>{m} min</option>)}
              </select>
            </label>
            <label className="field"><span>From</span>
              <input type="time" value={page.day_start} onChange={(e) => set({ day_start: e.target.value })} />
            </label>
            <label className="field"><span>To</span>
              <input type="time" value={page.day_end} onChange={(e) => set({ day_end: e.target.value })} />
            </label>
          </div>
          <div className="field"><span>Days</span>
            <div className="bp-weekdays">
              {DAYS.map((d, i) => (
                <button type="button" key={d} className={page.weekdays.includes(i) ? "on" : ""}
                  onClick={() => set({ weekdays: page.weekdays.includes(i) ? page.weekdays.filter((x) => x !== i) : [...page.weekdays, i] })}>
                  {d}
                </button>
              ))}
            </div>
          </div>
          <div className="field-row">
            <label className="field"><span>Book up to</span>
              <select value={page.days_ahead} onChange={(e) => set({ days_ahead: Number(e.target.value) })}>
                {[7, 14, 21, 30, 60].map((d) => <option key={d} value={d}>{d} days ahead</option>)}
              </select>
            </label>
            <label className="field"><span>Notice</span>
              <select value={page.notice_hours} onChange={(e) => set({ notice_hours: Number(e.target.value) })}>
                {[0, 2, 12, 24, 48].map((h) => <option key={h} value={h}>{h ? `${h} h` : "None"}</option>)}
              </select>
            </label>
            <label className="field"><span>Buffer</span>
              <select value={page.buffer} onChange={(e) => set({ buffer: Number(e.target.value) })}>
                {[0, 10, 15, 30].map((b) => <option key={b} value={b}>{b ? `${b} min` : "None"}</option>)}
              </select>
            </label>
          </div>
          <p className="muted-line">Hours are in {page.timezone}.{page.timezone !== MY_TZ && (
            <> <button type="button" className="link-btn" onClick={() => set({ timezone: MY_TZ })}>Use {MY_TZ}</button></>
          )}</p>
          {error && <p className="error-text">{error}</p>}
          <div className="btn-row">
            <button className="btn btn-primary" type="submit" disabled={saving || page.weekdays.length === 0}>{saving ? "Saving..." : "Save"}</button>
            <button className="btn btn-ghost" type="button" onClick={onClose}>Close</button>
          </div>
        </form>
      </div>
    </div>
  );
}
