import { useEffect, useState } from "react";
import { API_URL } from "../config";
import { formatSpan } from "../util";

// Polls (2026-11-25): the admin proposes 2-5 times, everyone taps the ones that work, closing books the winner.
export default function PollsCard({ authHeaders, group, freeTimes, refreshKey, notify, onBooked }) {
  const [polls, setPolls] = useState([]);
  const [making, setMaking] = useState(false);
  const [title, setTitle] = useState("");
  const [picked, setPicked] = useState([]);
  const [error, setError] = useState("");
  const canRun = group.is_admin || group.claimable;
  const candidates = freeTimes.slice(0, 5);

  async function load() {
    try {
      const res = await fetch(`${API_URL}/groups/polls?group_id=${group.id}`, { headers: authHeaders() });
      if (res.ok) setPolls((await res.json()).polls);
    } catch { /* keep */ }
  }

  useEffect(() => {
    load();
    const timer = setInterval(() => document.visibilityState === "visible" && load(), 30000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group.id, refreshKey]);

  async function call(path, body) {
    const res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Something went wrong.");
    return data;
  }

  function startMaking() {
    setTitle(`${group.name || "Group"} meeting`);
    setPicked(candidates.slice(0, 3).map((f) => f.start));
    setError("");
    setMaking(true);
  }

  async function create(e) {
    e.preventDefault();
    try {
      const options = candidates.filter((f) => picked.includes(f.start)).map((f) => {
        // Each option is one meeting-length block at the start of the free slot.
        const len = Math.min(f.duration_minutes, group.settings?.meetingLength || 30);
        return { start: f.start, end: new Date(new Date(f.start).getTime() + len * 60000).toISOString() };
      });
      await call(`/groups/polls?group_id=${group.id}`, { title, options });
      setMaking(false);
      notify?.("Poll started. Everyone in the group can vote.");
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function toggleVote(poll, i) {
    const mine = poll.options.map((o, idx) => (o.mine ? idx : null)).filter((x) => x !== null);
    const next = mine.includes(i) ? mine.filter((x) => x !== i) : [...mine, i];
    try {
      const data = await call(`/polls/vote?id=${poll.id}`, { options: next });
      setPolls((ps) => ps.map((p) => (p.id === poll.id ? data.poll : p)));
    } catch (err) {
      notify?.(err.message, "error");
    }
  }

  async function close(poll) {
    try {
      await call(`/polls/close?id=${poll.id}`);
      notify?.(`Poll closed: "${poll.title}" is booked.`);
      load();
      onBooked?.();
    } catch (err) {
      notify?.(err.message, "error");
    }
  }

  async function remove(poll) {
    try {
      await call(`/polls/delete?id=${poll.id}`);
      load();
    } catch (err) {
      notify?.(err.message, "error");
    }
  }

  return (
    <div className="card">
      <div className="card-title">
        <h2>🗳️ Polls</h2>
        {canRun && !making && candidates.length >= 2 && (
          <button className="link-btn" onClick={startMaking}>+ New poll</button>
        )}
      </div>

      {making && (
        <form onSubmit={create} className="poll-new">
          <label className="field">
            <span>What's it for</span>
            <input value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <p className="muted-line">Times to vote on (pick 2 to 5):</p>
          <ul className="plan-list">
            {candidates.map((f) => (
              <li key={f.start}>
                <label className="poll-pick">
                  <input
                    type="checkbox"
                    checked={picked.includes(f.start)}
                    onChange={(e) => setPicked((p) => (e.target.checked ? [...p, f.start] : p.filter((x) => x !== f.start)))}
                  />
                  {formatSpan(f.start, f.end)}
                </label>
              </li>
            ))}
          </ul>
          {error && <p className="error-text">{error}</p>}
          <div className="btn-row">
            <button className="btn btn-primary" type="submit" disabled={picked.length < 2 || picked.length > 5}>Start poll</button>
            <button className="btn btn-ghost" type="button" onClick={() => setMaking(false)}>Cancel</button>
          </div>
        </form>
      )}

      {!making && polls.length === 0 && (
        <p className="muted-line">
          {canRun ? "Not sure which time? Put the best few up for a vote." : "No polls yet. The group's admin can start one."}
        </p>
      )}

      {polls.map((poll) => {
        const top = Math.max(0, ...poll.options.map((o) => o.votes));
        return (
          <div key={poll.id} className={`poll ${poll.closed ? "closed" : ""}`}>
            <div className="poll-head">
              <strong>{poll.title}</strong>
              <small>{poll.closed ? "Closed · booked" : `${poll.voters} voted · by ${poll.created_by_name}`}</small>
            </div>
            <ul className="poll-options">
              {poll.options.map((o, i) => (
                <li key={i}>
                  <button
                    type="button"
                    className={`poll-option ${o.mine ? "mine" : ""} ${poll.closed && poll.winner === i ? "winner" : ""}`}
                    disabled={poll.closed}
                    onClick={() => toggleVote(poll, i)}
                    title={o.voters.length ? `Works for: ${o.voters.join(", ")}` : "No votes yet"}
                    aria-pressed={o.mine}
                  >
                    <span className="poll-check" aria-hidden="true">{o.mine ? "✓" : ""}</span>
                    <span className="poll-time">{formatSpan(o.start, o.end)}</span>
                    <span className="poll-count">{o.votes}{!poll.closed && o.votes === top && top > 0 ? " 🔥" : ""}{poll.closed && poll.winner === i ? " ✅" : ""}</span>
                  </button>
                </li>
              ))}
            </ul>
            {poll.can_manage && !poll.closed && (
              <div className="btn-row">
                <button className="btn btn-primary" onClick={() => close(poll)} disabled={poll.voters === 0}>Close &amp; book the winner</button>
                <button className="link-btn danger" onClick={() => remove(poll)}>Delete</button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
