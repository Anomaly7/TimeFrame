import { API_URL } from "./config";

// Where the sign-in lives. "Remember me" on (the default): localStorage, renewed on every
// visit so active users stay signed in. Off: sessionStorage, which the browser forgets when
// it closes, and the server gives that token only 12 hours.

const KEY = "authToken";
const PREF = "rememberMe";
const RENEW_AFTER_MS = 6 * 60 * 60 * 1000; // renew at most every 6 hours

export function rememberMe() {
  return localStorage.getItem(PREF) !== "0";
}

export function setRememberMe(on) {
  localStorage.setItem(PREF, on ? "1" : "0");
}

export function getToken() {
  return sessionStorage.getItem(KEY) || localStorage.getItem(KEY);
}

// Tokens straight from a sign-in are swapped for one with the right lifetime on the next
// renewToken() call; only tokens from /auth/refresh count as freshly renewed.
export function saveToken(token, { renewed = false } = {}) {
  if (rememberMe()) {
    localStorage.setItem(KEY, token);
    sessionStorage.removeItem(KEY);
  } else {
    sessionStorage.setItem(KEY, token);
    localStorage.removeItem(KEY);
  }
  if (renewed) localStorage.setItem("authRenewedAt", String(Date.now()));
  else localStorage.removeItem("authRenewedAt");
}

export function clearToken() {
  localStorage.removeItem(KEY);
  sessionStorage.removeItem(KEY);
  localStorage.removeItem("authRenewedAt");
}

// Swap the current token for a fresh one (90 days with Remember me, 12 hours without).
export async function renewToken({ force = false } = {}) {
  const token = getToken();
  if (!token) return;
  const last = Number(localStorage.getItem("authRenewedAt") || 0);
  if (!force && Date.now() - last < RENEW_AFTER_MS) return;
  try {
    const res = await fetch(`${API_URL}/auth/refresh?remember=${rememberMe()}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) saveToken((await res.json()).token, { renewed: true });
  } catch {
    // Offline or the API is waking up: keep the current token and try again next visit.
  }
}
