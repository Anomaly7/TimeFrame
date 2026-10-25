import { useState } from "react";
import { API_URL } from "../config";

const TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

function ymd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// When2meet-style poll setup: pick candidate dates on a small month grid,
// the hours to consider, then share the link.
export default function PollCreate({ authHeaders }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [month, setMonth] = useState(() => {
    const d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), 1);
  });
  const [dates, setDates] = useState([]);
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("17:00");
  const [slot, setSlot] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const today = ymd(new Date());
  const gridStart = new Date(month);
  gridStart.setDate(1 - month.getDay());
  const cells = Array.from({ length: 42 }, (_, i) => {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    return d;
  });

  function toggle(iso) {
    setDates((ds) => (ds.includes(iso) ? ds.filter((x) => x !== iso) : [...ds, iso].sort()));
  }

  function shiftMonth(n) {
    setMonth((m) => new Date(m.getFullYear(), m.getMonth() + n, 1));
  }

  async function create() {
    setError("");
    if (!dates.length) {
      setError("Pick at least one date.");
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(`${API_URL}/polls`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ title, dates, start, end, slot_minutes: slot, timezone: TIMEZONE }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Couldn't create the poll.");
      window.location.href = `${window.location.origin}/?poll=${data.id}`;
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="card poll-create">
        <div className="card-title">
          <h2>Group poll</h2>
        </div>
        <p className="card-subtitle">
          Like When2meet: pick some dates, share the link, and everyone paints when they're free. No account needed.
        </p>
        <button className="btn btn-primary" onClick={() => setOpen(true)}>New poll</button>
      </div>
    );
  }

  return (
    <div className="card poll-create">
      <div className="card-title">
        <h2>New group poll</h2>
      </div>

      <input
        className="activity-name-input"
        placeholder="What's it for? (e.g. Project meeting)"
        value={title}
        maxLength={100}
        onChange={(e) => setTitle(e.target.value)}
      />

      <div className="poll-date-picker">
        <div className="calendar-nav">
          <button className="btn-ghost" onClick={() => shiftMonth(-1)} aria-label="Previous month">‹</button>
          <span className="calendar-nav-label">
            {month.toLocaleDateString(undefined, { month: "long", year: "numeric" })}
          </span>
          <button className="btn-ghost" onClick={() => shiftMonth(1)} aria-label="Next month">›</button>
        </div>
        <div className="poll-month">
          {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
            <div key={i} className="month-weekday-label">{d}</div>
          ))}
          {cells.map((d) => {
            const iso = ymd(d);
            const past = iso < today;
            return (
              <button
                key={iso}
                disabled={past}
                className={`poll-day ${dates.includes(iso) ? "selected" : ""} ${d.getMonth() !== month.getMonth() ? "other-month" : ""}`}
                onClick={() => toggle(iso)}
              >
                {d.getDate()}
              </button>
            );
          })}
        </div>
        <p className="card-subtitle">{dates.length} date{dates.length === 1 ? "" : "s"} picked</p>
      </div>

      <div className="settings-row">
        <label className="settings-field">
          No earlier than
          <input type="time" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="settings-field">
          No later than
          <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label className="settings-field">
          Slot length
          <select value={slot} onChange={(e) => setSlot(Number(e.target.value))}>
            <option value={15}>15 minutes</option>
            <option value={30}>30 minutes</option>
            <option value={60}>1 hour</option>
          </select>
        </label>
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="btn-row">
        <button className="btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
        <button className="btn btn-primary" onClick={create} disabled={busy}>
          {busy ? "Creating…" : "Create poll"}
        </button>
      </div>
      <p className="tz-note">Times are in {TIMEZONE}.</p>
    </div>
  );
}
