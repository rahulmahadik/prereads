/* PreReads service worker: offline shell + saved reading paths. Hand-written, no dependencies. */
const VERSION = "v2";
const SHELL = `prereads-shell-${VERSION}`;
const API = `prereads-api-${VERSION}`;
const API_PATHS = ["/api/route", "/api/targets", "/api/popular", "/api/branches", "/api/similar", "/api/mode", "/api/health"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL);
      try {
        const res = await fetch("/", { cache: "reload" });
        const html = await res.clone().text();
        await cache.put("/", res);
        const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1]);
        await Promise.all(["/manifest.webmanifest", "/icon.svg", "/icon-192.png", ...assets].map((u) => cache.add(u).catch(() => {})));
      } catch (e) { /* offline at install: runtime caching will fill in */ }
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL, API]);
      for (const k of await caches.keys()) if (!keep.has(k)) await caches.delete(k);
      await self.clients.claim();
    })(),
  );
});

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (e) {
    const hit = await cache.match(req, { ignoreVary: true });
    if (hit) return hit;
    throw e;
  }
}

async function cacheFirst(req) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(req, { ignoreVary: true });
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(req, res.clone());
  return res;
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return; // never cache POST (discover, tts, stt, scan)
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.destination === "audio" || req.headers.get("range") || /\.(mp3|wav|ogg|m4a)$/.test(url.pathname)) return;

  if (url.pathname.startsWith("/api/")) {
    if (API_PATHS.some((p) => url.pathname === p)) event.respondWith(networkFirst(req, API));
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(cacheFirst(req));
    return;
  }
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).then((res) => {
        if (res.ok) caches.open(SHELL).then((c) => c.put("/", res.clone()));
        return res;
      }).catch(async () => (await caches.match("/", { ignoreVary: true, ignoreSearch: true })) || Response.error()),
    );
    return;
  }
  if (/\.(png|svg|webmanifest|ico)$/.test(url.pathname)) event.respondWith(networkFirst(req, SHELL));
});
