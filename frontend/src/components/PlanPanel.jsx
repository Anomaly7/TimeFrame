import { useEffect, useState } from "react";
import { API_URL } from "../config";
import { formatSpan } from "../util";
import AddToCalendar from "./AddToCalendar";

// The Plan tab: the next booked meeting (pinned), the best times to book, and everything coming up.
export default function PlanPanel({ authHeaders, group, freeTimes, almostFree = [], refreshKey, onBook, onChanged, notify, children }) {
  const [bookings, setBookings] = useState([]);
  const [confirmCancel, setConfirmCancel] = useState(null);

  async function load() {
    try {
      const res = await fetch(`${API_URL}/bookings/mine`, { headers: authHeaders() });
      if (res.ok) setBookings((await res.json()).bookings);
    } catch { /* keep what we have */ }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey, group?.id]);

  async function cancel(b) {
    const res = await fetch(`${API_URL}/bookings/cancel?id=${encodeURIComponent(b.id)}`, { method: "POST", headers: authHeaders() })
      .catch(() => null);
    setConfirmCancel(null);
    if (!res?.ok) return notify?.("Couldn't cancel that booking.", "error");
    notify?.(`Cancelled "${b.title}".`);
    load();
    onChanged?.();
  }

  function cancelControls(b) {
    if (!b.can_cancel) return null;
    return confirmCancel === b.id ? (
      <span className="btn-row">
        <button className="btn btn-danger" onClick={() => cancel(b)}>Cancel it</button>
        <button className="btn btn-ghost" onClick={() => setConfirmCancel(null)}>Keep</button>
      </span>
    ) : (
      <button className="link-btn danger" onClick={() => setConfirmCancel(b.id)}>Cancel</button>
    );
  }

  const shown = group ? bookings.filter((b) => b.group_id === group.id) : bookings;
  const next = shown[0];
  const best = freeTimes.slice(0, 5);
  const detailsFor = (b) => (b.group_name || group?.name ? `${b.group_name || group.name} · booked with TimeFrame` : undefined);

  return (
    <>
      <div className="card plan-next">
        <div className="card-title">
          <h2>📌 Next meeting</h2>
          {next && cancelControls(next)}
        </div>
        {next ? (
          <>
            <p className="plan-title">{next.title}</p>
            <p className="muted-line">
              {formatSpan(next.start, next.end)}
              {!group && next.group_name ? ` · ${next.group_name}` : ""}
              {next.booking_page && next.guest_name ? ` · with ${next.guest_name}` : ""}
            </p>
            <AddToCalendar booking={next} compact details={detailsFor(next)} />
          </>
        ) : (
          <p className="muted-line">Nothing booked yet. Pick one of the best times below{group ? " to lock it in for everyone" : ""}.</p>
        )}
      </div>

      <div className="card">
        <div className="card-title"><h2>Best times</h2></div>
        {best.length === 0 && <p className="muted-line">No free time in this view. Try another week.</p>}
        <ul className="plan-list">
          {best.map((f, i) => (
            <li key={`${f.start}-${i}`}>
              <span>{i === 0 ? "👑 " : ""}{formatSpan(f.start, f.end)}</span>
              <button className="btn btn-ghost" onClick={() => onBook(f)}>{group ? "Book" : "Use"}</button>
            </li>
          ))}
        </ul>
      </div>

      {almostFree.length > 0 && (
        <div className="card">
          <div className="card-title"><h2>Almost works</h2></div>
          <p className="muted-line">Nothing fits everyone here. These work for all but one person:</p>
          <ul className="plan-list">
            {almostFree.map((f, i) => (
              <li key={`${f.start}-${f.missing_id}-${i}`}>
                <span>{formatSpan(f.start, f.end)}<br /><small>Everyone except {f.missing}</small></span>
                <button className="btn btn-ghost" onClick={() => onBook(f)}>Book</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {children}

      {shown.length > 1 && (
        <div className="card">
          <div className="card-title"><h2>Coming up</h2></div>
          <ul className="plan-list">
            {shown.slice(1).map((b) => (
              <li key={b.id} className="plan-booking">
                <span>
                  <strong>{b.title}</strong><br />
                  <small>{formatSpan(b.start, b.end)}{!group && b.group_name ? ` · ${b.group_name}` : ""}</small>
                </span>
                {cancelControls(b)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
