// Uygulama kabuğu: önce internetten dener, bağlantı yoksa son kaydedilen sürümü gösterir.
const KASA = "mac-analizi-v1";
const KABUK = ["/", "/logo.svg", "/ikon-192.png", "/ikon-512.png", "/manifest.webmanifest"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(KASA).then(k => k.addAll(KABUK)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(adlar => Promise.all(adlar.filter(a => a !== KASA).map(a => caches.delete(a))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const istek = e.request;
  if (istek.method !== "GET" || new URL(istek.url).origin !== location.origin) return;
  e.respondWith(
    fetch(istek)
      .then(yanit => {
        if (yanit.ok) {
          const kopya = yanit.clone();
          caches.open(KASA).then(k => k.put(istek, kopya));
        }
        return yanit;
      })
      .catch(() => caches.match(istek).then(eski => eski || caches.match("/")))
  );
});
