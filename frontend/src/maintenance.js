// Maintenance mode (2026-11-25): the owner can switch TimeFrame off from the admin page.
// The site asks the API's /status when it opens, and also notices if any API call comes back
// "down for maintenance" while someone is already using it. Either way it shows the maintenance screen.
import { API_URL } from "./config";

const EVENT = "tf-maintenance";

// Is TimeFrame in maintenance? Returns the status, or null if the API couldn't be reached
// (then the app opens as usual and handles that itself).
export async function fetchStatus(timeoutMs = 5000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await nativeFetch(`${API_URL}/status`, { signal: ctl.signal, cache: "no-store" });
    if (!res.ok && res.status !== 503) return null;
    return await res.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export function onMaintenance(handler) {
  const listener = (e) => handler(e.detail);
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}

// Watch every call to the API: a 503 that says "maintenance" switches the whole site to the maintenance screen.
const nativeFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const res = await nativeFetch(input, init);
  const url = typeof input === "string" ? input : input?.url || "";
  if (res.status === 503 && url.startsWith(API_URL)) {
    res.clone().json().then((body) => {
      if (body?.maintenance) window.dispatchEvent(new CustomEvent(EVENT, { detail: body }));
    }).catch(() => {});
  }
  return res;
};
