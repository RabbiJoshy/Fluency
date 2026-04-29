// Stale-while-revalidate: serve from cache instantly, fetch in background to
// update for next time. The previous network-first strategy made every cold
// start wait on a full round-trip per asset (HTML, CSS, JS modules, JSON),
// which on a PWA is most of the perceived "startup" cost.
//
// Trade-off: a deploy takes one extra page load to roll out (visit N shows
// stale assets but populates the cache; visit N+1 shows fresh). For an
// install-grade PWA used daily, that's an acceptable price for instant boot.
// Bump CACHE_NAME alongside any change to ASSET_VERSION below — old caches
// are deleted in the activate handler, so a bump forces the new pre-cache
// list to be rebuilt on next install.
const CACHE_NAME = 'flashcards-v25';

// Single source of truth for the module/CSS version tags. Must match
// js/main.js's import URLs and index.html's modulepreload links. When you
// bump the ?v= tags, change this and bump CACHE_NAME above.
const ASSET_VERSION = '20260427r';

// Pre-cache the boot-critical static assets on install. Without this, the
// first install populates the cache lazily — visit 1 doesn't go through
// the SW at all (it's not registered yet), and visit 2 has to fetch each
// asset from network before stale-while-revalidate has anything to serve.
// With pre-cache, visit 2 hits the SW with a fully-warm cache and the app
// boots offline-fast even on first reload after install.
const urlsToCache = [
  '/',
  '/index.html',
  '/css/style.css',
  '/config/config.json',
  '/config/cefr_levels.json',
  '/config/artists.json',
  '/backend/secrets.json',
  `/js/main.js?v=${ASSET_VERSION}`,
  `/js/state.js?v=${ASSET_VERSION}`,
  `/js/speech.js?v=${ASSET_VERSION}`,
  `/js/artist-ui.js?v=${ASSET_VERSION}`,
  `/js/auth.js?v=${ASSET_VERSION}`,
  `/js/spotify.js?v=${ASSET_VERSION}`,
  `/js/estimation.js?v=${ASSET_VERSION}`,
  `/js/config.js?v=${ASSET_VERSION}`,
  `/js/progress.js?v=${ASSET_VERSION}`,
  `/js/ui.js?v=${ASSET_VERSION}`,
  `/js/vocab.js?v=${ASSET_VERSION}`,
  `/js/flashcards.js?v=${ASSET_VERSION}`,
  `/js/flashcards-modals.js?v=${ASSET_VERSION}`,
  `/js/flashcards-conj.js?v=${ASSET_VERSION}`
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
