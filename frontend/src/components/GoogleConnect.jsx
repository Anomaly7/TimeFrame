import { API_URL } from "../config";
export default function GoogleConnect({ connected }) {

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
      </div>
    </div>
  );
}
