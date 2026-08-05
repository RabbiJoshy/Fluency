// Navigations use network-first so the HTML shell immediately receives new
// module version tags after a deploy. Versioned assets and large data files
// are cache-first until the next cache/content version, avoiding repeated
// multi-megabyte background transfers during ordinary study.
// Bump CACHE_NAME alongside any change to ASSET_VERSION below — old caches
// are deleted in the activate handler, so a bump forces the new pre-cache
// list to be rebuilt on next install.
const CACHE_NAME = 'flashcards-v200';
const SHELL_CACHE_PREFIX = 'flashcards-v';
const CONTENT_CACHE_PREFIX = 'fluency-content-';
const CONTENT_STAGING_PREFIX = `${CONTENT_CACHE_PREFIX}staging-`;

// Single source of truth for the module/CSS version tags. Must match
// js/main.js's import URLs and index.html's modulepreload links. When you
// bump the ?v= tags, change this and bump CACHE_NAME above.
const ASSET_VERSION = '20260805g';

// Pre-cache the boot-critical static assets on install. Without this, the
// first install populates the cache lazily — visit 1 doesn't go through
// the SW at all (it's not registered yet), and visit 2 has to fetch each
// asset from network before stale-while-revalidate has anything to serve.
// With pre-cache, visit 2 hits the SW with a fully-warm cache and the app
// boots offline-fast even on first reload after install.
const urlsToCache = [
  '/',
  '/index.html',
  `/css/style.css?v=${ASSET_VERSION}`,
  '/config/config.json',
  '/config/cefr_levels.json',
  '/config/artists.json',
  '/config/offline-content-manifest.json',
  `/js/main.js?v=${ASSET_VERSION}`,
  `/js/state.js?v=${ASSET_VERSION}`,
  `/js/offline-db.js?v=${ASSET_VERSION}`,
  `/js/sync-queue.js?v=${ASSET_VERSION}`,
  `/js/offline-content.js?v=${ASSET_VERSION}`,
  `/js/speech.js?v=${ASSET_VERSION}`,
  `/js/artist-ui.js?v=${ASSET_VERSION}`,
  `/js/auth.js?v=${ASSET_VERSION}`,
  `/js/spotify.js?v=${ASSET_VERSION}`,
  `/js/estimation.js?v=${ASSET_VERSION}`,
  `/js/config.js?v=${ASSET_VERSION}`,
  `/js/progress.js?v=${ASSET_VERSION}`,
  `/js/knowledge.js?v=${ASSET_VERSION}`,
  `/js/ui.js?v=${ASSET_VERSION}`,
  `/js/vocab.js?v=${ASSET_VERSION}`,
  `/js/flashcards.js?v=${ASSET_VERSION}`,
  `/js/example-personalisation.js?v=${ASSET_VERSION}`,
  `/js/flashcards-modals.js?v=${ASSET_VERSION}`,
  `/js/flashcards-conj.js?v=${ASSET_VERSION}`
];

self.addEventListener('install', event => {
  // `cache: 'reload'` bypasses the browser HTTP cache for every precache
  // fetch. Without it, addAll() is free to satisfy an unchanged URL from disk,
  // so bumping CACHE_NAME re-cached the same stale bytes. That is invisible
  // for the ?v=-tagged modules and was silently fatal for the entries without
  // a version tag — index.html, the config JSONs, and (until now) style.css.
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(
      urlsToCache.map(url => new Request(url, { cache: 'reload' }))
    ))
  );
});

// Resolve retained downloads by their manifest ownership instead of opening
// and probing every downloaded cache for every module, image, and data fetch.
// The promise is process-local: it is rebuilt when the worker wakes, and the
// page invalidates it after a download/remove changes CacheStorage.
let retainedContentIndexPromise = null;

async function buildRetainedContentIndex() {
  const shell = await caches.open(CACHE_NAME);
  const manifestResponse = await shell.match('/config/offline-content-manifest.json');
  if (!manifestResponse) return new Map();

  const manifest = await manifestResponse.json();
  const cacheNames = (await caches.keys()).filter(name =>
    name.startsWith(CONTENT_CACHE_PREFIX) && !name.startsWith(CONTENT_STAGING_PREFIX));
  const index = new Map();

  for (const source of manifest.sources || []) {
    const prefix = `${CONTENT_CACHE_PREFIX}${source.id}-`;
    const expectedName = `${prefix}${source.contentVersion}`;
    const candidates = cacheNames.filter(name => name.startsWith(prefix));
    candidates.sort((a, b) => Number(b === expectedName) - Number(a === expectedName));
    let cacheName = null;
    for (const candidate of candidates) {
      const cache = await caches.open(candidate);
      if (await cache.match('/__fluency_content_complete__')) {
        cacheName = candidate;
        break;
      }
    }
    if (!cacheName) continue;
    for (const file of source.files || []) {
      const pathname = new URL(file.path, self.location.origin).pathname;
      if (!index.has(pathname)) index.set(pathname, cacheName);
    }
  }
  return index;
}

async function matchRetainedContent(request) {
  retainedContentIndexPromise ||= buildRetainedContentIndex().catch(error => {
    console.warn('Retained content index unavailable:', error);
    return new Map();
  });
  const index = await retainedContentIndexPromise;
  const cacheName = index.get(new URL(request.url).pathname);
  if (!cacheName) return null;
  return (await caches.open(cacheName)).match(request);
}

self.addEventListener('fetch', event => {
  const request = event.request;

  // Don't intercept cross-origin requests (Google Apps Script, Spotify,
  // Google Fonts, etc. — those go straight to the network).
  if (!request.url.startsWith(self.location.origin)) return;

  // Only cache GET. Mutating verbs (POST/PUT/DELETE) must always hit network.
  // This is what keeps Google Sheets writes (POST to the Apps Script endpoint)
  // out of the SW entirely — those are handled by js/sync-queue.js instead.
  if (request.method !== 'GET') return;

  // The old cache-first navigation path meant the cached HTML continued to
  // request yesterday's ?v= modules on the first visit after every deploy.
  // Pay one small HTML request while online, cache it for offline fallback,
  // and keep every heavier asset on the fast path below.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).then(response => {
        if (response && response.status === 200 && response.type === 'basic') {
          return caches.open(CACHE_NAME)
            .then(cache => cache.put('/index.html', response.clone()))
            .then(() => response);
        }
        return response;
      }).catch(() => caches.open(CACHE_NAME).then(cache =>
        cache.match(request).then(cached => cached || cache.match('/index.html') || cache.match('/'))
      ))
    );
    return;
  }

  // Explicit retained downloads live in immutable, source-versioned content
  // caches. Prefer those before ordinary runtime cache entries.
  // includes the deck DATA the app fetches to render a deck: the per-artist
  // *.index.json / *.examples.json, shared vocabulary_master.json, config/*.json,
  // and the Data/Spanish/* rank & conjugation files. Runtime misses are cached
  // once for the lifetime of this version; retained downloads stay separately
  // versioned and survive shell upgrades.
  // They're intentionally NOT in the install-time pre-cache list: they're large,
  // per-artist, and use accented/space-containing paths — caching them lazily on
  // first real fetch keeps the pre-cache lean while still giving full offline
  // study to a returning user.
  event.respondWith(
    matchRetainedContent(request).then(async retained => {
      if (retained) return retained;
      const cache = await caches.open(CACHE_NAME);
      return cache.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          // Only cache valid 200 responses. Don't poison the cache with
          // 404s, opaque cross-origin responses, or partial content.
          if (response && response.status === 200 && response.type === 'basic') {
            cache.put(request, response.clone());
          }
          return response;
        });
      });
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames =>
      Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName.startsWith(SHELL_CACHE_PREFIX) && cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
  if (event.data?.type === 'CONTENT_CACHES_CHANGED') retainedContentIndexPromise = null;
});
