import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_URL } from "../config";

const VIEWER_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
const REFRESH_MS = 10000;

function authHeaders() {
  const token = localStorage.getItem("authToken");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function timeLabel(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  const suffix = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  return m ? `${h12}:${String(m).padStart(2, "0")} ${suffix}` : `${h12} ${suffix}`;
}

function dateLabel(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return {
    weekday: dt.toLocaleDateString(undefined, { weekday: "short" }),
    day: dt.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
  };
}

function minutesToHHMM(min) {
  return `${String(Math.floor(min / 60) % 24).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
}

// The shared When2meet-style poll page: paint your own free times on the
// left, see everyone's overlap as a heatmap on the right. Anyone with the
// link can answer with just a name; the edit token kept in this browser
// lets them change their answer later.
export default function PollPage({ pollId }) {
  const storeKey = `poll:${pollId}`;
  const signedIn = !!localStorage.getItem("authToken");

  const [poll, setPoll] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [me, setMe] = useState(() => JSON.parse(localStorage.getItem(storeKey) || "null"));
  const [nameDraft, setNameDraft] = useState(me?.name || "");
  const [mySlots, setMySlots] = useState(new Set());
  const [saveState, setSaveState] = useState("");
  const [error, setError] = useState("");
  const [hoverCell, setHoverCell] = useState(null);
  const [copied, setCopied] = useState(false);

  const drag = useRef(null); // { add: bool } while painting
  const slotsRef = useRef(mySlots);
  slotsRef.current = mySlots;

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/polls/${pollId}`);
      if (!res.ok) throw new Error(res.status === 404 ? "This poll doesn't exist (check the link)." : "Couldn't load the poll.");
      const data = await res.json();
      setPoll(data);
      setLoadError("");
      return data;
    } catch (e) {
      setLoadError(e.message);
      return null;
    }
  }, [pollId]);

  // First load: pick up my existing answer, if I have one.
  useEffect(() => {
    load().then((data) => {
      const saved = JSON.parse(localStorage.getItem(storeKey) || "null");
      const mine = data && saved && data.responses.find((r) => r.id === saved.id);
      if (mine) setMySlots(new Set(mine.slots));
    });
  }, [load, storeKey]);

  // Keep the group view live while people fill it in (not mid-drag).
  useEffect(() => {
    const t = setInterval(() => {
      if (!drag.current && document.visibilityState === "visible") load();
    }, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  async function save(slots, name = me?.name) {
    if (!name) return;
    setSaveState("Saving…");
    setError("");
    try {
      const res = await fetch(`${API_URL}/polls/${pollId}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ name, slots: [...slots], edit_token: me?.edit_token || undefined }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Couldn't save.");
      const next = { id: data.id, name, edit_token: data.edit_token || me?.edit_token || null };
      localStorage.setItem(storeKey, JSON.stringify(next));
      setMe(next);
      setSaveState("Saved");
      load();
      return true;
    } catch (e) {
      setError(e.message);
      setSaveState("");
      return false;
    }
  }

  async function signIn(e) {
    e.preventDefault();
    const name = nameDraft.trim();
    if (!name) return;
    if (await save(mySlots, name)) setNameDraft(name);
  }

  async function fillFromCalendar() {
    setError("");
    const res = await fetch(`${API_URL}/polls/${pollId}/autofill`, { headers: authHeaders() });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(data.detail || "Couldn't read your calendar.");
      return;
    }
    const next = new Set(data.slots);
    setMySlots(next);
    save(next);
  }

  // ---- painting (mouse and touch share pointer events) ----
  function cellAt(e) {
    const el = document.elementFromPoint(e.clientX, e.clientY);
    return el?.closest?.("[data-cell]")?.dataset.cell || null;
  }

  function paint(cell) {
    if (!cell || !drag.current) return;
    setMySlots((prev) => {
      if (prev.has(cell) === drag.current.add) return prev;
      const next = new Set(prev);
      if (drag.current.add) next.add(cell);
      else next.delete(cell);
      return next;
    });
  }

  function onPointerDown(e) {
    if (!me) return;
    const cell = cellAt(e);
    if (!cell) return;
    e.preventDefault();
    drag.current = { add: !slotsRef.current.has(cell) };
    paint(cell);
  }

  function onPointerMove(e) {
    if (drag.current) paint(cellAt(e));
  }

  useEffect(() => {
    function end() {
      if (!drag.current) return;
      drag.current = null;
      save(slotsRef.current);
    }
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    return () => {
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me]);

  // ---- group overlap ----
  const others = useMemo(
    () => (poll ? poll.responses.filter((r) => r.id !== me?.id) : []),
    [poll, me]
  );
  const everyone = useMemo(() => {
    const list = others.map((r) => ({ name: r.name, slots: new Set(r.slots) }));
    if (me) list.push({ name: `${me.name} (you)`, slots: mySlots });
    return list;
  }, [others, me, mySlots]);

  const counts = useMemo(() => {
    const c = {};
    for (const p of everyone) for (const s of p.slots) c[s] = (c[s] || 0) + 1;
    return c;
  }, [everyone]);

  // Best times: runs of consecutive slots where the most people are free.
  const bestTimes = useMemo(() => {
    if (!poll || !everyone.length) return [];
    const max = Math.max(0, ...Object.values(counts));
    if (!max) return [];
    const runs = [];
    for (const d of poll.dates) {
      let run = null;
      for (let m = poll.start_min; m + poll.slot_min <= poll.end_min; m += poll.slot_min) {
        const key = `${d}T${minutesToHHMM(m)}`;
        if ((counts[key] || 0) === max) {
          if (run) run.end = m + poll.slot_min;
          else run = { date: d, start: m, end: m + poll.slot_min };
        } else if (run) {
          runs.push(run);
          run = null;
        }
      }
      if (run) runs.push(run);
    }
    return runs
      .sort((a, b) => b.end - b.start - (a.end - a.start))
      .slice(0, 5)
      .map((r) => ({ ...r, count: max }));
  }, [poll, counts, everyone]);

  function copyLink() {
    navigator.clipboard.writeText(window.location.href).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  if (loadError && !poll) {
    return (
      <div className="app">
        <PollHeader />
        <div className="card"><p className="error-text">{loadError}</p></div>
      </div>
    );
  }
  if (!poll) {
    return (
      <div className="app" style={{ display: "grid", placeItems: "center", minHeight: "60vh", opacity: 0.7 }}>
        <p>Loading the poll… this can take up to a minute the first time.</p>
      </div>
    );
  }

  const times = [];
  for (let m = poll.start_min; m + poll.slot_min <= poll.end_min; m += poll.slot_min) times.push(minutesToHHMM(m));
  const total = everyone.length;
  const hovered = hoverCell
    ? {
        free: everyone.filter((p) => p.slots.has(hoverCell)).map((p) => p.name),
        busy: everyone.filter((p) => !p.slots.has(hoverCell)).map((p) => p.name),
      }
    : null;

  function renderGrid(mode) {
    return (
      <div
        className={`poll-grid ${mode === "mine" && !me ? "locked" : ""}`}
        style={{ gridTemplateColumns: `56px repeat(${poll.dates.length}, minmax(40px, 1fr))` }}
        onPointerDown={mode === "mine" ? onPointerDown : undefined}
        onPointerMove={mode === "mine" ? onPointerMove : undefined}
        onPointerLeave={mode === "group" ? () => setHoverCell(null) : undefined}
      >
        <div />
        {poll.dates.map((d) => {
          const l = dateLabel(d);
          return (
            <div key={d} className="poll-col-head">
              <span>{l.weekday}</span>
              <strong>{l.day}</strong>
            </div>
          );
        })}
        {times.map((t) => (
          renderRow(t, mode)
        ))}
      </div>
    );
  }

  function renderRow(t, mode) {
    const onHour = t.endsWith(":00");
    return (
      <Fragment key={t}>
        <div className="poll-time">{onHour ? timeLabel(t) : ""}</div>
        {poll.dates.map((d) => {
          const key = `${d}T${t}`;
          if (mode === "mine") {
            return (
              <div
                key={key}
                data-cell={key}
                className={`poll-cell ${onHour ? "hour" : ""} ${mySlots.has(key) ? "mine" : ""}`}
              />
            );
          }
          const n = counts[key] || 0;
          const pct = total ? Math.round((n / total) * 100) : 0;
          return (
            <div
              key={key}
              className={`poll-cell ${onHour ? "hour" : ""} ${n && n === total ? "all" : ""}`}
              style={n ? { background: `color-mix(in srgb, var(--success) ${Math.max(15, pct)}%, var(--surface))` } : undefined}
              onPointerEnter={() => setHoverCell(key)}
              title={`${n}/${total} available`}
            />
          );
        })}
      </Fragment>
    );
  }

  return (
    <div className="app poll-page">
      <PollHeader />

      <div className="card">
        <div className="card-title poll-title-row">
          <h2>{poll.title}</h2>
          <button className="btn btn-primary" onClick={copyLink}>{copied ? "Link copied!" : "Copy link"}</button>
        </div>
        <p className="card-subtitle">
          {total} {total === 1 ? "person has" : "people have"} answered · times in <strong>{poll.timezone}</strong>
          {poll.timezone !== VIEWER_TZ && <> (you're in {VIEWER_TZ})</>}
        </p>

        {!me ? (
          <form className="poll-name-form" onSubmit={signIn}>
            <input
              className="activity-name-input"
              placeholder="Your name"
              value={nameDraft}
              maxLength={40}
              onChange={(e) => setNameDraft(e.target.value)}
            />
            <button className="btn btn-primary" type="submit">Add my availability</button>
          </form>
        ) : (
          <div className="btn-row poll-me-row">
            <span>Answering as <strong>{me.name}</strong></span>
            {signedIn && (
              <button className="btn-ghost" onClick={fillFromCalendar}>Fill from my TimeFrame calendar</button>
            )}
            <button className="btn-ghost" onClick={() => { setMySlots(new Set()); save(new Set()); }}>Clear mine</button>
            <span className="poll-save-state">{saveState}</span>
          </div>
        )}
        {error && <p className="error-text">{error}</p>}
      </div>

      <div className="poll-grids">
        <div className="card">
          <h3 className="poll-grid-title">Your availability</h3>
          <p className="card-subtitle">{me ? "Click and drag to mark when you're free." : "Enter your name above first."}</p>
          {renderGrid("mine")}
        </div>

        <div className="card">
          <h3 className="poll-grid-title">Group availability</h3>
          <div className="poll-legend">
            <span>0/{total}</span>
            <span className="poll-legend-bar" />
            <span>{total}/{total} available</span>
          </div>
          {renderGrid("group")}
          <div className="poll-hover">
            {hovered ? (
              <>
                <div><strong>Free ({hovered.free.length}):</strong> {hovered.free.join(", ") || "nobody"}</div>
                <div><strong>Not free ({hovered.busy.length}):</strong> {hovered.busy.join(", ") || "nobody"}</div>
              </>
            ) : (
              <span className="card-subtitle">Hover a time to see who's free.</span>
            )}
          </div>
        </div>
      </div>

      {bestTimes.length > 0 && (
        <div className="card">
          <h3 className="poll-grid-title">Best times</h3>
          <ul className="poll-best">
            {bestTimes.map((b, i) => {
              const l = dateLabel(b.date);
              return (
                <li key={`${b.date}-${b.start}`}>
                  {i === 0 && "👑 "}
                  <strong>{l.weekday} {l.day}</strong>, {timeLabel(minutesToHHMM(b.start))} – {timeLabel(minutesToHHMM(b.end))}
                  {" "}· {b.count}/{total} free
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function PollHeader() {
  return (
    <header className="app-header">
      <a className="brand" href="/" style={{ textDecoration: "none", color: "inherit" }}>
        <span className="brand-mark">🗓️</span>
        <h1>TimeFrame</h1>
      </a>
    </header>
  );
}
