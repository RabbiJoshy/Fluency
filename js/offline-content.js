import { dbDelete, dbGetAll, dbPut } from './offline-db.js?v=20260805k';

const MANIFEST_URL = 'config/offline-content-manifest.json';
const CONTENT_CACHE_PREFIX = 'fluency-content-';
let manifest = null;
let activeDownload = null;

function notifyContentCachesChanged() {
    navigator.serviceWorker?.controller?.postMessage({ type: 'CONTENT_CACHES_CHANGED' });
}

const fmt = bytes => {
    if (!Number.isFinite(bytes)) return 'Unknown';
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
    return `${value.toFixed(unit < 2 ? 0 : 1)} ${units[unit]}`;
};

export async function loadOfflineManifest({ refresh = false } = {}) {
    if (manifest && !refresh) return manifest;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4000);
    let response;
    try {
        response = await fetch(MANIFEST_URL, {
            cache: refresh ? 'no-cache' : 'default', signal: controller.signal
        });
    } finally {
        clearTimeout(timeout);
    }
    if (!response.ok) throw new Error(`Content catalogue HTTP ${response.status}`);
    const next = await response.json();
    if (next.schemaVersion !== 1 || !Array.isArray(next.sources)) {
        throw new Error('Unsupported offline content catalogue');
    }
    manifest = next;
    return manifest;
}

async function sha256(response) {
    if (!crypto.subtle) return null;
    const digest = await crypto.subtle.digest('SHA-256', await response.clone().arrayBuffer());
    return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
}

export async function downloadSource(sourceId, onProgress = () => {}) {
    const catalogue = await loadOfflineManifest();
    const source = catalogue.sources.find(item => item.id === sourceId);
    if (!source) throw new Error('Unknown offline source');
    const controller = new AbortController();
    activeDownload?.abort();
    activeDownload = controller;
    const stagingName = `${CONTENT_CACHE_PREFIX}staging-${source.id}-${source.contentVersion}`;
    const finalName = `${CONTENT_CACHE_PREFIX}${source.id}-${source.contentVersion}`;
    const staging = await caches.open(stagingName);
    let downloaded = 0;
    try {
        await dbPut('downloads', {
            sourceId, contentVersion: source.contentVersion, status: 'downloading',
            filesCompleted: 0, bytesDownloaded: 0, updatedAt: Date.now()
        });
        for (const [index, file] of source.files.entries()) {
            const response = await fetch(file.path, { signal: controller.signal, cache: 'no-store' });
            if (!response.ok) throw new Error(`${file.path}: HTTP ${response.status}`);
            if (file.sha256 && crypto.subtle) {
                const actual = await sha256(response);
                if (actual !== file.sha256) throw new Error(`${file.path}: integrity check failed`);
            }
            await staging.put(file.path, response.clone());
            downloaded += file.bytes;
            onProgress({ source, downloaded, total: source.storageBytes, file: index + 1 });
            await dbPut('downloads', {
                sourceId, contentVersion: source.contentVersion, status: 'downloading',
                filesCompleted: index + 1, bytesDownloaded: downloaded, updatedAt: Date.now()
            });
        }
        const existingFinal = await caches.open(finalName);
        for (const request of await staging.keys()) {
            await existingFinal.put(request, await staging.match(request));
        }
        // The worker ignores version caches without this final marker, so a
        // terminated copy can never become the active partially-written deck.
        await existingFinal.put('/__fluency_content_complete__', new Response(source.contentVersion));
        await dbPut('downloads', {
            sourceId, contentVersion: source.contentVersion, status: 'installed',
            filesCompleted: source.files.length, bytesDownloaded: downloaded,
            installedAt: Date.now(), lastUsedAt: Date.now(), updatedAt: Date.now()
        });
        await caches.delete(stagingName);
        for (const name of await caches.keys()) {
            if (name.startsWith(`${CONTENT_CACHE_PREFIX}${source.id}-`) && name !== finalName) {
                await caches.delete(name);
            }
        }
        notifyContentCachesChanged();
    } catch (error) {
        await dbPut('downloads', {
            sourceId, contentVersion: source.contentVersion,
            status: error.name === 'AbortError' ? 'paused' : 'failed',
            filesCompleted: 0, bytesDownloaded: downloaded, updatedAt: Date.now(),
            lastError: error.name === 'AbortError' ? 'Download paused' : String(error.message || error)
        });
        throw error;
    } finally {
        if (activeDownload === controller) activeDownload = null;
    }
    await renderOfflineContent();
}

export function cancelOfflineDownload() {
    activeDownload?.abort();
}

export async function removeOfflineSource(sourceId) {
    for (const name of await caches.keys()) {
        if (name.startsWith(`${CONTENT_CACHE_PREFIX}${sourceId}-`)) await caches.delete(name);
    }
    await dbDelete('downloads', sourceId);
    notifyContentCachesChanged();
    await renderOfflineContent();
}

export async function getOfflineContentState() {
    const catalogue = await loadOfflineManifest();
    const records = await dbGetAll('downloads');
    const byId = Object.fromEntries(records.map(record => [record.sourceId, record]));
    return catalogue.sources.map(source => ({ ...source, local: byId[source.id] || null }));
}

export async function renderOfflineContent() {
    const target = document.getElementById('offlineContentList');
    if (!target) return;
    try {
        const sources = await getOfflineContentState();
        target.innerHTML = sources.map(source => {
            const installed = source.local?.status === 'installed';
            const update = installed && source.local.contentVersion !== source.contentVersion;
            const status = installed ? (update ? 'Update available' : 'Downloaded') :
                source.local?.status === 'downloading' ? 'Downloading…' :
                source.local?.status === 'failed' ? 'Download failed' : 'Not downloaded';
            return `<article class="offline-source" data-source="${source.id}">
                <div><strong>${source.name}</strong><small>${source.scopeLabel} · ${fmt(source.storageBytes)} device space · ${fmt(source.transferBytes)} transfer</small></div>
                <span class="offline-source-status">${status}</span>
                <button type="button" data-offline-action="${installed && !update ? 'remove' : 'download'}">${installed && !update ? 'Remove' : update ? 'Update' : 'Download'}</button>
                ${source.local?.lastError ? `<small class="offline-error">${source.local.lastError}</small>` : ''}
            </article>`;
        }).join('');
        target.querySelectorAll('[data-offline-action]').forEach(button => {
            button.addEventListener('click', async () => {
                const sourceId = button.closest('[data-source]').dataset.source;
                button.disabled = true;
                try {
                    if (button.dataset.offlineAction === 'remove') await removeOfflineSource(sourceId);
                    else await downloadSource(sourceId, ({ downloaded, total }) => {
                        button.textContent = `${Math.round(downloaded / total * 100)}%`;
                    });
                } catch (error) {
                    if (error.name !== 'AbortError') console.warn('Offline content:', error);
                    await renderOfflineContent();
                }
            });
        });
    } catch (error) {
        target.textContent = `Offline content catalogue unavailable: ${error.message}`;
    }
}

export async function initOfflineContent() {
    document.getElementById('downloadEverythingBtn')?.addEventListener('click', async event => {
        event.currentTarget.disabled = true;
        try {
            for (const source of await getOfflineContentState()) {
                if (source.local?.status !== 'installed' || source.local.contentVersion !== source.contentVersion) {
                    await downloadSource(source.id);
                }
            }
        } finally {
            event.currentTarget.disabled = false;
            await renderOfflineContent();
        }
    });
    document.getElementById('cancelOfflineDownloadBtn')?.addEventListener('click', cancelOfflineDownload);
    await renderOfflineContent();
}

window.renderOfflineContent = renderOfflineContent;
