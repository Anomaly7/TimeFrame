import { downloadIcs, googleCalendarUrl } from "../util";

// "Add to Google Calendar" + ".ics" for a booked meeting.
export default function AddToCalendar({ booking, details, compact = false }) {
  const event = { ...booking, details };
  return (
    <div className={`btn-row add-cal ${compact ? "compact" : ""}`}>
      <a className="btn btn-ghost" href={googleCalendarUrl(event)} target="_blank" rel="noopener noreferrer">
        {compact ? "Google" : "Add to Google Calendar"}
      </a>
      <button type="button" className="btn btn-ghost" onClick={() => downloadIcs(event)}>
        {compact ? ".ics" : "Download .ics"}
      </button>
    </div>
  );
}
