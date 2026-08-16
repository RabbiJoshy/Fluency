import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';

const root = resolve(import.meta.dirname, '..');
const text = path => readFile(resolve(root, path), 'utf8');

test('offline manifest files have exact sizes and checksums', async () => {
    const manifest = JSON.parse(await text('config/offline-content-manifest.json'));
    assert.equal(manifest.schemaVersion, 1);
    for (const source of manifest.sources) {
        assert.ok(source.id && source.contentVersion && source.scope);
        assert.equal(source.storageBytes, source.files.reduce((sum, file) => sum + file.bytes, 0));
        for (const file of source.files) {
            const body = await readFile(resolve(root, file.path));
            assert.equal(body.byteLength, file.bytes, file.path);
            assert.equal(createHash('sha256').update(body).digest('hex'), file.sha256, file.path);
        }
    }
});

test('service worker separates shell, staging, and retained content policies', async () => {
    const [worker, content] = await Promise.all([
        text('service-worker.js'), text('js/offline-content.js')
    ]);
    assert.match(worker, /fluency-content-/);
    assert.match(worker, /CONTENT_STAGING_PREFIX/);
    assert.match(worker, /cacheName\.startsWith\(SHELL_CACHE_PREFIX\)/);
    assert.doesNotMatch(worker, /cacheName !== CACHE_NAME\) return caches\.delete/);
    assert.match(worker, /SKIP_WAITING/);
    assert.match(worker, /buildRetainedContentIndex/);
    assert.match(worker, /index\.get\(new URL\(request\.url\)\.pathname\)/);
    assert.doesNotMatch(worker, /for \(const name of contentNames\)/);
    assert.match(worker, /if \(cached\) return cached/);
    assert.doesNotMatch(worker, /const fetchPromise = fetch\(request\)/);
    assert.match(content, /CONTENT_CACHES_CHANGED/);
});

test('queue records durable retry and idempotency metadata', async () => {
    const queue = await text('js/sync-queue.js');
    for (const field of [
        'idempotencyKey', 'accountId', 'operationType', 'createdAt', 'updatedAt',
        'attemptCount', 'lastError', 'retryState', 'serverReceipt'
    ]) assert.match(queue, new RegExp(`\\b${field}\\b`));
    assert.match(queue, /Ambiguous response/);
    assert.match(queue, /auth-paused/);
    assert.match(queue, /visibilitychange/);
    assert.match(queue, /MAX_ACTIVE_ATTEMPTS/);
    assert.match(queue, /MAX_AUTOMATIC_ATTEMPTS/);
    assert.match(queue, /RECONNECT_GRACE_MS = 1500/);
    assert.match(queue, /nextAutomaticRetryDelay/);
    assert.match(queue, /resetTransientFailures/);
    // Parse the actual module in a browser-equivalent grammar. This catches
    // malformed regex literals before they can abort the full import graph.
    assert.doesNotMatch(queue, /https\?:\\\\\/\\\\\//);
    assert.match(queue, /replace\(\/https\?:\\\/\\\/\\S\+\/g/);
});

test('whole progress snapshots are batched outside answer interactions', async () => {
    const [auth, knowledge] = await Promise.all([
        text('js/auth.js'), text('js/knowledge.js')
    ]);
    assert.match(auth, /PROGRESS_CACHE_DELAY_MS = 750/);
    assert.match(auth, /requestIdleCallback/);
    assert.match(auth, /window\.addEventListener\('pagehide', flushProgressCache\)/);
    assert.match(auth, /progressCacheWrite = progressCacheWrite/);
    assert.match(auth, /sendOrQueue\(\{/);
    assert.doesNotMatch(knowledge, /localStorage\.setItem\(cacheKey/);
    assert.match(knowledge, /window\.cacheProgressLocally\?\.\(\)/);
});

test('optional offline services cannot block authentication indefinitely', async () => {
    const [main, auth, database, content, html] = await Promise.all([
        text('js/main.js'), text('js/auth.js'), text('js/offline-db.js'), text('js/offline-content.js'), text('index.html')
    ]);
    assert.ok(main.indexOf('setupAuthEventListeners();') < main.indexOf('await resolveArtist();'));
    assert.ok(main.indexOf('checkAuthentication();') < main.indexOf('await resolveArtist();'));
    assert.match(main, /window\.initSync\(\)\.catch/);
    assert.match(main, /initOfflineContent\(\)\.catch/);
    assert.match(auth, /AbortController/);
    assert.match(auth, /if \(!GOOGLE_SCRIPT_URL\) return false/);
    assert.match(database, /Offline database open timed out/);
    assert.match(content, /controller\.abort/);
    assert.match(auth, /window\.hideAppLoading\?\.\(\)/);
    assert.match(html, /window\.fluencyAuthFallback/);
    for (const action of ['openLogin()', 'guest()', 'submit()', 'cancelLogin()']) {
        assert.ok(html.includes(`window.fluencyAuthFallback.${action}`), action);
    }
});

test('asset versions remain in lockstep', async () => {
    const [worker, main, html, cards] = await Promise.all([
        text('service-worker.js'), text('js/main.js'), text('index.html'), text('js/flashcards.js')
    ]);
    const version = worker.match(/const ASSET_VERSION = '([^']+)'/)[1];
    assert.ok(version);
    assert.doesNotMatch(main, /v=20260729/);
    assert.doesNotMatch(html, /v=20260729/);
    assert.match(cards, new RegExp(`const ASSET_VERSION = '${version}'`));
    for (const file of [
        'main.js', 'state.js', 'offline-db.js', 'sync-queue.js', 'offline-content.js', 'reverse-cues.js'
    ]) {
        assert.ok(worker.includes(`/js/${file}?v=\${ASSET_VERSION}`), file);
    }
});
