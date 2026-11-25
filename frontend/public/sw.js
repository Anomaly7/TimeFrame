// TimeFrame service worker (2026-11-25): installable app with an offline copy, plus push notifications.
// The app's own last calendar view lives in localStorage, so with this cache it opens (read-only) with no network.
/* eslint-disable no-restricted-globals */

const VERSION = "tf-v1";
const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/favicon.svg", "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function put(request, response) {
  if (response && (response.ok || response.type === "opaque")) {
    const copy = response.clone();
    caches.open(VERSION).then((c) => c.put(request, copy)).catch(() => {});
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Pages (the app, booking pages): network first, the cached app when offline.
  if (req.mode === "navigate" && url.origin === self.location.origin) {
    if (url.pathname.startsWith("/admin")) return; // never cache the owner's admin page
    event.respondWith(
      fetch(req)
        .then((res) => (url.pathname === "/" ? put("/", res) : res))
        .catch(() => caches.match("/").then((r) => r || caches.match("/index.html")))
    );
    return;
  }

  // Built files have a content hash in the name: cache first, they never change.
  if (url.origin === self.location.origin && url.pathname.startsWith("/assets/")) {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => put(req, res))));
    return;
  }

  // Fonts: cache first.
  if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => put(req, res))));
    return;
  }

  // Other files on this site (icons, privacy page): fresh when online, cached when not.
  if (url.origin === self.location.origin && !url.pathname.endsWith("sw.js")) {
    event.respondWith(fetch(req).then((res) => put(req, res)).catch(() => caches.match(req)));
  }
  // Everything else (the API) goes straight to the network.
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "TimeFrame", {
      body: data.body || "",
      icon: "/icon-192.png",
      badge: "/favicon-32.png",
      tag: data.kind === "reminder" ? `reminder-${data.data?.booking || ""}` : undefined,
      data: data.data || {},
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const group = event.notification.data?.group;
  const url = group ? `/?group=${encodeURIComponent(group)}` : "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const c of clients) {
        if (new URL(c.url).origin === self.location.origin) return c.focus();
      }
      return self.clients.openWindow(url);
    })
  );
});
