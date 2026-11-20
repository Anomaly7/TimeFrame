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

let state = { token: null, groups: [], groupId: "", personal: DEFAULTS };

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

async function loadSlots() {
  const s = settingsFor(state.groupId);
  const group = state.groupId ? `&group=${encodeURIComponent(state.groupId)}` : "";
  const q = `min_minutes=${s.meetingLength}&day_start=${s.dayStart}&day_end=${s.dayEnd}&timezone=${encodeURIComponent(TZ)}` +
    `&days=7&start_offset=0${group}&prefer=${(s.timePrefs || DEFAULTS.timePrefs).join(",")}&keep_manual=1`;
  $("status").textContent = "Finding times…";
  const list = $("slots");
  try {
    const data = await api(`/availability/merge?${q}`, { method: "POST", body: "[]" });
    const now = Date.now();
    const slots = (data.ranked_free_time || []).filter((f) => new Date(f.end).getTime() > now).slice(0, 5);
    list.replaceChildren();
    if (!slots.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = "No shared free time this week.";
      list.append(li);
    }
    slots.forEach((f, i) => {
      const li = document.createElement("li");
      li.className = "slot" + (i === 0 ? " best" : "");
      const when = document.createElement("div");
      when.className = "when";
      const day = document.createElement("div");
      day.className = "day";
      day.textContent = fmtDay(f.start);
      const time = document.createElement("div");
      time.className = "time";
      time.textContent = `${fmtTime(f.start)} – ${fmtTime(f.end)}`;
      when.append(day, time);
      if (i === 0) {
        const badge = document.createElement("div");
        badge.className = "badge";
        badge.textContent = "👑 Best";
        when.prepend(badge);
      }
      const copy = document.createElement("button");
      copy.className = "ghost copy";
      copy.textContent = "Copy";
      copy.title = "Copy this time to paste in a message";
      copy.onclick = async () => {
        await navigator.clipboard.writeText(`${fmtDay(f.start)}, ${fmtTime(f.start)} – ${fmtTime(f.end)}`);
        copy.textContent = "Copied";
        setTimeout(() => (copy.textContent = "Copy"), 1500);
      };
      li.append(when, copy);
      list.append(li);
    });
    $("status").textContent = "";
  } catch (err) {
    if (err.message !== "signed out") $("status").textContent = "Couldn't load times. The server may be waking up; try again in a moment.";
  }
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
  $("group").onchange = async (e) => {
    state.groupId = e.target.value;
    $("copy-link").hidden = !state.groupId;
    await store.set({ groupId: state.groupId });
    loadSlots();
  };

  const saved = await store.get(["token", "renewedAt", "remember", "groupId", "settings"]);
  if (!saved.token) return showSignedOut();
  state.token = saved.token;
  state.groupId = saved.groupId || "";
  try { state.personal = { ...DEFAULTS, ...JSON.parse(saved.settings || "{}") }; } catch { /* defaults */ }
  $("signed-in").hidden = false;

  await renew(saved);
  try {
    const [me, groups] = await Promise.all([api("/auth/me"), api("/groups")]);
    $("who").textContent = `Signed in as ${me.name || me.email}`;
    state.groups = groups.groups || [];
  } catch (err) {
    if (err.message === "signed out") return;
  }
  fillGroups();
  loadSlots();
}

init();
