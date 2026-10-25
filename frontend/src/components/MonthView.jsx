const PERSON_COLOR_COUNT = 6;
const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function ymd(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function parseISODate(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function addDays(dateStr, n) {
  const dt = parseISODate(dateStr);
  dt.setDate(dt.getDate() + n);
  return ymd(dt);
}

// Same deterministic per-person coloring as CalendarView, kept in sync so a
// given person always gets the same color across Day/Week/Month.
// Chips never show what an event is (titles aren't stored), only whose it is.
function whoseBlock(owner, currentUserId) {
  return !owner || owner === currentUserId ? "You" : owner.split("@")[0];
}

function assignPersonColors(owners, currentUserId) {
  const others = owners.filter((o) => o !== currentUserId).sort();
  const ordered = currentUserId ? [currentUserId, ...others] : others;
  const colorByOwner = {};
  ordered.forEach((owner, i) => {
    colorByOwner[owner] = i % PERSON_COLOR_COUNT;
  });
  return colorByOwner;
}

export default function MonthView({
  viewDate,
  busyTimes,
  freeTimes,
  currentUserId,
  excludeWeekends = false,
  onSelectDay
}) {
  const today = ymd(new Date());
  const anchor = parseISODate(viewDate);
  const monthIndex = anchor.getMonth();
  const monthStart = ymd(new Date(anchor.getFullYear(), monthIndex, 1));
  const gridStart = addDays(monthStart, -parseISODate(monthStart).getDay());
  const days = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));

  const eligibleFreeTimes = excludeWeekends
    ? freeTimes.filter((f) => {
        const dow = parseISODate(f.date).getDay();
        return dow !== 0 && dow !== 6;
      })
    : freeTimes;
  const topFree = eligibleFreeTimes.slice(0, 3);
  const rankMarker = ["👑", "2", "3"];

  const owners = [...new Set(busyTimes.map((b) => b.owner).filter(Boolean))];
  const personColorByOwner = assignPersonColors(owners, currentUserId);

  // A block appears on every day it covers (multi-day trips, overnight
  // events), not only the day it starts. An end at exactly midnight
  // doesn't spill onto the next day.
  const busyByDate = {};
  for (const b of busyTimes) {
    const start = new Date(b.start);
    const end = new Date(b.end);
    if (!(end > start)) continue;
    const last = new Date(end.getTime() - 1);
    const cursor = new Date(start.getFullYear(), start.getMonth(), start.getDate());
    for (let n = 0; cursor <= last && n < 62; n++) {
      (busyByDate[ymd(cursor)] ||= []).push(b);
      cursor.setDate(cursor.getDate() + 1);
    }
  }

  return (
    <div className="card">
      <div className="card-title">
        <h2>{anchor.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</h2>
      </div>

      <div className="month-grid">
        {WEEKDAY_LABELS.map((label) => (
          <div className="month-weekday-label" key={label}>{label}</div>
        ))}

        {days.map((date) => {
          const inMonth = parseISODate(date).getMonth() === monthIndex;
          const isToday = date === today;
          const rankOnDay = topFree.findIndex((f) => f.date === date) + 1; // 0 = not in top 3
          const dayBusy = (busyByDate[date] || []).slice().sort((a, b) => a.start.localeCompare(b.start));
          const visible = dayBusy.slice(0, 3);
          const overflow = dayBusy.length - visible.length;

          return (
            <button
              type="button"
              className={`month-cell ${inMonth ? "" : "outside-month"}`}
              key={date}
              onClick={() => onSelectDay(date)}
            >
              <span className={`month-cell-date ${isToday ? "today-circle" : ""}`}>
                {Number(date.split("-")[2])}
              </span>

              {rankOnDay > 0 && (
                <span
                  className={`month-best-marker rank-${rankOnDay}`}
                  title={rankOnDay === 1 ? "Best free slot this month" : `${rankOnDay === 2 ? "2nd" : "3rd"} best free slot this month`}
                >
                  {rankMarker[rankOnDay - 1]}
                </span>
              )}

              <div className="month-cell-events">
                {visible.map((b, i) => {
                  const personIdx = personColorByOwner[b.owner] ?? 0;
                  return (
                    <span className={`month-event-chip person-${personIdx}`} key={i}>
                      {whoseBlock(b.owner, currentUserId)}
                    </span>
                  );
                })}
                {overflow > 0 && <span className="month-event-more">+{overflow} more</span>}
              </div>
            </button>
          );
        })}
      </div>

      <div className="timeline-legend">
        {owners.map((owner) => (
          <span key={owner}>
            <span className={`swatch person-${personColorByOwner[owner]}`} />
            {owner === currentUserId ? "You" : owner.split("@")[0]}
          </span>
        ))}
        <span>👑 = best free slot that day, ② / ③ = runner-up</span>
      </div>
    </div>
  );
}
