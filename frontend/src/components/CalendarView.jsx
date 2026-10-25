const PX_PER_HOUR = 60;
const PERSON_COLOR_COUNT = 6;

function todayLocal() {
  const d = new Date();
  return ymd(d);
}

function ymd(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function addDays(dateStr, n) {
  const [y, m, d] = dateStr.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + n);
  return ymd(dt);
}

function dayOfWeek(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d).getDay(); // 0 = Sunday .. 6 = Saturday
}

function dayNumber(dateStr) {
  return String(Number(dateStr.split("-")[2]));
}

function weekdayLabel(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short" });
}

function monthDayLabel(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "numeric", day: "numeric" });
}

function wallClockMinutes(iso, timeZone, dayStartHour) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).formatToParts(new Date(iso));

  const hour = Number(parts.find((p) => p.type === "hour").value) % 24;
  const minute = Number(parts.find((p) => p.type === "minute").value);

  return (hour - dayStartHour) * 60 + minute;
}

function formatHourLabel(hour) {
  const h = ((hour % 24) + 24) % 24;
  if (h === 0) return "12 AM";
  if (h === 12) return "12 PM";
  return h < 12 ? `${h} AM` : `${h - 12} PM`;
}

function formatBlockTime(iso, timeZone) {
  return new Date(iso).toLocaleTimeString(undefined, {
    timeZone,
    hour: "numeric",
    minute: "2-digit",
    hour12: true
  });
}

// Greedy lane assignment so overlapping busy blocks sit side by side
// instead of stacking on top of each other. Lanes are computed per cluster
// of mutually-overlapping blocks, not for the whole day at once - a block
// that doesn't overlap anything should always render full width, even if
// two other blocks elsewhere that same day happen to overlap each other.
function assignLanes(blocks) {
  const sorted = [...blocks].sort((a, b) => a.startMin - b.startMin);
  const placed = [];

  let cluster = [];
  let clusterEnd = -Infinity;

  function flushCluster() {
    if (cluster.length === 0) return;

    const laneEnds = [];
    const withLane = cluster.map((block) => {
      let lane = laneEnds.findIndex((end) => end <= block.startMin);
      if (lane === -1) {
        lane = laneEnds.length;
        laneEnds.push(block.endMin);
      } else {
        laneEnds[lane] = block.endMin;
      }
      return { ...block, lane };
    });

    const laneCount = laneEnds.length;
    withLane.forEach((b) => placed.push({ ...b, laneCount }));
    cluster = [];
  }

  for (const block of sorted) {
    if (cluster.length > 0 && block.startMin >= clusterEnd) {
      flushCluster();
    }
    cluster.push(block);
    clusterEnd = cluster.length === 1 ? block.endMin : Math.max(clusterEnd, block.endMin);
  }
  flushCluster();

  return placed;
}

// Blocks never show what an event is (titles aren't stored), only whose
// it is: "You", or the part of someone's email before the @ (all we have -
// we only ever store an email, not a display name from their profile).
function ownerLabel(owner, currentUserId) {
  if (!owner || owner === currentUserId) return null;
  return owner.split("@")[0];
}

function whoseBlock(owner, currentUserId) {
  return ownerLabel(owner, currentUserId) || "You";
}

// Deterministic color per person: you always get index 0, everyone else
// gets the remaining slots in alphabetical order (stable across refetches,
// unlike first-seen order which can shift as data comes back in a
// different order).
function assignPersonColors(owners, currentUserId) {
  const others = owners.filter((o) => o !== currentUserId).sort();
  const ordered = currentUserId ? [currentUserId, ...others] : others;
  const colorByOwner = {};
  ordered.forEach((owner, i) => {
    colorByOwner[owner] = i % PERSON_COLOR_COUNT;
  });
  return colorByOwner;
}

export default function CalendarView({
  mode,
  viewDate,
  busyTimes,
  freeTimes,
  timezone,
  currentUserId,
  excludeWeekends = false,
  dayStartHour = 8,
  dayEndHour = 22
}) {
  const today = todayLocal();
  const anchor = viewDate || today;
  const weekStart = addDays(anchor, -dayOfWeek(anchor));
  let dates = mode === "week" ? Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)) : [anchor];

  // Only trims weekend columns from the week grid - Day view should
  // always show today, even if today happens to be a Saturday/Sunday.
  if (excludeWeekends && mode === "week") {
    dates = dates.filter((d) => {
      const dow = dayOfWeek(d);
      return dow !== 0 && dow !== 6;
    });
  }

  // In week mode, weekends shouldn't be candidates for "best free slot"
  // either, not just hidden from the grid. In day mode we're always
  // looking at today specifically, so don't second-guess that even if
  // today happens to be a weekend.
  const eligibleFreeTimes = excludeWeekends && mode === "week"
    ? freeTimes.filter((f) => {
        const dow = dayOfWeek(f.date);
        return dow !== 0 && dow !== 6;
      })
    : freeTimes;

  const totalMinutes = (dayEndHour - dayStartHour) * 60;
  const totalHeight = (dayEndHour - dayStartHour) * PX_PER_HOUR;
  const hourMarks = Array.from({ length: dayEndHour - dayStartHour + 1 }, (_, i) => dayStartHour + i);

  function toSpan(startIso, endIso) {
    const startMin = wallClockMinutes(startIso, timezone, dayStartHour);
    const endMin = wallClockMinutes(endIso, timezone, dayStartHour);
    return {
      startMin: Math.max(0, startMin),
      endMin: Math.min(totalMinutes, endMin <= 0 ? totalMinutes : endMin)
    };
  }

  const now = new Date();
  const nowMin = wallClockMinutes(now.toISOString(), timezone, dayStartHour);
  const showNowLine = nowMin >= 0 && nowMin <= totalMinutes;

  const topFree = eligibleFreeTimes.slice(0, 3);
  const rankLabel = ["👑 Best free slot", "2nd best free slot", "3rd best free slot"];
  const showHeaders = mode === "week";

  const owners = [...new Set(busyTimes.map((b) => b.owner).filter(Boolean))];
  const personColorByOwner = assignPersonColors(owners, currentUserId);

  return (
    <div className="card">
      <div className="card-title">
        <h2>Calendar</h2>
      </div>

      <div className="calendar">
        <div className="calendar-hours">
          {showHeaders && <div className="calendar-header-spacer" />}
          <div className="calendar-hours-track" style={{ height: `${totalHeight}px` }}>
            {hourMarks.map((h) => (
              <div
                className="timeline-hour-label"
                key={h}
                style={{ top: `${(h - dayStartHour) * PX_PER_HOUR}px` }}
              >
                {formatHourLabel(h)}
              </div>
            ))}
          </div>
        </div>

        <div className="calendar-main">
          {showHeaders && (
            <div className="calendar-headers-row">
              {dates.map((date) => {
                const isToday = date === today;
                return (
                  <div className={`calendar-day-header ${isToday ? "today" : ""}`} key={date}>
                    <span className="wd">{weekdayLabel(date)}</span>
                    <span className="md">
                      {isToday ? (
                        <span className="today-circle">{dayNumber(date)}</span>
                      ) : (
                        monthDayLabel(date)
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          <div className="calendar-grid-frame">
            {dates.map((date) => {
              const isToday = date === today;

              const dayBusy = busyTimes
                .filter((b) => b.date === date)
                .map((b) => ({ ...b, ...toSpan(b.start, b.end) }))
                .filter((b) => b.endMin > 0 && b.startMin < totalMinutes);

              const busyLaned = assignLanes(dayBusy);

              // Free time is just the absence of a block - only the top 3
              // ranked slots (wherever they fall) get highlighted.
              const dayFree = freeTimes
                .filter((f) => f.date === date && topFree.includes(f))
                .map((f) => ({ ...f, ...toSpan(f.start, f.end), rank: topFree.indexOf(f) + 1 }))
                .filter((f) => f.endMin > 0 && f.startMin < totalMinutes);

              return (
                <div className="timeline-track" style={{ height: `${totalHeight}px` }} key={date}>
                  {hourMarks.map((h) => (
                    <div
                      className="timeline-gridline"
                      key={h}
                      style={{ top: `${(h - dayStartHour) * PX_PER_HOUR}px` }}
                    />
                  ))}

                  {dayFree.map((f, i) => (
                    <div
                      key={`free-${i}`}
                      className={`timeline-block best-free rank-${f.rank}`}
                      style={{
                        top: `${(f.startMin / totalMinutes) * totalHeight}px`,
                        height: `${Math.max(4, ((f.endMin - f.startMin) / totalMinutes) * totalHeight)}px`
                      }}
                      title={`${rankLabel[f.rank - 1]} · ${f.duration_minutes} min`}
                    >
                      <div className="block-content">
                        <span className="block-time">
                          {formatBlockTime(f.start, timezone)} – {formatBlockTime(f.end, timezone)}
                        </span>
                        <span className="block-sub">{rankLabel[f.rank - 1]}</span>
                      </div>
                    </div>
                  ))}

                  {busyLaned.map((b, i) => {
                    const owner = whoseBlock(b.owner, currentUserId);
                    const personIdx = personColorByOwner[b.owner] ?? 0;
                    return (
                      <div
                        key={`busy-${i}`}
                        className={`timeline-block busy person-${personIdx}`}
                        style={{
                          top: `${(b.startMin / totalMinutes) * totalHeight}px`,
                          height: `${Math.max(4, ((b.endMin - b.startMin) / totalMinutes) * totalHeight)}px`,
                          left: `calc(${(b.lane / b.laneCount) * 100}% + 2px)`,
                          width: `calc(${100 / b.laneCount}% - 4px)`
                        }}
                        title={`${owner} · ${formatBlockTime(b.start, timezone)} – ${formatBlockTime(b.end, timezone)}`}
                      >
                        <div className="block-content">
                          <span className="block-time">{owner}</span>
                          <span className="block-sub">
                            {formatBlockTime(b.start, timezone)} – {formatBlockTime(b.end, timezone)}
                          </span>
                        </div>
                      </div>
                    );
                  })}

                  {isToday && showNowLine && (
                    <div
                      className="timeline-now-line"
                      style={{ top: `${(nowMin / totalMinutes) * totalHeight}px` }}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="timeline-legend">
        {owners.map((owner) => (
          <span key={owner}>
            <span className={`swatch person-${personColorByOwner[owner]}`} />
            {owner === currentUserId ? "You" : ownerLabel(owner, null)}
          </span>
        ))}
        <span><span className="swatch best-free rank-1" /> 👑 Best free slot</span>
        <span><span className="swatch best-free rank-2" /> 2nd/3rd best</span>
      </div>
    </div>
  );
}
