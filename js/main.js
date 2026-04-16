import './state.js';
import './speech.js';
import './artist-ui.js';
import './auth.js';
import './spotify.js';
import './estimation.js';
import './config.js';
import './progress.js';
import './ui.js';
import './vocab.js?v=20260416e';
import './flashcards.js?v=20260416e';

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
    document.getElementById('estimateLevelTextBtn').addEventListener('click', () => openEstimationModal());
    document.getElementById('topBarGearBtn').addEventListener('click', () => showSettingsModal());
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
        // In artist mode → offer switch to normal
        btn.textContent = 'Normal Mode';
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
