const PERIOD_LABELS = {
  morning: ["Morning", "before 12 PM"],
  afternoon: ["Afternoon", "12 – 5 PM"],
  evening: ["Evening", "after 5 PM"],
};

// readOnly: viewing a group you're not the admin of - its settings show but
// can't be changed. note: who controls these settings, when in a group.
export default function SettingsPanel({ settings, setSettings, readOnly = false, note = null, error = "" }) {
  function update(patch) {
    setSettings({ ...settings, ...patch });
  }

  // Swap a time of day with its neighbour in the ranking.
  function move(index, delta) {
    const prefs = [...settings.timePrefs];
    const to = index + delta;
    if (to < 0 || to >= prefs.length) return;
    [prefs[index], prefs[to]] = [prefs[to], prefs[index]];
    update({ timePrefs: prefs });
  }

  return (
    <div className="card settings-panel">
      <div className="card-title">
        <h2>Settings</h2>
      </div>
      {note && <p className={`settings-note ${readOnly ? "locked" : ""}`}>{readOnly ? "🔒 " : ""}{note}</p>}
      {error && <p className="error-text">{error}</p>}

      <fieldset className="settings-fieldset" disabled={readOnly}>

      <div className="settings-row time-prefs">
        <div className="settings-field">
          Best meeting time (rank your favourite first)
          <ol className="time-prefs-list">
            {settings.timePrefs.map((p, i) => (
              <li key={p} className="time-prefs-item">
                <span className="time-prefs-rank">{i === 0 ? "👑" : i + 1}</span>
                <span>
                  <strong>{PERIOD_LABELS[p][0]}</strong>{" "}
                  <span className="time-prefs-hint">{PERIOD_LABELS[p][1]}</span>
                </span>
                <span className="time-prefs-moves">
                  <button type="button" className="btn-ghost" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move ${PERIOD_LABELS[p][0]} up`}>↑</button>
                  <button type="button" className="btn-ghost" onClick={() => move(i, 1)} disabled={i === settings.timePrefs.length - 1} aria-label={`Move ${PERIOD_LABELS[p][0]} down`}>↓</button>
                </span>
              </li>
            ))}
          </ol>
        </div>
      </div>

      <label className="settings-row settings-checkbox">
        <input
          type="checkbox"
          checked={settings.excludeWeekends}
          onChange={(e) => update({ excludeWeekends: e.target.checked })}
        />
        Exclude weekends as viable meeting options
      </label>

      <div className="settings-row">
        <label className="settings-field">
          Day starts at
          <input
            type="time"
            value={settings.dayStart}
            onChange={(e) => update({ dayStart: e.target.value })}
          />
        </label>
        <label className="settings-field">
          Day ends at
          <input
            type="time"
            value={settings.dayEnd}
            onChange={(e) => update({ dayEnd: e.target.value })}
          />
        </label>
        <label className="settings-field">
          Meeting length
          <select
            value={settings.meetingLength}
            onChange={(e) => update({ meetingLength: Number(e.target.value) })}
          >
            <option value={15}>15 minutes</option>
            <option value={30}>30 minutes</option>
            <option value={45}>45 minutes</option>
            <option value={60}>1 hour</option>
            <option value={90}>1.5 hours</option>
            <option value={120}>2 hours</option>
          </select>
        </label>
      </div>
      </fieldset>
    </div>
  );
}
