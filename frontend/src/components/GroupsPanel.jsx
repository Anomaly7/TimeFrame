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
  const [menuFor, setMenuFor] = useState(null); // group whose ⋯ menu is open
  const [managing, setManaging] = useState(null); // group whose member list is open
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


  function initials(name) {
    return (name || "?").trim().charAt(0).toUpperCase();
  }

  function avatars(members) {
    const shown = members.slice(0, 3);
    return (
      <span className="g-avatars" aria-hidden="true">
        {shown.map((m, i) => (
          <span key={m.id} className={`g-avatar p${i}`} title={m.name}>{m.you ? "Y" : initials(m.name)}</span>
        ))}
        {members.length > 3 && <span className="g-avatar more">+{members.length - 3}</span>}
      </span>
    );
  }

  return (
    <div className="card groups-panel">
      <form className="groups-new" onSubmit={createGroup}>
        <input
          className="activity-name-input"
          placeholder="New group name"
          aria-label="New group name"
          value={newName}
          maxLength={60}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button className="btn btn-primary" type="submit">
          Create link{!canCreate && <span className="pro-tag">PRO</span>}
        </button>
      </form>

      {made && (
        <div className={`link-made ${made.copied ? "ok" : ""}`} role="status">
          <div className="link-made-head">
            <strong>{made.copied ? "✓ Group created · link copied" : "Group created · copy your link"}</strong>
            <button type="button" className="icon-x" onClick={() => setMade(null)} aria-label="Dismiss">✕</button>
          </div>
          <p>{made.copied ? "Paste it anywhere to invite people." : "Your browser blocked automatic copying. Use the button below."}</p>
          <div className="link-made-row">
            <input readOnly value={made.link} onFocus={(e) => e.target.select()} aria-label="Group link" />
            <button type="button" className="btn-ghost" onClick={() => copyText(made.link).then((ok) => setMade({ ...made, copied: ok || made.copied }))}>Copy</button>
            {canShare && <button type="button" className="btn-ghost" onClick={() => share(made.link)}>Share</button>}
          </div>
        </div>
      )}
      {error && (
        <div className="notice notice-error" role="alert">
          <span>{error}</span>
          <button type="button" className="icon-x" onClick={() => setError("")} aria-label="Dismiss">✕</button>
        </div>
      )}

      <ul className="groups-list">
        <li className={`g-row ${!activeGroupId ? "active" : ""}`}>
          <div className="g-head">
            <button type="button" className="g-main" onClick={() => onSwitch(null)} aria-pressed={!activeGroupId}>
              <span className="g-avatars" aria-hidden="true"><span className="g-avatar p0">Y</span></span>
              <span className="g-text">
                <strong>Just me</strong>
                <span className="g-sub">Only your calendar</span>
              </span>
            </button>
            {!activeGroupId && <span className="g-viewing">Viewing</span>}
          </div>
        </li>

        {groups.map((g) => {
          const others = g.members.filter((m) => !m.you);
          const active = g.id === activeGroupId;
          return (
            <li className={`g-row ${active ? "active" : ""}`} key={g.id}>
              {renaming === g.id ? (
                <form className="groups-rename" onSubmit={(e) => saveRename(e, g.id)}>
                  <input
                    value={renameDraft}
                    maxLength={60}
                    autoFocus
                    onFocus={(e) => e.target.select()}
                    placeholder="Group name"
                    aria-label="Group name"
                    onChange={(e) => setRenameDraft(e.target.value)}
                  />
                  <button className="btn btn-primary btn-sm" type="submit">Save</button>
                  <button className="btn-ghost btn-sm" type="button" onClick={() => setRenaming(null)}>Cancel</button>
                </form>
              ) : (
                <div className="g-head">
                  <button type="button" className="g-main" onClick={() => onSwitch(g.id)} aria-pressed={active}>
                    {avatars(g.members)}
                    <span className="g-text">
                      <strong>
                        <span className="g-name">{g.name || `Unnamed group (${g.id})`}</span>
                        {g.is_admin && <span className="g-badge" title="You're the admin">Admin</span>}
                      </strong>
                      <span className="g-sub">
                        {g.members.length} {g.members.length === 1 ? "member" : "members"}
                        {others.length > 0 && ` · ${others.slice(0, 2).map((m) => m.name).join(", ")}${others.length > 2 ? ` +${others.length - 2}` : ""}`}
                      </span>
                    </span>
                  </button>
                  {active && <span className="g-viewing">Viewing</span>}
                  <button
                    type="button"
                    className={`g-icon ${copied === g.id ? "done" : ""}`}
                    onClick={() => copy(g.id)}
                    title={copied === g.id ? "Copied!" : "Copy invite link"}
                    aria-label="Copy invite link"
                  >
                    {copied === g.id ? "✓" : (
                      <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
                        <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" />
                      </svg>
                    )}
                  </button>
                  <div className="g-more">
                    <button
                      type="button"
                      className="g-icon"
                      aria-label="More actions"
                      title="More actions"
                      aria-expanded={menuFor === g.id}
                      onClick={() => setMenuFor(menuFor === g.id ? null : g.id)}
                    >
                      ⋯
                    </button>
                    {menuFor === g.id && (
                      <>
                        <div className="dash-menu-backdrop" onClick={() => setMenuFor(null)} />
                        <div className="g-menu" role="menu">
                          <button role="menuitem" onClick={() => { setMenuFor(null); copy(g.id); }}>Copy invite link</button>
                          {canShare && <button role="menuitem" onClick={() => { setMenuFor(null); share(linkFor(g.id)); }}>Share…</button>}
                          {g.is_admin && (
                            <button role="menuitem" onClick={() => { setMenuFor(null); setRenameDraft(g.name || ""); setRenaming(g.id); }}>Rename</button>
                          )}
                          {g.is_admin && others.length > 0 && (
                            <button role="menuitem" onClick={() => { setMenuFor(null); setManaging(managing === g.id ? null : g.id); }}>
                              {managing === g.id ? "Hide members" : "Manage members"}
                            </button>
                          )}
                          {g.claimable && (
                            <button role="menuitem" onClick={() => { setMenuFor(null); claim(g.id); }}>Make me admin</button>
                          )}
                          <hr />
                          <button role="menuitem" className="danger" onClick={() => { setMenuFor(null); setConfirmDelete(null); setConfirmLeave(g.id); }}>Leave group</button>
                          {g.is_admin && (
                            <button role="menuitem" className="danger" onClick={() => { setMenuFor(null); setConfirmLeave(null); setConfirmDelete(g.id); }}>Delete group</button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}

              {managing === g.id && g.is_admin && others.length > 0 && (
                <ul className="g-members">
                  {others.map((m) => {
                    const key = `${g.id}|${m.id}`;
                    return (
                      <li key={m.id}>
                        <span className="g-avatar sm" aria-hidden="true">{initials(m.name)}</span>
                        <span className="g-member-name">{m.name}</span>
                        {confirmKick === key ? (
                          <span className="g-actions">
                            <button className="btn-ghost btn-sm" onClick={() => setConfirmKick(null)}>Cancel</button>
                            <button className="btn btn-danger btn-sm" onClick={() => kick(g.id, m.id)}>Remove</button>
                          </span>
                        ) : (
                          <button className="btn-ghost btn-sm" onClick={() => setConfirmKick(key)} aria-label={`Remove ${m.name} from the group`}>
                            Remove
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}

              {confirmLeave === g.id && (
                <div className="g-confirm">
                  <p><strong>Leave {g.name || "this group"}?</strong> You'll need the link to rejoin.</p>
                  <div className="g-actions">
                    <button className="btn-ghost btn-sm" onClick={() => setConfirmLeave(null)}>Cancel</button>
                    <button className="btn btn-danger btn-sm" onClick={() => leave(g.id)}>Leave</button>
                  </div>
                </div>
              )}
              {confirmDelete === g.id && (
                <div className="g-confirm">
                  <p>
                    <strong>Delete {g.name || "this group"}?</strong>{" "}
                    {others.length > 0
                      ? `This removes ${others.length} ${others.length === 1 ? "person" : "people"} and the link stops working. It can't be undone.`
                      : "The link stops working. It can't be undone."}
                  </p>
                  <div className="g-actions">
                    <button className="btn-ghost btn-sm" onClick={() => setConfirmDelete(null)}>Cancel</button>
                    <button className="btn btn-danger btn-sm" onClick={() => removeGroup(g.id)}>Delete group</button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {groups.length === 0 && (
        <p className="g-empty">Create a group and share the link. Everyone who joins sees when you're all free.</p>
      )}
    </div>
  );
}
