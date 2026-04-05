const CACHE_NAME = 'flashcards-v9';
const urlsToCache = [
  '/',
  '/index.html',
  '/artists.json'
];

// Install event - cache files and skip waiting
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
      .then(() => self.skipWaiting())
  );
});

// Fetch event - network-first strategy for HTML files
self.addEventListener('fetch', event => {
  const request = event.request;

  // Don't intercept cross-origin requests (e.g. Google Apps Script API calls)
  if (!request.url.startsWith(self.location.origin)) return;

  // Network-first for everything: fresh when online, cached when offline
  event.respondWith(
    fetch(request)
      .then(response => {
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(request, responseClone));
        return response;
      })
      .catch(() => caches.match(request))
  );
});

// Activate event - clean up old caches and claim clients
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});
