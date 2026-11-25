import { useState } from "react";
import { API_URL } from "../config";
import { ago } from "../util";

// Disconnect removes your Google busy times from TimeFrame (signing out no longer does, 2026-11-25).
// Auto-sync (2026-11-25): with it on, the server re-reads your calendar every few hours; "Sync now" does it at once
// (without auto-sync it sends you through Google sign-in again, which re-imports).
export default function GoogleConnect({ connected, status, authHeaders, onChanged, onSynced, notify }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState(false);

  async function disconnect() {
    setBusy(true);
    await fetch(`${API_URL}/auth/disconnect`, { method: "POST", headers: authHeaders() }).catch(() => null);
    setBusy(false);
    setConfirming(false);
    onChanged?.();
  }

  function connectGoogle(consent = false) {
    window.location.href = `${API_URL}/auth/login${consent ? "?consent=1" : ""}`;
  }

  async function syncNow() {
    setSyncing(true);
    try {
      const res = await fetch(`${API_URL}/sync/google`, { method: "POST", headers: authHeaders() });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.reconnect) return connectGoogle();
      if (!res.ok) throw new Error(data.detail || "Couldn't sync Google Calendar.");
      notify?.("Google Calendar synced.");
      onSynced?.();
    } catch (err) {
      notify?.(err.message, "error");
    } finally {
      setSyncing(false);
    }
  }

  const updated = ago(status?.synced_at);

  return (
    <div className="card">
      <div className="card-title">
        <h2>Google Calendar</h2>
        <span className={`status-pill ${connected ? "connected" : "disconnected"}`}>
          <span className="dot" />
          {connected ? "Connected" : "Not connected"}
        </span>
      </div>

      {connected && (
        <p className="sync-line">
          {updated ? `Updated ${updated}` : "Synced when you connected"}
          {status?.auto_sync ? " · Auto-sync on" : ""}
        </p>
      )}
      {connected && status?.sync_error && <p className="error-text">{status.sync_error}</p>}

      <div className="btn-row">
        {connected ? (
          <button className="btn btn-primary" onClick={syncNow} disabled={syncing}>
            {syncing ? "Syncing..." : "Sync now"}
          </button>
        ) : (
          <button className="btn btn-primary" onClick={() => connectGoogle()}>Connect Google Calendar</button>
        )}
        {connected && status?.auto_sync_available && !status?.auto_sync && (
          <button className="btn btn-ghost" onClick={() => connectGoogle(true)} title="Keeps your busy times up to date automatically">
            Turn on auto-sync
          </button>
        )}
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
