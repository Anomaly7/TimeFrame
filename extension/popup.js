// TimeFrame toolbar popup: the best free times this week for you or one of your groups.
// Read-only apart from renewing its own sign-in; everything else happens on the website.

const API = "https://calender-app-mm4q.onrender.com";
const SITE = "https://www.timeframecalender.com";
const RENEW_AFTER_MS = 6 * 60 * 60 * 1000;
const DEFAULTS = { dayStart: "08:00", dayEnd: "22:00", meetingLength: 30, timePrefs: ["afternoon", "morning", "evening"] };
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

const $ = (id) => document.getElementById(id);
const store = {
  get: (keys) => new Promise((r) => chrome.storage.local.get(keys, r)),
  set: (obj) => new Promise((r) => chrome.storage.local.set(obj, r)),
  remove: (keys) => new Promise((r) => chrome.storage.local.remove(keys, r)),
};

let state = { token: null, groups: [], groupId: "", personal: DEFAULTS, week: 0, userId: "" };

function openSite(path = "/") {
  chrome.tabs.create({ url: SITE + path });
  window.close();
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    ...options,
    headers: { Authorization: `Bearer ${state.token}`, "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (res.status === 401) {
    await store.remove(["token", "renewedAt"]);
    showSignedOut();
    throw new Error("signed out");
  }
  if (!res.ok) throw new Error(`TimeFrame answered ${res.status}`);
  return res.json();
}

// Same "Keep me signed in" behaviour as the site: renew the sign-in while it's being used.
async function renew(saved) {
  if (Date.now() - (saved.renewedAt || 0) < RENEW_AFTER_MS) return;
  try {
    const data = await api(`/auth/refresh?remember=${saved.remember !== false}`, { method: "POST" });
    state.token = data.token;
    await store.set({ token: data.token, renewedAt: Date.now() });
  } catch { /* keep the current token; try again next time */ }
}

function showSignedOut() {
  state.token = null;
  $("signed-in").hidden = true;
  $("signed-out").hidden = false;
}

function settingsFor(groupId) {
  const g = state.groups.find((x) => x.id === groupId);
  // A group's admin sets its hours for everyone; otherwise your own settings apply.
  const s = g && !g.claimable && g.settings ? g.settings : state.personal;
  return { ...DEFAULTS, ...s };
}

function fmtDay(iso) {
  return new Date(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}
function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

const DAY_MS = 86400000;
const PERSON_COLORS = ["#2f6fda", "#c2660d", "#7c3aed", "#c2266d", "#0f8a82", "#b45309"];
const hhmm = (str) => { const [h, m] = String(str).split(":").map(Number); return h * 60 + (m || 0); };

// One week as a small calendar: busy blocks (coloured by person) and the top 3 free slots in green
// (best one crowned). Tap a green slot to see it below and copy it.
async function loadSlots() {
  const s = settingsFor(state.groupId);
  const group = state.groupId ? `&group=${encodeURIComponent(state.groupId)}` : "";
  const q = `min_minutes=${s.meetingLength}&day_start=${s.dayStart}&day_end=${s.dayEnd}&timezone=${encodeURIComponent(TZ)}` +
    `&days=7&start_offset=${state.week * 7}${group}&prefer=${(s.timePrefs || DEFAULTS.timePrefs).join(",")}&keep_manual=1`;
  $("status").textContent = "Finding times…";
  $("prev-week").disabled = state.week <= 0;
  try {
    const data = await api(`/availability/merge?${q}`, { method: "POST", body: "[]" });
    const now = Date.now();
    const free = (data.ranked_free_time || []).filter((f) => new Date(f.end).getTime() > now).slice(0, 3);
    renderCalendar(data.busy_times || [], free, s);
    $("status").textContent = free.length ? "" : "No shared free time this week.";
  } catch (err) {
    if (err.message !== "signed out") $("status").textContent = "Couldn't load times. The server may be waking up; try again in a moment.";
  }
}

function renderCalendar(busy, free, s) {
  const start = new Date(); start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() + state.week * 7);
  const days = [...Array(7)].map((_, i) => { const d = new Date(start); d.setDate(d.getDate() + i); return d; });
  const short = (d) => d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  $("week-label").textContent = state.week === 0 ? "Next 7 days" : `${short(days[0])} – ${short(days[6])}`;

  const dayStart = hhmm(s.dayStart);
  let dayEnd = hhmm(s.dayEnd);
  if (dayEnd <= dayStart) dayEnd = dayStart + 60;
  const span = dayEnd - dayStart;
  const owners = [...new Set(busy.map((b) => b.owner || ""))]
    .sort((x, y) => (x === state.userId ? -1 : y === state.userId ? 1 : x.localeCompare(y)));
  const colorOf = (o) => PERSON_COLORS[Math.max(0, owners.indexOf(o || "")) % PERSON_COLORS.length];

  const cal = $("cal");
  cal.replaceChildren();

  // Hour labels down the left, every 2 hours.
  const hours = document.createElement("div");
  hours.className = "cal-hours";
  const spacer = document.createElement("div");
  spacer.className = "cal-head";
  const hb = document.createElement("div");
  hb.className = "cal-hours-body";
  for (let m = Math.ceil(dayStart / 120) * 120; m < dayEnd; m += 120) {
    const l = document.createElement("span");
    l.style.top = `${((m - dayStart) / span) * 100}%`;
    const h = m / 60;
    l.textContent = `${h % 12 || 12}${h < 12 ? "a" : "p"}`;
    hb.append(l);
  }
  hours.append(spacer, hb);
  cal.append(hours);

  // Where [startIso, endIso) falls in one day's visible window, as top/height percentages.
  const place = (startIso, endIso, day) => {
    const lo = day.getTime() + dayStart * 60000, hi = day.getTime() + dayEnd * 60000;
    const a = Math.max(new Date(startIso).getTime(), lo), b = Math.min(new Date(endIso).getTime(), hi);
    if (b <= a) return null;
    return { top: ((a - lo) / 60000 / span) * 100, height: ((b - a) / 60000 / span) * 100 };
  };

  const todayKey = new Date().toDateString();
  days.forEach((day) => {
    const col = document.createElement("div");
    col.className = "cal-day" + (day.toDateString() === todayKey ? " today" : "");
    const head = document.createElement("div");
    head.className = "cal-head";
    const wd = document.createElement("span");
    wd.textContent = day.toLocaleDateString(undefined, { weekday: "narrow" });
    const dn = document.createElement("b");
    dn.textContent = day.getDate();
    head.append(wd, dn);
    const track = document.createElement("div");
    track.className = "cal-track";
    // Grid lines every 2 hours, lined up with the labels on the left (track is 250 px tall).
    const firstLine = Math.ceil(dayStart / 120) * 120;
    track.style.backgroundSize = `100% ${(120 / span) * 250}px`;
    track.style.backgroundPosition = `0 ${((firstLine - dayStart) / span) * 250}px`;
    for (const b of busy) {
      const pos = place(b.start, b.end, day);
      if (!pos) continue;
      const el = document.createElement("i");
      el.className = "cal-busy";
      el.style.top = pos.top + "%";
      el.style.height = Math.max(pos.height, 1.5) + "%";
      el.style.setProperty("--c", colorOf(b.owner));
      el.title = `${b.owner && b.owner !== state.userId ? b.owner_name || "Busy" : "You"}: ${fmtTime(b.start)} – ${fmtTime(b.end)}`;
      track.append(el);
    }
    free.forEach((f, i) => {
      const pos = place(f.start, f.end, day);
      if (!pos) return;
      const el = document.createElement("button");
      el.className = "cal-free" + (i === 0 ? " best" : "");
      el.dataset.rank = i;
      el.style.top = pos.top + "%";
      el.style.height = Math.max(pos.height, 5) + "%";
      el.title = `${i === 0 ? "Best time" : "Free"}: ${fmtDay(f.start)}, ${fmtTime(f.start)} – ${fmtTime(f.end)}`;
      if (i === 0) el.textContent = "👑";
      el.onclick = () => pick(f, i);
      track.append(el);
    });
    col.append(head, track);
    cal.append(col);
  });

  // Legend: who's who, plus free.
  const legend = $("legend");
  legend.replaceChildren();
  owners.forEach((o) => {
    const b = busy.find((x) => (x.owner || "") === o);
    const item = document.createElement("span");
    const dot = document.createElement("i");
    dot.style.background = colorOf(o);
    item.append(dot, document.createTextNode(!o || o === state.userId ? "You" : (b && b.owner_name) || o.split("@")[0]));
    legend.append(item);
  });
  const fr = document.createElement("span");
  const fdot = document.createElement("i");
  fdot.className = "free";
  fr.append(fdot, document.createTextNode("Free"));
  legend.append(fr);

  if (free.length) pick(free[0], 0); else $("pick").hidden = true;
}

function pick(f, i) {
  const text = `${fmtDay(f.start)}, ${fmtTime(f.start)} – ${fmtTime(f.end)}`;
  $("pick").hidden = false;
  $("pick").classList.toggle("best", i === 0);
  $("pick-badge").textContent = i === 0 ? "👑 Best time" : `Option ${i + 1}`;
  $("pick-when").textContent = text;
  $("pick-copy").textContent = "Copy";
  $("pick-copy").onclick = async () => {
    await navigator.clipboard.writeText(text);
    $("pick-copy").textContent = "Copied";
    setTimeout(() => ($("pick-copy").textContent = "Copy"), 1500);
  };
  document.querySelectorAll(".cal-free").forEach((el) => el.classList.toggle("selected", Number(el.dataset.rank) === i));
}

function fillGroups() {
  const sel = $("group");
  sel.replaceChildren();
  const mine = new Option("Just me", "");
  sel.append(mine);
  for (const g of state.groups) sel.append(new Option(`${g.name || "Group"} (${g.members.length})`, g.id));
  sel.value = state.groups.some((g) => g.id === state.groupId) ? state.groupId : "";
  state.groupId = sel.value;
  $("copy-link").hidden = !state.groupId;
}

async function init() {
  $("open").onclick = () => openSite("/");
  $("signin").onclick = () => openSite("/");
  $("signout").onclick = async () => {
    await store.remove(["token", "renewedAt", "userId"]);
    showSignedOut();
  };
  $("copy-link").onclick = async () => {
    await navigator.clipboard.writeText(`${SITE}/?group=${state.groupId}`);
    $("copy-link").textContent = "Copied!";
    setTimeout(() => ($("copy-link").textContent = "Copy group link"), 1500);
  };
  $("prev-week").onclick = () => { if (state.week > 0) { state.week--; loadSlots(); } };
  $("next-week").onclick = () => { if (state.week < 8) { state.week++; loadSlots(); } };
  $("group").onchange = async (e) => {
    state.groupId = e.target.value;
    $("copy-link").hidden = !state.groupId;
    await store.set({ groupId: state.groupId });
    loadSlots();
  };

  // Sign in right here (2026-11-20): Google through the background worker, or email + password.
  $("google").onclick = () => {
    $("signin-error").textContent = "";
    $("google").disabled = true;
    // The popup may close when Google's window opens; the background worker finishes and saves the sign-in.
    chrome.runtime.sendMessage({ type: "google-signin", remember: $("remember").checked }, (r) => {
      $("google").disabled = false;
      if (chrome.runtime.lastError) return;
      if (r?.ok) start(); else $("signin-error").textContent = r?.error || "Google sign-in didn't finish.";
    });
  };
  $("email-form").onsubmit = async (e) => {
    e.preventDefault();
    $("signin-error").textContent = "";
    $("email-submit").disabled = true;
    try {
      const res = await fetch(`${API}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: $("email").value.trim(), password: $("password").value }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Couldn't sign in.");
      $("password").value = "";
      await store.set({ token: data.token, userId: data.email || "", renewedAt: 0, remember: $("remember").checked });
      start();
    } catch (err) {
      $("signin-error").textContent = err.message === "Failed to fetch" ? "Couldn't reach TimeFrame. Try again in a moment." : err.message;
    } finally {
      $("email-submit").disabled = false;
    }
  };
  // Signed in from the background worker (or the website) while the popup is open.
  chrome.storage.onChanged.addListener((changes) => {
    if (changes.token?.newValue && !state.token) start();
  });

  await start();
}

// One load at a time: sign-in, storage changes and the popup opening can all ask for it.
let starting = null;
function start() {
  if (!starting) starting = doStart().finally(() => { starting = null; });
  return starting;
}

async function doStart() {
  const saved = await store.get(["token", "renewedAt", "remember", "groupId", "settings", "userId"]);
  if (!saved.token) return showSignedOut();
  $("signed-out").hidden = true;
  state.token = saved.token;
  state.groupId = saved.groupId || "";
  state.userId = saved.userId || "";
  try { state.personal = { ...DEFAULTS, ...JSON.parse(saved.settings || "{}") }; } catch { /* defaults */ }
  $("signed-in").hidden = false;

  await renew(saved);
  try {
    const [me, groups] = await Promise.all([api("/auth/me"), api("/groups")]);
    $("who").textContent = `Signed in as ${me.name || me.email}`;
    state.userId = me.email || state.userId;
    state.groups = groups.groups || [];
  } catch (err) {
    if (err.message === "signed out") return;
  }
  fillGroups();
  loadSlots();
}

init();
