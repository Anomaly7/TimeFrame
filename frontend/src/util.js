// Small helpers shared by several components.

// "Updated 2 h ago" for the last Google import.
export function ago(unixSeconds) {
  if (!unixSeconds) return null;
  const mins = Math.max(0, Math.round((Date.now() / 1000 - unixSeconds) / 60));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}


// "Tue, Dec 2 · 2:00 – 3:00 PM"
export function formatSpan(startIso, endIso) {
  const s = new Date(startIso), e = new Date(endIso);
  const day = s.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const t = (d) => d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${day} · ${t(s)} – ${t(e)}`;
}

function utcStamp(iso) {
  return new Date(iso).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
}

// Google Calendar's "create event" page, pre-filled. No Google permission needed: you save it yourself.
export function googleCalendarUrl({ title, start, end, details = "" }) {
  const q = new URLSearchParams({
    action: "TEMPLATE",
    text: title || "Meeting",
    dates: `${utcStamp(start)}/${utcStamp(end)}`,
    details: details || "Booked with TimeFrame · https://www.timeframecalender.com",
  });
  return `https://calendar.google.com/calendar/render?${q}`;
}

function icsEscape(text) {
  return String(text || "").replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}

// A one-event .ics file (Apple Calendar, Outlook, anything) made in the browser.
export function downloadIcs({ id, title, start, end, details = "" }) {
  const lines = [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TimeFrame//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:${id || Date.now()}@timeframecalender.com`,
    `DTSTAMP:${utcStamp(new Date().toISOString())}`,
    `DTSTART:${utcStamp(start)}`,
    `DTEND:${utcStamp(end)}`,
    `SUMMARY:${icsEscape(title || "Meeting")}`,
    `DESCRIPTION:${icsEscape(details || "Booked with TimeFrame")}`,
    "END:VEVENT", "END:VCALENDAR",
  ];
  const blob = new Blob([lines.join("\r\n") + "\r\n"], { type: "text/calendar" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${(title || "meeting").replace(/[^\w -]+/g, "").trim() || "meeting"}.ics`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// "YYYY-MM-DDTHH:MM" in this browser's time zone, for <input type="datetime-local">.
export function toLocalInputValue(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
