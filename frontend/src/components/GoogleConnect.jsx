import { useState } from "react";
import { API_URL } from "../config";

// Disconnect removes your Google busy times from TimeFrame (signing out no longer does, 2026-11-25).
export default function GoogleConnect({ connected, authHeaders, onChanged }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function disconnect() {
    setBusy(true);
    await fetch(`${API_URL}/auth/disconnect`, { method: "POST", headers: authHeaders() }).catch(() => null);
    setBusy(false);
    setConfirming(false);
    onChanged?.();
  }

  function connectGoogle() {
    window.location.href = `${API_URL}/auth/login`;
  }

  return (
    <div className="card">
      <div className="card-title">
        <h2>Google Calendar</h2>
        <span className={`status-pill ${connected ? "connected" : "disconnected"}`}>
          <span className="dot" />
          {connected ? "Connected" : "Not connected"}
        </span>
      </div>

      <div className="btn-row">
        <button className="btn btn-primary" onClick={connectGoogle}>
          {connected ? "Reconnect Google Calendar" : "Connect Google Calendar"}
        </button>
        {connected && !confirming && (
          <button className="btn btn-danger-ghost" onClick={() => setConfirming(true)}>Disconnect</button>
        )}
        {connected && confirming && (
          <>
            <button className="btn btn-danger" onClick={disconnect} disabled={busy}>
              {busy ? "Removing..." : "Remove Google times"}
            </button>
            <button className="btn btn-ghost" onClick={() => setConfirming(false)}>Cancel</button>
          </>
        )}
      </div>
    </div>
  );
}
