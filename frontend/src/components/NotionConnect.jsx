import { useState } from "react";
import { API_URL } from "../config";
import { getToken } from "../session";

// signedIn=false: "Continue with Notion" on the sign-in screen (the account is
// your Notion email). signedIn=true: connect Notion to the account you're in.
export default function NotionConnect({ signedIn, connected, imported, onChanged }) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function start() {
    setError("");
    if (!signedIn) {
      window.location.href = `${API_URL}/notion/login`;
      return;
    }
    // A redirect can't carry the session token, so get a 2-minute ticket first.
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/notion/link-ticket`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || "Couldn't start connecting Notion.");
      window.location.href = `${API_URL}/notion/login?ticket=${encodeURIComponent(data.ticket)}`;
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  async function disconnect() {
    await fetch(`${API_URL}/notion/disconnect`, {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },
    }).catch(() => null);
    await onChanged();
  }

  if (!signedIn) {
    return (
      <div className="btn-row">
        <button className="btn btn-primary" onClick={start}>Continue with Notion</button>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-title">
        <h2>Notion</h2>
        <span className={`status-pill ${connected ? "connected" : "disconnected"}`}>
          <span className="dot" />
          {connected ? "Connected" : "Not connected"}
        </span>
      </div>
      <p className="card-subtitle">
        Imports timed dates from the Notion databases you share with TimeFrame (a schedule, planner or meetings
        database). Date-only entries like deadlines don't count as busy.
      </p>
      <div className="btn-row">
        <button className="btn btn-primary" onClick={start} disabled={loading}>
          {loading && <span className="spinner" />}
          {connected ? "Sync Notion again" : "Connect Notion"}
        </button>
        {connected && <button className="btn btn-danger-ghost" onClick={disconnect}>Disconnect</button>}
      </div>
      {imported != null && (
        <p className="empty-state">
          Imported {imported} event{imported === 1 ? "" : "s"} from Notion.
          {imported === 0 && " Share a database with a date-and-time property with TimeFrame, then sync again."}
        </p>
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
