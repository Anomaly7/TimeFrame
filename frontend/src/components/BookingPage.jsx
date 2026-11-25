import { useEffect, useMemo, useState } from "react";
import { API_URL } from "../config";
import { hideLoader } from "../loading";
import { formatSpan } from "../util";
import AddToCalendar from "./AddToCalendar";

// The public booking page at timeframecalender.com/<handle> (Pro). Visitors see open times only.
export default function BookingPage({ handle }) {
  const [page, setPage] = useState(null);
  const [error, setError] = useState("");
  const [day, setDay] = useState(null);
  const [slot, setSlot] = useState(null);
  const [form, setForm] = useState({ name: "", email: "", note: "" });
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(null);

  async function load() {
    try {
      const res = await fetch(`${API_URL}/book/${encodeURIComponent(handle)}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "This booking page isn't available.");
      setPage(data);
    } catch (err) {
      setError(err.message);
    } finally {
      hideLoader();
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handle]);

  const days = useMemo(() => {
    const map = new Map();
    for (const s of page?.slots || []) {
      const d = new Date(s.start);
      const key = d.toDateString();
      if (!map.has(key)) map.set(key, { key, date: d, slots: [] });
      map.get(key).slots.push(s);
    }
    return [...map.values()];
  }, [page]);
  const activeDay = days.find((d) => d.key === day) || days[0];

  async function book(e) {
    e.preventDefault();
    setSending(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/book/${encodeURIComponent(handle)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, start: slot.start }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status === 409) { setSlot(null); load(); }
        throw new Error(data.detail || "Couldn't book that time.");
      }
      setDone(data.booking);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  const time = (iso) => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

  return (
    <div className="bp-shell">
      <main className="bp-card">
        <a className="auth-logo bp-logo" href="/"><img src="/favicon.svg" alt="" /><span>TimeFrame</span></a>
        {!page && !error && <p className="muted-line">Loading…</p>}
        {!page && error && (
          <>
            <h1 className="bp-title">Not available</h1>
            <p className="muted-line">{error}</p>
          </>
        )}
        {page && done && (
          <>
            <h1 className="bp-title">You're booked ✓</h1>
            <p className="muted-line"><strong>{done.title}</strong><br />{formatSpan(done.start, done.end)}</p>
            <p className="muted-line">{page.name} has been told. Add it to your calendar:</p>
            <AddToCalendar booking={done} details={`Booked on TimeFrame with ${page.name}`} />
          </>
        )}
        {page && !done && (
          <>
            <p className="bp-host">{page.name}</p>
            <h1 className="bp-title">{page.title}</h1>
            <p className="muted-line">{page.minutes} minutes · times shown in your time zone ({Intl.DateTimeFormat().resolvedOptions().timeZone})</p>
            {days.length === 0 && <p className="muted-line">No open times right now. Check back soon.</p>}
            {days.length > 0 && !slot && (
              <>
                <div className="bp-days" role="tablist" aria-label="Day">
                  {days.map((d) => (
                    <button key={d.key} role="tab" aria-selected={activeDay.key === d.key}
                      className={activeDay.key === d.key ? "on" : ""} onClick={() => setDay(d.key)}>
                      <span>{d.date.toLocaleDateString(undefined, { weekday: "short" })}</span>
                      <b>{d.date.getDate()}</b>
                      <small>{d.date.toLocaleDateString(undefined, { month: "short" })}</small>
                    </button>
                  ))}
                </div>
                <div className="bp-times">
                  {activeDay.slots.map((s) => (
                    <button key={s.start} className="btn btn-ghost" onClick={() => setSlot(s)}>{time(s.start)}</button>
                  ))}
                </div>
              </>
            )}
            {slot && (
              <form onSubmit={book}>
                <p className="bp-picked">{formatSpan(slot.start, slot.end)} <button type="button" className="link-btn" onClick={() => setSlot(null)}>Change</button></p>
                <label className="field"><span>Your name</span>
                  <input required maxLength={60} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                </label>
                <label className="field"><span>Email</span>
                  <input required type="email" maxLength={254} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </label>
                <label className="field"><span>Anything they should know? (optional)</span>
                  <textarea rows={2} maxLength={300} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
                </label>
                <button className="btn btn-primary bp-confirm" type="submit" disabled={sending}>{sending ? "Booking..." : "Confirm booking"}</button>
              </form>
            )}
            {error && <p className="error-text">{error}</p>}
          </>
        )}
        <p className="bp-foot">Only open times are shown, never anyone's events. <a href="/privacy.html">Privacy</a></p>
      </main>
    </div>
  );
}
