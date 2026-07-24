import './state.js?v=20260724h';
import './sync-queue.js?v=20260724h';
import './speech.js?v=20260724h';
import './artist-ui.js?v=20260724h';
import './auth.js?v=20260724h';
import './spotify.js?v=20260724h';
import './estimation.js?v=20260724h';
import './config.js?v=20260724h';
import './progress.js?v=20260724h';
import './ui.js?v=20260724h';
import './vocab.js?v=20260724h';
import './flashcards.js?v=20260724h';

// Boot profiling — opt-in via ?perf=1 URL param so normal users don't see
// console noise. After boot, call window.perfSummary() in DevTools (or it
// auto-runs at the end of boot) to see a table of phase timings: cumulative
// time since navigation start + delta from the previous mark. Useful for
// validating whether a given perf change actually moved the needle.
const _perfEnabled = new URLSearchParams(window.location.search).has('perf');
const _perfMarks = [];
function perfMark(name) {
    if (!_perfEnabled) return;
    _perfMarks.push({ name, t: performance.now() });
}
function perfSummary() {
    if (!_perfEnabled || _perfMarks.length === 0) return;
    console.table(_perfMarks.map((m, i) => ({
        phase: m.name,
        cumulative_ms: m.t.toFixed(1),
        delta_ms: (i === 0 ? m.t : m.t - _perfMarks[i - 1].t).toFixed(1),
    })));
}
window.perfMark = perfMark;
window.perfSummary = perfSummary;
perfMark('main.js top — module imports done');

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
perfMark('after resolveArtist');

// Expose for use by ui.js artist selection
window._allArtistsConfig = allArtistsConfig;
window._selectedArtistSlugs = selectedArtistSlugs;

// Add artist mode class to body and load albums dictionary
if (activeArtist) {
    document.body.classList.add('artist-mode');
    loadArtistAlbumsDictionary();
}

loadConfig().then(async () => {
    perfMark('after loadConfig');
    renderLanguageTabs();
    // Set first language with data as default (but don't auto-select it)
    const firstLang = Object.keys(config.languages).find(lang => config.languages[lang].hasData !== false) || Object.keys(config.languages)[0];
    selectedLanguage = firstLang;
    // Spanish-only boot fetches: rank lookup (personal easiness), conjugation
    // tables, conjugated-English translations. Skip when the first language
    // isn't Spanish — the ui.js language-tab handler refires them on
    // switch-to-Spanish, and the load helpers themselves are idempotent.
    if (selectedLanguage === 'spanish') {
        if (window.loadSpanishRanks) window.loadSpanishRanks();
        if (window.loadConjugationData) window.loadConjugationData();
        if (window.loadConjugatedEnglishData) window.loadConjugatedEnglishData();
    }
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
    // Welcome tab → "More about this project" link opens the standalone
    // project explainer modal (the same one the Account tab uses), so
    // there's a single canonical "what is this app" surface.
    const helpMoreInfoBtn = document.getElementById('helpMoreInfoBtn');
    if (helpMoreInfoBtn) {
        helpMoreInfoBtn.addEventListener('click', () => {
            document.getElementById('helpModal').classList.add('hidden');
            if (window.openAboutProjectModal) window.openAboutProjectModal();
        });
    }
    // Hide floating gear — replaced by gear in the top bar
    document.getElementById('gearBtn').style.display = 'none';
    perfMark('after sync setup phase');
    await migrateLocalStorageIds();
    await migrateLocalStorageIdsV2();
    perfMark('after migrations');
    await loadSecrets();
    perfMark('after loadSecrets');
    // Retry Spotify player init now that client ID is available (handles race with SDK load)
    if (window._spotifyTryInit) window._spotifyTryInit();
    checkAuthentication();
    perfMark('after checkAuthentication');

    // Offline sync: wire connectivity listeners, render the status indicator,
    // and drain any writes queued while previously offline. Runs after
    // loadSecrets() so GOOGLE_SCRIPT_URL is populated for the initial flush.
    if (window.initSync) window.initSync();

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
            // Renumber steps: in artist mode the language step is hidden,
            // so Choose Level becomes step 1 and Choose Set becomes step 2.
            // Lemma/cognate are sub-settings inside Choose Level — they
            // no longer carry their own numbers.
            document.querySelector('#step2 .step-number').textContent = '1';
            await loadPpmData(activeArtist.language || 'spanish');
            document.getElementById('step2').style.display = 'block';
            // Title is now static ("Choose level" in the HTML); the
            // CEFR/% toggle hides itself in artist mode via
            // setupPercentModeButton() — both are no-ops here.
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
        perfMark('after artist init');
    }

    // Wait for Sheets refresh to complete; re-render set badges if data changed
    const dataChanged = await progressPromise;
    if (dataChanged && selectedLanguage) {
        try { await renderRangeSelector(); } catch (e) { /* range selector may not be visible yet */ }
    }
    perfMark('boot complete');
    perfSummary();
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

// Build the initials shown on the color fallback (no image) — up to 2 letters.
function artistInitials(name) {
    const words = (name || '').trim().split(/\s+/).filter(Boolean);
    if (words.length === 0) return '?';
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    return (words[0][0] + words[1][0]).toUpperCase();
}

// Pick the image to represent an artist in the radial picker.
// Priority: explicit picker image → default album art → (none → color fallback).
function artistPickerImage(cfg) {
    return cfg.pickerImage || cfg.image || cfg.defaultAlbumArt || '';
}

// Shared radial "clock of pictures" picker used by artists and languages.
function showRadialPicker({ id, ariaLabel, hubHTML, entries }) {
    const existing = document.getElementById(id);
    if (existing) { closeRadialPicker(id); return; }

    const n = entries.length;
    if (n === 0) return;
    const overlay = document.createElement('div');
    overlay.id = id;
    overlay.className = 'artist-radial-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', ariaLabel);

    const stage = document.createElement('div');
    stage.className = 'artist-radial-stage';

    // Center hub: label + close affordance.
    const hub = document.createElement('div');
    hub.className = 'artist-radial-hub';
    hub.innerHTML = `<span class="artist-radial-hub-title">${hubHTML}</span>`;
    stage.appendChild(hub);

    // Radius as a fraction of the stage half-size. Thumbs sit on this ring.
    const ringPct = 38; // percent from center toward the edge
    // Start at the top (12 o'clock) and go clockwise.
    const startAngle = -90;

    entries.forEach((entry, i) => {
        const angle = (startAngle + (360 / n) * i) * (Math.PI / 180);
        const x = 50 + ringPct * Math.cos(angle);
        const y = 50 + ringPct * Math.sin(angle);

        const thumb = document.createElement('button');
        thumb.className = 'artist-radial-thumb';
        thumb.style.left = `${x}%`;
        thumb.style.top = `${y}%`;
        thumb.setAttribute('aria-label', entry.disabled ? `${entry.label} — coming soon` : entry.label);
        thumb.title = entry.disabled ? `${entry.label} — Data coming soon` : entry.label;
        thumb.disabled = !!entry.disabled;
        if (entry.disabled) thumb.classList.add('artist-radial-thumb--disabled');

        const accent = entry.accent || 'var(--accent-primary)';
        thumb.style.setProperty('--artist-accent', accent);

        const disc = document.createElement('span');
        disc.className = 'artist-radial-disc';
        if (entry.image) {
            disc.style.backgroundImage = `url('${entry.image}')`;
        } else {
            disc.classList.add('artist-radial-disc--fallback');
            disc.style.background = accent;
            disc.textContent = entry.fallbackText || '?';
        }
        if (entry.discClass) disc.classList.add(entry.discClass);
        thumb.appendChild(disc);

        const label = document.createElement('span');
        label.className = 'artist-radial-label';
        label.textContent = entry.disabled ? `${entry.label} · soon` : entry.label;
        thumb.appendChild(label);

        thumb.addEventListener('click', (e) => {
            e.stopPropagation();
            if (entry.disabled) return;
            closeRadialPicker(id);
            entry.onSelect();
        });

        stage.appendChild(thumb);
    });

    overlay.appendChild(stage);
    document.body.appendChild(overlay);
    // Trigger enter transition on next frame.
    requestAnimationFrame(() => overlay.classList.add('is-open'));

    // Close on backdrop click, Escape, or hub tap.
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeRadialPicker(id);
    });
    hub.addEventListener('click', () => closeRadialPicker(id));
    overlay._radialKeyHandler = e => {
        if (e.key === 'Escape') closeRadialPicker(id);
    };
    document.addEventListener('keydown', overlay._radialKeyHandler);
}

function closeRadialPicker(id) {
    const overlay = document.getElementById(id);
    if (!overlay) return;
    if (overlay._radialKeyHandler) {
        document.removeEventListener('keydown', overlay._radialKeyHandler);
    }
    overlay.classList.remove('is-open');
    setTimeout(() => overlay.remove(), 200);
}

// Artist adapter: album art around the shared radial component.
function showArtistPicker(anchorBtn, artists) {
    const entries = Object.entries(artists).map(([slug, cfg]) => ({
        label: cfg.name,
        image: artistPickerImage(cfg),
        fallbackText: artistInitials(cfg.name),
        accent: (cfg.colorTheme && cfg.colorTheme.primary) || 'var(--accent-primary)',
        onSelect: () => {
            window.location.href = `${window.location.pathname}?artist=${slug}`;
        }
    }));
    showRadialPicker({
        id: 'artistRadialPicker',
        ariaLabel: 'Choose an artist',
        hubHTML: 'Choose<br>an artist',
        entries
    });
}

// Standard-mode language adapter: flag pictures + existing hidden language
// buttons, so all loading/theme/progress behavior stays in ui.js.
function showLanguagePicker(languages) {
    const languageOrder = ['spanish', 'swedish', 'italian', 'dutch', 'polish', 'french', 'russian'];
    const flags = {
        spanish: '🇪🇸', swedish: '🇸🇪', italian: '🇮🇹', dutch: '🇳🇱',
        polish: '🇵🇱', french: '🇫🇷', russian: '🇷🇺'
    };
    const entries = languageOrder.filter(key => languages[key]).map(key => {
        const cfg = languages[key];
        return {
            label: cfg.name,
            fallbackText: flags[key] || '🌐',
            discClass: 'language-radial-disc',
            accent: (cfg.colorTheme && cfg.colorTheme.primary) || 'var(--accent-primary)',
            disabled: cfg.hasData === false,
            onSelect: () => document.querySelector(`.lang-tab[data-lang="${key}"]`)?.click()
        };
    });
    showRadialPicker({
        id: 'languageRadialPicker',
        ariaLabel: 'Choose a language',
        hubHTML: 'Choose a<br>language',
        entries
    });
}

window.showLanguagePicker = showLanguagePicker;

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
    // Open the word as a standalone popup card via the cardNavStack pattern.
    // navigateBack reopens the search modal afterwards.
    if (window.popupFoundWord) {
        try {
            await window.popupFoundWord(entry);
        } catch (e) {
            console.error('Find-word: popupFoundWord failed', e);
            const statusEl = document.getElementById('findWordStatus');
            if (statusEl) statusEl.textContent = 'Could not open card.';
        }
    }
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
