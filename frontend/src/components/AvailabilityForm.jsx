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

// Adding or removing a block saves it right away (App.jsx), which also refreshes the free times.
export default function AvailabilityForm({ manualBusy, setManualBusy }) {
  const [startDate, setStartDate] = useState(todayLocal());
  const [startTime, setStartTime] = useState("09:00");
  const [endDate, setEndDate] = useState(todayLocal());
  const [endTime, setEndTime] = useState("10:00");
  const [error, setError] = useState("");

  function addBusy() {
    if (!startDate || !endDate) return;
    // Zero-length or backwards blocks were silently dropped by the server.
    if (new Date(`${endDate}T${endTime}`) <= new Date(`${startDate}T${startTime}`)) {
      setError("The end time must be after the start time.");
      return;
    }
    setError("");

    setManualBusy([
      ...manualBusy,
      { start: `${startDate}T${startTime}`, end: `${endDate}T${endTime}` }
    ]);
  }

  function removeBusy(index) {
    setManualBusy(manualBusy.filter((_, i) => i !== index));
  }

  return (
    <div className="card">
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
        <button className="btn btn-primary" onClick={addBusy}>Add busy time</button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {manualBusy.length === 0 ? (
        <p className="empty-state">Nothing added yet. Busy times you add here show up for your groups too.</p>
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
