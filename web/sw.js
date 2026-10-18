// Emvryx service worker: keeps the page shell so the app opens instantly and can be installed. It never caches the API.
const SHELL = 'emvryx-shell-v37';
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(['/', '/editor.js', '/vryx.css', '/modern.css', '/js/core.js', '/js/tour.js', '/js/chat.js', '/js/documents.js', '/js/qr.js', '/js/settings.js', '/js/admin.js', '/js/send.js', '/js/code.js', '/js/ide.js', '/js/preview.js', '/js/auth.js', '/js/boot.js', '/icon.svg', '/icon-192.png', '/manifest.webmanifest'])).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request).then((r) => {
    const copy = r.clone();
    caches.open(SHELL).then((c) => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request)));
});
