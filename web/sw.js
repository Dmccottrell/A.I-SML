// Emvryx service worker: keeps the page shell so the app opens instantly and can be installed. It never caches the API.
// The server fills in the version and the file list (routes_get.shell_files): every script the page loads, and a new version after any change.
// SHELL is the name of this version's cache; the server fills in a version number here so every release starts a fresh cache.
const SHELL = 'emvryx-shell-__VERSION__';
// install: store all the page's files so the app opens instantly and can be installed.
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(__FILES__)).then(() => self.skipWaiting()));
});
// activate: delete the caches of older versions and take control of the open pages.
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
// fetch: for page files, try the network first and keep a copy; if offline, answer from the copy. The /api/ calls are never stored.
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request).then((r) => {
    const copy = r.clone();
    caches.open(SHELL).then((c) => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request)));
});
// pwa_push: a notification from the server (web_push.py) while the app is closed; a tap opens Emvryx where it points
self.addEventListener('push', (e) => {
  let d = {}; try { d = e.data ? e.data.json() : {}; } catch (x) { d = {body: e.data ? e.data.text() : ''}; }
  e.waitUntil(self.registration.showNotification(d.title || 'Emvryx', {body: d.body || '', icon: '/icon-192.png', badge: '/icon-192.png', data: {url: d.url || '/'}}));
});
// notificationclick: when a notification is tapped, close it and open or focus the app, going to the address in the notification.
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then((list) => {
    const open = list.find((c) => new URL(c.url).origin === self.location.origin);
    if (open) { open.focus(); return open.navigate ? open.navigate(url).catch(() => {}) : null; }
    return self.clients.openWindow(url);
  }));
});
