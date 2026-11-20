import { useState } from "react";
import { API_URL } from "../config";
import { getToken } from "../session";

export default function ImportIcs({ onImported }) {
  const [files, setFiles] = useState([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  async function upload() {
    const token = getToken();
    if (!token) {
      setStatus("Connect Google Calendar or sign in first.");
      return;
    }
    if (!files.length) return;

    setLoading(true);
    setStatus("");

    try {
      const formData = new FormData();
      // Several files at once (e.g. a class timetable and a work schedule): they import together.
      for (const f of files) formData.append("files", f);

      const res = await fetch(
        `${API_URL}/import/ics`,
        { method: "POST", body: formData, headers: { Authorization: `Bearer ${token}` } }
      );

      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail || "Import failed");
      }

      const data = await res.json();
      const from = files.length > 1 ? ` from ${files.length} files` : "";
      setStatus(`Imported ${data.imported} event${data.imported === 1 ? "" : "s"}${from}.`);
      setFiles([]);
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
        Upload one or more .ics files exported from Outlook, Apple Calendar, or another app. Pick them all at
        once: each import replaces the previous one.
      </p>

      <div className="btn-row">
        <input
          type="file"
          accept=".ics"
          multiple
          onChange={(e) => setFiles(Array.from(e.target.files || []).slice(0, 10))}
        />
        <button className="btn btn-primary" onClick={upload} disabled={!files.length || loading}>
          {loading && <span className="spinner" />}
          {loading ? "Importing..." : "Import"}
        </button>
      </div>

      {status && <p className="empty-state">{status}</p>}
    </div>
  );
}
