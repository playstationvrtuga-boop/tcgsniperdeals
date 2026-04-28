const CACHE_NAME = "tcg-sniper-deals-v8-live-feed-poll";
const OFFLINE_URL = "/offline";
const CORE_ASSETS = [
  OFFLINE_URL,
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/icons/app-icon-180.png",
  "/static/icons/app-icon-192.png",
  "/static/icons/app-icon-512.png",
  "/static/icons/app-splash.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  const request = event.request;
  const url = new URL(request.url);
  const isSameOrigin = url.origin === self.location.origin;
  const isStaticAsset = ["style", "script", "image", "font"].includes(request.destination);
  const mustRefresh = isSameOrigin && ["style", "script"].includes(request.destination);

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(async () => {
        return (await caches.match(request)) || caches.match(OFFLINE_URL);
      })
    );
    return;
  }

  if (mustRefresh) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request).then((cached) => cached || Response.error()))
    );
    return;
  }

  if (isSameOrigin && isStaticAsset) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;

        return fetch(request)
          .then((response) => {
            if (response && response.ok) {
              const copy = response.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
            }
            return response;
          })
          .catch(() => Response.error());
      })
    );
    return;
  }

  event.respondWith(fetch(request));
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (error) {
    data = { body: event.data ? event.data.text() : "New VIP deal available." };
  }
  const title = data.title || "TCG Sniper Deals";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || "New VIP deal available.",
      icon: "/static/icons/app-icon-192.png",
      badge: "/static/icons/app-icon-192.png",
      data: { url: data.url || "/feed" },
      tag: data.tag || "listing-alert",
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/feed", self.location.origin).href;
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (new URL(client.url).origin !== self.location.origin) continue;
        return client.focus().then(() => {
          if ("navigate" in client) {
            return client.navigate(url);
          }
          return client;
        });
      }
      return clients.openWindow(url);
    })
  );
});
