import { useState } from "react";
import { API_URL } from "../config";

export default function ImportIcs({ onImported }) {
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  async function upload() {
    const token = localStorage.getItem("authToken");
    if (!token) {
      setStatus("Connect Google Calendar or sign in first.");
      return;
    }
    if (!file) return;

    setLoading(true);
    setStatus("");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(
        `${API_URL}/import/ics`,
        { method: "POST", body: formData, headers: { Authorization: `Bearer ${token}` } }
      );

      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail || "Import failed");
      }

      const data = await res.json();
      setStatus(`Imported ${data.imported} event${data.imported === 1 ? "" : "s"}.`);
      setFile(null);
      await onImported();
    } catch (err) {
      console.error(err);
      setStatus(err.message || "Something went wrong importing that file.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title">
        <h2>Import Calendar File</h2>
      </div>
      <p className="card-subtitle">
        Upload a .ics file exported from Outlook, Apple Calendar, or another app.
      </p>

      <div className="btn-row">
        <input
          type="file"
          accept=".ics"
          onChange={(e) => setFile(e.target.files[0] || null)}
        />
        <button className="btn btn-primary" onClick={upload} disabled={!file || loading}>
          {loading && <span className="spinner" />}
          {loading ? "Importing..." : "Import"}
        </button>
      </div>

      {status && <p className="empty-state">{status}</p>}
    </div>
  );
}
