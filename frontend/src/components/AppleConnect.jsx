import { useState } from "react";
import { API_URL } from "../config";

// Apple has no "Sign in to read my calendar" button for other apps: iCloud
// calendars are read with your Apple ID email plus an app-specific password.
// The password is used once for this import and never saved.
export default function AppleConnect({ connected, onChanged }) {
  const [open, setOpen] = useState(false);
  const [appleId, setAppleId] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  function headers() {
    return { Authorization: `Bearer ${localStorage.getItem("authToken")}`, "Content-Type": "application/json" };
  }

  async function connect(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setStatus("");
    try {
      const res = await fetch(`${API_URL}/apple/connect`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ apple_id: appleId, app_password: password }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || "Couldn't connect Apple Calendar.");
      setStatus(`Imported ${data.imported} event${data.imported === 1 ? "" : "s"} from Apple Calendar.`);
      setPassword("");
      setOpen(false);
      await onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function disconnect() {
    await fetch(`${API_URL}/apple/disconnect`, { method: "POST", headers: headers() }).catch(() => null);
    setStatus("Apple Calendar disconnected.");
    await onChanged();
  }

  return (
    <div className="card">
      <div className="card-title">
        <h2>Apple Calendar</h2>
        <span className={`status-pill ${connected ? "connected" : "disconnected"}`}>
          <span className="dot" />
          {connected ? "Connected" : "Not connected"}
        </span>
      </div>

      {!open && (
        <div className="btn-row">
          <button className="btn btn-primary" onClick={() => setOpen(true)}>
            {connected ? "Sync Apple Calendar again" : "Connect Apple Calendar"}
          </button>
          {connected && (
            <button className="btn btn-danger-ghost" onClick={disconnect}>Disconnect</button>
          )}
        </div>
      )}

      {open && (
        <form className="email-auth" onSubmit={connect}>
          <p className="card-subtitle">
            Sign in with your Apple ID email and an <strong>app-specific password</strong> (not your normal
            Apple password). Make one at{" "}
            <a href="https://account.apple.com/account/manage" target="_blank" rel="noreferrer">account.apple.com</a>{" "}
            → Sign-In and Security → App-Specific Passwords. TimeFrame uses it once to read when you're busy
            and never saves it.
          </p>
          <div className="email-auth-fields">
            <input
              type="email"
              placeholder="Apple ID email"
              autoComplete="username"
              value={appleId}
              onChange={(e) => setAppleId(e.target.value)}
              required
            />
            <input
              type="password"
              placeholder="App-specific password (xxxx-xxxx-xxxx-xxxx)"
              autoComplete="off"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <div className="btn-row">
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading && <span className="spinner" />}
                {loading ? "Importing..." : "Connect"}
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => { setOpen(false); setError(""); }}>
                Cancel
              </button>
            </div>
          </div>
          {error && <p className="error-text">{error}</p>}
        </form>
      )}

      {status && <p className="empty-state">{status}</p>}
    </div>
  );
}
