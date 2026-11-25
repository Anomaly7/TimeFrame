import { useState } from "react";
import { API_URL } from "../config";

const MY_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

function timeLabel(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

// Recurring-meeting finder (2026-11-25): the weekly time that's free for everyone in the most of the coming weeks.
export default function WeeklyFinder({ authHeaders, group, settings, onBook }) {
  const [weeks, setWeeks] = useState(10);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function find() {
    setLoading(true);
    setError("");
    try {
      const q = new URLSearchParams({
        weeks: String(weeks), timezone: MY_TZ, length: String(settings.meetingLength),
        day_start: settings.dayStart, day_end: settings.dayEnd, exclude_weekends: String(!!settings.excludeWeekends),
        buffer: String(settings.bufferMinutes || 0), prefer: settings.timePrefs.join(","),
      });
      if (group) q.set("group", group.id);
      const res = await fetch(`${API_URL}/availability/recurring?${q}`, { headers: authHeaders() });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Couldn't search.");
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title"><h2>🔁 Weekly meeting</h2></div>
      <p className="muted-line">The best {settings.meetingLength}-minute slot that repeats every week{group ? " for everyone" : ""}.</p>
      <div className="weekly-controls">
        <select value={weeks} onChange={(e) => { setWeeks(Number(e.target.value)); setResult(null); }} aria-label="How many weeks">
          {[4, 8, 10, 13, 16].map((w) => <option key={w} value={w}>Next {w} weeks</option>)}
        </select>
        <button className="btn btn-primary" onClick={find} disabled={loading}>{loading ? "Searching..." : "Find a weekly time"}</button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {result && result.slots.length === 0 && <p className="muted-line">No time repeats in those weeks. Try fewer weeks or a shorter meeting.</p>}
      {result && result.slots.length > 0 && (
        <ul className="plan-list">
          {result.slots.map((s, i) => (
            <li key={`${s.weekday}-${s.time}`}>
              <span>
                {i === 0 ? "👑 " : ""}<strong>{s.weekday}s</strong> {timeLabel(s.start)}
                <br /><small>Free {s.free_weeks} of {s.weeks} weeks</small>
              </span>
              <button className="btn btn-ghost" onClick={() => onBook({ ...s, duration_minutes: result.minutes })}>
                {group ? "Book first" : "Use"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
