import { useState } from "react";
import { API_URL } from "../config";
import { formatSpan, toLocalInputValue } from "../util";
import AddToCalendar from "./AddToCalendar";

// Book a free slot ("Lock it in"): name it, pick the length, and the whole group sees it as Booked.
// Outside a group it just makes the calendar links (nothing is saved).
export default function BookModal({ slot, group, meetingLength = 30, authHeaders, onClose, onBooked, notify }) {
  const slotMinutes = Math.round((new Date(slot.end) - new Date(slot.start)) / 60000);
  const [title, setTitle] = useState(group ? `${group.name || "Group"} meeting` : "Meeting");
  const [start, setStart] = useState(toLocalInputValue(slot.start));
  const [length, setLength] = useState(Math.min(slotMinutes, Math.max(5, meetingLength)));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(null);

  const startDate = new Date(start);
  const endIso = new Date(startDate.getTime() + length * 60000).toISOString();
  const fitsSlot = startDate >= new Date(slot.start) && new Date(endIso) <= new Date(slot.end);

  async function book(e) {
    e.preventDefault();
    setError("");
    const span = { title, start: startDate.toISOString(), end: endIso };
    if (!group) return setDone({ ...span, id: null });
    setSaving(true);
    try {
      const res = await fetch(`${API_URL}/groups/book?group_id=${group.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(span),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Couldn't book that time.");
      setDone(data.booking);
      notify?.(`Booked "${data.booking.title}" for ${group.name || "the group"}.`);
      onBooked?.(data.booking);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal book-modal" role="dialog" aria-modal="true" aria-label="Book this time" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        {done ? (
          <>
            <h2>{group ? "Booked" : "Add it to your calendar"}</h2>
            <p className="muted-line"><strong>{done.title}</strong><br />{formatSpan(done.start, done.end)}</p>
            {group && <p className="muted-line">Everyone in {group.name || "the group"} sees it in their Plan tab.</p>}
            <AddToCalendar booking={done} details={group ? `${group.name || "Group"} · booked with TimeFrame` : undefined} />
            <div className="btn-row"><button className="btn btn-primary" onClick={onClose}>Done</button></div>
          </>
        ) : (
          <form onSubmit={book}>
            <h2>{group ? "Lock in this time" : "Use this time"}</h2>
            <p className="muted-line">Free: {formatSpan(slot.start, slot.end)}</p>
            <label className="field">
              <span>Name</span>
              <input value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <div className="field-row">
              <label className="field">
                <span>Starts</span>
                <input type="datetime-local" value={start} step={300} onChange={(e) => setStart(e.target.value)} />
              </label>
              <label className="field">
                <span>Length (min)</span>
                <input type="number" min={5} max={720} step={5} value={length} onChange={(e) => setLength(Number(e.target.value) || 5)} />
              </label>
            </div>
            {!fitsSlot && <p className="hint-warn">That runs outside the free slot, so someone may be busy.</p>}
            {error && <p className="error-text">{error}</p>}
            <div className="btn-row">
              <button type="submit" className="btn btn-primary" disabled={saving || !title.trim()}>
                {saving ? "Booking..." : group ? "Book for the group" : "Next"}
              </button>
              <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
