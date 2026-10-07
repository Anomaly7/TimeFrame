import { useState, useEffect } from "react";
import "./App.css";
import { API_URL } from "./config";

import AvailabilityForm from "./components/AvailabilityForm";
import GoogleConnect from "./components/GoogleConnect";
import EmailAuth from "./components/EmailAuth";
import CalendarView from "./components/CalendarView";
import MonthView from "./components/MonthView";
import SettingsPanel from "./components/SettingsPanel";
import ImportIcs from "./components/ImportIcs";

const MY_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

const DEFAULT_SETTINGS = { dayStart: "08:00", dayEnd: "22:00", excludeWeekends: false, meetingLength: 30 };

function ymd(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function parseISODate(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function addDaysISO(iso, n) {
  const d = parseISODate(iso);
  d.setDate(d.getDate() + n);
  return ymd(d);
}

function addMonthsISO(iso, n) {
  const d = parseISODate(iso);
  d.setMonth(d.getMonth() + n);
  return ymd(d);
}

// The date range to request from the backend for whichever period is
// currently in view - Day/Week/Month all page independently through the
// full year of synced data instead of always fetching "this week."
function getRequestRange(viewMode, viewDate) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const vd = parseISODate(viewDate);

  if (viewMode === "day") {
    const startOffset = Math.round((vd - today) / 86400000);
    return { startOffset, days: 1 };
  }

  if (viewMode === "week") {
    const weekStart = new Date(vd);
    weekStart.setDate(weekStart.getDate() - weekStart.getDay());
    const startOffset = Math.round((weekStart - today) / 86400000);
    return { startOffset, days: 7 };
  }

  // month - always a fixed 6-week (42 day) grid so the request always
  // covers every cell MonthView renders, including the leading/trailing
  // days borrowed from adjacent months.
  const monthStart = new Date(vd.getFullYear(), vd.getMonth(), 1);
  const gridStart = new Date(monthStart);
  gridStart.setDate(gridStart.getDate() - gridStart.getDay());
  const startOffset = Math.round((gridStart - today) / 86400000);
  return { startOffset, days: 42 };
}

function formatRangeLabel(viewMode, viewDate) {
  const d = parseISODate(viewDate);

  if (viewMode === "day") {
    return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  }

  if (viewMode === "week") {
    const weekStart = new Date(d);
    weekStart.setDate(weekStart.getDate() - weekStart.getDay());
    const weekEnd = new Date(weekStart);
    weekEnd.setDate(weekEnd.getDate() + 6);
    const sameMonth = weekStart.getMonth() === weekEnd.getMonth();
    const startLabel = weekStart.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    const endLabel = weekEnd.toLocaleDateString(undefined, sameMonth ? { day: "numeric" } : { month: "short", day: "numeric" });
    return `${startLabel} – ${endLabel}, ${weekEnd.getFullYear()}`;
  }

  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

export default function App() {
  // 🔹 MANUAL BUSY SLOTS (input form)
  const [manualBusy, setManualBusy] = useState(() => {
    const saved = localStorage.getItem("manualBusy");
    return saved ? JSON.parse(saved) : [];
  });

  // undefined = still checking for a valid session, null = confirmed signed
  // out, a string = confirmed signed in as that email. Kept 3-way so the
  // login gate below never flashes before a valid returning session has
  // had a chance to verify itself.
  const [email, setEmail] = useState(undefined);

  const [viewMode, setViewMode] = useState(() => {
    return localStorage.getItem("viewMode") || "day";
  });

  // The anchor date for whichever period is in view - always starts on
  // today on a fresh load rather than persisting, so reopening the app
  // doesn't strand you on a date you navigated to last time.
  const [viewDate, setViewDate] = useState(() => ymd(new Date()));

  function goToPrevious() {
    if (viewMode === "day") setViewDate((d) => addDaysISO(d, -1));
    else if (viewMode === "week") setViewDate((d) => addDaysISO(d, -7));
    else setViewDate((d) => addMonthsISO(d, -1));
  }

  function goToNext() {
    if (viewMode === "day") setViewDate((d) => addDaysISO(d, 1));
    else if (viewMode === "week") setViewDate((d) => addDaysISO(d, 7));
    else setViewDate((d) => addMonthsISO(d, 1));
  }

  function goToToday() {
    setViewDate(ymd(new Date()));
  }

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState(() => {
    const saved = localStorage.getItem("settings");
    return saved ? { ...DEFAULT_SETTINGS, ...JSON.parse(saved) } : DEFAULT_SETTINGS;
  });

  // 🔹 MERGED BUSY TIMES (from backend)
  const [busyTimes, setBusyTimes] = useState(() => {
    const saved = localStorage.getItem("busyTimes");
    return saved ? JSON.parse(saved) : [];
  });

  // The Google sign-in redirect puts the session in the #fragment (never sent
  // to any server); ?query is still read for links made before that change.
  const params = new URLSearchParams(window.location.search);
  const hashParams = new URLSearchParams(window.location.hash.slice(1));
  const userId = hashParams.get("user") || params.get("user");
  const groupIdFromLink = params.get("group");
  const tokenFromUrl = hashParams.get("token") || params.get("token");
  const authError = hashParams.get("auth_error");

  // The session token proves who's making a request - the backend never
  // trusts a plain user_id from a query param for that (anyone could type
  // in someone else's email and read/overwrite their schedule otherwise).
  function authHeaders() {
    const token = tokenFromUrl || localStorage.getItem("authToken");
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  useEffect(() => {
    if (userId) {
      localStorage.setItem("userId", userId);
    }
  }, [userId]);

  useEffect(() => {
    if (tokenFromUrl) {
      localStorage.setItem("authToken", tokenFromUrl);
    }
    // Saved - now take the token out of the address bar so it isn't left in
    // history, bookmarks or a copied link.
    if (tokenFromUrl || authError || params.get("user")) {
      const clean = new URLSearchParams(window.location.search);
      clean.delete("token"); clean.delete("user");
      const q = clean.toString();
      window.history.replaceState(null, "", window.location.pathname + (q ? "?" + q : ""));
    }
    if (authError) alert(authError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tokenFromUrl]);


  useEffect(() => {
    if (groupIdFromLink) {
      localStorage.setItem("groupId", groupIdFromLink);
    }
  }, [groupIdFromLink]);

  useEffect(() => {
    // Google's OAuth redirect drops the ?group= param, so by the time we
    // learn the token (from the redirect) the group id may only be in
    // localStorage, not the URL. Check both so the join actually happens
    // regardless of which one arrives first.
    const joiningGroupId = groupIdFromLink || localStorage.getItem("groupId");
    const token = tokenFromUrl || localStorage.getItem("authToken");


    if (!token || !joiningGroupId) return;


    fetch(
      `${API_URL}/groups/join?group_id=${joiningGroupId}`,
      { method: "POST", headers: authHeaders() }
    ).then(() => {
      // The mount-time availability fetch (below) can win the race and
      // complete before this join is processed server-side, showing only
      // your own calendar with no automatic retry - refetch once the
      // join has actually gone through so the group's merged data shows
      // up without needing to touch anything else first.
      fetchAvailability(manualBusy).catch((err) => console.error(err));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupIdFromLink, tokenFromUrl]);

  // 🔹 FREE TIMES
  const [freeTimes, setFreeTimes] = useState(() => {
    const saved = localStorage.getItem("freeTimes");
    return saved ? JSON.parse(saved) : [];
  });

  useEffect(() => {
    const token = tokenFromUrl || localStorage.getItem("authToken");
    if (!token) {
      setEmail(null);
      return;
    }

    fetch(`${API_URL}/auth/me`, { headers: authHeaders() })
      .then(res => {
        if (!res.ok) throw new Error("Session invalid");
        return res.json();
      })
      .then(data => setEmail(data.email))
      .catch(() => {
        // An expired/invalid token shouldn't leave the app stuck showing
        // stale data behind the gate - drop it and fall back to signed out.
        localStorage.removeItem("authToken");
        localStorage.removeItem("userId");
        setEmail(null);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Busy/free times are scoped server-side, so cached results from a
  // previous visit (or an earlier day) are stale as soon as the page
  // loads. Re-fetch automatically instead of waiting for the user to
  // click "Find Free Time" again - also whenever the day-start/day-end
  // settings change, since those are query params the backend needs.
  useEffect(() => {
    if (localStorage.getItem("userId")) {
      fetchAvailability(manualBusy).catch(err => console.error(err));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.dayStart, settings.dayEnd, settings.meetingLength, viewMode, viewDate]);

  // 🔁 Persist everything
  useEffect(() => {
    localStorage.setItem("manualBusy", JSON.stringify(manualBusy));
  }, [manualBusy]);

  useEffect(() => {
    localStorage.setItem("busyTimes", JSON.stringify(busyTimes));
  }, [busyTimes]);

  useEffect(() => {
    localStorage.setItem("freeTimes", JSON.stringify(freeTimes));
  }, [freeTimes]);

  useEffect(() => {
    localStorage.setItem("viewMode", viewMode);
  }, [viewMode]);

  useEffect(() => {
    localStorage.setItem("settings", JSON.stringify(settings));
  }, [settings]);

  async function fetchAvailability(extraBusy = []) {
    const token = tokenFromUrl || localStorage.getItem("authToken");
    if (!token) return;

    const groupId = localStorage.getItem("groupId");
    const groupParam = groupId ? `&group=${groupId}` : "";

    const { startOffset, days } = getRequestRange(viewMode, viewDate);

    const url = `${API_URL}/availability/merge?min_minutes=${settings.meetingLength}&day_start=${settings.dayStart}&day_end=${settings.dayEnd}&timezone=${encodeURIComponent(MY_TIMEZONE)}&days=${days}&start_offset=${startOffset}${groupParam}`;

    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(extraBusy.length ? [extraBusy] : []),
    });

    if (!res.ok) {
      throw new Error("Failed to fetch availability");
    }

    const data = await res.json();
    setBusyTimes(data.busy_times);
    setFreeTimes(data.ranked_free_time);
  }

  // 🧼 CLEAR EVERYTHING
  function clearAll() {
    setManualBusy([]);
    setBusyTimes([]);
    setFreeTimes([]);
    localStorage.removeItem("userId");
    localStorage.removeItem("authToken");
    localStorage.removeItem("groupId");
    localStorage.removeItem("manualBusy");
    localStorage.removeItem("busyTimes");
    localStorage.removeItem("freeTimes");

  }
  function logout() {
    fetch(`${API_URL}/auth/logout`, {
      method: "POST",
      headers: authHeaders()
    }).then(() => {
      localStorage.clear();
      setEmail(null);
      setManualBusy([]);
      setBusyTimes([]);
      setFreeTimes([]);
      window.location.reload();
    });
  }

  // Short, easy-to-share/type code instead of a full UUID - collisions are
  // astronomically unlikely at this app's scale (58^8 possibilities).
  function generateShortGroupId() {
    const alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    const bytes = crypto.getRandomValues(new Uint8Array(8));
    return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join("");
  }

  async function createGroupLink() {
    const groupId = generateShortGroupId();

    // Join first: the server only shows a group's calendars to its members.
    const res = await fetch(
      `${API_URL}/groups/join?group_id=${groupId}`,
      { method: "POST", headers: authHeaders() }
    );
    if (!res.ok) {
      alert("Couldn't create the group link. Please try again.");
      return;
    }

    localStorage.setItem("groupId", groupId);

    const link = `${window.location.origin}/?group=${groupId}`;

    navigator.clipboard.writeText(link)
      .then(() => {
        alert("Group link copied to clipboard!");
      })
      .catch(() => {
        alert(`Copy this link:\n${link}`);
      });
  }


  // Still verifying a returning session. Usually instant, but a sleeping
  // server can take most of a minute to wake, so say what's happening
  // instead of showing a blank page.
  if (email === undefined) {
    return (
      <div className="app" style={{ display: "grid", placeItems: "center", minHeight: "60vh", opacity: 0.7 }}>
        <p>Connecting to TimeFrame… this can take up to a minute the first time.</p>
      </div>
    );
  }

  // No valid session - the rest of the app (and the data it would show)
  // stays completely hidden until Google sign-in succeeds.
  if (email === null) {
    return (
      <div className="app login-gate">
        <header className="app-header">
          <div className="brand">
            <span className="brand-mark">🗓️</span>
            <h1>TimeFrame</h1>
          </div>
        </header>

        <div className="login-card">
          <h2>Sign in to continue</h2>
          <p className="card-subtitle">
            Sign in so only you can see and manage your own schedule.
          </p>
          <GoogleConnect connected={false} />

          <div className="auth-divider"><span>or</span></div>

          <EmailAuth
            onAuthenticated={(token, authedEmail) => {
              localStorage.setItem("authToken", token);
              localStorage.setItem("userId", authedEmail);
              // A full reload (not just setEmail) so the mount-time
              // fetchAvailability effect actually runs - the same thing
              // a Google sign-in redirect naturally does by reloading
              // the page.
              window.location.reload();
            }}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">🗓️</span>
          <h1>TimeFrame</h1>
        </div>
        <div className="user-chip">
          Signed in as <strong>{email}</strong>
        </div>
      </header>

      <GoogleConnect connected={!!email} />

      <ImportIcs onImported={fetchAvailability} />

      <AvailabilityForm
        manualBusy={manualBusy}
        setManualBusy={setManualBusy}
        onSubmit={fetchAvailability}
      />

      <div className="toolbar">
        <button className="btn-ghost" onClick={clearAll}>Clear Schedule</button>
        <button className="btn-ghost" onClick={logout}>Logout / Disconnect Google</button>
        <button className="btn btn-primary" onClick={createGroupLink}>Create Group Link</button>
      </div>

      <p className="tz-note">
        🌐 Your times: <strong>{MY_TIMEZONE}</strong> · Other group members'
        times are shown relative to this same timezone
      </p>

      <div className="tabs">
        <button
          className={`tab ${viewMode === "day" ? "active" : ""}`}
          onClick={() => setViewMode("day")}
        >
          Day
        </button>
        <button
          className={`tab ${viewMode === "week" ? "active" : ""}`}
          onClick={() => setViewMode("week")}
        >
          Week
        </button>
        <button
          className={`tab ${viewMode === "month" ? "active" : ""}`}
          onClick={() => setViewMode("month")}
        >
          Month
        </button>
        <button
          className="settings-toggle"
          onClick={() => setSettingsOpen(!settingsOpen)}
          aria-label="Settings"
          title="Settings"
        >
          ⚙️
        </button>
      </div>

      {settingsOpen && (
        <SettingsPanel settings={settings} setSettings={setSettings} />
      )}

      <div className="calendar-nav">
        <button className="btn-ghost" onClick={goToPrevious} aria-label="Previous">‹</button>
        <button className="btn-ghost" onClick={goToToday}>Today</button>
        <button className="btn-ghost" onClick={goToNext} aria-label="Next">›</button>
        <span className="calendar-nav-label">{formatRangeLabel(viewMode, viewDate)}</span>
      </div>

      {viewMode === "month" ? (
        <MonthView
          viewDate={viewDate}
          busyTimes={busyTimes}
          freeTimes={freeTimes}
          excludeWeekends={settings.excludeWeekends}
          currentUserId={localStorage.getItem("userId")}
          onSelectDay={(date) => {
            setViewDate(date);
            setViewMode("day");
          }}
        />
      ) : (
        <CalendarView
          mode={viewMode}
          viewDate={viewDate}
          busyTimes={busyTimes}
          freeTimes={freeTimes}
          excludeWeekends={settings.excludeWeekends}
          dayStartHour={parseInt(settings.dayStart.split(":")[0], 10)}
          dayEndHour={parseInt(settings.dayEnd.split(":")[0], 10)}
          timezone={MY_TIMEZONE}
          currentUserId={localStorage.getItem("userId")}
        />
      )}
    </div>
  );
}
