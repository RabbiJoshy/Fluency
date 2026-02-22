const CACHE_NAME = 'flashcards-v2';
const urlsToCache = [
  '/',
  '/index.html'
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

  // For HTML and JS files, use network-first strategy
  if (request.destination === 'document' || request.url.endsWith('.html') || request.url.endsWith('.js')) {
    event.respondWith(
      fetch(request)
        .then(response => {
          // Cache the fresh response
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, responseClone));
          return response;
        })
        .catch(() => caches.match(request))
    );
  } else {
    // For other assets, use cache-first
    event.respondWith(
      caches.match(request)
        .then(response => response || fetch(request))
    );
  }
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
