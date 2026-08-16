import './theme.js?v=20260816j';
import './state.js?v=20260816j';
import './offline-db.js?v=20260816j';
import './sync-queue.js?v=20260816j';
import { initOfflineContent } from './offline-content.js?v=20260816j';
import './speech.js?v=20260816j';
import './artist-ui.js?v=20260816j';
import './auth.js?v=20260816j';
import './about-example.js?v=20260816j';
import './estimation.js?v=20260816j';
import './config.js?v=20260816j';
import './progress.js?v=20260816j';
import './knowledge.js?v=20260816j';
import './ui.js?v=20260816j';
import './vocab.js?v=20260816j';
import './song-sets.js?v=20260816j';
import './vocabulary-import.js?v=20260816j';
import './flashcards.js?v=20260816j';

// Spotify is lyrics-only and its module is sizeable. Start the dynamic import
// immediately for an artist URL so it races setup/data loading, but keep it
// entirely out of normal Speech startup. Card/modal code already has its own
// lazy module stubs in flashcards.js.
const _initialParams = new URLSearchParams(window.location.search);
const _speechVnextRoute = _initialParams.get('speech') === 'vnext';
const _spotifyModulePromise = (_initialParams.has('artist') || _initialParams.get('mode') === 'badbunny')
    ? import('./spotify.js?v=20260816j').catch(error => {
        console.warn('Spotify controls deferred:', error);
        return null;
    })
    : null;

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

const APP_LOADING_MESSAGE_KEY = 'fluency_loading_message_v1';

function showAppLoading(title = 'Getting things ready', detail = 'Loading your language and progress…', persist = false) {
    const screen = document.getElementById('appLoadingScreen');
    if (!screen) return;
    document.getElementById('appLoadingTitle').textContent = title;
    document.getElementById('appLoadingDetail').textContent = detail;
    screen.classList.remove('is-hidden');
    screen.setAttribute('aria-busy', 'true');
    if (persist) {
        try { sessionStorage.setItem(APP_LOADING_MESSAGE_KEY, JSON.stringify({ title, detail })); } catch (_) {}
    }
}

function hideAppLoading() {
    const screen = document.getElementById('appLoadingScreen');
    document.documentElement.classList.remove('app-booting');
    screen?.classList.add('is-hidden');
    screen?.setAttribute('aria-busy', 'false');
    try { sessionStorage.removeItem(APP_LOADING_MESSAGE_KEY); } catch (_) {}
}

try {
    const pendingLoadingMessage = JSON.parse(sessionStorage.getItem(APP_LOADING_MESSAGE_KEY) || 'null');
    if (pendingLoadingMessage?.title) {
        showAppLoading(pendingLoadingMessage.title, pendingLoadingMessage.detail || 'Preparing the next screen…');
    }
} catch (_) {}

window.showAppLoading = showAppLoading;
window.hideAppLoading = hideAppLoading;

// Wire the static authentication surface before any configuration fetch or
// artist resolution. The HTML intentionally contains this modal as a boot
// fallback; its buttons must never depend on loadConfig() having completed.
setupAuthEventListeners();
checkAuthentication();
perfMark('after early authentication');

// Register service worker for PWA functionality
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('service-worker.js')
            .then(registration => {
                console.log('SW registered');
                const announceUpdate = () => {
                    if (!registration.waiting) return;
                    const indicator = document.getElementById('syncStatusIndicator');
                    if (indicator) {
                        indicator.className = 'sync-status is-update';
                        indicator.textContent = 'Update ready';
                        indicator.onclick = () => registration.waiting.postMessage({ type: 'SKIP_WAITING' });
                    }
                };
                announceUpdate();
                registration.addEventListener('updatefound', () => {
                    registration.installing?.addEventListener('statechange', announceUpdate);
                });
                let reloading = false;
                navigator.serviceWorker.addEventListener('controllerchange', () => {
                    if (!reloading) { reloading = true; location.reload(); }
                });
            })
            .catch(err => console.log('SW registration failed'));
    });
}

// All available artist configs, keyed by slug. Loaded once from artists.json.
let allArtistsConfig = null;
// Slugs of artists currently selected for multi-artist merge
let selectedArtistSlugs = [];
const ARTIST_EXTRA_UNLOCK_KEY = 'fluency_artist_extra_unlocked_v1';
const ARTIST_EXTRA_UNLOCK_PCT = 60;

function readArtistExtraUnlocks() {
    try {
        const saved = JSON.parse(localStorage.getItem(ARTIST_EXTRA_UNLOCK_KEY) || '[]');
        return new Set(Array.isArray(saved) ? saved : []);
    } catch (_) {
        return new Set();
    }
}

function isArtistExtraUnlocked(slug = window._urlArtistSlug) {
    return !!slug && readArtistExtraUnlocks().has(slug);
}

function updateArtistExtraUnlock(coveragePct) {
    if (!activeArtist || artistVocabularyScope !== 'main') return;
    const pct = Math.max(0, Number(coveragePct) || 0);
    window._artistMainCoveragePct = pct;
    const slug = window._urlArtistSlug;
    if (slug && pct >= ARTIST_EXTRA_UNLOCK_PCT && !isArtistExtraUnlocked(slug)) {
        const unlocks = readArtistExtraUnlocks();
        unlocks.add(slug);
        try { localStorage.setItem(ARTIST_EXTRA_UNLOCK_KEY, JSON.stringify(Array.from(unlocks))); } catch (_) {}
    }
    renderArtistSourceSummary();
}

window.isArtistExtraUnlocked = isArtistExtraUnlocked;
window.updateArtistExtraUnlock = updateArtistExtraUnlock;

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
            const requestedExtra = params.get('scope') === 'extra';
            artistVocabularyScope = requestedExtra && isArtistExtraUnlocked(artistSlug)
                ? 'extra'
                : 'main';
            if (requestedExtra && artistVocabularyScope === 'main') {
                const url = new URL(window.location.href);
                url.searchParams.delete('scope');
                history.replaceState(null, '', url);
            }

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
    const isResumeNavigation = new URLSearchParams(window.location.search).get('resume') === '1';
    perfMark('after loadConfig');
    renderLanguageTabs();
    // Set first language with data as default (but don't auto-select it)
    const firstLang = Object.keys(config.languages).find(lang => config.languages[lang].hasData !== false) || Object.keys(config.languages)[0];
    selectedLanguage = firstLang;
    // Spanish-only boot fetches: rank lookup (personal easiness) and
    // conjugated-English translations. Full conjugation paradigms are loaded
    // only when their already-lazy panel is opened. Skip when the first language
    // isn't Spanish — the ui.js language-tab handler refires them on
    // switch-to-Spanish, and the load helpers themselves are idempotent.
    if (selectedLanguage === 'spanish') {
        if (window.loadSpanishRanks) window.loadSpanishRanks();
        if (window.loadConjugatedEnglishData) window.loadConjugatedEnglishData();
    }
    applyLanguageColorTheme();
    setupLemmaToggle();
    setupCognateToggle();
    setupGlobalStudyDefaults();
    setupPercentModeButton();
    setupEstimationModal();
    setupTooltipHandlers();

    // Wire shared top bar buttons (How to start, Estimate Level, gear)
    document.getElementById('helpBtn').addEventListener('click', () => openHelpModal());
    document.getElementById('topBarGearBtn').addEventListener('click', () => showSettingsModal());
    // Level-estimate CTA (shown when user has no progress yet, in the slot
    // where the personal coverage bar will live once they do).
    document.getElementById('levelEstimateCTABtn').addEventListener('click', () => openEstimationModal());
    document.getElementById('personalProgressInfoBtn')?.addEventListener('click', event => {
        event.stopPropagation();
        showTotalStatsModal();
    });
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
    document.getElementById('closeHelpModal').addEventListener('click', () => {
        document.getElementById('helpModal').classList.add('hidden');
    });
    wireExtraScopeModal();
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

    // Set user name in top bar immediately (don't wait for progress load).
    const userName = currentUser ? (currentUser.isGuest ? 'GUEST' : currentUser.initials) : '';
    document.getElementById('topBarUserName').textContent = userName;

    // Shareable landing URL: ?about=1 opens the About modal on top of whatever
    // state the app lands in.
    if (_initialParams.has('about')) {
        window.openAboutProjectModal && window.openAboutProjectModal();
    }

    // Speech vNext is a compact, local-data route. Start it before migrations,
    // remote secrets, sync, progress or offline-catalogue work so evaluating
    // the new method does not inherit legacy runtime cost or write behavior.
    if (_speechVnextRoute) {
        try {
            selectedLanguage = 'spanish';
            applyLanguageColorTheme();
            const speechVnext = await import('./speech-vnext.js?v=20260816j');
            await speechVnext.startSpeechVnext();
        } catch (error) {
            console.error('Speech vNext preview failed to load:', error);
            document.getElementById('loadingMessage').textContent = 'Speech vNext could not be loaded.';
            document.getElementById('loadingMessage').style.display = 'block';
            document.getElementById('setupPanel').classList.remove('hidden');
            document.getElementById('setupPanel').style.display = 'block';
        } finally {
            hideAppLoading();
        }
        return;
    }

    perfMark('after sync setup phase');
    await Promise.allSettled([migrateLocalStorageIds(), migrateLocalStorageIdsV2()]);
    perfMark('after migrations');
    await loadSecrets();
    perfMark('after loadSecrets');
    if (activeArtist?.songsPath && window.initArtistSongSelection) {
        try {
            await window.initArtistSongSelection();
        } catch (error) {
            console.warn('Per-song Lyrics selection unavailable; using the full artist deck.', error);
            artistSongCatalog = null;
            selectedSongIds = [];
        }
    }
    // Retry Spotify player init now that client ID is available (handles race with SDK load)
    _spotifyModulePromise?.then(() => window._spotifyTryInit?.());
    // Offline sync: wire connectivity listeners, render the status indicator,
    // and drain any writes queued while previously offline. Runs after
    // loadSecrets() so GOOGLE_SCRIPT_URL is populated for the initial flush.
    // These enhance the already-interactive app. Neither is allowed to block
    // authentication or source rendering when Safari storage is unavailable.
    if (window.initSync) window.initSync().catch(error =>
        console.warn('Offline sync initialization deferred:', error));
    initOfflineContent().catch(error =>
        console.warn('Offline content initialization deferred:', error));

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
            renderArtistSourceSummary();
            // Renumber steps: in artist mode the language step is hidden,
            // so Choose Level becomes step 1 and Continue Level becomes step 2.
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
            await renderLevelSelector(activeArtist.language || 'spanish');
            await updateExclusionBars();
        } finally {
            if (!isResumeNavigation) hideAppLoading();
        }
        perfMark('after artist init');
    } else {
        const pendingSpeechLanguage = sessionStorage.getItem('fluencyPendingSpeechLanguage');
        const pendingTab = pendingSpeechLanguage
            ? document.querySelector(`.lang-tab[data-lang="${pendingSpeechLanguage}"]`)
            : null;
        if (pendingTab && !pendingTab.disabled) pendingTab.click();
        else if (!isResumeNavigation) hideAppLoading();
    }

    // Cached progress is already loaded synchronously by
    // loadUserProgressFromSheet(). Do not hold boot or exact-session resume
    // behind the remote Sheets round trip.
    window.renderResumeLastSetCard?.();
    if (isResumeNavigation) {
        await window.resumeLastStudySession?.();
    }

    // Reconcile the setup badges once the background Sheets refresh finishes.
    const dataChanged = await progressPromise;
    const setupIsVisible = !document.getElementById('setupPanel')?.classList.contains('hidden');
    if (dataChanged && selectedLanguage && selectedLevel && setupIsVisible) {
        try { await window.refreshSetupAfterProgress?.(); } catch (e) { /* setup may not be visible yet */ }
    }
    perfMark('boot complete');
    perfSummary();
}).catch(error => {
    console.error('App initialization failed:', error);
    hideAppLoading();
});

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

function renderArtistSourceSummary() {
    const step = document.getElementById('artistSourceStep');
    const picker = document.getElementById('artistSourcePickerBtn');
    const artistBtn = document.getElementById('artistSourceArtistBtn');
    const speechBtn = document.getElementById('artistSourceSpeechBtn');
    const name = document.getElementById('artistSourceName');
    const selectionLabel = document.getElementById('artistSourceSelectionLabel');
    const image = document.getElementById('artistSourceImage');
    if (!step || !picker || !artistBtn || !speechBtn || !name || !image || !activeArtist) return;

    const artistName = activeArtist.name || 'Artist';
    const art = artistPickerImage(activeArtist);
    name.textContent = artistName;
    if (selectionLabel) selectionLabel.textContent = window.songSelectionSummary?.() || 'Choose songs';
    image.textContent = art ? '' : artistInitials(artistName);
    image.classList.toggle('artist-source-image--fallback', !art);
    image.style.backgroundImage = art ? `url('${art}')` : '';
    image.style.backgroundColor = art ? '' : (activeArtist.colorTheme?.primary || 'var(--accent-primary)');
    step.style.display = 'block';

    const scopeHint = document.getElementById('artistVocabularyScopeHint');
    const extraUnlocked = isArtistExtraUnlocked();
    if (artistVocabularyScope === 'extra' && !extraUnlocked) {
        artistVocabularyScope = 'main';
        const url = new URL(window.location.href);
        url.searchParams.delete('scope');
        history.replaceState(null, '', url);
    }
    document.querySelectorAll('.artist-vocabulary-scope-btn').forEach(button => {
        const selected = button.dataset.artistScope === artistVocabularyScope;
        const locked = button.dataset.artistScope === 'extra' && !extraUnlocked;
        button.classList.toggle('selected', selected);
        button.classList.toggle('is-locked', locked);
        button.setAttribute('aria-pressed', selected ? 'true' : 'false');
        button.disabled = locked;
        button.textContent = locked ? 'Extra · 60%' : (button.dataset.artistScope === 'extra' ? 'Extra' : 'Main');
        button.title = locked ? 'Unlocks at 60% lyrics understood' : '';
        button.onclick = () => {
            const scope = button.dataset.artistScope;
            // Extra is deliberately not a plain toggle — confirm via explainer
            // so it can't be switched on by accident. Main switches directly.
            if (scope === 'extra' && artistVocabularyScope !== 'extra') {
                openExtraScopeModal();
            } else {
                setArtistVocabularyScope(scope);
            }
        };
    });
    if (scopeHint) {
        scopeHint.textContent = artistVocabularyScope === 'extra'
            ? `One-off ${artistName} lemma families, supported by shared Speech examples where available`
            : extraUnlocked
                ? 'Recurring lemma families · Extra unlocked'
                : `Extra unlocks at 60% lyrics understood · ${Math.min(59.9, window._artistMainCoveragePct || 0).toFixed(1)}% now`;
    }

    picker.onclick = () => {
        if (artistSongCatalog?.songs?.length && window.showSongSetPicker) {
            window.showSongSetPicker();
            return;
        }
        artistBtn.click();
    };
    artistBtn.onclick = () => {
        const language = activeArtist.language || 'spanish';
        const matchingArtists = Object.fromEntries(Object.entries(allArtistsConfig || {}).filter(([, cfg]) =>
            (cfg.language || 'spanish') === language));
        showArtistPicker(picker, matchingArtists);
    };
    speechBtn.onclick = () => {
        showAppLoading('Switching to Speech', 'Preparing your language and progress…', true);
        sessionStorage.setItem('fluencyPendingSpeechLanguage', activeArtist.language || 'spanish');
        window.location.href = window.location.pathname;
    };
}

window.renderArtistSourceSummary = renderArtistSourceSummary;

window.addEventListener('fluency-song-selection-changed', async () => {
    if (!activeArtist) return;
    cachedVocabularyData = null;
    selectedLevel = null;
    selectedRanges = [];
    _findWordIndex = null;
    _findWordIndexKey = null;
    document.getElementById('step4').style.display = 'none';
    renderArtistSourceSummary();
    const loading = document.getElementById('dataLoadingIndicator');
    loading?.classList.add('visible');
    try {
        await renderLevelSelector(selectedLanguage, { preferActionable: true });
        await updateExclusionBars();
    } finally {
        loading?.classList.remove('visible');
    }
});

async function setArtistVocabularyScope(scope, { autoStart = false } = {}) {
    if (!activeArtist || !['main', 'extra'].includes(scope)) return;
    if (scope === 'extra' && !isArtistExtraUnlocked()) return;
    const changed = artistVocabularyScope !== scope;
    artistVocabularyScope = scope;
    const url = new URL(window.location.href);
    if (scope === 'extra') url.searchParams.set('scope', 'extra');
    else url.searchParams.delete('scope');
    history.replaceState(null, '', url);
    renderArtistSourceSummary();
    if (!changed && !autoStart) return;

    selectedLevel = null;
    selectedRanges = [];
    _findWordIndex = null;
    _findWordIndexKey = null;
    document.getElementById('step4').style.display = 'none';
    document.getElementById('lemmaToggleContainer').style.display = 'none';
    document.getElementById('cognateToggleContainer').style.display = 'none';
    const loading = document.getElementById('dataLoadingIndicator');
    loading?.classList.add('visible');
    try {
        await renderLevelSelector(selectedLanguage, { preferActionable: true });
        await updateExclusionBars();
        if (autoStart) {
            const firstLevel = document.querySelector('.level-btn.selected')
                || document.querySelector('.level-selector-buttons .level-btn, #levelSelector > .level-btn');
            if (!firstLevel) return;
            const firstSet = Array.from(document.querySelectorAll('#rangeSelector .study-set-dot'))
                .find(dot => !dot.disabled && Number(dot.dataset.pct) < 100)
                || Array.from(document.querySelectorAll('#rangeSelector .study-set-dot'))
                    .find(dot => !dot.disabled);
            if (firstSet) {
                await loadVocabularyData(firstSet.dataset.range, {
                    rankBasis: firstSet.dataset.rankBasis || 'stable',
                    setNumber: Number(firstSet.dataset.index) + 1,
                    levelSetCount: document.querySelectorAll('#rangeSelector .study-set-dot').length,
                });
            }
        }
    } finally {
        loading?.classList.remove('visible');
    }
}

window.setArtistVocabularyScope = setArtistVocabularyScope;

// Extra explainer/confirm modal. Extra is supplementary and reorganises the
// study interface, so entering it requires an explicit confirmation rather than
// a one-tap toggle.
function openExtraScopeModal() {
    const modal = document.getElementById('extraScopeModal');
    if (!modal) { setArtistVocabularyScope('extra'); return; }
    const nameEl = document.getElementById('extraScopeArtistName');
    if (nameEl) {
        nameEl.textContent = activeArtist?.name
            ? `${activeArtist.name} Extra`
            : 'Extra';
    }
    modal.classList.remove('hidden');
}

function closeExtraScopeModal() {
    document.getElementById('extraScopeModal')?.classList.add('hidden');
}

function wireExtraScopeModal() {
    const modal = document.getElementById('extraScopeModal');
    if (!modal) return;
    document.getElementById('closeExtraScopeModal')?.addEventListener('click', closeExtraScopeModal);
    document.getElementById('cancelExtraScopeBtn')?.addEventListener('click', closeExtraScopeModal);
    document.getElementById('confirmExtraScopeBtn')?.addEventListener('click', () => {
        closeExtraScopeModal();
        setArtistVocabularyScope('extra');
    });
    // Dismiss when tapping the backdrop.
    modal.addEventListener('click', event => {
        if (event.target === modal) closeExtraScopeModal();
    });
}

window.openExtraScopeModal = openExtraScopeModal;

// Shared radial "clock of pictures" picker used by artists and languages.
function showRadialPicker({ id, ariaLabel, hubHTML, entries, className = '', closeLabel = '' }) {
    const existing = document.getElementById(id);
    if (existing) { closeRadialPicker(id); return; }

    const n = entries.length;
    if (n === 0) return;
    const overlay = document.createElement('div');
    overlay.id = id;
    overlay.className = 'artist-radial-overlay';
    if (className) overlay.classList.add(...className.split(/\s+/).filter(Boolean));
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', ariaLabel);

    const stage = document.createElement('div');
    stage.className = 'artist-radial-stage';

    // Center hub: label + close affordance.
    const hub = document.createElement('div');
    hub.className = 'artist-radial-hub';
    hub.innerHTML = `<span class="artist-radial-hub-title">${hubHTML}</span>${closeLabel ? `<span class="artist-radial-close-label">${closeLabel}</span>` : ''}`;
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
        if (entry.iconHTML) {
            disc.classList.add('artist-radial-disc--icon');
            disc.innerHTML = entry.iconHTML;
        } else if (entry.image) {
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

window.showRadialPicker = showRadialPicker;
window.closeRadialPicker = closeRadialPicker;

// Artist adapter: album art around the shared radial component.
function showArtistPicker(anchorBtn, artists) {
    const entries = Object.entries(artists).map(([slug, cfg]) => ({
        label: cfg.name,
        image: artistPickerImage(cfg),
        fallbackText: artistInitials(cfg.name),
        accent: (cfg.colorTheme && cfg.colorTheme.primary) || 'var(--accent-primary)',
        onSelect: () => {
            showAppLoading(`Loading ${cfg.name}`, 'Preparing lyrics, levels and progress…', true);
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

// Language is deliberately chosen first so Lyrics can offer only artists
// whose material matches it. Speech continues the existing standard setup.
async function showLearningSourcePicker(language, onSpeech) {
    let artists = allArtistsConfig;
    try {
        if (!artists) {
            artists = await fetch('config/artists.json').then(response => response.json());
            allArtistsConfig = artists;
            window._allArtistsConfig = artists;
        }
    } catch (error) {
        console.warn('Could not load lyric artists:', error);
        artists = {};
    }

    const matchingArtists = Object.fromEntries(Object.entries(artists || {}).filter(([, cfg]) =>
        (cfg.language || 'spanish') === language));
    const hasLyrics = Object.keys(matchingArtists).length > 0;
    showRadialPicker({
        id: 'learningSourceRadialPicker',
        ariaLabel: 'Choose speech or lyrics',
        hubHTML: 'Learn from<br>…',
        entries: [
            {
                label: 'Speech',
                fallbackText: '💬',
                discClass: 'learning-source-radial-disc',
                accent: 'var(--accent-secondary)',
                onSelect: onSpeech
            },
            {
                label: 'Lyrics',
                fallbackText: '♫',
                discClass: 'learning-source-radial-disc',
                accent: 'var(--accent-primary)',
                disabled: !hasLyrics,
                onSelect: () => showArtistPicker(null, matchingArtists)
            }
        ]
    });
}

window.showLearningSourcePicker = showLearningSourcePicker;
window.showArtistPicker = showArtistPicker;

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
        activeArtist ? artistVocabularyScope : (hideSingleOccurrence ? '1' : '0'),
        excludeProperNouns ? '1' : '0',
        excludeNoise ? '1' : '0',
        excludeEnglishLoanwords ? '1' : '0'
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
    // Build displayRank via the normal filter pipeline so ranks line up with
    // the set buttons. Clone each entry because the deck filter intentionally
    // strips empty meanings; search must not mutate its full source index.
    const filterInput = vocabularyData.map(item => ({
        ...item,
        meanings: Array.isArray(item.meanings) ? [...item.meanings] : []
    }));
    const { vocab: filtered } = window.buildFilteredVocab(filterInput);
    const byRank = new Map();
    filtered.forEach(it => byRank.set(it.rank, it.displayRank));
    const idx = vocabularyData.map(item => {
        const meanings = item.meanings || [];
        const matchedMeanings = meanings.filter(meaning =>
            meaning
            && String(meaning.translation || '').trim()
            && (!activeArtist || Number(meaning.frequency || 0) > 0));
        const firstMeaning = matchedMeanings.find(m =>
            m.pos !== 'MWE' && m.pos !== 'CLITIC' && m.pos !== 'SENSE_CYCLE');
        // Headwords, not lemma: a surface-keyed card can group several
        // (casa -> casa + casar), and the single `lemma` field is the old
        // one-lemma-per-card model.
        const headwords = [...new Set(
            meanings.map(meaning => meaning && meaning.headword).filter(Boolean)
        )];
        return {
            targetWord: item.word || item.targetWord || '',
            lemma: item.lemma || '',
            headwords,
            fullId: window.getWordId(item),
            rank: item.rank,
            displayRank: byRank.get(item.rank) || null,
            id: item.id || window.getWordId(item),
            firstMeaning: firstMeaning ? firstMeaning.translation : '',
            exclusionReason: window.getVocabularyExclusionReason?.(item) || null,
            examplesOnly: matchedMeanings.length === 0,
            sourceEntry: item
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
        // Searching a headword should still find the card that carries it —
        // `casar` lands on the `casa` card, because that is where the meaning
        // now lives.
        const heads = (entry.headwords || []).map(normalizeForSearch);
        const exact = w === q || heads.includes(q);
        const starts = w.startsWith(q) || heads.some(h => h.startsWith(q));
        const contains = w.includes(q) || heads.some(h => h.includes(q));
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
        // Headwords only when the card groups more than one, or when the single
        // headword differs from the surface. One headword equal to the surface
        // is the common case and says nothing worth a chip.
        const heads = (entry.headwords || []).filter(Boolean);
        const showHeads = heads.length > 1
            || (heads.length === 1 && heads[0] !== entry.targetWord);
        const lemmaHTML = showHeads
            ? `<span class="fw-lemma">${heads.join(' · ')}</span>` : '';

        // Whether this card is done. Without it there is no way to check a card
        // from search — the whole reason for looking one up. Falls back to the
        // other mode's record, so a word studied only in lyrics reads as known
        // in speech, which is exactly what surface identity restored.
        const progress = progressData?.[entry.fullId]
            || (window.getCrossModeId?.(entry.fullId)
                ? progressData?.[window.getCrossModeId(entry.fullId)]
                : null);
        const state = window.getProgressState?.(progress) || { status: 'unseen' };
        let doneHTML = '<span class="fw-done fw-done--unseen">Not seen</span>';
        if (state.status === 'learned') {
            doneHTML = `<span class="fw-done fw-done--known">Known${
                state.lastCorrect ? ` · ${new Date(state.lastCorrect).toLocaleDateString()}` : ''}</span>`;
        } else if (state.status === 'review') {
            doneHTML = state.reviewReason === 'due'
                ? '<span class="fw-done fw-done--due">Due</span>'
                : '<span class="fw-done fw-done--review">Review</span>';
        }

        const statusHTML = entry.exclusionReason
            ? `<span class="fw-status fw-status--excluded">Excluded · ${entry.exclusionReason}</span>`
            : (entry.examplesOnly
                ? '<span class="fw-status">Examples only</span>'
                : (entry.displayRank ? `<span class="fw-rank">#${entry.displayRank}</span>` : ''));
        btn.innerHTML = `
            <span class="fw-word">${entry.targetWord}</span>
            ${lemmaHTML}
            <span class="fw-meaning">${(entry.firstMeaning || '').replace(/</g, '&lt;')}</span>
            ${doneHTML}
            ${statusHTML}`;
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
            document.getElementById('findWordModal')?.classList.remove('hidden');
            const statusEl = document.getElementById('findWordStatus');
            // Name the actual failure. A bare "Could not open card" is
            // indistinguishable between a missing entry, a lazy-module load
            // failure, and a render exception — and on a phone there is no
            // console to check, so the reason has to reach the sheet itself.
            if (statusEl) {
                const where = String(e?.stack || '').split('\n')[1]?.trim() || '';
                statusEl.textContent = `Could not open card — ${e?.message || e}`
                    + (where ? ` (${where.slice(0, 80)})` : '');
            }
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
