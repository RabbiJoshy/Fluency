/**
 * Kill switch for the retired Fluency app.
 *
 * This app now redirects to Fluency-Next. A service worker outlives the page
 * that registered it, so without this the old one would keep answering
 * requests for this origin from its own cache — including the cached app
 * shell — and a returning visitor could land back in the retired app instead
 * of being forwarded.
 *
 * It unregisters itself, deletes every cache it created, and reloads any open
 * clients so they pick up the redirect page. The previous worker is preserved
 * as legacy-service-worker.js.
 */

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) await caches.delete(key);
    await self.registration.unregister();
    for (const client of await self.clients.matchAll({ type: 'window' })) {
      client.navigate(client.url);
    }
  })());
});

// Nothing is served from cache any more: every request goes to the network,
// which for a navigation means the redirect page.
self.addEventListener('fetch', () => {});
