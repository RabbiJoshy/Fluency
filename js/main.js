import './state.js';
import './speech.js';
import './artist-ui.js';
import './auth.js';
import './spotify.js';
import './estimation.js';
import './config.js';
import './progress.js';
import './ui.js';
import './vocab.js?v=20260420g';
import './flashcards.js?v=20260420g';

// Register service worker for PWA functionality
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('service-worker.js')
            .then(registration => console.log('SW registered'))
            .catch(err => console.log('SW registration failed'));
    });
}

// All available artist configs, keyed by slug. Loaded once from artists.json.
let allArtistsConfig = null;
// Slugs of artists currently selected for multi-artist merge
let selectedArtistSlugs = [];

// Resolve artist from URL params: ?artist=bad-bunny or ?mode=badbunny (legacy alias)
async function resolveArtist() {
    const params = new URLSearchParams(window.location.search);
    let artistSlug = params.get('artist');

    // Legacy alias: ?mode=badbunny → ?artist=bad-bunny (keep for PWA home screen installs)
    if (!artistSlug && params.get('mode') === 'badbunny') {
        artistSlug = 'bad-bunny';
    }

    if (!artistSlug) return; // normal mode

    try {
        const response = await fetch('config/artists.json');
        allArtistsConfig = await response.json();

        // Tag each config with its slug
        for (const [slug, cfg] of Object.entries(allArtistsConfig)) {
            cfg.slug = slug;
        }

        const artistConfig = allArtistsConfig[artistSlug];
        if (artistConfig) {
            activeArtist = artistConfig;

            // Store the URL artist slug — this is the immutable primary artist
            window._urlArtistSlug = artistSlug;

            // Start with the URL artist; user can add more via settings
            selectedArtistSlugs = [artistSlug];
        } else {
            console.warn(`Unknown artist slug: ${artistSlug}`);
        }
    } catch (error) {
        console.error('Failed to load artists.json:', error);
    }
}

await resolveArtist();

// Expose for use by ui.js artist selection
window._allArtistsConfig = allArtistsConfig;
window._selectedArtistSlugs = selectedArtistSlugs;

// Add artist mode class to body and load albums dictionary
if (activeArtist) {
    document.body.classList.add('artist-mode');
    loadArtistAlbumsDictionary();
}

loadConfig().then(async () => {
    // Fire-and-forget: load Spanish rank lookup for personal easiness scoring
    if (window.loadSpanishRanks) window.loadSpanishRanks();
    if (window.loadConjugationData) window.loadConjugationData();
    renderLanguageTabs();
    // Set first language with data as default (but don't auto-select it)
    const firstLang = Object.keys(config.languages).find(lang => config.languages[lang].hasData !== false) || Object.keys(config.languages)[0];
    selectedLanguage = firstLang;
    applyLanguageColorTheme();
    setupGroupSizeSelector();
    setupLemmaToggle();
    setupCognateToggle();
    setupPercentModeButton();
    setupEstimationModal();
    setupTooltipHandlers();
    setupAuthEventListeners();

    // Wire shared top bar buttons (How to start, Estimate Level, mode switch, gear)
    document.getElementById('helpBtn').addEventListener('click', () => openHelpModal());
    document.getElementById('topBarGearBtn').addEventListener('click', () => showSettingsModal());
    // Level-estimate CTA (shown when user has no progress yet, in the slot
    // where the personal coverage bar will live once they do).
    document.getElementById('levelEstimateCTABtn').addEventListener('click', () => openEstimationModal());
    setupFindWord();
    document.getElementById('topBarUserName').addEventListener('click', () => {
        if (currentUser && !currentUser.isGuest && selectedLanguage) {
            // In flashcard mode, show set stats; on setup page, show total stats
            const appContent = document.getElementById('appContent');
            if (appContent && !appContent.classList.contains('hidden')) {
                showStatsModal();
            } else {
                showTotalStatsModal();
            }
        }
    });
    setupModeSwitchButton();
    document.getElementById('closeHelpModal').addEventListener('click', () => {
        document.getElementById('helpModal').classList.add('hidden');
    });
    setupTabSwitching(document.getElementById('helpModal'));
    // Hide floating gear — replaced by gear in the top bar
    document.getElementById('gearBtn').style.display = 'none';
    await migrateLocalStorageIds();
    await migrateLocalStorageIdsV2();
    await loadSecrets();
    // Retry Spotify player init now that client ID is available (handles race with SDK load)
    if (window._spotifyTryInit) window._spotifyTryInit();
    checkAuthentication();

    // Set user name in top bar immediately (don't wait for progress load)
    const userName = currentUser ? (currentUser.isGuest ? 'GUEST' : currentUser.initials) : '';
    document.getElementById('topBarUserName').textContent = userName;

    // Shareable landing URL: ?about=1 opens the About modal on top of whatever
    // state the app lands in. If the visitor has no session, they see the
    // landing layered over the auth modal and can pick an auth path from the
    // CTAs at the bottom of the About content. If they DO have a session,
    // they see the landing over the app and can dismiss back to it.
    if (new URLSearchParams(window.location.search).has('about')) {
        window.openAboutProjectModal && window.openAboutProjectModal();
    }

    // Start loading progress from Google Sheets (loads cache synchronously, then fetches)
    let progressPromise = Promise.resolve(false);
    if (currentUser && !currentUser.isGuest) {
        progressPromise = loadUserProgressFromSheet();
    }

    // Render UI immediately using cached progress data
    if (activeArtist) {
        try {
            selectedLanguage = activeArtist.language || 'spanish';
            applyLanguageColorTheme();
            // Hide step 1 entirely (language auto-selected)
            document.getElementById('step1').style.display = 'none';
            // Renumber steps: 1, 2, 3, 4 (since step 1 is hidden)
            document.querySelector('#step2 .step-number').textContent = '1';
            document.querySelector('#lemmaToggleContainer .step-number').textContent = '2';
            document.querySelector('#cognateToggleContainer .step-number').textContent = '3';
            await loadPpmData(activeArtist.language || 'spanish');
            document.getElementById('step2').style.display = 'block';
            document.getElementById('step2Title').textContent = 'Choose Level';
            document.getElementById('percentModeBtn').style.display = 'none';
            updateStep2Tooltip();
            updateStep5Tooltip();
            await updateLemmaToggleVisibility();
            await updateCognateToggleVisibility();
            renderLevelSelector(activeArtist.language || 'spanish');
            await updateExclusionBars();
            setupArtistSelection();
        } finally {
            // Always reveal body, even if something above threw
            document.documentElement.classList.remove('artist-loading');
        }
    }

    // Wait for Sheets refresh to complete; re-render set badges if data changed
    const dataChanged = await progressPromise;
    if (dataChanged && selectedLanguage) {
        try { await renderRangeSelector(); } catch (e) { /* range selector may not be visible yet */ }
    }
});

// Mode switch button: toggle between normal and artist modes
async function setupModeSwitchButton() {
    const btn = document.getElementById('modeSwitchBtn');
    if (!btn) return;

    if (activeArtist) {
        // In artist mode → offer switch to standard
        btn.textContent = 'Standard Mode';
        btn.style.display = '';
        btn.addEventListener('click', () => {
            window.location.href = window.location.pathname;
        });
    } else {
        // In normal mode → offer switch to artist mode
        // Load artists.json to discover available artists
        try {
            const artists = allArtistsConfig || await fetch('config/artists.json').then(r => r.json());
            const slugs = Object.keys(artists);
            if (slugs.length === 0) return;

            if (slugs.length === 1) {
                btn.textContent = `${artists[slugs[0]].name} Lyrics`;
                btn.style.display = '';
                btn.addEventListener('click', () => {
                    window.location.href = `${window.location.pathname}?artist=${slugs[0]}`;
                });
            } else {
                btn.textContent = 'Lyrics Mode';
                btn.style.display = '';
                btn.addEventListener('click', () => {
                    // Show a small picker dropdown
                    showArtistPicker(btn, artists);
                });
            }
        } catch (e) {
            // No artists.json or fetch failed — hide button
            console.warn('Could not load artists for mode switch:', e);
        }
    }
}

function showArtistPicker(anchorBtn, artists) {
    // Remove existing picker if open
    const existing = document.getElementById('modeSwitchPicker');
    if (existing) { existing.remove(); return; }

    const picker = document.createElement('div');
    picker.id = 'modeSwitchPicker';
    picker.className = 'mode-switch-picker';

    for (const [slug, cfg] of Object.entries(artists)) {
        const item = document.createElement('button');
        item.className = 'mode-switch-picker-item';
        item.textContent = cfg.name;
        item.addEventListener('click', () => {
            window.location.href = `${window.location.pathname}?artist=${slug}`;
        });
        picker.appendChild(item);
    }

    anchorBtn.style.position = 'relative';
    anchorBtn.appendChild(picker);

    // Close on outside click
    const closeHandler = (e) => {
        if (!picker.contains(e.target) && e.target !== anchorBtn) {
            picker.remove();
            document.removeEventListener('click', closeHandler);
        }
    };
    setTimeout(() => document.addEventListener('click', closeHandler), 0);
}

// ===== Find-word: simple lookup of a word across the current language's vocab =====
let _findWordIndex = null; // [{ targetWord, lemma, rank, displayRank, id, firstMeaning }]
let _findWordIndexKey = null;

function normalizeForSearch(s) {
    return (s || '')
        .toString()
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '');
}

function findWordCacheKey() {
    const slugs = (window._selectedArtistSlugs || []).slice().sort().join(',');
    // Filter toggles change displayRank; include them so the cache invalidates.
    return [
        selectedLanguage || '',
        slugs,
        useLemmaMode ? '1' : '0',
        excludeCognates ? '1' : '0',
        hideSingleOccurrence ? '1' : '0'
    ].join('|');
}

async function buildFindWordIndex() {
    if (!selectedLanguage) return [];
    const key = findWordCacheKey();
    if (_findWordIndex && _findWordIndexKey === key) return _findWordIndex;
    const langConfig = config.languages[selectedLanguage];
    if (!langConfig) return [];
    let vocabularyData;
    // Reuse the cached merged index in multi-artist mode when present
    if (activeArtist && window._cachedMergedIndex) {
        vocabularyData = window._cachedMergedIndex;
    } else {
        vocabularyData = await window.fetchAndJoinIndex(langConfig);
    }
    vocabularyData.forEach((item, idx) => { if (!item.rank) item.rank = idx + 1; });
    // Build displayRank via the normal filter pipeline so ranks line up with the set buttons
    const { vocab: filtered } = window.buildFilteredVocab(vocabularyData);
    const byRank = new Map();
    filtered.forEach(it => byRank.set(it.rank, it.displayRank));
    const idx = vocabularyData.map(item => {
        const meanings = item.meanings || [];
        const firstMeaning = meanings.find(m => m && m.meaning && m.pos !== 'MWE' && m.pos !== 'CLITIC' && m.pos !== 'SENSE_CYCLE');
        return {
            targetWord: item.word || item.targetWord || '',
            lemma: item.lemma || '',
            rank: item.rank,
            displayRank: byRank.get(item.rank) || null,
            id: item.id || window.getWordId(item),
            firstMeaning: firstMeaning ? firstMeaning.meaning : ''
        };
    });
    _findWordIndex = idx;
    _findWordIndexKey = key;
    return idx;
}

function renderFindResults(query) {
    const resultsEl = document.getElementById('findWordResults');
    const statusEl = document.getElementById('findWordStatus');
    resultsEl.innerHTML = '';
    const q = normalizeForSearch(query).trim();
    if (!q) {
        statusEl.textContent = _findWordIndex ? `${_findWordIndex.length.toLocaleString()} words loaded` : '';
        return;
    }
    if (!_findWordIndex) { statusEl.textContent = 'Loading…'; return; }
    const matches = [];
    for (const entry of _findWordIndex) {
        const w = normalizeForSearch(entry.targetWord);
        const l = normalizeForSearch(entry.lemma);
        const exact = w === q || l === q;
        const starts = w.startsWith(q) || l.startsWith(q);
        const contains = w.includes(q) || l.includes(q);
        if (exact || starts || contains) {
            matches.push({ entry, score: exact ? 0 : (starts ? 1 : 2) });
        }
        if (matches.length > 300) break;
    }
    matches.sort((a, b) => a.score - b.score || (a.entry.rank || 1e9) - (b.entry.rank || 1e9));
    const top = matches.slice(0, 30);
    if (top.length === 0) {
        statusEl.textContent = 'No matches';
        return;
    }
    statusEl.textContent = `${matches.length} match${matches.length === 1 ? '' : 'es'}${matches.length > top.length ? ` — showing top ${top.length}` : ''}`;
    for (const { entry } of top) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'find-word-result';
        const lemmaHTML = (entry.lemma && entry.lemma !== entry.targetWord)
            ? `<span class="fw-lemma">${entry.lemma}</span>` : '';
        const rankHTML = entry.displayRank ? `<span class="fw-rank">#${entry.displayRank}</span>` : '';
        btn.innerHTML = `
            <span class="fw-word">${entry.targetWord}</span>
            ${lemmaHTML}
            <span class="fw-meaning">${(entry.firstMeaning || '').replace(/</g, '&lt;')}</span>
            ${rankHTML}`;
        btn.addEventListener('click', () => jumpToFoundWord(entry));
        resultsEl.appendChild(btn);
    }
}

async function jumpToFoundWord(entry) {
    const statusEl = document.getElementById('findWordStatus');
    if (!entry.displayRank) {
        statusEl.textContent = 'Word is excluded by current filters (cognate/lemma/mastered). Adjust filters and try again.';
        return;
    }
    const gs = (typeof groupSize === 'number' && groupSize > 0) ? groupSize : 25;
    const rangeStart = Math.floor((entry.displayRank - 1) / gs) * gs + 1;
    const rangeEnd = rangeStart + gs;
    const rangeStr = `${rangeStart}-${rangeEnd}`;
    statusEl.textContent = `Loading set ${rangeStr}…`;
    // Close the modal now; loadVocabularyData drives its own loading UI
    document.getElementById('findWordModal').classList.add('hidden');
    try {
        await window.loadVocabularyData(rangeStr, { includeWordId: entry.id });
    } catch (e) {
        console.error('Find-word: loadVocabularyData failed', e);
        return;
    }
    // loadVocabularyData schedules a ~800ms setTimeout before initializing the card view.
    // Wait past that, then try to locate the card in the current deck.
    setTimeout(() => {
        const targetId = entry.id;
        const targetWord = (entry.targetWord || '').toLowerCase();
        const targetLemma = (entry.lemma || '').toLowerCase();
        let found = -1;
        for (let i = 0; i < (flashcards || []).length; i++) {
            const c = flashcards[i];
            if (targetId && (c.id === targetId || c.fullId === targetId)) { found = i; break; }
            if (c.targetWord && c.targetWord.toLowerCase() === targetWord &&
                (!targetLemma || (c.lemma || '').toLowerCase() === targetLemma)) {
                found = i; break;
            }
        }
        if (found >= 0) {
            window.currentIndex = found;
            if (window.updateCard) window.updateCard();
        } else {
            console.warn('Find-word: word loaded set but was filtered out of deck', entry);
        }
    }, 950);
}

function setupFindWord() {
    const btn = document.getElementById('findWordBtn');
    const modal = document.getElementById('findWordModal');
    const closeBtn = document.getElementById('closeFindWordModal');
    const input = document.getElementById('findWordInput');
    if (!btn || !modal || !input) return;

    btn.addEventListener('click', async () => {
        modal.classList.remove('hidden');
        input.value = '';
        document.getElementById('findWordResults').innerHTML = '';
        document.getElementById('findWordStatus').textContent = 'Loading vocabulary…';
        setTimeout(() => input.focus(), 50);
        try {
            await buildFindWordIndex();
            renderFindResults(input.value);
        } catch (e) {
            console.error('Find-word: failed to build index', e);
            document.getElementById('findWordStatus').textContent = 'Could not load vocabulary.';
        }
    });

    closeBtn.addEventListener('click', () => modal.classList.add('hidden'));
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.classList.add('hidden');
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            modal.classList.add('hidden');
        }
    });

    let debounce = null;
    input.addEventListener('input', () => {
        clearTimeout(debounce);
        debounce = setTimeout(() => renderFindResults(input.value), 80);
    });
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const first = document.querySelector('#findWordResults .find-word-result');
            if (first) first.click();
        }
    });
}
