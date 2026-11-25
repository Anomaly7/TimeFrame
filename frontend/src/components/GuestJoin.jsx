import { useEffect, useState } from "react";
import { API_URL } from "../config";

// On the sign-in page when you opened a group link: join with just your name (no account).
export default function GuestJoin({ groupId, onJoined }) {
  const [info, setInfo] = useState(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API_URL}/guest/group?group_id=${encodeURIComponent(groupId)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then(setInfo)
      .catch(() => setInfo(null));
  }, [groupId]);

  if (!info || !info.guests_allowed) return null;

  async function join(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/guest/join`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group_id: groupId, name }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Couldn't join as a guest.");
      onJoined(data.token, data.user);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <form className="guest-join" onSubmit={join}>
      <p className="guest-join-head">
        You're invited to <strong>{info.name || "a group"}</strong>
        {info.members ? ` · ${info.members} ${info.members === 1 ? "person" : "people"}` : ""}
      </p>
      <p className="muted-line">No account needed: add your name, then mark when you're busy.</p>
      <div className="guest-join-row">
        <input value={name} maxLength={40} placeholder="Your name" aria-label="Your name" onChange={(e) => setName(e.target.value)} />
        <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>
          {busy ? "Joining..." : "Join as guest"}
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      <div className="auth-divider"><span>or sign in</span></div>
    </form>
  );
}
