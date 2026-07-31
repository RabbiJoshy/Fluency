// Shared durable storage for offline content, local-first state, and sync.
// Keep this module dependency-free so it can be tested and migrated safely.
const DB_NAME = 'fluency-offline';
const DB_VERSION = 3;
const STORES = ['operations', 'receipts', 'downloads', 'localState', 'migrations'];

let dbPromise;

export function openOfflineDb() {
    if (!('indexedDB' in globalThis)) return Promise.reject(new Error('IndexedDB unavailable'));
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains('operations')) {
                const store = db.createObjectStore('operations', { keyPath: 'id' });
                store.createIndex('accountCreated', ['accountId', 'createdAt']);
                store.createIndex('retryState', 'retryState');
            }
            if (!db.objectStoreNames.contains('receipts')) {
                db.createObjectStore('receipts', { keyPath: 'idempotencyKey' });
            }
            if (!db.objectStoreNames.contains('downloads')) {
                db.createObjectStore('downloads', { keyPath: 'sourceId' });
            }
            if (!db.objectStoreNames.contains('localState')) {
                db.createObjectStore('localState', { keyPath: 'key' });
            }
            if (!db.objectStoreNames.contains('migrations')) {
                db.createObjectStore('migrations', { keyPath: 'id' });
            }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
        request.onblocked = () => reject(new Error('Offline database upgrade blocked'));
    });
    return dbPromise;
}

export async function dbRequest(storeName, mode, callback) {
    const db = await openOfflineDb();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, mode);
        const result = callback(tx.objectStore(storeName));
        tx.oncomplete = () => resolve(result?.result);
        tx.onerror = () => reject(tx.error || result?.error);
        tx.onabort = () => reject(tx.error || new Error('Offline transaction aborted'));
    });
}

export const dbGet = (store, key) => dbRequest(store, 'readonly', s => s.get(key));
export const dbGetAll = store => dbRequest(store, 'readonly', s => s.getAll());
export const dbPut = (store, value) => dbRequest(store, 'readwrite', s => s.put(value));
export const dbDelete = (store, key) => dbRequest(store, 'readwrite', s => s.delete(key));

export async function dbMutate(storeName, mutator) {
    const db = await openOfflineDb();
    return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, 'readwrite');
        const store = tx.objectStore(storeName);
        const request = store.getAll();
        let result;
        request.onsuccess = () => {
            result = mutator(request.result, store);
        };
        tx.oncomplete = () => resolve(result);
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error || new Error('Offline transaction aborted'));
    });
}

export function makeOperationId(accountId, dedupeKey, createdAt = Date.now()) {
    const base = dedupeKey || `${createdAt}-${crypto.randomUUID?.() || Math.random().toString(36).slice(2)}`;
    return `${accountId || 'anonymous'}|${base}`;
}

export { DB_NAME, DB_VERSION, STORES };
