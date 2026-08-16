import './state.js?v=20260816n';
import { sendOrQueue } from './sync-queue.js?v=20260816n';
import {
    filterExamplesForSongs,
    filterVocabularyForSongs,
    selectedSongIdSet
} from './song-sets-core.js?v=20260816n';

const STORAGE_PREFIX = 'fluency_song_set_v1:';
let draftSongIds = new Set();
let remoteLoaded = false;

function sourceSlug() {
    return String(window._urlArtistSlug || activeArtist?.slug || 'lyrics');
}

function storageKey() {
    return `${STORAGE_PREFIX}${sourceSlug()}`;
}

function readLocalSongSet() {
    try {
        const parsed = JSON.parse(localStorage.getItem(storageKey()) || 'null');
        return parsed && Array.isArray(parsed.songIds) ? parsed : null;
    } catch (_) {
        return null;
    }
}

function writeLocalSongSet(record) {
    try { localStorage.setItem(storageKey(), JSON.stringify(record)); } catch (_) {}
}

function validSongIds(songIds) {
    return Array.from(selectedSongIdSet(artistSongCatalog, songIds));
}

export async function initArtistSongSelection() {
    if (!activeArtist?.songsPath) {
        artistSongCatalog = null;
        selectedSongIds = [];
        return null;
    }
    const response = await fetch(activeArtist.songsPath);
    if (!response.ok) throw new Error(`Song catalog HTTP ${response.status}`);
    window.trackDataFreshness?.(response);
    const catalog = await response.json();
    if (catalog?.schemaVersion !== 1 || !Array.isArray(catalog.songs) || !catalog.songs.length) {
        throw new Error('Song catalog is empty or unsupported.');
    }
    artistSongCatalog = catalog;
    const local = readLocalSongSet();
    selectedSongIds = validSongIds(local?.songIds || catalog.songs.map(song => song.id));
    window._activeSongSetUpdatedAt = local?.updatedAt || '';
    reconcileRemoteSongSet().catch(error => console.warn('Song-set sync deferred:', error));
    return catalog;
}

async function reconcileRemoteSongSet() {
    if (remoteLoaded || !currentUser || currentUser.isGuest || !GOOGLE_SCRIPT_URL || !artistSongCatalog) return;
    remoteLoaded = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3500);
    try {
        const response = await fetch(GOOGLE_SCRIPT_URL, {
            method: 'POST',
            body: JSON.stringify({ action: 'loadSongSets', user: currentUser.initials }),
            signal: controller.signal
        });
        const result = await response.json();
        if (!result?.success || !Array.isArray(result.data?.songSets)) return;
        const remote = result.data.songSets.find(row =>
            row.source === sourceSlug() && row.setId === 'active');
        if (!remote || !Array.isArray(remote.songIds)) return;
        const remoteTime = Date.parse(remote.updatedAt || '') || 0;
        const localTime = Date.parse(window._activeSongSetUpdatedAt || '') || 0;
        if (remoteTime <= localTime) return;
        selectedSongIds = validSongIds(remote.songIds);
        window._activeSongSetUpdatedAt = remote.updatedAt;
        writeLocalSongSet({ songIds: selectedSongIds, updatedAt: remote.updatedAt });
        refilterCachedExamples();
        window.dispatchEvent(new CustomEvent('fluency-song-selection-changed', {
            detail: { source: sourceSlug(), remote: true }
        }));
    } finally {
        clearTimeout(timeout);
    }
}

export function filterActiveSongVocabulary(vocabulary) {
    return filterVocabularyForSongs(vocabulary, artistSongCatalog, selectedSongIds);
}

export function setActiveExamplesData(examples) {
    window._cachedExamplesDataRaw = examples;
    window._cachedExamplesData = filterExamplesForSongs(examples, artistSongCatalog, selectedSongIds);
    return window._cachedExamplesData;
}

function refilterCachedExamples() {
    if (window._cachedExamplesDataRaw) setActiveExamplesData(window._cachedExamplesDataRaw);
}

export function songSelectionSummary() {
    if (!artistSongCatalog?.songs?.length) return 'Choose another artist';
    const count = selectedSongIds.length;
    const total = artistSongCatalog.songs.length;
    if (count === total) return `All ${total} songs`;
    if (count === 1) {
        return artistSongCatalog.songs.find(song => String(song.id) === String(selectedSongIds[0]))?.title
            || '1 song';
    }
    return `${count} of ${total} songs`;
}

function updatePickerCount() {
    const count = document.getElementById('songSetCount');
    const apply = document.getElementById('applySongSetBtn');
    if (count) count.textContent = `${draftSongIds.size} selected`;
    if (apply) apply.disabled = draftSongIds.size === 0;
}

function renderSongOptions() {
    const list = document.getElementById('songSetList');
    if (!list || !artistSongCatalog) return;
    const query = String(document.getElementById('songSetSearch')?.value || '').trim().toLocaleLowerCase();
    const songs = artistSongCatalog.songs.filter(song =>
        !query || `${song.title} ${song.artist}`.toLocaleLowerCase().includes(query));
    list.replaceChildren();
    if (!songs.length) {
        const empty = document.createElement('p');
        empty.className = 'song-set-empty';
        empty.textContent = 'No songs match that search.';
        list.appendChild(empty);
        return;
    }
    const fragment = document.createDocumentFragment();
    for (const song of songs) {
        const label = document.createElement('label');
        label.className = 'song-set-option';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.value = String(song.id);
        checkbox.checked = draftSongIds.has(String(song.id));
        checkbox.addEventListener('change', () => {
            if (checkbox.checked) draftSongIds.add(checkbox.value);
            else draftSongIds.delete(checkbox.value);
            updatePickerCount();
        });
        const copy = document.createElement('span');
        const title = document.createElement('strong');
        title.textContent = song.title;
        copy.appendChild(title);
        if (song.artist) {
            const artist = document.createElement('small');
            artist.textContent = song.artist;
            copy.appendChild(artist);
        }
        label.append(checkbox, copy);
        fragment.appendChild(label);
    }
    list.appendChild(fragment);
}

export function showSongSetPicker() {
    if (!artistSongCatalog?.songs?.length) return;
    draftSongIds = new Set(selectedSongIds.map(String));
    const modal = document.getElementById('songSetModal');
    const title = document.getElementById('songSetTitle');
    const intro = document.getElementById('songSetIntro');
    const search = document.getElementById('songSetSearch');
    if (title) title.textContent = `Choose ${activeArtist?.name || 'Lyrics'} songs`;
    if (intro) intro.textContent = 'Cards are limited by complete per-song membership; sampled lyric examples are limited to the selected songs too.';
    if (search) search.value = '';
    document.getElementById('songSetStatus').textContent = '';
    renderSongOptions();
    updatePickerCount();
    modal?.classList.remove('hidden');
    search?.focus();
}

function hideSongSetPicker() {
    document.getElementById('songSetModal')?.classList.add('hidden');
}

async function applySongSet() {
    if (!draftSongIds.size || !artistSongCatalog) return;
    const status = document.getElementById('songSetStatus');
    const apply = document.getElementById('applySongSetBtn');
    apply.disabled = true;
    status.textContent = 'Saving song selection…';
    const updatedAt = new Date().toISOString();
    selectedSongIds = validSongIds(Array.from(draftSongIds));
    window._activeSongSetUpdatedAt = updatedAt;
    writeLocalSongSet({ songIds: selectedSongIds, updatedAt });
    if (currentUser && !currentUser.isGuest) {
        await sendOrQueue({
            action: 'saveSongSet',
            user: currentUser.initials,
            setId: 'active',
            source: sourceSlug(),
            name: activeArtist?.name || sourceSlug(),
            language: activeArtist?.language || selectedLanguage,
            songIds: selectedSongIds,
            updatedAt
        }, `song-set|${currentUser.initials}|${sourceSlug()}|active`);
    }
    refilterCachedExamples();
    hideSongSetPicker();
    window.dispatchEvent(new CustomEvent('fluency-song-selection-changed', {
        detail: { source: sourceSlug(), remote: false }
    }));
}

function setupSongSetPicker() {
    const modal = document.getElementById('songSetModal');
    if (!modal || modal.dataset.listenersReady === '1') return;
    modal.dataset.listenersReady = '1';
    document.getElementById('songSetSearch')?.addEventListener('input', renderSongOptions);
    document.getElementById('selectAllSongsBtn')?.addEventListener('click', () => {
        draftSongIds = new Set((artistSongCatalog?.songs || []).map(song => String(song.id)));
        renderSongOptions();
        updatePickerCount();
    });
    document.getElementById('clearAllSongsBtn')?.addEventListener('click', () => {
        draftSongIds.clear();
        renderSongOptions();
        updatePickerCount();
    });
    document.getElementById('applySongSetBtn')?.addEventListener('click', () => {
        applySongSet().catch(error => {
            document.getElementById('songSetStatus').textContent = error?.message || 'Could not save the song selection.';
            document.getElementById('applySongSetBtn').disabled = false;
        });
    });
    document.getElementById('closeSongSetModal')?.addEventListener('click', hideSongSetPicker);
    document.getElementById('cancelSongSetBtn')?.addEventListener('click', hideSongSetPicker);
    modal.addEventListener('click', event => {
        if (event.target === modal) hideSongSetPicker();
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !modal.classList.contains('hidden')) hideSongSetPicker();
    });
}

setupSongSetPicker();

window.initArtistSongSelection = initArtistSongSelection;
window.filterActiveSongVocabulary = filterActiveSongVocabulary;
window.setActiveExamplesData = setActiveExamplesData;
window.showSongSetPicker = showSongSetPicker;
window.songSelectionSummary = songSelectionSummary;
