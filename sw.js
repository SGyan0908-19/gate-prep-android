const CACHE = 'gate-prep-shell-v058';
const SHELL = ['/', '/static/manifest.json', '/static/icons/icon-192.png', '/static/icons/icon-512.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  event.respondWith(fetch(req).then(res => {
    if (res.ok) caches.open(CACHE).then(cache => cache.put(req, res.clone()));
    return res;
  }).catch(() => caches.match(req).then(cached => cached || caches.match('/'))));
});
