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
        // Hide language tabs and the "Spanish (Bad Bunny)" pill completely
        document.getElementById('languageTabs').style.display = 'none';
        document.getElementById('selectedLanguagePill').style.display = 'none';
        // Update step 1 title for Bad Bunny mode - replace "Choose Language" with "Estimate Level"
        document.querySelector('#step1Header .step-title').textContent = 'Estimate Level';
        // Show the Estimate Level button in step 1 for Bad Bunny mode
        document.getElementById('step1EstimateContainer').style.display = 'block';
        // Update step 1 tooltip for Bad Bunny mode
        document.getElementById('step1Tooltip').innerHTML = `
            <p><strong>How to Study:</strong></p>
            <p><strong>Tap card</strong> to flip and see translation</p>
            <p><strong>Swipe right</strong> if you know the word ✓</p>
            <p><strong>Swipe left</strong> if you don't know it ✗</p>
            <p><strong>Tap example lyrics</strong> to cycle through different song examples</p>
            <p><strong>Words with multiple meanings:</strong> Swipe up/down on the back of the card to cycle through different definitions</p>
            <p><strong>Arrow buttons</strong> to navigate cards manually</p>
            <hr style="margin: 15px 0; border: none; border-top: 1px solid var(--border-color);">
            <p><strong>About This Mode:</strong></p>
            <p>Learn Spanish vocabulary from Bad Bunny's lyrics. Words are ranked by how often they appear across his discography, so you learn the most common words first.</p>
            <p>Each word includes real lyric examples from his songs.</p>
        `;
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

