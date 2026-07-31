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
    const worker = await text('service-worker.js');
    assert.match(worker, /fluency-content-/);
    assert.match(worker, /!name\.includes\('staging-'\)/);
    assert.match(worker, /cacheName\.startsWith\(SHELL_CACHE_PREFIX\)/);
    assert.doesNotMatch(worker, /cacheName !== CACHE_NAME\) return caches\.delete/);
    assert.match(worker, /SKIP_WAITING/);
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
});

test('optional offline services cannot block authentication indefinitely', async () => {
    const [main, auth, database, content] = await Promise.all([
        text('js/main.js'), text('js/auth.js'), text('js/offline-db.js'), text('js/offline-content.js')
    ]);
    assert.ok(main.indexOf('checkAuthentication();') < main.indexOf('await loadSecrets();'));
    assert.match(main, /window\.initSync\(\)\.catch/);
    assert.match(main, /initOfflineContent\(\)\.catch/);
    assert.match(auth, /AbortController/);
    assert.match(auth, /if \(!GOOGLE_SCRIPT_URL\) return false/);
    assert.match(database, /Offline database open timed out/);
    assert.match(content, /controller\.abort/);
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
    for (const file of ['main.js', 'state.js', 'offline-db.js', 'sync-queue.js', 'offline-content.js']) {
        assert.ok(worker.includes(`/js/${file}?v=\${ASSET_VERSION}`), file);
    }
});
