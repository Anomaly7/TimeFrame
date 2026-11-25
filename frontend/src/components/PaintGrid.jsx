import { useMemo, useRef, useState } from "react";

// Paint when you're busy (When2meet-style, 2026-11-25): drag over 30-minute cells for the next 7 days, then Save.
// Saved as ordinary manual busy blocks, so it works the same for guests and accounts. Blocks outside the grid's
// days are kept as they are.
const STEP = 30;

function p2(n) { return String(n).padStart(2, "0"); }
function ymd(d) { return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`; }
function localStr(d) { return `${ymd(d)}T${p2(d.getHours())}:${p2(d.getMinutes())}`; }

export default function PaintGrid({ manualBusy, setManualBusy, dayStart = "08:00", dayEnd = "22:00", days = 7, onSaved }) {
  const startHour = parseInt(dayStart, 10);
  const endHour = Math.max(startHour + 1, Math.ceil(parseInt(dayEnd, 10) + (dayEnd.endsWith(":00") ? 0 : 1)));
  const dates = useMemo(() => {
    const t = new Date(); t.setHours(0, 0, 0, 0);
    return Array.from({ length: days }, (_, i) => { const d = new Date(t); d.setDate(d.getDate() + i); return d; });
  }, [days]);
  const slots = (endHour - startHour) * (60 / STEP);

  function cellStart(di, si) {
    const d = new Date(dates[di]);
    d.setHours(startHour, si * STEP, 0, 0);
    return d;
  }

  // Cells already covered by a saved block.
  const initial = useMemo(() => {
    const set = new Set();
    for (const b of manualBusy) {
      const s = new Date(b.start), e = new Date(b.end);
      dates.forEach((_, di) => {
        for (let si = 0; si < slots; si++) {
          const cs = cellStart(di, si), ce = new Date(cs.getTime() + STEP * 60000);
          if (cs < e && ce > s) set.add(`${di}:${si}`);
        }
      });
    }
    return set;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manualBusy, dates, slots]);

  const [cells, setCells] = useState(initial);
  const [dirty, setDirty] = useState(false);
  const painting = useRef(null); // true = adding, false = erasing

  function apply(key) {
    setCells((prev) => {
      const next = new Set(prev);
      if (painting.current) next.add(key); else next.delete(key);
      return next;
    });
    setDirty(true);
  }

  function down(key, e) {
    e.preventDefault();
    painting.current = !cells.has(key);
    apply(key);
  }

  // Touch: follow the finger across cells.
  function touchMove(e) {
    if (painting.current === null) return;
    const t = e.touches[0];
    const el = document.elementFromPoint(t.clientX, t.clientY);
    const key = el?.dataset?.cell;
    if (key) apply(key);
  }

  function save() {
    const gridStart = dates[0];
    const gridEnd = new Date(dates[dates.length - 1]); gridEnd.setDate(gridEnd.getDate() + 1);
    // Keep blocks that don't touch the grid's days; replace the rest with what's painted.
    const outside = manualBusy.filter((b) => new Date(b.end) <= gridStart || new Date(b.start) >= gridEnd);
    const painted = [];
    dates.forEach((_, di) => {
      let runStart = null;
      for (let si = 0; si <= slots; si++) {
        const on = si < slots && cells.has(`${di}:${si}`);
        if (on && runStart === null) runStart = si;
        if (!on && runStart !== null) {
          painted.push({ start: localStr(cellStart(di, runStart)), end: localStr(cellStart(di, si)) });
          runStart = null;
        }
      }
    });
    setManualBusy([...outside, ...painted]);
    setDirty(false);
    onSaved?.(painted.length);
  }

  const hourRows = Array.from({ length: slots }, (_, si) => si);

  return (
    <div className="paint">
      <p className="muted-line">Drag over the times you're <strong>busy</strong>, then Save. Tap a cell again to clear it.</p>
      <div
        className="paint-grid"
        style={{ "--paint-cols": dates.length }}
        onMouseUp={() => { painting.current = null; }}
        onMouseLeave={() => { painting.current = null; }}
        onTouchEnd={() => { painting.current = null; }}
        onTouchMove={touchMove}
      >
        <div className="paint-corner" />
        {dates.map((d) => (
          <div key={ymd(d)} className="paint-day">
            <span>{d.toLocaleDateString(undefined, { weekday: "short" })}</span>
            <b>{d.getDate()}</b>
          </div>
        ))}
        {hourRows.map((si) => (
          <div key={`row-${si}`} className="paint-row" style={{ display: "contents" }}>
            <div className="paint-hour">{si % 2 === 0 ? new Date(2000, 0, 1, startHour + si / 2).toLocaleTimeString(undefined, { hour: "numeric" }) : ""}</div>
            {dates.map((d, di) => {
              const key = `${di}:${si}`;
              return (
                <div
                  key={key}
                  data-cell={key}
                  className={`paint-cell ${cells.has(key) ? "on" : ""} ${si % 2 === 1 ? "half" : ""}`}
                  onMouseDown={(e) => down(key, e)}
                  onMouseEnter={() => painting.current !== null && apply(key)}
                  onTouchStart={(e) => down(key, e)}
                />
              );
            })}
          </div>
        ))}
      </div>
      <div className="btn-row">
        <button type="button" className="btn btn-primary" onClick={save} disabled={!dirty}>
          {dirty ? "Save busy times" : "Saved"}
        </button>
        {cells.size > 0 && (
          <button type="button" className="btn btn-ghost" onClick={() => { setCells(new Set()); setDirty(true); }}>Clear grid</button>
        )}
      </div>
    </div>
  );
}
