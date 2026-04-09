// Authentication, Google Sheets sync, and progress persistence.
// Key functions: saveWordProgress(), loadUserProgressFromSheet(), submitLogin().
import './state.js';

async function loadSecrets() {
    try {
        const response = await fetch('backend/secrets.json');
        if (response.ok) {
            const secrets = await response.json();
            GOOGLE_SCRIPT_URL = secrets.googleScriptUrl || '';
            window._spotifyClientId = secrets.spotifyClientId || '';
            window._spotifyRedirectUri = secrets.spotifyRedirectUri || '';
        }
    } catch (error) {
        console.warn('Could not load backend/secrets.json - Google Sheets sync will be disabled');
    }
}

// Check authentication on page load
function checkAuthentication() {
    const savedUser = localStorage.getItem('flashcardUser');
    if (savedUser) {
        currentUser = JSON.parse(savedUser);
        showUserInfo();
        hideAuthModal();
    } else {
        showAuthModal();
    }
}

// Show authentication modal
function showAuthModal() {
    const authModal = document.getElementById('authModal');
    authModal.classList.remove('hidden');
    document.getElementById('setupPanel').style.display = 'none';
}

// Hide authentication modal
function hideAuthModal() {
    const authModal = document.getElementById('authModal');
    authModal.classList.add('hidden');
    document.getElementById('setupPanel').style.display = 'block';
}

// Show user info badge — no longer unhides #userInfo here;
// the floating toolbar is shown/hidden by showFloatingBtns() in flashcard mode.
function showUserInfo() {
}

// Guest mode handler
function enterGuestMode() {
    currentUser = { isGuest: true };
    localStorage.setItem('flashcardUser', JSON.stringify(currentUser));
    showUserInfo();
    hideAuthModal();
    updateIncorrectButtonVisibility();
}

// Show login form
function showLoginForm() {
    document.getElementById('guestModeBtn').style.display = 'none';
    document.getElementById('loginModeBtn').style.display = 'none';
    document.getElementById('loginForm').classList.remove('hidden');
    document.getElementById('userInitials').focus();
}

// Hide login form
function hideLoginForm() {
    document.getElementById('guestModeBtn').style.display = 'flex';
    document.getElementById('loginModeBtn').style.display = 'flex';
    document.getElementById('loginForm').classList.add('hidden');
    document.getElementById('userInitials').value = '';
}

// Submit initials and login
async function submitLogin() {
    const initials = document.getElementById('userInitials').value.trim().toUpperCase();

    if (initials.length < 2 || initials.length > 4 || !/^[A-Z]+$/.test(initials)) {
        alert('Please enter 2-4 letters (A-Z only)');
        return;
    }

    currentUser = { initials: initials, isGuest: false };
    localStorage.setItem('flashcardUser', JSON.stringify(currentUser));
    showUserInfo();
    hideAuthModal();

    // Load user progress from Google Sheets
    await loadUserProgressFromSheet();
}

// Logout handler
function logout() {
    if (confirm('Are you sure you want to logout? Unsaved progress will be lost.')) {
        if (currentUser?.initials) {
            localStorage.removeItem(`progress_cache_${currentUser.initials}`);
        }
        localStorage.removeItem('flashcardUser');
        currentUser = null;
        progressData = {};
        document.getElementById('userInfo').classList.add('hidden');

        // Reset app state
        flashcards = [];
        currentIndex = 0;
        stats = {
            studied: new Set(),
            correct: 0,
            incorrect: 0,
            total: 0,
            cardStats: {}
        };

        // Hide app content and show auth modal
        document.getElementById('appContent').classList.add('hidden');
        showAuthModal();
    }
}

// ========== ID MIGRATION (one-time) ==========

// Migrate localStorage progress from old rank-based IDs to new md5-based IDs
async function migrateLocalStorageIds() {
    if (localStorage.getItem('id_migration_v1') === 'done') return;

    const key = 'flashcard_progress_guest';
    const guestProgress = JSON.parse(localStorage.getItem(key) || '{}');
    if (Object.keys(guestProgress).length === 0) {
        localStorage.setItem('id_migration_v1', 'done');
        return;
    }

    // Determine which languages have progress (from the 2-char prefix of fullIds)
    const langMap = { es: 'Spanish', sv: 'Swedish', it: 'Italian', nl: 'Dutch', pl: 'Polish' };
    const neededLangs = new Set();
    for (const fullId of Object.keys(guestProgress)) {
        const prefix = fullId.slice(0, 2);
        if (langMap[prefix]) neededLangs.add(prefix);
    }

    // Load migration mappings for needed languages
    const mappings = {};
    for (const prefix of neededLangs) {
        const lang = langMap[prefix];
        try {
            const resp = await fetch(`Data/${lang}/id_migration.json`);
            if (resp.ok) mappings[prefix] = await resp.json();
        } catch (e) {
            console.warn(`Could not load ID migration for ${lang}:`, e);
        }
    }

    // Remap keys
    const migrated = {};
    let remapped = 0;
    for (const [fullId, data] of Object.entries(guestProgress)) {
        const prefix = fullId.slice(0, 2);
        const mode = fullId[2];
        const oldHex = fullId.slice(3);
        const mapping = mappings[prefix];

        if (mapping && mode === '0' && mapping[oldHex]) {
            const newFullId = prefix + mode + mapping[oldHex];
            migrated[newFullId] = data;
            remapped++;
        } else {
            migrated[fullId] = data; // keep as-is (artist mode IDs unchanged, or no mapping)
        }
    }

    if (remapped > 0) {
        localStorage.setItem(key, JSON.stringify(migrated));
        console.log(`Migrated ${remapped} localStorage progress IDs`);
    }
    localStorage.setItem('id_migration_v1', 'done');
}

// Migrate localStorage progress from 4-char hex IDs to 6-char hex IDs
// Uses the same id_migration.json files (which now include 4char→6char mappings)
async function migrateLocalStorageIdsV2() {
    if (localStorage.getItem('id_migration_v2') === 'done') return;

    const key = 'flashcard_progress_guest';
    const guestProgress = JSON.parse(localStorage.getItem(key) || '{}');
    if (Object.keys(guestProgress).length === 0) {
        localStorage.setItem('id_migration_v2', 'done');
        return;
    }

    const langMap = { es: 'Spanish', sv: 'Swedish', it: 'Italian', nl: 'Dutch', pl: 'Polish' };
    const neededLangs = new Set();
    for (const fullId of Object.keys(guestProgress)) {
        const prefix = fullId.slice(0, 2);
        if (langMap[prefix]) neededLangs.add(prefix);
    }

    const mappings = {};
    for (const prefix of neededLangs) {
        const lang = langMap[prefix];
        try {
            const resp = await fetch(`Data/${lang}/id_migration.json`);
            if (resp.ok) mappings[prefix] = await resp.json();
        } catch (e) {
            console.warn(`Could not load ID migration for ${lang}:`, e);
        }
    }

    const migrated = {};
    let remapped = 0;
    for (const [fullId, data] of Object.entries(guestProgress)) {
        const prefix = fullId.slice(0, 2);
        const mode = fullId[2];
        const oldHex = fullId.slice(3);
        const mapping = mappings[prefix];

        if (mapping && mode === '0' && mapping[oldHex]) {
            const newFullId = prefix + mode + mapping[oldHex];
            migrated[newFullId] = data;
            remapped++;
        } else {
            migrated[fullId] = data;
        }
    }

    if (remapped > 0) {
        localStorage.setItem(key, JSON.stringify(migrated));
        console.log(`Migrated ${remapped} localStorage progress IDs (4-char → 6-char)`);
    }
    localStorage.setItem('id_migration_v2', 'done');
}

// ========== GOOGLE SHEETS INTEGRATION ==========

// Load user progress from Google Sheets (both mode tabs for cross-mode sharing).
// Loads from localStorage cache first (instant), then refreshes from Sheets.
// Returns true if the Sheets fetch brought different data than the cache.
async function loadUserProgressFromSheet() {
    if (!currentUser || currentUser.isGuest) return false;

    // 1. Load from localStorage cache immediately
    const cacheKey = `progress_cache_${currentUser.initials}`;
    const cached = localStorage.getItem(cacheKey);
    if (cached) {
        try {
            const { progress, estimates } = JSON.parse(cached);
            progressData = progress || {};
            levelEstimates = estimates || {};
            updateIncorrectButtonVisibility();
            updateTotalStatsButtonVisibility();
            console.log(`Loaded ${Object.keys(progressData).length} cached progress entries`);
        } catch (e) {
            console.warn('Failed to parse progress cache:', e);
        }
    }

    // 2. Fetch fresh data from Google Sheets
    const primarySheet = activeArtist ? 'Lyrics' : 'UserProgress';
    const secondarySheet = activeArtist ? 'UserProgress' : 'Lyrics';

    const fetchSheet = (sheet) =>
        fetch(GOOGLE_SCRIPT_URL, {
            method: 'POST',
            body: JSON.stringify({ action: 'load', user: currentUser.initials, sheet })
        }).then(r => r.json()).catch(() => null);

    try {
        const [primaryResult, secondaryResult] = await Promise.all([
            fetchSheet(primarySheet),
            fetchSheet(secondarySheet)
        ]);

        const prevCount = Object.keys(progressData).length;
        progressData = {};

        // Load secondary sheet first so primary overwrites on conflict
        const mergeProgress = (result, label) => {
            if (!result?.success || !result.data?.progress) return 0;
            result.data.progress.forEach(item => {
                progressData[item.wordId] = {
                    word: item.word,
                    language: item.language,
                    correct: item.correct,
                    wrong: item.wrong,
                    lastCorrect: item.lastCorrect,
                    lastWrong: item.lastWrong,
                    lastSeen: item.lastSeen
                };
            });
            return result.data.progress.length;
        };

        const secondaryCount = mergeProgress(secondaryResult, secondarySheet);
        const primaryCount = mergeProgress(primaryResult, primarySheet);
        console.log(`Loaded progress: ${primaryCount} from ${primarySheet}, ${secondaryCount} from ${secondarySheet}`);

        if (primaryResult?.success && primaryResult.data?.levelEstimates) {
            levelEstimates = primaryResult.data.levelEstimates;
        }
        // Also pick up level estimates from secondary sheet if primary had none
        if (secondaryResult?.success && secondaryResult.data?.levelEstimates) {
            for (const [lang, rank] of Object.entries(secondaryResult.data.levelEstimates)) {
                if (!levelEstimates[lang]) levelEstimates[lang] = rank;
            }
        }

        updateIncorrectButtonVisibility();
        updateTotalStatsButtonVisibility();

        // 3. Update cache
        localStorage.setItem(cacheKey, JSON.stringify({
            progress: progressData,
            estimates: levelEstimates
        }));

        // Return whether data changed (different count = something changed)
        const newCount = Object.keys(progressData).length;
        return newCount !== prevCount || !cached;
    } catch (error) {
        console.error('Failed to load progress from Google Sheets:', error);
        // Continue with cached data if available
        return false;
    }
}

// Save the level estimate sentinel row to Google Sheets
async function saveLevelEstimateToSheet(rank) {
    if (!currentUser || currentUser.isGuest) return;
    try {
        await fetch(GOOGLE_SCRIPT_URL, {
            method: 'POST',
            body: JSON.stringify({
                action: 'save',
                user: currentUser.initials,
                word: '_LEVEL_ESTIMATE_',
                language: selectedLanguage,
                wordId: rank,
                sheet: activeArtist ? 'Lyrics' : 'UserProgress'
            })
        });
    } catch (error) {
        console.error('Failed to save level estimate:', error);
    }
}

// Save progress for a single word to Google Sheets
async function saveWordProgress(card, isCorrect) {
    const wordId = card.fullId; // composite ID: {lang}{mode}{hex} e.g. "es00001", "es10039"
    const word = card.targetWord;
    const language = selectedLanguage;
    const timestamp = new Date().toISOString();

    if (!currentUser || currentUser.isGuest) {
        // For guest mode, save to LocalStorage
        saveToLocalStorage(wordId, isCorrect);
        return;
    }

    // Update local progress data
    if (!progressData[wordId]) {
        progressData[wordId] = {
            word: word,
            language: language,
            correct: 0,
            wrong: 0,
            lastCorrect: null,
            lastWrong: null,
            lastSeen: null
        };
    }

    if (isCorrect) {
        progressData[wordId].correct++;
        progressData[wordId].lastCorrect = timestamp;
    } else {
        progressData[wordId].wrong++;
        progressData[wordId].lastWrong = timestamp;
    }
    progressData[wordId].lastSeen = timestamp;
    progressData[wordId].word = word;
    progressData[wordId].language = language;

    // Save to Google Sheets
    try {
        const response = await fetch(GOOGLE_SCRIPT_URL, {
            method: 'POST',
            body: JSON.stringify({
                action: 'save',
                user: currentUser.initials,
                word: word,
                language: language,
                wordId: wordId,
                correct: progressData[wordId].correct,
                wrong: progressData[wordId].wrong,
                lastCorrect: progressData[wordId].lastCorrect,
                lastWrong: progressData[wordId].lastWrong,
                lastSeen: progressData[wordId].lastSeen,
                sheet: activeArtist ? 'Lyrics' : 'UserProgress'
            })
        });

        const result = await response.json();
        if (!result.success) {
            console.error('Failed to save progress:', result.message);
        }
    } catch (error) {
        console.error('Failed to save progress to Google Sheets:', error);
        // Fallback to LocalStorage
        saveToLocalStorage(wordId, isCorrect);
    }
}

// LocalStorage fallback for guest mode
function saveToLocalStorage(wordId, isCorrect) {
    const key = 'flashcard_progress_guest';
    let guestProgress = JSON.parse(localStorage.getItem(key) || '{}');

    if (!guestProgress[wordId]) {
        guestProgress[wordId] = { correct: 0, wrong: 0 };
    }

    if (isCorrect) {
        guestProgress[wordId].correct++;
    } else {
        guestProgress[wordId].wrong++;
    }

    localStorage.setItem(key, JSON.stringify(guestProgress));
}

// Setup authentication modal event listeners
function setupAuthEventListeners() {
    // Guest mode button
    document.getElementById('guestModeBtn').addEventListener('click', enterGuestMode);

    // Login mode button
    document.getElementById('loginModeBtn').addEventListener('click', showLoginForm);

    // Cancel login button
    document.getElementById('cancelLoginBtn').addEventListener('click', hideLoginForm);

    // Submit initials button
    document.getElementById('submitInitialsBtn').addEventListener('click', submitLogin);

    // Enter key in initials input
    document.getElementById('userInitials').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            submitLogin();
        }
    });

    // Enable/disable submit button based on input
    document.getElementById('userInitials').addEventListener('input', (e) => {
        const initials = e.target.value.trim();
        const submitBtn = document.getElementById('submitInitialsBtn');
        const isValid = initials.length >= 2 && initials.length <= 4 && /^[A-Za-z]+$/.test(initials);
        submitBtn.disabled = !isValid;
    });

    // Clear level estimate button
    document.getElementById('clearLevelEstimateRow').addEventListener('click', function() {
        levelEstimates[selectedLanguage] = 0;
        saveLevelEstimateToSheet(0);
        document.getElementById('clearLevelEstimateRow').style.display = 'none';
        renderRangeSelector(); // refresh range mastered states
    });

    // Logout button (now in settings modal)
    document.getElementById('logoutBtn').addEventListener('click', function() {
        hideSettingsModal();
        logout();
    });

    // Gear button opens settings modal
    document.getElementById('gearBtn').addEventListener('click', function() {
        showSettingsModal();
    });

    // Settings modal tabs
    document.querySelectorAll('.settings-tab').forEach(tab => {
        tab.addEventListener('click', function() {
            const tabName = this.dataset.tab;

            // Update active tab button
            document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
            this.classList.add('active');

            // Update active tab content
            document.querySelectorAll('.settings-tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(tabName + 'TabContent').classList.add('active');
        });
    });

    // Settings modal close button
    document.getElementById('closeSettingsModal').addEventListener('click', hideSettingsModal);

    // Click outside settings modal to close
    document.getElementById('settingsModal').addEventListener('click', function(e) {
        if (e.target === this) {
            hideSettingsModal();
        }
    });

    // Total stats modal close button
    document.getElementById('closeTotalStatsModal').addEventListener('click', hideTotalStatsModal);

    // Click outside total stats modal to close
    document.getElementById('totalStatsModal').addEventListener('click', function(e) {
        if (e.target === this) {
            hideTotalStatsModal();
        }
    });
}

window.migrateLocalStorageIds = migrateLocalStorageIds;
window.migrateLocalStorageIdsV2 = migrateLocalStorageIdsV2;
window.loadSecrets = loadSecrets;
window.checkAuthentication = checkAuthentication;
window.showAuthModal = showAuthModal;
window.hideAuthModal = hideAuthModal;
window.showUserInfo = showUserInfo;
window.enterGuestMode = enterGuestMode;
window.showLoginForm = showLoginForm;
window.hideLoginForm = hideLoginForm;
window.submitLogin = submitLogin;
window.logout = logout;
window.loadUserProgressFromSheet = loadUserProgressFromSheet;
window.saveLevelEstimateToSheet = saveLevelEstimateToSheet;
window.saveWordProgress = saveWordProgress;
window.saveToLocalStorage = saveToLocalStorage;
window.setupAuthEventListeners = setupAuthEventListeners;
