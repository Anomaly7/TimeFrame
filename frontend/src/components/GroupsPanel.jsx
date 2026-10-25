import { useEffect, useState } from "react";
import { API_URL } from "../config";

// Short, easy-to-share/type code instead of a full UUID - collisions are
// astronomically unlikely at this app's scale (58^8 possibilities).
function generateShortGroupId() {
  const alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join("");
}

function linkFor(groupId) {
  return `${window.location.origin}/?group=${groupId}`;
}

// Every group link you're in: make named ones, switch which one the
// calendar shows, copy a link, rename or leave. Each link stays live until
// everyone leaves it.
export default function GroupsPanel({ authHeaders, activeGroupId, onSwitch, refreshKey }) {
  const [groups, setGroups] = useState([]);
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState(null); // group id being renamed
  const [renameDraft, setRenameDraft] = useState("");
  const [confirmLeave, setConfirmLeave] = useState(null);
  const [copied, setCopied] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    try {
      const res = await fetch(`${API_URL}/groups`, { headers: authHeaders() });
      if (!res.ok) throw new Error();
      setGroups((await res.json()).groups);
    } catch {
      setError("Couldn't load your groups.");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  async function post(path) {
    setError("");
    const res = await fetch(`${API_URL}${path}`, { method: "POST", headers: authHeaders() });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Something went wrong.");
    return res.json();
  }

  async function createGroup(e) {
    e.preventDefault();
    const id = generateShortGroupId();
    try {
      // Join first: the server only shows a group's calendars to its members.
      await post(`/groups/join?group_id=${id}&name=${encodeURIComponent(newName)}`);
      setNewName("");
      await load();
      onSwitch(id);
      copy(id);
    } catch (err) {
      setError(err.message);
    }
  }

  async function saveRename(e, id) {
    e.preventDefault();
    try {
      await post(`/groups/rename?group_id=${id}&name=${encodeURIComponent(renameDraft)}`);
      setRenaming(null);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function leave(id) {
    try {
      await post(`/groups/leave?group_id=${id}`);
      setConfirmLeave(null);
      if (id === activeGroupId) onSwitch(null);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  function copy(id) {
    navigator.clipboard.writeText(linkFor(id)).then(
      () => {
        setCopied(id);
        setTimeout(() => setCopied((c) => (c === id ? null : c)), 2000);
      },
      () => setError(`Copy this link: ${linkFor(id)}`)
    );
  }

  return (
    <div className="card groups-panel">
      <div className="card-title">
        <h2>My groups</h2>
      </div>
      <p className="card-subtitle">
        Share a group's link: everyone who opens it and signs in sees each other's busy times. Each link stays live.
      </p>

      <form className="groups-new" onSubmit={createGroup}>
        <input
          className="activity-name-input"
          placeholder="Name a new group (e.g. Robotics team)"
          value={newName}
          maxLength={60}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button className="btn btn-primary" type="submit">Create group link</button>
      </form>

      <ul className="groups-list">
        <li className={`groups-row ${!activeGroupId ? "active" : ""}`}>
          <div className="groups-info">
            <strong>Just me</strong>
            <span className="groups-members">Only your own calendar</span>
          </div>
          <div className="groups-actions">
            {!activeGroupId ? <span className="status-pill connected">Viewing</span> : (
              <button className="btn-ghost" onClick={() => onSwitch(null)}>View</button>
            )}
          </div>
        </li>

        {groups.map((g) => (
          <li className={`groups-row ${g.id === activeGroupId ? "active" : ""}`} key={g.id}>
            <div className="groups-info">
              {renaming === g.id ? (
                <form className="groups-rename" onSubmit={(e) => saveRename(e, g.id)}>
                  <input
                    value={renameDraft}
                    maxLength={60}
                    autoFocus
                    onFocus={(e) => e.target.select()}
                    placeholder="Group name"
                    onChange={(e) => setRenameDraft(e.target.value)}
                  />
                  <button className="link-btn" type="submit">Save</button>
                  <button className="link-btn muted" type="button" onClick={() => setRenaming(null)}>Cancel</button>
                </form>
              ) : (
                <strong>{g.name || `Unnamed group (${g.id})`}</strong>
              )}
              <span className="groups-members">{g.members.join(", ")}</span>
            </div>

            <div className="groups-actions">
              {g.id === activeGroupId ? <span className="status-pill connected">Viewing</span> : (
                <button className="btn-ghost" onClick={() => onSwitch(g.id)}>View</button>
              )}
              <button className="btn-ghost" onClick={() => copy(g.id)}>{copied === g.id ? "Copied!" : "Copy link"}</button>
              <button className="btn-ghost" onClick={() => { setRenameDraft(g.name || ""); setRenaming(g.id); }}>Rename</button>
              {confirmLeave === g.id ? (
                <>
                  <button className="btn-danger-ghost" onClick={() => leave(g.id)}>Leave?</button>
                  <button className="link-btn muted" onClick={() => setConfirmLeave(null)}>Cancel</button>
                </>
              ) : (
                <button className="btn-ghost" onClick={() => setConfirmLeave(g.id)}>Leave</button>
              )}
            </div>
          </li>
        ))}
      </ul>

      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
