import { useState } from "react";
import TimeWheelPicker from "./TimeWheelPicker";

function todayLocal() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function formatLocal(datetimeLocalValue) {
  // datetime-local values have no timezone - they're the browser's own
  // local time, so parsing/formatting them needs no zone conversion.
  const d = new Date(datetimeLocalValue);
  if (isNaN(d)) return datetimeLocalValue;

  return d.toLocaleString(undefined, {
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true
  });
}

export default function AvailabilityForm({
  manualBusy,
  setManualBusy,
  onSubmit
}) {
  const [startDate, setStartDate] = useState(todayLocal());
  const [startTime, setStartTime] = useState("09:00");
  const [endDate, setEndDate] = useState(todayLocal());
  const [endTime, setEndTime] = useState("10:00");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function addBusy() {
    if (!startDate || !endDate) return;

    setManualBusy([
      ...manualBusy,
      { start: `${startDate}T${startTime}`, end: `${endDate}T${endTime}` }
    ]);
  }

  function removeBusy(index) {
    setManualBusy(manualBusy.filter((_, i) => i !== index));
  }

  async function submit() {
    setLoading(true);
    setError("");

    try {
      await onSubmit(manualBusy);
    } catch (err) {
      console.error(err);
      setError("Something went wrong. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title">
        <h2>Manual Busy Times</h2>
      </div>

      <div className="datetime-row">
        <div className="datetime-group">
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
          <TimeWheelPicker value={startTime} onChange={setStartTime} />
        </div>
        <span className="arrow">→</span>
        <div className="datetime-group">
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
          <TimeWheelPicker value={endTime} onChange={setEndTime} />
        </div>
      </div>

      <div className="form-actions">
        <button className="btn-ghost" onClick={addBusy}>Add Busy Slot</button>
        <button className="btn btn-primary" onClick={submit} disabled={loading}>
          {loading && <span className="spinner" />}
          {loading ? "Finding..." : "Find Free Time"}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {manualBusy.length === 0 ? (
        <p className="empty-state">No manual busy times added yet.</p>
      ) : (
        <ul className="chip-list">
          {manualBusy.map((b, i) => (
            <li className="chip" key={i}>
              <span>
                {formatLocal(b.start)} → {formatLocal(b.end)}
              </span>
              <button
                className="chip-remove"
                onClick={() => removeBusy(i)}
                aria-label="Remove this busy slot"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
