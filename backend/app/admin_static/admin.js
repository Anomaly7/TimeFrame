// TimeFrame owner admin page. Talks only to this same server; the session lives in an HttpOnly cookie.
// Everything shown is built with textContent (never innerHTML), so an odd email or name can't run code here.
"use strict";

const $ = (id) => document.getElementById(id);
let page = 0;

async function api(path, body) {
  const opts = { method: body ? "POST" : "GET", credentials: "same-origin", headers: { "X-TF-Admin": "1" } };
  if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch("/admin/api/" + path, opts);
  let data = {};
  try { data = await r.json(); } catch { /* empty */ }
  if (r.status === 401) { showLogin(data.detail || ""); throw new Error("signed out"); }
  if (!r.ok) throw new Error(data.detail || "Something went wrong (" + r.status + ").");
  return data;
}

function el(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const kid of kids) if (kid != null) e.append(kid);
  return e;
}
const date = (t) => (t ? new Date(t * 1000).toLocaleDateString("en-CA", { year: "numeric", month: "short", day: "numeric" }) : "before Nov 20");
const when = (t) => new Date(t * 1000).toLocaleString("en-CA", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
function msg(id, text, kind) { const m = $(id); m.textContent = text; m.className = "msg " + (kind || ""); }

// ---- sign in ----
function showLogin(text) {
  $("app").hidden = true; $("login").hidden = false;
  msg("loginMsg", text && text !== "Signed out. Sign in again." ? text : "", "err");
  $("pw").focus();
}
$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("loginBtn").disabled = true; msg("loginMsg", "Checking…");
  try {
    await api("login", { password: $("pw").value, code: $("code") ? $("code").value : "" });
    $("pw").value = ""; if ($("code")) $("code").value = ""; msg("loginMsg", "");
    start();
  } catch (err) {
    if (err.message !== "signed out") msg("loginMsg", err.message, "err");
    if ($("code")) $("code").value = "";
  } finally { $("loginBtn").disabled = false; }
});
$("logout").addEventListener("click", async () => { try { await api("logout", {}); } catch { /* fine */ } showLogin(""); });

// ---- overview + health ----
async function loadOverview() {
  const d = await api("overview");
  $("you").textContent = "signed in from " + d.you;
  const pro = d.pro || {}, proTotal = Object.values(pro).reduce((a, b) => a + b, 0);
  const proBits = Object.entries(pro).map(([k, v]) => v + " " + ({ stripe: "paying/trial", coupon: "coupon", manual: "given by you", early: "early" }[k] || k)).join(" · ");
  const stats = [
    [d.users, "accounts"], [d.new7, "new in 7 days"], [d.new30, "new in 30 days"],
    [proTotal, "Pro" + (proBits ? " (" + proBits + ")" : "")], [d.groups, "groups created"], [d.members, "group memberships"],
  ];
  $("stats").replaceChildren(...stats.map(([n, label]) => el("div", { class: "stat" }, el("b", { text: String(n) }), el("span", { text: label }))));
  const cals = Object.entries(d.calendars || {}).map(([k, v]) => v + " " + k).join(" · ");
  $("cals").textContent = (cals ? "Calendars connected: " + cals + ". " : "") +
    (d.unknownJoin ? d.unknownJoin + (d.unknownJoin === 1 ? " account is" : " accounts are") + " from before join dates were recorded (Nov 20, 2026)." : "");
  const h = d.health;
  const items = [
    [h.database ? "ok" : "bad", "Database " + (h.database ? "up" : "DOWN")],
    [h.stripe === "live" ? "ok" : "warn", "Stripe: " + (h.stripe === "live" ? "live" : h.stripe === "test" ? "TEST mode" : "not set up")],
    ["ok", "Prices " + h.prices.month + "/mo, " + h.prices.year + "/yr " + h.currency + ", " + h.trialDays + "-day trial"],
    [h.tax ? "ok" : "warn", "Sales tax " + (h.tax ? "added on top at checkout" : "not charged yet (turn on after GST/HST registration)")],
    ["ok", "Coupon " + (h.coupon ? "set" : "not set")],
    [h.alerts ? "ok" : "bad", "Phone alerts " + (h.alerts ? "on" : "OFF: set OWNER_NTFY_TOPIC")],
    ["ok", "Server up since " + when(h.upSince)],
  ];
  $("health").replaceChildren(...items.map(([cls, text]) => el("li", { class: cls, text })));
}

// ---- accounts ----
async function loadUsers() {
  const d = await api("users?page=" + page + "&q=" + encodeURIComponent($("q").value));
  const rows = d.users.map((u) => {
    const how = [u.password ? "email + password" : null, u.googleVerified ? "Google" : null].filter(Boolean).join(", ") || "calendar sign-in";
    const plan = u.plan === "pro"
      ? el("span", { class: "pill pro", text: "Pro · " + ({ stripe: "Stripe", coupon: "coupon", manual: "given by you", early: "early" }[u.source] || u.source) })
      : el("span", { class: "pill", text: "Free" });
    const until = u.plan === "pro" && u.source === "stripe" && u.proUntil ? el("div", { class: "sub", text: "paid through " + date(u.proUntil) }) : null;
    const act = (action, label, cls, confirmText) => el("button", {
      type: "button", class: "small " + (cls || "ghost"), text: label,
      onclick: async (ev) => {
        if (confirmText && !window.confirm(confirmText)) return;
        ev.target.disabled = true;
        try { const r = await api("users/pro", { id: u.id, action }); msg("actMsg", r.message, "ok"); await loadUsers(); loadAudit(); }
        catch (err) { if (err.message !== "signed out") msg("actMsg", err.message, "err"); ev.target.disabled = false; }
      },
    });
    const actions = el("td", { class: "actions" },
      u.plan !== "pro" ? act("grant", "Give Pro", "ghost", "Give " + u.email + " Pro for free?") : null,
      u.plan === "pro" && u.source !== "stripe" ? act("revoke", "Remove Pro", "danger", "Put " + u.email + " back on Free?") : null,
      u.hasSub ? act("recheck", "Re-check Stripe") : null);
    return el("tr", {},
      el("td", {}, el("div", { text: u.email }), u.name ? el("div", { class: "sub", text: u.name }) : null),
      el("td", { text: date(u.joined) }),
      el("td", {}, el("div", { text: how }), u.calendars.length ? el("div", { class: "sub", text: u.calendars.join(", ") }) : null),
      el("td", { text: u.groups + (u.owns ? " (" + u.owns + " own)" : "") }),
      el("td", {}, plan, until),
      actions);
  });
  if (!rows.length) rows.push(el("tr", {}, el("td", { colspan: "6", class: "dim", text: "No accounts match." })));
  $("users").replaceChildren(...rows);
  $("prev").disabled = page === 0; $("next").disabled = !d.more;
}
$("searchForm").addEventListener("submit", (e) => { e.preventDefault(); page = 0; loadUsers().catch(show); });
$("prev").addEventListener("click", () => { page = Math.max(0, page - 1); loadUsers().catch(show); });
$("next").addEventListener("click", () => { page += 1; loadUsers().catch(show); });

// ---- audit ----
async function loadAudit() {
  const d = await api("audit");
  const label = { login: "Signed in", login_failed: "Wrong sign-in", grant_pro: "Gave Pro", revoke_pro: "Removed Pro", recheck_stripe: "Re-checked Stripe" };
  $("audit").replaceChildren(...d.events.map((e) => el("li", { class: e.action === "login_failed" ? "bad" : "" },
    when(e.at) + " · " + (label[e.action] || e.action) + " · " + e.ip + (e.detail && e.action !== "login" ? " · " + e.detail : ""))));
}

// ---- task bar: one section at a time (remembered in the address, e.g. /admin#accounts) ----
const TABS = ["overview", "accounts", "health", "activity"];
function openTab(name) {
  if (!TABS.includes(name)) name = "overview";
  for (const b of document.querySelectorAll("#tabs button")) b.setAttribute("aria-selected", String(b.dataset.tab === name));
  for (const p of document.querySelectorAll("[data-panel]")) p.hidden = p.dataset.panel !== name;
  if (location.hash.slice(1) !== name) history.replaceState(null, "", "#" + name);
}
$("tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) openTab(b.dataset.tab); });
window.addEventListener("hashchange", () => openTab(location.hash.slice(1)));
openTab(location.hash.slice(1));

function show(err) { if (err.message !== "signed out") msg("actMsg", err.message, "err"); }
async function start() {
  try {
    await loadOverview();
  } catch (err) {
    if (err.message === "signed out") return;
    msg("actMsg", "Overview didn't load: " + err.message, "err"); // never leave a blank page
  }
  $("login").hidden = true; $("app").hidden = false;
  await Promise.all([loadUsers().catch(show), loadAudit().catch(show)]);
}
start();
