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

// Detect whether this page load is a reload (F5 / Cmd-R) versus a fresh
// navigation (link click, mode switch to ?artist=..., new tab). Uses the
// modern Navigation Timing API with a fallback to the deprecated
// performance.navigation interface for older browsers.
function _isPageReload() {
    try {
        const nav = performance.getEntriesByType('navigation')[0];
        if (nav && nav.type) return nav.type === 'reload';
    } catch (_) {}
    if (performance && performance.navigation) {
        return performance.navigation.type === 1;  // TYPE_RELOAD
    }
    return false;
}

// Check authentication on page load.
//
// Named users persist in localStorage — survive across browser sessions.
// Guest users persist in sessionStorage but ONLY across same-tab
// navigations (mode switch, artist switch). A user-initiated reload
// explicitly drops the guest session, so refreshing always surfaces the
// landing — useful for Josh's testing and for any visitor who wants to
// see the landing again without closing the tab.
//
// Summary of cases:
//   - refresh (F5/Cmd-R)   → clear guest session → landing
//   - mode/artist switch   → keep guest session → app, no landing
//   - new tab at app URL   → no session → landing
//   - new tab at ?about=1  → no session → landing + About on top
//   - named user, any case → logged in (localStorage)
function checkAuthentication() {
    // User-initiated refresh should drop guest mode so the landing reappears.
    if (_isPageReload()) {
        sessionStorage.removeItem('flashcardGuestSession');
    }

    const savedUser = localStorage.getItem('flashcardUser');
    if (savedUser) {
        try {
            const parsed = JSON.parse(savedUser);
            if (parsed && parsed.isGuest) {
                localStorage.removeItem('flashcardUser');  // legacy cleanup
            } else if (parsed) {
                currentUser = parsed;
                showUserInfo();
                hideAuthModal();
                return;
            }
        } catch (e) {
            localStorage.removeItem('flashcardUser');
        }
    }
    // Tab-scoped guest session: survives same-tab navigations (mode/artist
    // switches) but was just cleared above if this load is a reload.
    if (sessionStorage.getItem('flashcardGuestSession') === '1') {
        currentUser = { isGuest: true };
        showUserInfo();
        hideAuthModal();
        return;
    }
    showAuthModal();
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

// Guest mode handler.
//
// Writes a sessionStorage marker so guest state survives same-tab
// navigations (mode switch → ?artist=..., artist swap, etc.) but NOT a
// user-initiated refresh. The refresh distinction is enforced in
// checkAuthentication() via the Navigation Timing API — so refreshing
// always surfaces the landing, while clicking "Normal mode" from the top
// bar keeps you in the app as guest.
//
// Progress is still never persisted for guests.
function enterGuestMode() {
    currentUser = { isGuest: true };
    sessionStorage.setItem('flashcardGuestSession', '1');
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

// Logout handler. Guests skip the confirm (nothing to lose); named users get
// the prompt since they might have unsaved progress in flight.
function logout() {
    const isGuest = currentUser?.isGuest;
    if (!isGuest && !confirm('Are you sure you want to logout? Unsaved progress will be lost.')) {
        return;
    }

    if (currentUser?.initials) {
        localStorage.removeItem(`progress_cache_${currentUser.initials}`);
    }
    localStorage.removeItem('flashcardUser');
    // Clean the legacy sessionStorage guest marker too, in case it's lingering.
    sessionStorage.removeItem('flashcardGuestSession');
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

    // Guest sessions are ephemeral — nothing to persist.
    if (!currentUser || currentUser.isGuest) return;

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
        // In-memory progressData was already updated above; the card counts
        // stay correct for this session. A transient network blip means the
        // write just misses the sheet — not catastrophic for a single card.
    }
}

// Minimal Markdown → HTML renderer. Handles headings (##/###), paragraphs,
// unordered lists, bold/italic, inline code, links, and images. Enough for
// the About copy at docs/about.md without a runtime dependency.
function renderMarkdown(md) {
    const escape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    // Media extensions that render as <video autoplay loop muted> instead of <img>.
    // Drop a recording at the referenced path and it becomes a looping silent demo
    // clip inside the About modal.
    const VIDEO_EXT_RE = /\.(webm|mp4|mov|ogv|m4v)$/i;

    const inline = (s) => {
        let out = escape(s);
        out = out.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => {
            // demo://<mode> — mount point for a live animated card demo. The mode
            // ("normal" or "artist") picks which card variant to render. alt text
            // becomes the accessible label for screen readers.
            if (src.startsWith('demo://')) {
                const mode = src.slice('demo://'.length).replace(/[^a-zA-Z0-9_-]/g, '');
                return '<div class="about-demo-card" data-mode="' + mode + '"'
                    + ' role="img" aria-label="' + alt + '"></div>';
            }
            if (VIDEO_EXT_RE.test(src)) {
                return '<figure class="about-figure about-figure-video">'
                    + '<video src="' + src + '" autoplay loop muted playsinline preload="metadata"'
                    + ' onerror="this.parentElement.classList.add(\'about-figure-missing\')">'
                    + '</video>'
                    + '<figcaption>' + alt + '</figcaption>'
                    + '</figure>';
            }
            return '<figure class="about-figure">'
                + '<img src="' + src + '" alt="' + alt + '" loading="lazy"'
                + ' onerror="this.parentElement.classList.add(\'about-figure-missing\')" />'
                + '<figcaption>' + alt + '</figcaption>'
                + '</figure>';
        });
        out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
            '<a href="$2" target="_blank" rel="noopener">$1</a>');
        out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
        out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
        return out;
    };

    const lines = md.split('\n');
    const html = [];
    let list = [];
    let para = [];
    const flushList = () => {
        if (list.length) {
            html.push('<ul>' + list.map(l => '<li>' + inline(l) + '</li>').join('') + '</ul>');
            list = [];
        }
    };
    const flushPara = () => {
        if (para.length) {
            html.push('<p>' + inline(para.join(' ')) + '</p>');
            para = [];
        }
    };
    const flushAll = () => { flushList(); flushPara(); };

    // Simple HTML-comment skip so sections can be temporarily hidden in
    // about.md without deleting them. Single-line `<!-- ... -->` is dropped;
    // multi-line blocks starting with `<!--` consume lines until one ends
    // with `-->`.
    let inComment = false;
    for (const raw of lines) {
        const line = raw.trim();
        if (inComment) {
            if (line.endsWith('-->')) inComment = false;
            continue;
        }
        if (line.startsWith('<!--')) {
            if (!line.endsWith('-->')) inComment = true;
            continue;
        }
        if (!line) { flushAll(); continue; }
        if (line.startsWith('### ')) { flushAll(); html.push('<h3>' + inline(line.slice(4)) + '</h3>'); }
        else if (line.startsWith('## ')) { flushAll(); html.push('<h2>' + inline(line.slice(3)) + '</h2>'); }
        else if (line.startsWith('# ')) { flushAll(); html.push('<h1>' + inline(line.slice(2)) + '</h1>'); }
        else if (line.startsWith('- ') || line.startsWith('* ')) { flushPara(); list.push(line.slice(2)); }
        else { flushList(); para.push(line); }
    }
    flushAll();
    return html.join('\n');
}

// Keep the `?about=1` URL param in sync with the About modal's open state so
// the landing page is shareable (send `?about=1` to a recruiter; they see the
// landing cold) AND refreshing while viewing it stays on the landing.
function _setAboutURLParam(open) {
    try {
        const url = new URL(window.location);
        const has = url.searchParams.has('about');
        if (open && !has) {
            url.searchParams.set('about', '1');
            history.replaceState(null, '', url.toString());
        } else if (!open && has) {
            url.searchParams.delete('about');
            const qs = url.searchParams.toString();
            const clean = url.pathname + (qs ? '?' + qs : '') + url.hash;
            history.replaceState(null, '', clean);
        }
    } catch (_) { /* older browsers: no-op */ }
}

// Append the footnote + data-sources section at the bottom of the About
// body. The ¹ footnote is paired with the superscript next to the Spotify
// logo on the artist demo card. The sources line credits the external
// datasets the pipeline depends on — short, reads as end-matter, same
// muted styling as the footnote above it.
function _appendAboutFootnotes(body) {
    const existing = body.querySelector('.about-footnotes');
    if (existing) existing.remove();

    const notes = document.createElement('aside');
    notes.className = 'about-footnotes';
    notes.innerHTML =
        '<p id="about-footnote-1">'
        + '<sup class="about-footnote-number">1</sup> '
        + 'Right now three Spanish artists (Bad Bunny, Rosalía, Young Miko) and one French playlist are built in. '
        + 'The pipeline itself runs on any Spotify playlist — '
        + 'the goal is to let anyone paste in a playlist URL and generate a full vocabulary deck from its lyrics.'
        + '</p>'
        + '<p class="about-references">'
        + '<strong>Sources:</strong> lyrics from Genius, synced timestamps via LRCLIB and Spotify, '
        + 'word senses from Wiktionary and SpanishDict, frequency corpora from OpenSubtitles and Tatoeba, '
        + 'Spanish conjugations from Jehle, cognate detection via CogNet.'
        + '</p>';
    body.appendChild(notes);
}

// Swap the top-right close affordance based on auth state. For already-
// authenticated users it becomes a pill-shaped "Back to the app" button
// (same action as the bottom CTA — visible while scrolling). For
// unauthenticated users the plain ✕ stays, because the bottom CTAs push
// them to pick Guest/Login and a "Back to the app" affordance makes no
// sense before they've chosen.
function _updateAboutCloseButton() {
    const btn = document.getElementById('closeAboutProjectModal');
    if (!btn) return;
    if (currentUser) {
        btn.textContent = '← Back to the app';
        btn.classList.add('about-close-as-pill');
        btn.setAttribute('aria-label', 'Back to the app');
    } else {
        btn.textContent = '✕';
        btn.classList.remove('about-close-as-pill');
        btn.setAttribute('aria-label', 'Close');
    }
}

// Append CTAs to the rendered About body so a first-time visitor has a direct
// path into the app from the landing. If the user is already authenticated,
// collapse the pair into a single "Back to the app" button.
function _appendAboutCTAs(body) {
    const existing = body.querySelector('.about-ctas');
    if (existing) existing.remove();

    const cta = document.createElement('div');
    cta.className = 'about-ctas';

    if (currentUser) {
        const name = currentUser.isGuest ? 'Guest' : (currentUser.initials || 'Back');
        cta.innerHTML =
            '<button type="button" class="about-cta-btn primary" id="aboutCTABack">'
            + 'Back to the app' + (currentUser.isGuest ? '' : ' (' + name + ')') + '</button>';
        body.appendChild(cta);
        document.getElementById('aboutCTABack').addEventListener('click', hideAboutProjectModal);
    } else {
        cta.innerHTML =
            '<div class="about-ctas-label">Ready to try it?</div>'
            + '<div class="about-ctas-buttons">'
            +   '<button type="button" class="about-cta-btn secondary" id="aboutCTAGuest">Try it as Guest</button>'
            +   '<button type="button" class="about-cta-btn primary" id="aboutCTALogin">Log in with your name</button>'
            + '</div>';
        body.appendChild(cta);
        document.getElementById('aboutCTAGuest').addEventListener('click', () => {
            hideAboutProjectModal();
            enterGuestMode();
        });
        document.getElementById('aboutCTALogin').addEventListener('click', () => {
            hideAboutProjectModal();
            // Auth modal is already visible underneath; surface the login form.
            if (typeof showLoginForm === 'function') showLoginForm();
        });
    }
}

let _aboutMarkdownCache = null;
async function openAboutProjectModal() {
    const modal = document.getElementById('aboutProjectModal');
    const body = document.getElementById('aboutProjectBody');
    modal.classList.remove('hidden');
    _setAboutURLParam(true);
    if (_aboutMarkdownCache) {
        body.innerHTML = _aboutMarkdownCache;
        layoutAboutTwoModes(body);
        mountAboutDemos(body);
        _appendAboutFootnotes(body);
        _appendAboutCTAs(body);
        _updateAboutCloseButton();
        return;
    }
    try {
        const resp = await fetch('docs/about.md');
        if (!resp.ok) throw new Error('Failed to load about.md');
        const md = await resp.text();
        _aboutMarkdownCache = renderMarkdown(md);
        body.innerHTML = _aboutMarkdownCache;
        layoutAboutTwoModes(body);
        mountAboutDemos(body);
        _appendAboutFootnotes(body);
        _appendAboutCTAs(body);
        _updateAboutCloseButton();
    } catch (e) {
        console.error('About modal: failed to load markdown', e);
        body.innerHTML = '<p style="color: var(--text-muted);">Could not load project description.</p>';
    }
}

function hideAboutProjectModal() {
    const modal = document.getElementById('aboutProjectModal');
    if (!modal) return;
    modal.classList.add('hidden');
    modal.querySelectorAll('video').forEach(v => { try { v.pause(); } catch (_) {} });
    _setAboutURLParam(false);
}

// ----- About-modal card demos --------------------------------------------------
//
// Live animated cards inserted into the About modal wherever `demo://<mode>`
// appears in the Markdown. Reuses the app's .card / .card-face / .flipped CSS so
// the demo is visually identical to the real flashcard — we just drive it with
// a tiny sequential animation instead of user input. Each demo runs in its own
// async loop that exits when its container leaves the DOM (modal closes).

// Demo data mirrors the real vocab entry shape from Data/Spanish/vocabulary.json:
//   { word, lemma, pos, rank, meanings: [{ pos, translation, target, english }] }
// The content is copy-pasted from actual entries so the demo shows what real
// cards say, not made-up examples. Rendering uses the same classes the main
// app's updateCard() produces (.card-word, .card-pos, .meaning-row.meaning-row-regular,
// .meanings-scroll, .sentence, .translation) so the look is 1:1 with the real card.
const _ABOUT_DEMO_DECKS = {
    normal: [
        {
            word: 'pasar',
            pos: 'VERB',
            rank: 47,
            meanings: [
                { pos: 'VERB', translation: 'to spend',
                  target: 'Él va a pasar el fin de semana con su tío.',
                  english: "He's going to spend the weekend with his uncle." },
                { pos: 'VERB', translation: 'to happen',
                  target: '¿Puede volver a pasar algo así?',
                  english: 'Could something like this happen again?' },
                { pos: 'VERB', translation: 'to pass',
                  target: 'Voy a tener que pasar de eso.',
                  english: "I'm going to have to pass on that." },
            ],
        },
        {
            word: 'decir',
            pos: 'VERB',
            rank: 36,
            meanings: [
                { pos: 'VERB', translation: 'to say',
                  target: 'Cuando estés enfadado, cuenta hasta diez antes de decir nada.',
                  english: 'When angry, count to ten before saying anything.' },
                { pos: 'VERB', translation: 'to tell',
                  target: 'Hay algo que te necesito decir antes de que te vayas.',
                  english: 'There is something I need to tell you before you leave.' },
            ],
        },
    ],
    artist: [
        {
            word: 'corazón',
            pos: 'NOUN',
            rank: 24,
            song: 'CALLAÍTA · Bad Bunny',
            meanings: [
                { pos: 'NOUN', translation: 'heart',
                  target: 'Tú eres la dueña de mi corazón',
                  english: "You're the owner of my heart" },
            ],
        },
        {
            word: 'fuego',
            pos: 'NOUN',
            rank: 58,
            song: 'ME PORTO BONITO · Bad Bunny',
            // Hand-curated sense examples — the demo cards are few enough that
            // we can hold this to a higher bar than the pipeline's automatic
            // assignments. Each example should unambiguously read as the sense
            // it's attached to.
            meanings: [
                { pos: 'NOUN', translation: 'fire',
                  target: 'La calle está en fuego, la calle tiene fuego',
                  english: 'The street is on fire, the street has fire' },
                { pos: 'NOUN', translation: 'passion',
                  target: 'Contigo siento un fuego que no se apaga',
                  english: "With you I feel a passion that doesn't fade" },
            ],
        },
    ],
};

function _buildAboutDemoCard(mode) {
    // DOM structure mirrors what updateCard() in flashcards.js produces:
    //   .card
    //     .card-face.card-front  — card-word, card-pos, card-ranking, song (artist only)
    //     .card-face.card-back
    //       .card-details
    //         .back-header        — big word repeated at the top of the back
    //         .meanings-scroll    — list of .meaning-row.meaning-row-regular
    //         .sentence           — accent-bordered example box
    //         .translation        — english line below
    // Rows are populated and a selected index is rotated by _runAboutDemo.
    const wrap = document.createElement('div');
    wrap.className = 'about-demo-card-inner';
    // Spotify logo as an inline SVG — tiny source-of-truth copy of the
    // iconic green-circle-with-soundwaves mark. Used only on artist-mode
    // cards to indicate lyric data comes from Spotify/Genius.
    const spotifyLogo =
        '<svg class="about-demo-spotify-logo" viewBox="0 0 24 24" aria-hidden="true">'
        + '<path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34'
        + 'c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539'
        + '-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3'
        + 'c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6'
        + '-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36'
        + 'C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381'
        + ' 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.42 1.56-.299.421-1.02.599-1.559.3z"/>'
        + '</svg>';
    wrap.innerHTML = `
        <div class="card">
            <div class="card-face card-front">
                <div class="card-word"></div>
                <div class="card-pos"></div>
                <div class="card-ranking"></div>
            </div>
            <div class="card-face card-back">
                <div class="card-details">
                    <div class="back-header">
                        <div class="about-demo-back-word"></div>
                    </div>
                    <div class="meanings-scroll"></div>
                    <div class="about-demo-example">
                        <div class="about-demo-example-target"></div>
                        <div class="about-demo-example-english"></div>
                    </div>
                    <div class="about-demo-spotify-row">
                        <span class="about-demo-song-back"></span>
                        <span class="about-demo-spotify-mark">
                            ${spotifyLogo}
                            <sup class="about-demo-footnote-ref" role="link" tabindex="0" aria-label="Read footnote 1">1</sup>
                        </span>
                    </div>
                </div>
            </div>
        </div>
    `;
    return wrap;
}

// Build the inner HTML of .meanings-scroll — one .meaning-row.meaning-row-regular
// per sense, with the selected one carrying .is-selected. Matches the inline
// structure produced by updateCard() at pipeline/flashcards.js:1453.
function _renderDemoMeaningRows(meanings, selectedIdx) {
    return meanings.map((m, idx) => {
        const selected = idx === selectedIdx ? ' is-selected' : '';
        const posClass = _posColorClass(m.pos);
        return `
            <div class="meaning-row meaning-row-regular${selected}">
                <span class="card-pos meaning-row-pos-pill ${posClass}">${m.pos}</span>
                <div class="meaning-row-body">
                    <span class="meaning-row-translation">${m.translation}</span>
                </div>
            </div>`;
    }).join('');
}

const _POS_CLASS_MAP = {
    VERB: 'pos-verb', NOUN: 'pos-noun', ADJ: 'pos-adj', ADV: 'pos-adv',
    PREP: 'pos-prep', ADP: 'pos-prep', CONJ: 'pos-conj', CCONJ: 'pos-conj',
    SCONJ: 'pos-conj', PRON: 'pos-pron', DET: 'pos-det', INT: 'pos-int',
    INTJ: 'pos-int', NUM: 'pos-num', MWE: 'pos-mwe',
};

function _posColorClass(pos) {
    const key = (pos || '').trim().toUpperCase().split(/[\s·]+/)[0];
    return _POS_CLASS_MAP[key] || '';
}

function _sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}

// Wrap any occurrence of `word` in the example sentence with a highlight span.
// Matches the real flashcard app's behaviour in updateCard() — word-boundary
// regex using unicode property escapes so it handles Spanish letters cleanly,
// case-insensitive so "Fuego" at sentence start still catches. Escapes HTML
// up-front so the raw sentence can't inject markup.
function _highlightTargetWord(sentence, word) {
    if (!sentence) return '';
    const escaped = sentence
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    if (!word) return escaped;
    const wordEsc = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    try {
        const re = new RegExp(`(?<![\\p{L}\\p{N}])(${wordEsc})(?![\\p{L}\\p{N}])`, 'giu');
        return escaped.replace(re, '<span class="about-demo-highlight">$1</span>');
    } catch (_) {
        // Older browsers without \p{...} support — just return the escaped text.
        return escaped;
    }
}

async function _runAboutDemo(container, mode) {
    const deck = _ABOUT_DEMO_DECKS[mode] || _ABOUT_DEMO_DECKS.normal;
    const card = container.querySelector('.card');
    const wordEl = container.querySelector('.card-word');
    const posEl = container.querySelector('.card-pos');
    const rankEl = container.querySelector('.card-ranking');
    const backWordEl = container.querySelector('.about-demo-back-word');
    const meaningsEl = container.querySelector('.meanings-scroll');
    const exampleTargetEl = container.querySelector('.about-demo-example-target');
    const exampleEnglishEl = container.querySelector('.about-demo-example-english');
    const spotifyRowEl = container.querySelector('.about-demo-spotify-row');
    const songBackEl = container.querySelector('.about-demo-song-back');

    const stillMounted = () => container.isConnected
        && !document.getElementById('aboutProjectModal').classList.contains('hidden');

    const setFrontPos = (pos) => {
        posEl.className = 'card-pos';
        const cls = _posColorClass(pos);
        if (cls) posEl.classList.add(cls);
        posEl.textContent = pos;
    };

    while (stillMounted()) {
        for (const entry of deck) {
            if (!stillMounted()) return;

            // -------- Front face --------
            card.classList.remove('flipped');
            wordEl.textContent = entry.word;
            setFrontPos(entry.pos);
            rankEl.textContent = entry.rank ? '#' + entry.rank : '';
            backWordEl.textContent = entry.word;
            // Spotify row on the back — only artist-mode entries carry a
            // `song` field; for normal-mode cards hide the row entirely.
            if (entry.song && songBackEl && spotifyRowEl) {
                songBackEl.textContent = entry.song;
                spotifyRowEl.style.display = '';
            } else if (spotifyRowEl) {
                spotifyRowEl.style.display = 'none';
            }

            await _sleep(4000);
            if (!stillMounted()) return;

            // -------- Flip and cycle through senses --------
            card.classList.add('flipped');
            await _sleep(1100); // matches .card transition + settle

            for (let i = 0; i < entry.meanings.length; i++) {
                if (!stillMounted()) return;
                const m = entry.meanings[i];
                meaningsEl.innerHTML = _renderDemoMeaningRows(entry.meanings, i);
                // Target sentence is HTML (with the target word wrapped in a
                // highlight span); the helper escapes the rest first so raw
                // data can't inject markup.
                exampleTargetEl.innerHTML = _highlightTargetWord(m.target, entry.word);
                exampleEnglishEl.textContent = m.english;
                // Dwell long enough to actually read the example sentence. A
                // single-sense entry sits longer since there's nothing else
                // to cycle to.
                const dwell = entry.meanings.length === 1 ? 5500 : 4500;
                await _sleep(dwell);
            }

            if (!stillMounted()) return;
            card.classList.remove('flipped');
            await _sleep(1500);
        }
    }
}

function mountAboutDemos(root) {
    const placeholders = root.querySelectorAll('.about-demo-card[data-mode]');
    placeholders.forEach(el => {
        if (el.dataset.mounted === '1') return;
        el.dataset.mounted = '1';
        const mode = el.dataset.mode;
        const inner = _buildAboutDemoCard(mode);
        el.appendChild(inner);

        // Wire the ¹ superscript next to the Spotify logo so clicking (or
        // pressing Enter on) it scrolls to the matching footnote. The modal
        // body owns its own scroll, so href="#..." anchors don't work — do
        // it explicitly with scrollIntoView.
        const ref = inner.querySelector('.about-demo-footnote-ref');
        if (ref) {
            const jumpToFootnote = (e) => {
                if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
                e.preventDefault();
                const note = root.querySelector('#about-footnote-1');
                if (note) note.scrollIntoView({ behavior: 'smooth', block: 'center' });
            };
            ref.addEventListener('click', jumpToFootnote);
            ref.addEventListener('keydown', jumpToFootnote);
        }

        _runAboutDemo(inner, mode);
    });
}

// Rewire the two mode-section <h3>s so they sit side by side on desktop.
// The Markdown source stays linear (easier to edit); we detect the
// "Normal mode" / "Lyrics mode" pair after rendering and wrap each h3 +
// its following siblings (up to the next h2 or h3) into a column. The
// "artist" alternative is matched for backward compatibility with any
// older about.md copy.
function layoutAboutTwoModes(root) {
    if (root.querySelector('.about-modes-row')) return;  // already laid out

    const h3s = Array.from(root.querySelectorAll('h3'));
    const normal = h3s.find(h => /^normal mode\b/i.test(h.textContent.trim()));
    const lyrics = h3s.find(h => /^(?:lyrics|artist) mode\b/i.test(h.textContent.trim()));
    if (!normal || !lyrics) return;

    // Drop a comment placeholder at the "Normal mode" h3's position BEFORE
    // we start detaching its siblings, so we have a stable anchor to swap
    // the finished row into afterwards.
    const anchor = document.createComment('about-modes-anchor');
    normal.parentNode.insertBefore(anchor, normal);

    const collectSection = (h3) => {
        const out = [h3];
        let el = h3.nextElementSibling;
        while (el && el.tagName !== 'H3' && el.tagName !== 'H2') {
            out.push(el);
            el = el.nextElementSibling;
        }
        return out;
    };
    const sections = [collectSection(normal), collectSection(lyrics)];

    const row = document.createElement('div');
    row.className = 'about-modes-row';
    for (const section of sections) {
        const col = document.createElement('div');
        col.className = 'about-modes-column';
        for (const child of section) col.appendChild(child);
        row.appendChild(col);
    }

    anchor.parentNode.replaceChild(row, anchor);
}

// Setup authentication modal event listeners
function setupAuthEventListeners() {
    // Guest mode button
    document.getElementById('guestModeBtn').addEventListener('click', enterGuestMode);

    // Login mode button
    document.getElementById('loginModeBtn').addEventListener('click', showLoginForm);

    // Login info button: toggle the no-password explanation
    const loginInfoBtn = document.getElementById('loginInfoBtn');
    const loginInfoNote = document.getElementById('loginInfoNote');
    if (loginInfoBtn && loginInfoNote) {
        loginInfoBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            loginInfoNote.classList.toggle('hidden');
        });
    }

    // About this project button. Fullscreen modal; only close paths are the ×
    // button and Escape. hideAboutProjectModal also strips ?about=1 from the
    // URL so refreshing after dismissing lands you in the app, not the modal.
    const aboutModal = document.getElementById('aboutProjectModal');
    document.getElementById('aboutProjectBtn').addEventListener('click', openAboutProjectModal);
    document.getElementById('closeAboutProjectModal').addEventListener('click', hideAboutProjectModal);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !aboutModal.classList.contains('hidden')) {
            hideAboutProjectModal();
        }
    });

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

    // Settings → Account → "About this project" row. Dismisses settings and
    // opens the landing page modal so signed-in users can revisit the
    // explainer after using the app for a bit.
    const aboutSettingsRow = document.getElementById('aboutProjectSettingsRow');
    if (aboutSettingsRow) {
        aboutSettingsRow.addEventListener('click', function() {
            hideSettingsModal();
            openAboutProjectModal();
        });
    }

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
window.openAboutProjectModal = openAboutProjectModal;
window.hideAboutProjectModal = hideAboutProjectModal;
window.hideLoginForm = hideLoginForm;
window.submitLogin = submitLogin;
window.logout = logout;
window.loadUserProgressFromSheet = loadUserProgressFromSheet;
window.saveLevelEstimateToSheet = saveLevelEstimateToSheet;
window.saveWordProgress = saveWordProgress;
window.setupAuthEventListeners = setupAuthEventListeners;
