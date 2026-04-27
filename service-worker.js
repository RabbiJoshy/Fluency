// Stale-while-revalidate: serve from cache instantly, fetch in background to
// update for next time. The previous network-first strategy made every cold
// start wait on a full round-trip per asset (HTML, CSS, JS modules, JSON),
// which on a PWA is most of the perceived "startup" cost.
//
// Trade-off: a deploy takes one extra page load to roll out (visit N shows
// stale assets but populates the cache; visit N+1 shows fresh). For an
// install-grade PWA used daily, that's an acceptable price for instant boot.
const CACHE_NAME = 'flashcards-v11';
const urlsToCache = [
  '/',
  '/index.html',
  '/config/artists.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;

  // Don't intercept cross-origin requests (Google Apps Script, Spotify,
  // Google Fonts, etc. — those go straight to the network).
  if (!request.url.startsWith(self.location.origin)) return;

  // Only cache GET. Mutating verbs (POST/PUT/DELETE) must always hit network.
  if (request.method !== 'GET') return;

  event.respondWith(
    caches.open(CACHE_NAME).then(cache =>
      cache.match(request).then(cached => {
        const fetchPromise = fetch(request).then(response => {
          // Only cache valid 200 responses. Don't poison the cache with
          // 404s, opaque cross-origin responses, or partial content.
          if (response && response.status === 200 && response.type === 'basic') {
            cache.put(request, response.clone());
          }
          return response;
        }).catch(() => cached);

        // Cached hit: return immediately, refresh in background. Cache
        // miss: wait for the network. The fetchPromise's .catch above
        // means a network failure on a cache miss propagates as a
        // rejected promise, which the browser surfaces as a normal
        // network error — same UX as having no service worker at all.
        return cached || fetchPromise;
      })
    )
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames =>
      Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) return caches.delete(cacheName);
        })
      )
    ).then(() => self.clients.claim())
  );
});
