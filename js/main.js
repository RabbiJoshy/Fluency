import './state.js';
import './speech.js';
import './artist-ui.js';
import './auth.js';
import './estimation.js';
import './config.js';
import './progress.js';
import './ui.js';
import './vocab.js';
import './flashcards.js';

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
        const response = await fetch('artists.json');
        allArtistsConfig = await response.json();

        // Tag each config with its slug
        for (const [slug, cfg] of Object.entries(allArtistsConfig)) {
            cfg.slug = slug;
        }

        const artistConfig = allArtistsConfig[artistSlug];
        if (artistConfig) {
            activeArtist = artistConfig;

            // Restore multi-artist selection from localStorage, ensuring URL artist is included
            const saved = JSON.parse(localStorage.getItem('selected_artists') || '[]');
            selectedArtistSlugs = saved.length > 0 ? saved : [artistSlug];
            if (!selectedArtistSlugs.includes(artistSlug)) {
                selectedArtistSlugs.push(artistSlug);
            }
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
    renderLanguageTabs();
    // Set first language with data as default (but don't auto-select it)
    const firstLang = Object.keys(config.languages).find(lang => config.languages[lang].hasData !== false) || Object.keys(config.languages)[0];
    selectedLanguage = firstLang;
    applyLanguageColorTheme();
    setupGroupSizeSelector();
    setupLemmaToggle();
    setupCognateToggle();
    setupPercentModeButton();
    setupEstimateLevelButton();
    setupTooltipHandlers();
    setupAuthEventListeners();
    await migrateLocalStorageIds();
    await loadSecrets();
    checkAuthentication();

    // Ensure progress data is loaded before rendering coverage bars
    if (currentUser && !currentUser.isGuest) {
        await loadUserProgressFromSheet();
    }

    // In artist mode, auto-select the artist's language and skip language selection
    if (activeArtist) {
        selectedLanguage = activeArtist.language || 'spanish';
        applyLanguageColorTheme();
        // Hide language tabs, pill, and step 1 entirely
        document.getElementById('languageTabs').style.display = 'none';
        document.getElementById('selectedLanguagePill').style.display = 'none';
        document.getElementById('step1').style.display = 'none';
        // Show artist top bar box with user name, How to start, Estimate Level, gear
        const userName = currentUser ? (currentUser.isGuest ? 'GUEST' : currentUser.initials) : 'GUEST';
        document.getElementById('topBarUserName').textContent = userName;
        document.getElementById('artistTopBar').style.display = 'block';
        document.getElementById('helpBtn').addEventListener('click', () => openHelpModal());
        document.getElementById('estimateLevelTextBtn').addEventListener('click', () => openEstimationModal());
        document.getElementById('artistGearBtn').addEventListener('click', () => showSettingsModal());
        // Renumber steps: 1, 2, 3, 4 (since step 1 is hidden)
        document.querySelector('#step2 .step-number').textContent = '1';
        document.querySelector('#lemmaToggleContainer .step-number').textContent = '2';
        document.querySelector('#cognateToggleContainer .step-number').textContent = '3';
        document.getElementById('closeHelpModal').addEventListener('click', () => {
            document.getElementById('helpModal').classList.add('hidden');
        });
        setupTabSwitching(document.getElementById('helpModal'));
        await loadPpmData(activeArtist.language || 'spanish');
        document.getElementById('step2').style.display = 'block';
        document.getElementById('step2Title').textContent = 'Choose Level';
        document.querySelector('#step2 .btn-with-info:has(#estimateLevelBtn)').style.display = 'none';
        document.querySelector('#step2 .btn-with-info:has(#percentModeBtn)').style.display = 'none';
        updateStep2Tooltip();
        updateStep5Tooltip();
        await updateLemmaToggleVisibility();
        await updateCognateToggleVisibility();
        renderLevelSelector(activeArtist.language || 'spanish');
        updateCoverageProgressBar();
        await updateExclusionBars();
        setupArtistSelection();
    }
});

