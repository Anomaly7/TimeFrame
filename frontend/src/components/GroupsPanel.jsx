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

// Copies text on every browser. Must be called straight from a click/submit: Safari, Firefox and phones only allow
// clipboard writes during the click itself, not after waiting for the server (Sam, 2026-11-25). Resolves true/false.
function copyText(text) {
  const fallback = () => {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:0;left:0;opacity:0;font-size:16px";
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, text.length); // iOS Safari
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  };
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    return navigator.clipboard.writeText(text).then(() => true, () => fallback());
  }
  return Promise.resolve(fallback());
}

// Every group link you're in: make named ones, switch which one the
// calendar shows, copy a link, rename or leave. Each link stays live until
// everyone leaves it.
// The creator of a link is its admin (👑): only they can rename it, set the
// group's scheduling settings (in Settings) and remove people. groups lives
// in App so the active group's settings can drive the calendar.
export default function GroupsPanel({ authHeaders, activeGroupId, onSwitch, refreshKey, groups, setGroups, personalSettings, isPro = true, onNeedPro }) {
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState(null); // group id being renamed
  const [renameDraft, setRenameDraft] = useState("");
  const [confirmLeave, setConfirmLeave] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [confirmKick, setConfirmKick] = useState(null); // `${groupId}|${memberId}`
  const [copied, setCopied] = useState(null);
  const [made, setMade] = useState(null); // { id, link, copied } after "Create group link"
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

  // Reload on demand, whenever the viewed group changes, every 30 s and
  // when you come back to the tab - so new members, removals and admin
  // changes show up without a page reload.
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey, activeGroupId]);

  useEffect(() => {
    const tick = () => document.visibilityState === "visible" && load();
    const timer = setInterval(tick, 30000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function post(path) {
    setError("");
    const res = await fetch(`${API_URL}${path}`, { method: "POST", headers: authHeaders() });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Something went wrong.");
    return res.json();
  }

  const canCreate = isPro || groups.filter((g) => g.is_admin).length < 1;

  async function createGroup(e) {
    e.preventDefault();
    // Free accounts can create 1 group, Pro unlimited (the server checks too); joining one stays free.
    if (!canCreate && onNeedPro) return onNeedPro();
    const id = generateShortGroupId();
    // Copy now, while it still counts as your click (see copyText). The link is known before the server call.
    const copying = copyText(linkFor(id));
    setMade(null);
    setError("");
    try {
      // Join first: the server only shows a group's calendars to its members.
      await post(`/groups/join?group_id=${id}&name=${encodeURIComponent(newName)}`);
      // A new group starts with its creator's current settings (custom settings are Pro).
      if (isPro) await fetch(`${API_URL}/groups/settings?group_id=${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(personalSettings),
      });
      setNewName("");
      await load();
      onSwitch(id);
      setMade({ id, link: linkFor(id), copied: await copying });
    } catch (err) {
      if (/Pro/.test(err.message) && onNeedPro) onNeedPro();
      else setError(err.message);
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

  // Admin only: removes everyone and deletes the group; the link stops working for good.
  async function removeGroup(id) {
    try {
      await post(`/groups/delete?group_id=${id}`);
      setConfirmDelete(null);
      if (made?.id === id) setMade(null);
      if (id === activeGroupId) onSwitch(null);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function kick(groupId, memberId) {
    try {
      await post(`/groups/kick?group_id=${groupId}&member=${encodeURIComponent(memberId)}`);
      setConfirmKick(null);
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function claim(groupId) {
    try {
      await post(`/groups/claim?group_id=${groupId}`);
      load();
    } catch (err) {
      setError(err.message);
      load();
    }
  }

  function copy(id) {
    copyText(linkFor(id)).then((ok) => {
      if (!ok) return setMade({ id, link: linkFor(id), copied: false });
      setCopied(id);
      setTimeout(() => setCopied((c) => (c === id ? null : c)), 2000);
    });
  }

  const canShare = typeof navigator !== "undefined" && !!navigator.share;
  function share(link) {
    navigator.share({ title: "Join my TimeFrame group", text: "Find a time that works for everyone:", url: link }).catch(() => {});
  }

  return (
    <div className="card groups-panel">
      <form className="groups-new" onSubmit={createGroup}>
        <input
          className="activity-name-input"
          placeholder="Name a new group (e.g. Robotics team)"
          value={newName}
          maxLength={60}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button className="btn btn-primary" type="submit">Create group link{!canCreate && <span className="pro-tag">PRO</span>}</button>
      </form>

      {made && (
        <div className={`link-made ${made.copied ? "ok" : ""}`} role="status">
          <div className="link-made-head">
            <strong>{made.copied ? "✓ Group created. Link copied" : "Group created. Copy your link"}</strong>
            <button type="button" className="link-btn muted" onClick={() => setMade(null)} aria-label="Dismiss">✕</button>
          </div>
          <p>{made.copied ? "Paste it anywhere to invite people." : "Your browser blocked automatic copying. Use the button below."}</p>
          <div className="link-made-row">
            <input readOnly value={made.link} onFocus={(e) => e.target.select()} aria-label="Group link" />
            <button type="button" className="btn-ghost" onClick={() => copyText(made.link).then((ok) => setMade({ ...made, copied: ok || made.copied }))}>Copy</button>
            {canShare && <button type="button" className="btn-ghost" onClick={() => share(made.link)}>Share</button>}
          </div>
        </div>
      )}
      {error && <p className="error-text">{error}</p>}

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
              <span className="groups-members">
                {g.members.map((m) => `${m.admin ? "👑 " : ""}${m.name}`).join(", ")}
              </span>
              {g.is_admin && g.members.some((m) => !m.you) && (
                <ul className="groups-member-list">
                  {g.members.filter((m) => !m.you).map((m) => {
                    const key = `${g.id}|${m.id}`;
                    return (
                      <li key={m.id}>
                        <span>{m.name}</span>
                        {confirmKick === key ? (
                          <>
                            <button className="btn-danger-ghost" onClick={() => kick(g.id, m.id)}>Yes, remove</button>
                            <button className="link-btn muted" onClick={() => setConfirmKick(null)}>Cancel</button>
                          </>
                        ) : (
                          <button
                            className="btn-ghost"
                            onClick={() => setConfirmKick(key)}
                            aria-label={`Remove ${m.name} from the group`}
                          >
                            Remove
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <div className="groups-actions">
              {g.id === activeGroupId ? <span className="status-pill connected">Viewing</span> : (
                <button className="btn-ghost" onClick={() => onSwitch(g.id)}>View</button>
              )}
              <button className="btn-ghost" onClick={() => copy(g.id)}>{copied === g.id ? "Copied!" : "Copy link"}</button>
              {g.is_admin && (
                <button className="btn-ghost" onClick={() => { setRenameDraft(g.name || ""); setRenaming(g.id); }}>Rename</button>
              )}
              {g.claimable && (
                <button className="btn-ghost" onClick={() => claim(g.id)} title="This older link has no admin yet">Make me admin</button>
              )}
              {g.is_admin && (confirmDelete === g.id ? (
                <>
                  <button className="btn-danger-ghost" onClick={() => removeGroup(g.id)}>
                    Delete for everyone{g.members.length > 1 ? ` (${g.members.length - 1} ${g.members.length === 2 ? "person" : "people"})` : ""}?
                  </button>
                  <button className="link-btn muted" onClick={() => setConfirmDelete(null)}>Cancel</button>
                </>
              ) : (
                <button className="btn-danger-ghost" onClick={() => { setConfirmLeave(null); setConfirmDelete(g.id); }}>Delete</button>
              ))}
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
    </div>
  );
}
