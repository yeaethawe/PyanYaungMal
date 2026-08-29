const CACHE_NAME = "pyanyaungmal-v5";
const PRECACHE_URLS = [
  "/offline",
  "/static/style.css",
  "/static/admin.css",
  "/static/js/pwa.js",
  "/static/js/admin.js",
  "/static/manifest.webmanifest",
  "/static/brand/logo.png",
  "/static/brand/mark.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

async function cachePut(request, response) {
  if (!response || !response.ok) {
    return response;
  }
  const cache = await caches.open(CACHE_NAME);
  cache.put(request, response.clone());
  return response;
}

async function networkFirst(request) {
  try {
    const fresh = await fetch(request);
    return cachePut(request, fresh);
  } catch (error) {
    const cached = await caches.match(request);
    if (cached) {
      return cached;
    }
    if (request.mode === "navigate") {
      const offline = await caches.match("/offline");
      if (offline) {
        return offline;
      }
    }
    throw error;
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    return cached;
  }
  try {
    const fresh = await fetch(request);
    return cachePut(request, fresh);
  } catch (error) {
    if (request.destination === "document") {
      const offline = await caches.match("/offline");
      if (offline) {
        return offline;
      }
    }
    throw error;
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  if (url.pathname === "/sw.js") {
    return;
  }

  if (request.mode === "navigate" || request.headers.get("accept")?.includes("text/html")) {
    event.respondWith(networkFirst(request));
    return;
  }

  event.respondWith(cacheFirst(request));
});
