// Durable, local-first synchronization queue.
import './state.js?v=20260816l';
import { dbDelete, dbGetAll, dbPut, makeOperationId, openOfflineDb } from './offline-db.js?v=20260816l';

const LEGACY_QUEUE_KEY = 'fluency_sync_queue_v1';
const LAST_SYNC_KEY = 'fluency_last_sync_v1';
const MAX_ACTIVE_ATTEMPTS = 4;
const MAX_AUTOMATIC_ATTEMPTS = 4;
const RECONNECT_GRACE_MS = 1500;
const REQUEST_TIMEOUT_MS = 15000;
let queue = [];
let readyPromise;
let flushing = false;
let flushTimer = null;
let lastError = null;

const accountId = payload => String(payload?.user || currentUser?.initials || 'anonymous');
const operationType = payload => String(payload?.action || 'unknown');
const sanitizedError = error => String(error?.message || error || 'Unknown sync error')
    .replace(/https?:\/\/\S+/g, '[endpoint]')
    .slice(0, 180);

function newestFirst(a, b) { return b.updatedAt - a.updatedAt; }

async function initializeQueue() {
    try {
        await openOfflineDb();
        queue = await dbGetAll('operations');
        const legacy = JSON.parse(localStorage.getItem(LEGACY_QUEUE_KEY) || '[]');
        if (Array.isArray(legacy)) {
            for (const old of legacy) {
                const createdAt = Number(old.ts) || Date.now();
                const acct = accountId(old.payload);
                const id = makeOperationId(acct, old.dedupeKey, createdAt);
                if (queue.some(item => item.id === id)) continue;
                const entry = {
                    id, idempotencyKey: id, dedupeKey: old.dedupeKey || null,
                    accountId: acct, operationType: operationType(old.payload),
                    payload: old.payload, createdAt, updatedAt: createdAt,
                    attemptCount: 0, retryState: 'pending', lastError: null,
                    nextAttemptAt: 0, serverReceipt: null
                };
                await dbPut('operations', entry);
                queue.push(entry);
            }
        }
        localStorage.removeItem(LEGACY_QUEUE_KEY);
    } catch (error) {
        // Retain the legacy queue when IndexedDB is unavailable.
        console.warn('sync-queue: IndexedDB unavailable; legacy queue retained', error);
        try {
            queue = JSON.parse(localStorage.getItem(LEGACY_QUEUE_KEY) || '[]').map(old => ({
                id: makeOperationId(accountId(old.payload), old.dedupeKey, old.ts),
                idempotencyKey: makeOperationId(accountId(old.payload), old.dedupeKey, old.ts),
                dedupeKey: old.dedupeKey || null, accountId: accountId(old.payload),
                operationType: operationType(old.payload), payload: old.payload,
                createdAt: old.ts || Date.now(), updatedAt: old.ts || Date.now(),
                attemptCount: 0, retryState: 'pending', nextAttemptAt: 0
            }));
        } catch (_) { queue = []; }
    }
    queue.sort((a, b) => a.createdAt - b.createdAt);
    updateIndicator();
    return queue;
}

function ensureReady() {
    if (!readyPromise) readyPromise = initializeQueue();
    return readyPromise;
}

async function persist(entry) {
    try { await dbPut('operations', entry); } catch (error) {
        localStorage.setItem(LEGACY_QUEUE_KEY, JSON.stringify(queue.map(item => ({
            dedupeKey: item.dedupeKey, payload: item.payload, ts: item.createdAt
        }))));
        throw error;
    }
    updateIndicator();
}

async function remove(entry) {
    queue = queue.filter(item => item.id !== entry.id);
    try { await dbDelete('operations', entry.id); } catch (_) {}
    updateIndicator();
}

async function enqueueWrite(payload, dedupeKey) {
    await ensureReady();
    const acct = accountId(payload);
    const existing = dedupeKey && queue.find(item =>
        item.dedupeKey === dedupeKey && item.accountId === acct);
    const now = Date.now();
    const entry = existing ? {
        ...existing, payload, updatedAt: now, operationType: operationType(payload),
        attemptCount: 0, retryState: 'pending', lastError: null, nextAttemptAt: 0
    } : {
        id: makeOperationId(acct, dedupeKey, now),
        idempotencyKey: makeOperationId(acct, dedupeKey, now),
        dedupeKey: dedupeKey || null, accountId: acct,
        operationType: operationType(payload), payload,
        createdAt: now, updatedAt: now, attemptCount: 0,
        retryState: 'pending', lastError: null, nextAttemptAt: 0,
        serverReceipt: null
    };
    entry.payload = { ...payload, idempotencyKey: entry.idempotencyKey };
    if (!existing) queue.push(entry);
    await persist(entry);
    dispatchStatus();
    return entry;
}

export function getPendingCount() { return queue.length; }
export async function inspectQueue() { await ensureReady(); return queue.slice().sort(newestFirst); }

async function postToSheet(entry) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
        const response = await fetch(GOOGLE_SCRIPT_URL, {
            method: 'POST', body: JSON.stringify(entry.payload), signal: controller.signal
        });
        let json;
        try { json = await response.json(); } catch (_) {
            throw new Error(`Ambiguous response (HTTP ${response.status})`);
        }
        if (!response.ok || json?.success !== true) {
            const error = new Error(json?.message || `Sync rejected (HTTP ${response.status})`);
            error.auth = response.status === 401 || response.status === 403 || /auth|login/i.test(error.message);
            throw error;
        }
        return json.receipt || json.operationId || entry.idempotencyKey;
    } finally {
        clearTimeout(timeout);
    }
}

export async function sendOrQueue(payload, dedupeKey) {
    await enqueueWrite(payload, dedupeKey);
    if (navigator.onLine && GOOGLE_SCRIPT_URL) scheduleFlush(0);
    return false; // only a queue drain may acknowledge/remove durable work
}

function scheduleFlush(delay = 400) {
    clearTimeout(flushTimer);
    flushTimer = setTimeout(() => flushQueue(), delay);
}

function nextAutomaticRetryDelay() {
    const now = Date.now();
    const eligible = queue.filter(item =>
        item.retryState !== 'auth-paused' && item.retryState !== 'failed');
    if (eligible.length === 0) return null;
    return Math.max(0, Math.min(...eligible.map(item => Number(item.nextAttemptAt) || now)) - now);
}

async function resetTransientFailures() {
    for (const entry of queue) {
        if (entry.retryState !== 'failed') continue;
        entry.attemptCount = 0;
        entry.retryState = 'pending';
        entry.nextAttemptAt = 0;
        await persist(entry);
    }
}

export async function flushQueue({ force = false } = {}) {
    await ensureReady();
    if (flushing || !navigator.onLine || !GOOGLE_SCRIPT_URL || queue.length === 0) {
        updateIndicator(); return;
    }
    flushing = true;
    lastError = null;
    updateIndicator();
    let attempts = 0;
    try {
        while (navigator.onLine && attempts < MAX_ACTIVE_ATTEMPTS) {
            const now = Date.now();
            const entry = queue.find(item =>
                (force || item.retryState !== 'auth-paused') &&
                (force || item.retryState !== 'failed') &&
                (force || !item.nextAttemptAt || item.nextAttemptAt <= now));
            if (!entry) break;
            attempts++;
            entry.attemptCount = Number(entry.attemptCount || 0) + 1;
            entry.updatedAt = now;
            entry.retryState = 'sending';
            await persist(entry);
            try {
                const receipt = await postToSheet(entry);
                await dbPut('receipts', {
                    idempotencyKey: entry.idempotencyKey, accountId: entry.accountId,
                    operationType: entry.operationType, acknowledgedAt: Date.now(), serverReceipt: receipt
                });
                await remove(entry);
                localStorage.setItem(LAST_SYNC_KEY, String(Date.now()));
            } catch (error) {
                lastError = sanitizedError(error);
                entry.lastError = lastError;
                entry.updatedAt = Date.now();
                const exhausted = entry.attemptCount >= MAX_AUTOMATIC_ATTEMPTS;
                entry.retryState = error.auth ? 'auth-paused' : exhausted ? 'failed' : 'pending';
                entry.nextAttemptAt = error.auth || exhausted ? 0 :
                    Date.now() + Math.min(30000, 1000 * (2 ** entry.attemptCount));
                await persist(entry);
                break; // preserve ordering after an uncertain outcome
            }
        }
    } finally {
        flushing = false;
        updateIndicator();
        dispatchStatus();
        const retryDelay = nextAutomaticRetryDelay();
        if (navigator.onLine && retryDelay !== null) scheduleFlush(retryDelay);
    }
}

export async function retryOperation(id) {
    await ensureReady();
    const entry = queue.find(item => item.id === id);
    if (entry) {
        entry.attemptCount = 0;
        entry.retryState = 'pending';
        entry.nextAttemptAt = 0;
        entry.lastError = null;
        await persist(entry);
    }
    return flushQueue({ force: true });
}

function dispatchStatus() {
    window.dispatchEvent(new CustomEvent('fluency-sync-status', { detail: getSyncStatus() }));
}

export function getSyncStatus() {
    const pending = queue.length;
    const online = navigator.onLine;
    const failed = queue.some(item => item.retryState === 'failed' || item.retryState === 'auth-paused');
    return {
        state: !online ? 'offline' : flushing ? 'syncing' : failed ? 'failed' : pending ? 'pending' : 'synced',
        online, pending, lastError, lastSuccessfulSync: Number(localStorage.getItem(LAST_SYNC_KEY)) || null
    };
}

export function updateIndicator() {
    const el = document.getElementById('syncStatusIndicator');
    if (!el) return;
    const status = getSyncStatus();
    el.className = `sync-status is-${status.state}`;
    const label = {
        offline: status.pending ? `Offline · ${status.pending}` : 'Offline',
        syncing: `Syncing ${status.pending}…`,
        failed: `Sync failed · ${status.pending}`,
        pending: `${status.pending} pending`,
        synced: 'Synced'
    }[status.state];
    el.textContent = label;
    el.title = status.lastError || (status.pending ? `${status.pending} changes saved locally` : 'Progress synchronized');
    updateSyncDetails();
}

async function updateSyncDetails() {
    const status = getSyncStatus();
    const count = document.getElementById('syncPendingCount');
    const last = document.getElementById('syncLastSuccess');
    const error = document.getElementById('syncLastError');
    if (count) count.textContent = String(status.pending);
    if (last) last.textContent = status.lastSuccessfulSync
        ? new Date(status.lastSuccessfulSync).toLocaleString() : 'Not yet';
    if (error) {
        error.textContent = status.lastError || '';
        error.hidden = !status.lastError;
    }
    const list = document.getElementById('syncQueueList');
    if (list) {
        list.innerHTML = queue.map(item =>
            `<li><span><strong>${item.operationType}</strong><small>${item.retryState} · ${item.attemptCount} attempts</small></span><button type="button" data-retry-op="${item.id}">Retry</button></li>`
        ).join('') || '<li class="sync-queue-empty">No pending changes.</li>';
        list.querySelectorAll('[data-retry-op]').forEach(button =>
            button.addEventListener('click', () => retryOperation(button.dataset.retryOp)));
    }
}

export function applyPendingProgressOverlay(progress) {
    for (const { payload: p } of queue) {
        if (!p || p.sheet === 'FlaggedWords') continue;
        const rows = p.action === 'bulkSave' && Array.isArray(p.rows)
            ? p.rows
            : p.action === 'save' ? [p] : [];
        for (const row of rows) {
            const wordId = row.itemId || row.wordId;
            if (row.word === '_LEVEL_ESTIMATE_' || row.itemType === 'meta' || !wordId) continue;
            progress[wordId] = {
                word: row.label || row.word,
                language: row.language,
                correct: row.correct,
                wrong: row.wrong,
                lastCorrect: row.lastCorrect,
                lastWrong: row.lastWrong,
                lastSeen: row.lastSeen,
                srsStage: row.srsStage
            };
        }
    }
    return progress;
}

export function applyPendingItemProgressOverlay(items) {
    for (const { payload: p } of queue) {
        if (p?.action === 'saveItem' && p.itemId) items[p.itemId] = { ...p };
    }
    return items;
}

export function applyPendingMetaProgressOverlay(estimates, doneLevels) {
    for (const { payload: p } of queue) {
        if (p?.action === 'save' && p.word === '_LEVEL_ESTIMATE_' && p.language) estimates[p.language] = p.wordId;
        if (p?.action === 'saveMeta' && p.metaKey === 'level-estimate' && p.language) estimates[p.language] = p.value;
        if (p?.action !== 'saveMeta' || p.metaKey !== 'level-done' || !p.scopeKey || !p.metaId) continue;
        const scope = { ...(doneLevels[p.scopeKey] || {}) };
        if (p.value === true || p.value === 1 || p.value === '1') scope[p.metaId] = true;
        else delete scope[p.metaId];
        doneLevels[p.scopeKey] = scope;
    }
    return { estimates, doneLevels };
}

export async function initSync() {
    await ensureReady();
    window.addEventListener('online', async () => {
        updateIndicator();
        await resetTransientFailures();
        scheduleFlush(RECONNECT_GRACE_MS);
    });
    window.addEventListener('offline', updateIndicator);
    document.addEventListener('visibilitychange', async () => {
        if (document.visibilityState === 'visible') {
            await resetTransientFailures();
            scheduleFlush(500);
        }
    });
    window.addEventListener('fluency-auth-restored', () => {
        queue.forEach(item => { if (item.retryState === 'auth-paused') item.retryState = 'pending'; });
        scheduleFlush(0);
    });
    document.getElementById('syncNowBtn')?.addEventListener('click', () => flushQueue({ force: true }));
    updateIndicator();
    await resetTransientFailures();
    scheduleFlush(500);
}

Object.assign(window, {
    sendOrQueue, flushQueue, retryOperation, getPendingCount, inspectSyncQueue: inspectQueue,
    applyPendingProgressOverlay, applyPendingItemProgressOverlay,
    applyPendingMetaProgressOverlay, updateSyncIndicator: updateIndicator, initSync
});
