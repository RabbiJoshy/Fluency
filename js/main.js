import './state.js';
import './speech.js';
import './badbunny.js';
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

// Add Bad Bunny mode class to body
if (isBadBunnyMode) {
    document.body.classList.add('badbunny-mode');
    // Load the albums dictionary
    loadBadBunnyAlbumsDictionary();
}

loadConfig().then(async () => {
    renderLanguageTabs();
    // Set first language with data as default (but don't auto-select it)
    const firstLang = Object.keys(config.languages).find(lang => config.languages[lang].hasData !== false) || Object.keys(config.languages)[0];
    selectedLanguage = firstLang;
    applyLanguageColorTheme();
    // Don't render level selector yet - wait for user to select a language
    // renderLevelSelector(firstLang);
    setupGroupSizeSelector();
    setupLemmaToggle();
    setupCognateToggle();
    setupPercentModeButton(); // Setup % Mode button early
    setupEstimateLevelButton(); // Setup Estimate Level button
    // updateLemmaToggleVisibility(); // Don't call yet - wait for language selection
    setupTooltipHandlers(); // Initialize tooltips early
    setupAuthEventListeners(); // Setup auth modal event listeners
    await loadSecrets(); // Load secrets before authentication
    checkAuthentication(); // Check if user is logged in

    // Ensure progress data is loaded before rendering coverage bars
    if (currentUser && !currentUser.isGuest) {
        await loadUserProgressFromSheet();
    }

    // In Bad Bunny mode, auto-select Spanish and skip language selection
    if (isBadBunnyMode) {
        selectedLanguage = 'spanish';
        applyLanguageColorTheme();
        // Hide language tabs, pill, and step 1 entirely (replaced by helpBar)
        document.getElementById('languageTabs').style.display = 'none';
        document.getElementById('selectedLanguagePill').style.display = 'none';
        document.getElementById('step1').style.display = 'none';
        // Show Help + Estimate bar at the top
        document.getElementById('helpBar').style.display = 'block';
        // Wire up Help button → help modal, Estimate Level → estimation modal
        document.getElementById('helpBtn').addEventListener('click', () => openHelpModal());
        document.getElementById('estimateLevelTextBtn').addEventListener('click', () => openEstimationModal());
        // Setup help modal close + tab switching
        document.getElementById('closeHelpModal').addEventListener('click', () => {
            document.getElementById('helpModal').classList.add('hidden');
        });
        setupTabSwitching(document.getElementById('helpModal'));
        // Load PPM data and show step 2
        await loadPpmData('spanish');
        document.getElementById('step2').style.display = 'block';
        // Update step 2 for Bad Bunny mode - simpler title, hide estimate button and % mode button
        document.getElementById('step2Title').textContent = 'Choose Level';
        // Hide the Estimate Level button and % Mode button in step 2 for Bad Bunny mode
        document.querySelector('#step2 .btn-with-info:has(#estimateLevelBtn)').style.display = 'none';
        document.querySelector('#step2 .btn-with-info:has(#percentModeBtn)').style.display = 'none';
        updateStep2Tooltip();
        updateStep5Tooltip();
        // Initialize lemma and cognate toggle visibility for Bad Bunny mode
        await updateLemmaToggleVisibility();
        await updateCognateToggleVisibility();
        renderLevelSelector('spanish');
        updateCoverageProgressBar();
        await updateExclusionBars();
    }
});

