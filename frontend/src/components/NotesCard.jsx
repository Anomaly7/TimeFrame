import { useEffect, useState } from "react";
import { API_URL } from "../config";
import { ago } from "../util";

// Group chat-lite (2026-11-25): short notes, plus one the admin pins on top.
export default function NotesCard({ authHeaders, group, refreshKey, notify }) {
  const [data, setData] = useState({ pinned: null, notes: [], can_pin: false });
  const [text, setText] = useState("");
  const [pinning, setPinning] = useState(false);
  const [pinDraft, setPinDraft] = useState("");

  async function load() {
    try {
      const res = await fetch(`${API_URL}/groups/notes?group_id=${group.id}`, { headers: authHeaders() });
      if (res.ok) setData(await res.json());
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
    const out = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(out.detail || "Something went wrong.");
    return out;
  }

  async function post(e) {
    e.preventDefault();
    try {
      await call(`/groups/notes?group_id=${group.id}`, { text });
      setText("");
      load();
    } catch (err) {
      notify?.(err.message, "error");
    }
  }

  async function savePin(e) {
    e.preventDefault();
    try {
      await call(`/groups/pin?group_id=${group.id}`, { text: pinDraft });
      setPinning(false);
      load();
    } catch (err) {
      notify?.(err.message, "error");
    }
  }

  async function remove(id) {
    try {
      await call(`/groups/notes/delete?id=${encodeURIComponent(id)}`);
      load();
    } catch (err) {
      notify?.(err.message, "error");
    }
  }

  return (
    <div className="card">
      <div className="card-title">
        <h2>💬 Notes</h2>
        {data.can_pin && !pinning && (
          <button className="link-btn" onClick={() => { setPinDraft(data.pinned || ""); setPinning(true); }}>
            {data.pinned ? "Edit pin" : "Pin a note"}
          </button>
        )}
      </div>

      {pinning ? (
        <form className="note-form" onSubmit={savePin}>
          <input value={pinDraft} maxLength={280} autoFocus placeholder="e.g. We meet in EME 1151" onChange={(e) => setPinDraft(e.target.value)} />
          <button className="btn btn-primary" type="submit">{pinDraft.trim() ? "Pin" : "Unpin"}</button>
          <button className="btn btn-ghost" type="button" onClick={() => setPinning(false)}>Cancel</button>
        </form>
      ) : data.pinned && (
        <p className="note-pinned">📌 {data.pinned}</p>
      )}

      <form className="note-form" onSubmit={post}>
        <input value={text} maxLength={280} placeholder={`Message ${group.name || "the group"}…`} aria-label="New note" onChange={(e) => setText(e.target.value)} />
        <button className="btn btn-primary" type="submit" disabled={!text.trim()}>Post</button>
      </form>

      {data.notes.length === 0 && <p className="muted-line">No notes yet. Leave one for the group ("Bring laptops").</p>}
      <ul className="notes-list">
        {data.notes.map((n) => (
          <li key={n.id} className={n.mine ? "mine" : ""}>
            <div className="note-meta">
              <strong>{n.author}</strong> <small>{ago(n.created_at)}</small>
              {n.can_delete && <button className="link-btn muted" onClick={() => remove(n.id)} aria-label="Delete note">✕</button>}
            </div>
            <p>{n.text}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
