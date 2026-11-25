import { useState, useEffect, useRef } from "react";
import "./App.css";
import { API_URL } from "./config";
import { getToken, saveToken, clearToken, renewToken } from "./session";

import AvailabilityForm from "./components/AvailabilityForm";
import GoogleConnect from "./components/GoogleConnect";
import AppleConnect from "./components/AppleConnect";
import NotionConnect from "./components/NotionConnect";
import SignInOptions from "./components/SignInOptions";
import CalendarView from "./components/CalendarView";
import MonthView from "./components/MonthView";
import SettingsPanel from "./components/SettingsPanel";
import ImportIcs from "./components/ImportIcs";
import GroupsPanel from "./components/GroupsPanel";
import UpgradeModal from "./components/UpgradeModal";
import BookModal from "./components/BookModal";
import PlanPanel from "./components/PlanPanel";
import { hideLoader, showLoader } from "./loading";

const MY_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

// timePrefs: times of day ranked best-first for the suggested meeting slots.
const DEFAULT_SETTINGS = {
  dayStart: "08:00",
  dayEnd: "22:00",
  excludeWeekends: false,
  meetingLength: 30,
  timePrefs: ["afternoon", "morning", "evening"],
};

function ymd(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// A saved block's ISO time -> the browser-local "YYYY-MM-DDTHH:MM" the
// manual-entry list uses.
function toLocalInput(iso) {
  const d = new Date(iso);
  return `${ymd(d)}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
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
  // Clamp to the target month's last day: Jan 31 + 1 month is Feb 28, not Mar 3 (which skipped February).
  const d = parseISODate(iso);
  const day = d.getDate();
  d.setDate(1);
  d.setMonth(d.getMonth() + n);
  const lastDay = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
  d.setDate(Math.min(day, lastDay));
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

  // The name group members see on your blocks (defaults to your email
  // before the @); editable from the header.
  const [myName, setMyName] = useState("");
  const [hasCustomName, setHasCustomName] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  // TimeFrame Pro (2026-11-20): billing status, the upgrade window and a one-line notice after checkout.
  const [billing, setBilling] = useState(null);
  const [upgrade, setUpgrade] = useState(null); // null = closed, otherwise the reason shown at the top
  const [billingNote, setBillingNote] = useState("");
  const [fetching, setFetching] = useState(0); // calendar requests in flight -> thin progress bar at the top
  const [nameDraft, setNameDraft] = useState("");
  const [nameError, setNameError] = useState("");

  async function saveName(e) {
    e.preventDefault();
    setNameError("");
    try {
      const res = await fetch(`${API_URL}/auth/name`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ name: nameDraft }),
      });
      if (!res.ok) throw new Error("save failed");
      const data = await res.json();
      setMyName(data.name);
      setHasCustomName(!!data.custom_name);
      setEditingName(false);
    } catch {
      setNameError("Couldn't save your name. Try again.");
    }
  }

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

  // Which group's calendars the view shows (null = just your own).
  const [activeGroupId, setActiveGroupId] = useState(() => localStorage.getItem("groupId"));
  const [groupsRefresh, setGroupsRefresh] = useState(0);
  const [groups, setGroups] = useState([]);
  const [settingsError, setSettingsError] = useState("");
  // In-app notice instead of alert(): alert() freezes the whole page until someone clicks OK (2026-11-25).
  const [toast, setToast] = useState(null); // { text, kind }
  const toastTimer = useRef(null);
  // Set once the on-load group join has answered; until then "not in that group" may just mean "not yet".
  const joinSettled = useRef(false);
  // Only the newest calendar request may update the view (a slow older one used to overwrite it).
  const fetchSeq = useRef(0);
  function showToast(text, kind = "info") {
    clearTimeout(toastTimer.current);
    setToast({ text, kind });
    toastTimer.current = setTimeout(() => setToast(null), 7000);
  }
  // Booking a free slot (BookModal) and the booked meetings in view.
  const [bookSlot, setBookSlot] = useState(null);
  const [bookings, setBookings] = useState([]);
  const [planRefresh, setPlanRefresh] = useState(0);
  // Sidebar tab, remembered between visits.
  const [sideTab, setSideTab] = useState(() => localStorage.getItem("sideTab") || "groups");
  function pickSideTab(tab) {
    setSideTab(tab);
    localStorage.setItem("sideTab", tab);
  }

  // Viewing a group: its admin's settings apply to everyone (the server
  // enforces this too). Groups made before admins existed have none until
  // someone claims them, so your own settings apply there.
  const activeGroup = groups.find((g) => g.id === activeGroupId) || null;
  const settingsLocked = !!activeGroup && !activeGroup.is_admin && !activeGroup.claimable;
  const groupAdminName = activeGroup?.members.find((m) => m.admin)?.name;

  async function saveGroupSettings(next) {
    const groupId = activeGroup.id;
    setSettingsError("");
    setGroups((gs) => gs.map((g) => (g.id === groupId ? { ...g, settings: next } : g)));
    try {
      const res = await fetch(`${API_URL}/groups/settings?group_id=${groupId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(next),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Couldn't save the group's settings.");
      setGroups((gs) => gs.map((g) => (g.id === groupId ? { ...g, settings: data.settings } : g)));
    } catch (err) {
      setSettingsError(err.message);
      setGroupsRefresh((n) => n + 1);
    }
  }

  // Settings are a Pro feature (Sam, 2026-11-24): free accounts use the defaults (the server enforces
  // this too). Until the plan has loaded, assume Pro so nothing flickers.
  const canCustomize = !billing || !!billing.pro;

  function changeSettings(next) {
    if (!canCustomize) return;
    if (activeGroup?.is_admin) saveGroupSettings(next);
    else if (!settingsLocked) setSettings(next);
  }

  const effectiveSettings = activeGroup?.settings
    ? { ...settings, ...activeGroup.settings }
    : canCustomize ? settings : DEFAULT_SETTINGS;
  const timePrefsKey = effectiveSettings.timePrefs.join(",");

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
  // How many events the Notion sign-in just imported (read once: the address bar is cleaned below).
  const [notionImported] = useState(() => {
    const n = hashParams.get("notion");
    return n == null ? null : Number(n);
  });

  // The session token proves who's making a request - the backend never
  // trusts a plain user_id from a query param for that (anyone could type
  // in someone else's email and read/overwrite their schedule otherwise).
  function authHeaders() {
    const token = tokenFromUrl || getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  useEffect(() => {
    if (userId) {
      localStorage.setItem("userId", userId);
    }
  }, [userId]);

  useEffect(() => {
    if (tokenFromUrl) {
      saveToken(tokenFromUrl);
    }
    // Saved - now take the token out of the address bar so it isn't left in
    // history, bookmarks or a copied link.
    if (tokenFromUrl || authError || params.get("user")) {
      const clean = new URLSearchParams(window.location.search);
      clean.delete("token"); clean.delete("user");
      const q = clean.toString();
      window.history.replaceState(null, "", window.location.pathname + (q ? "?" + q : ""));
    }
    if (authError) showToast(authError, "error");
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
    const token = tokenFromUrl || getToken();


    if (!token || !joiningGroupId) {
      joinSettled.current = true;
      return;
    }


    fetch(
      `${API_URL}/groups/join?group_id=${joiningGroupId}`,
      { method: "POST", headers: authHeaders() }
    ).then(async (res) => {
      joinSettled.current = true;
      if (!res.ok) {
        // e.g. the group's admin removed you: say so and stay on your own calendar.
        const detail = (await res.json().catch(() => ({}))).detail;
        localStorage.removeItem("groupId");
        setActiveGroupId(null);
        showToast(detail || "Couldn't join that group.", "error");
        fetchAvailability(manualBusy).catch((err) => console.error(err));
        return;
      }
      // The mount-time availability fetch (below) can win the race and
      // complete before this join is processed server-side, showing only
      // your own calendar with no automatic retry - refetch once the
      // join has actually gone through so the group's merged data shows
      // up without needing to touch anything else first.
      fetchAvailability(manualBusy).catch((err) => console.error(err));
      setActiveGroupId(joiningGroupId);
      setGroupsRefresh((n) => n + 1);
    }).catch(() => { joinSettled.current = true; });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupIdFromLink, tokenFromUrl]);

  // Whether Google Calendar is actually linked - not just "signed in"
  // (an email/password account isn't connected to Google).
  const [googleConnected, setGoogleConnected] = useState(false);
  const [googleStatus, setGoogleStatus] = useState(null); // last sync time, auto-sync on/off

  function refreshGoogleStatus() {
    return fetch(`${API_URL}/auth/status`, { headers: authHeaders() })
      .then((res) => (res.ok ? res.json() : { connected: false }))
      .then((data) => { setGoogleConnected(!!data.connected); setGoogleStatus(data); return data; })
      .catch(() => { setGoogleConnected(false); return null; });
  }

  useEffect(() => {
    if (!email) return;
    refreshGoogleStatus().then((data) => {
      // Stale data with auto-sync on: the server is re-reading Google now; show the result when it lands.
      if (data?.auto_sync && (!data.synced_at || Date.now() / 1000 - data.synced_at > 3 * 3600)) {
        setTimeout(() => {
          refreshGoogleStatus();
          fetchAvailability(manualBusy).catch(() => {});
        }, 15000);
      }
    });
    refreshLinks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email]);

  // Apple Calendar and Notion connections.
  const [appleConnected, setAppleConnected] = useState(false);
  const [notionConnected, setNotionConnected] = useState(false);
  // Notion needs keys on the server; until they're set its buttons stay hidden.
  const [notionAvailable, setNotionAvailable] = useState(false);
  useEffect(() => {
    fetch(`${API_URL}/notion/available`)
      .then((res) => (res.ok ? res.json() : { available: false }))
      .then((data) => setNotionAvailable(!!data.available))
      .catch(() => setNotionAvailable(false));
  }, []);

  function refreshLinks() {
    for (const [path, set] of [["/apple/status", setAppleConnected], ["/notion/status", setNotionConnected]]) {
      fetch(`${API_URL}${path}`, { headers: authHeaders() })
        .then((res) => (res.ok ? res.json() : { connected: false }))
        .then((data) => set(!!data.connected))
        .catch(() => set(false));
    }
  }

  async function onLinksChanged() {
    refreshLinks();
    // Re-send the manual blocks: an empty list would delete them server-side.
    await fetchAvailability(manualBusy);
  }

  // 🔹 FREE TIMES
  const [freeTimes, setFreeTimes] = useState(() => {
    const saved = localStorage.getItem("freeTimes");
    return saved ? JSON.parse(saved) : [];
  });

  useEffect(() => {
    const token = tokenFromUrl || getToken();
    if (!token) {
      setEmail(null);
      return;
    }

    fetch(`${API_URL}/auth/me`, { headers: authHeaders() })
      .then(res => {
        if (res.status === 401 || res.status === 403) {
          // Signed out, deleted or banned by the owner: forget everything this browser kept for that
          // account (calendar copy, manual blocks, groups), or a new sign-up here would re-upload it.
          const remember = localStorage.getItem("rememberMe");
          localStorage.clear();
          if (remember !== null) localStorage.setItem("rememberMe", remember);
          setManualBusy([]);
          setBusyTimes([]);
          setFreeTimes([]);
        }
        if (!res.ok) throw new Error("Session invalid");
        return res.json();
      })
      .then(data => {
        setMyName(data.name || "");
        setHasCustomName(!!data.custom_name);
        setEmail(data.email);
        renewToken(); // keeps an active user signed in (see session.js)
      })
      .catch(() => {
        // An expired/invalid token shouldn't leave the app stuck showing
        // stale data behind the gate - drop it and fall back to signed out.
        clearToken();
        localStorage.removeItem("userId");
        setEmail(null);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshBilling() {
    try {
      const res = await fetch(`${API_URL}/billing/status`, { headers: authHeaders() });
      if (res.ok) setBilling(await res.json());
    } catch { /* keep the last known status */ }
  }

  useEffect(() => {
    if (!email) return;
    const q = new URLSearchParams(window.location.search);
    const result = q.get("billing"), sessionId = q.get("session_id");
    if (q.get("upgrade")) setUpgrade("Unlimited groups, your own settings and the Chrome extension.");
    if (result || q.get("upgrade")) {
      ["billing", "session_id", "upgrade"].forEach((k) => q.delete(k));
      const rest = q.toString();
      window.history.replaceState(null, "", window.location.pathname + (rest ? "?" + rest : ""));
    }
    (async () => {
      if (result === "success" && sessionId) {
        try {
          const res = await fetch(`${API_URL}/billing/confirm`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify({ session_id: sessionId }),
          });
          const data = await res.json().catch(() => ({}));
          setBillingNote(res.ok
            ? (data.trial ? "Welcome to TimeFrame Pro! Your free trial has started." : "Welcome to TimeFrame Pro!")
            : data.detail || "We couldn't confirm the payment. If you were charged, contact us.");
        } catch {
          setBillingNote("We couldn't confirm the payment yet. Refresh in a moment.");
        }
      } else if (result === "cancelled") {
        setBillingNote("Checkout cancelled. You haven't been charged.");
      }
      refreshBilling();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email]);

  async function openBillingPortal() {
    try {
      const res = await fetch(`${API_URL}/billing/portal`, { method: "POST", headers: authHeaders() });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Couldn't open billing.");
      showLoader();
      window.location.href = data.url;
    } catch (err) {
      setBillingNote(err.message);
    }
  }

  // The session check is done (signed in or not): fade the logo loading screen away.
  useEffect(() => {
    if (email !== undefined) hideLoader();
  }, [email]);

  const isPro = !!billing?.pro;
  const proLabel = !billing?.pro ? "" : billing.source === "coupon" ? "Coupon" : billing.trial ? "Free trial" : "";

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
  }, [effectiveSettings.dayStart, effectiveSettings.dayEnd, effectiveSettings.meetingLength,
      timePrefsKey, effectiveSettings.excludeWeekends, activeGroupId, viewMode, viewDate]);

  // Your saved manual blocks live on the server; load them once signed in
  // so every device shows (and keeps) the same list. Until that's done,
  // nothing auto-saves, so a stale or empty local copy can't overwrite them.
  const manualReady = useRef(false);
  const skipNextManualSave = useRef(false);

  useEffect(() => {
    if (!email) return;
    fetch(`${API_URL}/availability/manual`, { headers: authHeaders() })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("load failed"))))
      .then((data) => {
        skipNextManualSave.current = true; // just loaded - nothing new to save
        setManualBusy(data.blocks.map((b) => ({ start: toLocalInput(b.start), end: toLocalInput(b.end) })));
        manualReady.current = true;
      })
      .catch((err) => console.error(err));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email]);

  // 🔁 Persist everything
  useEffect(() => {
    localStorage.setItem("manualBusy", JSON.stringify(manualBusy));
    // Adding or removing a block saves it right away, so group members see it.
    if (!manualReady.current) return;
    if (skipNextManualSave.current) {
      skipNextManualSave.current = false;
      return;
    }
    fetchAvailability(manualBusy, { save: true }).catch((err) => console.error(err));
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // save: true replaces your saved manual blocks with extraBusy (adding,
  // removing, Find Free Time, Clear). Anything else is a plain refresh that
  // leaves them alone - so opening the app on a device with nothing stored
  // locally can never wipe them.
  async function fetchAvailability(extraBusy = [], { save = false } = {}) {
    const token = tokenFromUrl || getToken();
    if (!token) return;
    const seq = ++fetchSeq.current;
    const afterJoin = joinSettled.current;
    setFetching((n) => n + 1);
    try {

    const groupId = localStorage.getItem("groupId");
    const groupParam = groupId ? `&group=${groupId}` : "";

    const { startOffset, days } = getRequestRange(viewMode, viewDate);

    const url = `${API_URL}/availability/merge?min_minutes=${effectiveSettings.meetingLength}&day_start=${effectiveSettings.dayStart}&day_end=${effectiveSettings.dayEnd}&timezone=${encodeURIComponent(MY_TIMEZONE)}&days=${days}&start_offset=${startOffset}${groupParam}&prefer=${effectiveSettings.timePrefs.join(",")}${save ? "" : "&keep_manual=1"}`;

    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(extraBusy.length ? [extraBusy] : []),
    });

    if (!res.ok) {
      throw new Error("Failed to fetch availability");
    }

    const data = await res.json();
    if (seq !== fetchSeq.current) return; // a newer request (other week, other group) is on its way
    // Removed from the group, or it was deleted, since this browser last looked: back to your own calendar.
    if (groupId && data.in_group === false && afterJoin && localStorage.getItem("groupId") === groupId) {
      localStorage.removeItem("groupId");
      setActiveGroupId(null);
      setGroupsRefresh((n) => n + 1);
      showToast("You're no longer in that group, so you're back on your own calendar.", "error");
    }
    setBusyTimes(data.busy_times);
    setFreeTimes(data.ranked_free_time);
    setBookings(data.bookings || []);
    } finally {
      setFetching((n) => Math.max(0, n - 1));
    }
  }

  // 🧼 CLEAR EVERYTHING
  // Clears your manual busy blocks and leaves the current group view, then
  // reloads your own schedule. Keeps you signed in (it used to also delete
  // the session token while leaving the page looking signed in, so nothing
  // loaded afterwards); "Logout" is the separate button for that.
  function clearAll() {
    setManualBusy([]);
    localStorage.removeItem("groupId");
    setActiveGroupId(null);
    localStorage.removeItem("manualBusy");
    // An empty list also deletes the saved manual blocks on the server.
    fetchAvailability([], { save: true }).catch((err) => console.error(err));
  }
  function logout() {
    fetch(`${API_URL}/auth/logout`, {
      method: "POST",
      headers: authHeaders()
    }).catch(() => {}).finally(() => {
      // Sign out on this device even if the server is asleep or unreachable.
      localStorage.clear();
      clearToken();
      setEmail(null);
      setManualBusy([]);
      setBusyTimes([]);
      setFreeTimes([]);
      window.location.reload();
    });
  }

  function switchGroup(groupId) {
    if (groupId) localStorage.setItem("groupId", groupId);
    else localStorage.removeItem("groupId");
    setActiveGroupId(groupId); // the effect watching activeGroupId reloads the calendar
  }

  // Still verifying a returning session. Usually instant, but a sleeping
  // server can take most of a minute to wake, so say what's happening
  // instead of showing a blank page.
  // Still checking the session: the logo loading screen from index.html stays up (see loading.js).
  if (email === undefined) return null;

  // No valid session - the rest of the app (and the data it would show)
  // stays completely hidden until Google sign-in succeeds.
  const toastEl = toast && (
    <div className={`toast toast-${toast.kind}`} role={toast.kind === "error" ? "alert" : "status"}>
      <span>{toast.text}</span>
      <button type="button" className="icon-x" onClick={() => setToast(null)} aria-label="Dismiss">✕</button>
    </div>
  );

  if (email === null) {
    return (
      <div className="auth-shell">
        {toastEl}
        <aside className="auth-hero" aria-hidden="true">
          <div className="auth-logo auth-logo-light">
            <img src="/favicon.svg" alt="" />
            <span>TimeFrame</span>
          </div>
          <div className="hero-copy">
            <h2>Find a time that works for everyone.</h2>
          </div>
          {/* A small picture of the product: three people's week, with the best shared slot picked. */}
          <div className="hero-preview">
            <div className="hp-head">
              <span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span>
            </div>
            <div className="hp-grid">
              <i className="hp-b p0" style={{ gridColumn: 1, gridRow: "1 / 3" }} />
              <i className="hp-b p1" style={{ gridColumn: 1, gridRow: "4 / 6" }} />
              <i className="hp-b p2" style={{ gridColumn: 2, gridRow: "2 / 4" }} />
              <i className="hp-b p0" style={{ gridColumn: 2, gridRow: "5 / 7" }} />
              <i className="hp-b p1" style={{ gridColumn: 3, gridRow: "1 / 2" }} />
              <i className="hp-b p2" style={{ gridColumn: 3, gridRow: "3 / 5" }} />
              <i className="hp-best" style={{ gridColumn: 4, gridRow: "3 / 5" }}>
                <b>👑 Best time</b><small>2:00 – 3:00 PM</small>
              </i>
              <i className="hp-b p0" style={{ gridColumn: 4, gridRow: "1 / 2" }} />
              <i className="hp-b p2" style={{ gridColumn: 4, gridRow: "6 / 7" }} />
              <i className="hp-b p1" style={{ gridColumn: 5, gridRow: "2 / 4" }} />
              <i className="hp-b p0" style={{ gridColumn: 5, gridRow: "5 / 6" }} />
            </div>
            <div className="hp-people">
              <span className="hp-dot p0" /><span className="hp-dot p1" /><span className="hp-dot p2" />
              <em>3 calendars merged</em>
            </div>
          </div>
        </aside>

        <div className="auth-side">
        <main className="auth-panel">
          <div className="auth-logo auth-logo-mobile">
            <img src="/favicon.svg" alt="" />
            <span>TimeFrame</span>
          </div>
          <h1 className="auth-title">Welcome to TimeFrame</h1>
          <p className="auth-sub">Sign in or create an account to continue.</p>
          <SignInOptions
            notionAvailable={notionAvailable}
            onAuthenticated={(token, authedEmail) => {
              saveToken(token);
              localStorage.setItem("userId", authedEmail);
              // A full reload (not just setEmail) so the mount-time fetchAvailability effect actually runs,
              // the same thing a Google sign-in redirect does by reloading the page.
              window.location.reload();
            }}
          />
          <p className="auth-legal">
            By continuing, you agree to the <a href="/terms.html">Terms</a> and <a href="/privacy.html">Privacy Policy</a>.
          </p>
        </main>

        <footer className="auth-footer">
          <span>© {new Date().getFullYear()} TimeFrame</span>
          <nav>
            <a href="/privacy.html">Privacy</a>
            <a href="/terms.html">Terms</a>
            <a href="mailto:sam.esebor@gmail.com">Contact</a>
          </nav>
        </footer>
        </div>
      </div>
    );
  }

  const displayName = myName || email;
  const firstName = (myName || email.split("@")[0]).trim().split(/[\s._-]+/)[0];
  const hour = new Date().getHours();
  const greeting = `${hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening"}, ${firstName.charAt(0).toUpperCase() + firstName.slice(1)}`;

  return (
    <div className="dash">
      {toastEl}
      {fetching > 0 && <div className="top-progress" role="progressbar" aria-label="Loading"><span /></div>}
      <header className="dash-topbar">
        <div className="auth-logo dash-logo">
          <img src="/favicon.svg" alt="" />
          <span>TimeFrame</span>
        </div>
        <div className="dash-user">
          {editingName ? (
            <form className="user-chip name-form" onSubmit={saveName}>
              <input
                value={nameDraft}
                maxLength={40}
                autoFocus
                onFocus={(e) => e.target.select()}
                placeholder={email.split("@")[0]}
                aria-label="Your name"
                onChange={(e) => setNameDraft(e.target.value)}
              />
              <button type="submit" className="link-btn">Save</button>
              <button type="button" className="link-btn muted" onClick={() => { setEditingName(false); setNameError(""); }}>
                Cancel
              </button>
              {nameError && <span className="error-text">{nameError}</span>}
            </form>
          ) : (
            <button type="button" className="dash-user-btn" title={email} onClick={() => setMenuOpen((o) => !o)} aria-expanded={menuOpen}>
              <span className="dash-avatar">{(displayName || "?").trim().charAt(0).toUpperCase()}</span>
              <span className="dash-user-name">{displayName}</span>
              {isPro && <span className="pro-badge">PRO</span>}
              <span className="dash-caret" aria-hidden="true">▾</span>
            </button>
          )}
          {menuOpen && (
            <>
              <div className="dash-menu-backdrop" onClick={() => setMenuOpen(false)} />
              <div className="dash-menu" role="menu">
                <div className="dash-menu-head">
                  <strong>{displayName}</strong>
                  <span>{email}</span>
                </div>
                <button role="menuitem" onClick={() => { setMenuOpen(false); setNameDraft(hasCustomName ? myName : ""); setEditingName(true); }}>
                  Edit display name
                </button>
                {billing && (isPro ? (
                  <div className="dash-menu-plan">TimeFrame Pro{proLabel ? ` · ${proLabel}` : ""}</div>
                ) : (
                  <button role="menuitem" className="upgrade-item" onClick={() => { setMenuOpen(false); setUpgrade(null); setUpgrade(""); }}>
                    ✦ Upgrade to Pro
                  </button>
                ))}
                {billing?.can_manage && (
                  <button role="menuitem" onClick={() => { setMenuOpen(false); openBillingPortal(); }}>Manage billing</button>
                )}
                <button role="menuitem" onClick={() => { setMenuOpen(false); clearAll(); }}>Clear my schedule</button>
                <hr />
                <button role="menuitem" className="danger" onClick={() => { setMenuOpen(false); logout(); }}>Sign out</button>
              </div>
            </>
          )}
        </div>
      </header>

      {billingNote && (
        <div className="billing-note" role="status">
          <span>{billingNote}</span>
          <button className="link-btn" onClick={() => setBillingNote("")} aria-label="Dismiss">×</button>
        </div>
      )}
      {upgrade !== null && (
        <UpgradeModal
          status={billing}
          authHeaders={authHeaders}
          reason={upgrade || undefined}
          onClose={() => setUpgrade(null)}
          onUpgraded={refreshBilling}
        />
      )}

      {bookSlot && (
        <BookModal
          slot={bookSlot}
          group={activeGroup}
          meetingLength={effectiveSettings.meetingLength}
          authHeaders={authHeaders}
          notify={showToast}
          onClose={() => setBookSlot(null)}
          onBooked={() => { setPlanRefresh((n) => n + 1); fetchAvailability(manualBusy).catch(() => {}); }}
        />
      )}

      <div className="dash-body">
        <main className="dash-main">
          <div className="dash-toolbar">
            <div className="dash-range">
              <span className="dash-greeting">{greeting}{activeGroup ? ` · ${activeGroup.name || "Group"}` : ""}</span>
              <h1>{formatRangeLabel(viewMode, viewDate)}</h1>
            </div>
            <div className="dash-controls">
              <div className="seg">
                {["day", "week", "month"].map((m) => (
                  <button key={m} className={viewMode === m ? "active" : ""} onClick={() => setViewMode(m)}>
                    {m[0].toUpperCase() + m.slice(1)}
                  </button>
                ))}
              </div>
              <div className="dash-nav">
                <button className="icon-btn" onClick={goToPrevious} aria-label="Previous">‹</button>
                <button className="today-btn" onClick={goToToday}>Today</button>
                <button className="icon-btn" onClick={goToNext} aria-label="Next">›</button>
              </div>
              <button
                className={`icon-btn ${settingsOpen ? "on" : ""}`}
                onClick={() => (canCustomize ? setSettingsOpen(!settingsOpen) : setUpgrade("Settings are part of TimeFrame Pro."))}
                aria-label="Settings"
                title="Settings"
              >
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                  <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="1.8" />
                  <path fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1" />
                </svg>
              </button>
            </div>
          </div>

          {settingsOpen && canCustomize && (
            <SettingsPanel
              settings={effectiveSettings}
              setSettings={changeSettings}
              readOnly={settingsLocked}
              error={settingsError}
              note={
                !activeGroup
                  ? null
                  : activeGroup.is_admin
                    ? `You're the admin of ${activeGroup.name || "this group"}: these settings apply to everyone in it.`
                    : activeGroup.claimable
                      ? "This group has no admin yet, so your own settings apply. Claim admin in My groups to set them for everyone."
                      : `Set by the group's admin${groupAdminName ? ` (${groupAdminName})` : ""}. Only they can change these.`
              }
            />
          )}

          {viewMode === "month" ? (
            <MonthView
              viewDate={viewDate}
              busyTimes={busyTimes}
              freeTimes={freeTimes}
              excludeWeekends={effectiveSettings.excludeWeekends}
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
              excludeWeekends={effectiveSettings.excludeWeekends}
              dayStartHour={parseInt(effectiveSettings.dayStart.split(":")[0], 10)}
              dayEndHour={parseInt(effectiveSettings.dayEnd.split(":")[0], 10)}
              timezone={MY_TIMEZONE}
              currentUserId={localStorage.getItem("userId")}
              bookings={bookings}
              onPickSlot={setBookSlot}
            />
          )}
        </main>

        <aside className="dash-side">
          <div className="side-tabs" role="tablist" aria-label="Sidebar">
            {[
              ["plan", "Plan", bookings.length || null],
              ["groups", "Groups", groups.length || null],
              ["calendars", "Calendars", [googleConnected, appleConnected, notionConnected].filter(Boolean).length || null],
              ["busy", "Busy times", manualBusy.length || null],
            ].map(([key, label, count]) => (
              <button
                key={key}
                role="tab"
                aria-selected={sideTab === key}
                className={sideTab === key ? "active" : ""}
                onClick={() => pickSideTab(key)}
              >
                {label}
                {count != null && <span className="side-count">{count}</span>}
              </button>
            ))}
          </div>

          <section className="side-section" hidden={sideTab !== "plan"}>
            <PlanPanel
              authHeaders={authHeaders}
              group={activeGroup}
              freeTimes={freeTimes}
              refreshKey={planRefresh}
              onBook={setBookSlot}
              onChanged={() => fetchAvailability(manualBusy).catch(() => {})}
              notify={showToast}
            />
          </section>

          <section className="side-section" hidden={sideTab !== "groups"}>
            <GroupsPanel
              authHeaders={authHeaders}
              activeGroupId={activeGroupId}
              onSwitch={switchGroup}
              refreshKey={groupsRefresh}
              groups={groups}
              setGroups={setGroups}
              personalSettings={settings}
              isPro={billing ? isPro : true}
              onNeedPro={() => setUpgrade("Free accounts can create 1 group. Pro gives you as many as you want.")}
            />
          </section>

          <section className="side-section" hidden={sideTab !== "calendars"}>
            <GoogleConnect
              connected={googleConnected}
              status={googleStatus}
              authHeaders={authHeaders}
              notify={showToast}
              onChanged={() => { setGoogleConnected(false); setGoogleStatus(null); onLinksChanged(); }}
              onSynced={() => { refreshGoogleStatus(); fetchAvailability(manualBusy).catch(() => {}); }}
            />
            <AppleConnect connected={appleConnected} onChanged={onLinksChanged} />
            {(notionAvailable || notionConnected) && (
              <NotionConnect signedIn connected={notionConnected} imported={notionImported} onChanged={onLinksChanged} />
            )}
            {/* Re-send the manual blocks: an empty list would delete them server-side. */}
            <ImportIcs onImported={() => fetchAvailability(manualBusy)} />
          </section>

          {/* Mounted only while open: the time wheels scroll to their value on mount, which fails while hidden. */}
          {sideTab === "busy" && (
            <section className="side-section">
              <AvailabilityForm
                manualBusy={manualBusy}
                setManualBusy={setManualBusy}
              />
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
