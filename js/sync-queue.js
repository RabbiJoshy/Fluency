// Offline write-queue + sync for Google Sheets writes.
//
// Progress saves, word flags, and level-estimate writes all POST to the
// GOOGLE_SCRIPT_URL (a cross-origin Google Apps Script endpoint the service
// worker deliberately does NOT intercept — mutating verbs must always hit the
// network). When the user is offline, or a write fails transiently, we can't
// let that write silently vanish. This module gives those writes a durable
// localStorage queue and flushes it back to Sheets when connectivity returns.
//
// Design:
//  - sendOrQueue(payload, dedupeKey): write-through when online (fast path,
//    unchanged latency for online users), enqueue on failure/offline.
//  - The queue is de-duped by dedupeKey so the LATEST state per word wins —
//    every Sheets "save" carries the full cumulative counts, so a newer save
//    for a word fully supersedes an older queued one (no need to replay both).
//  - flushQueue() drains in FIFO order; a partial failure stops the drain and
//    leaves the unsent tail in place (idempotent: re-sending a full-state save
//    is harmless).
//  - Flushes fire on the `online` event, on a periodic timer, and once at boot.
import './state.js';

const QUEUE_KEY = 'fluency_sync_queue_v1';
const FLUSH_INTERVAL_MS = 20000;

let _flushing = false;
let _intervalStarted = false;

// ---- Queue persistence ----------------------------------------------------

function loadQueue() {
    try {
        const raw = localStorage.getItem(QUEUE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
        console.warn('sync-queue: could not parse queue, resetting', e);
        return [];
    }
}

function saveQueue(q) {
    try {
        if (q.length === 0) localStorage.removeItem(QUEUE_KEY);
        else localStorage.setItem(QUEUE_KEY, JSON.stringify(q));
    } catch (e) {
        // localStorage full or unavailable — nothing more we can do; the
        // in-memory attempt already happened. Log and move on.
        console.warn('sync-queue: could not persist queue', e);
    }
    updateIndicator();
}

// Append (or replace, when dedupeKey matches an existing entry) a write.
// Replacing in place keeps FIFO ordering roughly stable while ensuring the
// latest state per key wins.
function enqueueWrite(payload, dedupeKey) {
    const q = loadQueue();
    const entry = { dedupeKey: dedupeKey || null, payload, ts: Date.now() };
    if (dedupeKey) {
        const i = q.findIndex(e => e.dedupeKey === dedupeKey);
        if (i >= 0) q[i] = entry;
        else q.push(entry);
    } else {
        q.push(entry);
    }
    saveQueue(q);
}

export function getPendingCount() {
    return loadQueue().length;
}

// ---- Network primitive ----------------------------------------------------

// POST one payload to the Apps Script endpoint. Resolves true on a confirmed
// save, throws on network failure or an explicit {success:false} from GAS.
async function postToSheet(payload) {
    const response = await fetch(GOOGLE_SCRIPT_URL, {
        method: 'POST',
        body: JSON.stringify(payload)
    });
    // GAS returns JSON like {success:true}. Some deployments/redirects can
    // yield an opaque-ish body; if we can't parse but the HTTP status is OK,
    // treat it as success rather than re-queueing forever.
    let json = null;
    try { json = await response.json(); } catch (_) { json = null; }
    if (json && json.success === false) {
        throw new Error(json.message || 'Sheet save reported failure');
    }
    if (!json && !response.ok) {
        throw new Error(`Sheet save HTTP ${response.status}`);
    }
    return true;
}

// ---- Public write path ----------------------------------------------------

// Write-through when online, enqueue otherwise. Fire-and-forget friendly:
// callers don't need to await. Returns a promise<bool> (true = confirmed sent).
export async function sendOrQueue(payload, dedupeKey) {
    if (!GOOGLE_SCRIPT_URL) {
        // Sheets sync disabled (no secrets) — nothing durable to do.
        return false;
    }
    if (navigator.onLine) {
        try {
            await postToSheet(payload);
            // A successful direct write is a good moment to also drain any
            // backlog that accumulated during a prior offline stretch.
            if (getPendingCount() > 0) scheduleFlush();
            return true;
        } catch (e) {
            console.warn('sync-queue: direct write failed, queueing', e);
            enqueueWrite(payload, dedupeKey);
            return false;
        }
    }
    enqueueWrite(payload, dedupeKey);
    return false;
}

// ---- Flush ----------------------------------------------------------------

let _flushScheduled = false;
function scheduleFlush() {
    if (_flushScheduled) return;
    _flushScheduled = true;
    setTimeout(() => { _flushScheduled = false; flushQueue(); }, 500);
}

// Drain the queue in FIFO order. Re-reads localStorage around each await so a
// concurrent enqueue (user answers a card mid-flush) is never clobbered.
export async function flushQueue() {
    if (_flushing) return;
    if (!navigator.onLine || !GOOGLE_SCRIPT_URL) return;
    if (getPendingCount() === 0) { updateIndicator(); return; }

    _flushing = true;
    updateIndicator();
    try {
        // Bound the loop by the starting length so a runaway can't spin.
        let guard = loadQueue().length + 5;
        while (guard-- > 0) {
            if (!navigator.onLine) break;
            const q = loadQueue();
            if (q.length === 0) break;
            const entry = q[0];
            try {
                await postToSheet(entry.payload);
            } catch (e) {
                // Network/endpoint problem — stop draining, keep the tail
                // (including this entry) for the next flush attempt.
                console.warn('sync-queue: flush interrupted, will retry', e);
                break;
            }
            // Remove exactly the entry we just sent, re-reading first so an
            // enqueue that landed during the await isn't overwritten.
            const q2 = loadQueue();
            const idx = q2.findIndex(e => e.ts === entry.ts && e.dedupeKey === entry.dedupeKey);
            if (idx >= 0) q2.splice(idx, 1);
            else q2.shift(); // fallback: entry was de-duped/replaced; drop head
            saveQueue(q2);
        }
    } finally {
        _flushing = false;
        updateIndicator();
    }
}

// ---- Progress overlay -----------------------------------------------------

// When progress is (re)loaded from Sheets, any writes still sitting in the
// queue are newer than what the sheet knows. Overlay them onto progressData so
// a refresh (e.g. reconnect triggers loadUserProgressFromSheet) never visually
// regresses un-synced local answers. Flag/level entries are skipped.
export function applyPendingProgressOverlay(progress) {
    if (!progress) return progress;
    const q = loadQueue();
    for (const e of q) {
        const p = e && e.payload;
        if (!p || p.action !== 'save') continue;
        if (p.sheet === 'FlaggedWords') continue;
        if (p.word === '_LEVEL_ESTIMATE_') continue;
        if (!p.wordId || p.correct === undefined) continue;
        progress[p.wordId] = {
            word: p.word,
            language: p.language,
            correct: p.correct,
            wrong: p.wrong,
            lastCorrect: p.lastCorrect,
            lastWrong: p.lastWrong,
            lastSeen: p.lastSeen
        };
    }
    return progress;
}

// ---- Indicator ------------------------------------------------------------

// Small status pill in the top bar. Three visible states:
//   offline           → "Offline" (+ "· N pending" if any queued)
//   online + pending  → "Syncing N…"
//   online + empty    → hidden
export function updateIndicator() {
    const el = document.getElementById('syncStatusIndicator');
    if (!el) return;
    const pending = getPendingCount();
    const online = navigator.onLine;

    el.classList.remove('is-offline', 'is-pending');
    if (!online) {
        el.classList.add('is-offline');
        el.classList.remove('hidden');
        el.textContent = pending > 0 ? `Offline · ${pending} pending` : 'Offline';
        el.title = pending > 0
            ? `${pending} change${pending === 1 ? '' : 's'} will sync when you reconnect`
            : 'You are offline. Progress is saved on this device.';
    } else if (pending > 0) {
        el.classList.add('is-pending');
        el.classList.remove('hidden');
        el.textContent = `Syncing ${pending}…`;
        el.title = `Syncing ${pending} pending change${pending === 1 ? '' : 's'} to your account`;
    } else {
        el.classList.add('hidden');
        el.textContent = '';
        el.title = '';
    }
}

// ---- Init -----------------------------------------------------------------

function onOnline() {
    updateIndicator();
    flushQueue();
}
function onOffline() {
    updateIndicator();
}

// Wire connectivity listeners + periodic retry. Safe to call more than once.
export function initSync() {
    updateIndicator();
    if (!_intervalStarted) {
        _intervalStarted = true;
        window.addEventListener('online', onOnline);
        window.addEventListener('offline', onOffline);
        setInterval(() => {
            if (navigator.onLine && getPendingCount() > 0) flushQueue();
        }, FLUSH_INTERVAL_MS);
    }
    // Attempt an initial drain in case we booted online with a backlog.
    if (navigator.onLine) flushQueue();
}

// Expose for cross-module (non-import) callers and debugging.
window.sendOrQueue = sendOrQueue;
window.flushQueue = flushQueue;
window.getPendingCount = getPendingCount;
window.applyPendingProgressOverlay = applyPendingProgressOverlay;
window.updateSyncIndicator = updateIndicator;
window.initSync = initSync;
