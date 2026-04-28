// Card rendering, flip, swipe, keyboard shortcuts.
// Main function: updateCard() (~line 950) renders the current flashcard front + back.
// Key exports: updateCard, flipCard, nextCard, handleSwipeAction, selectMeaning, cycleExample.
import './state.js';
import './speech.js';

// --- Spanish rank lookup for personal easiness ---
let _spanishRanks = null;  // word -> rank (loaded once)
let _spanishRanksLoading = false;
let _conjugationData = null;  // lemma -> {tenses, gerund, past_participle, translation}
let _conjugationLoading = false;
let _conjugatedEnglishData = null;  // lemma -> translation -> tense -> 6-element person-indexed array
let _conjugatedEnglishLoading = false;

// Map verbecc tense keys (used in vocabulary.index.json's morphology field) to
// the keys produced by step_5e_build_conjugated_english.py. Identical today, but
// the indirection makes the mapping explicit and easy to extend.
const _MORPH_TENSE_TO_CONJ_EN = {
    "presente": "presente",
    "pretérito-perfecto-simple": "pretérito-perfecto-simple",
    "futuro": "futuro",
};

const _PERSON_TO_INDEX = { "1s": 0, "2s": 1, "3s": 2, "1p": 3, "2p": 4, "3p": 5 };

// Regex cache for the render hot path. Word/MWE/clitic highlight + filter
// patterns are deterministic in their inputs, so compiling once per unique
// (pattern, flags) and reusing avoids thousands of RegExp constructions
// per card render — especially the deck-word highlight loop which scales
// with deck size. Safe to share: callers use .test() on non-/g regexes
// and .replace() on /g ones, both of which are stateless across calls.
const _regexCache = new Map();
function _cachedRegex(pattern, flags) {
    const key = flags + ':' + pattern;
    let re = _regexCache.get(key);
    if (re === undefined) {
        re = new RegExp(pattern, flags);
        _regexCache.set(key, re);
    }
    return re;
}

function getConjugatedEnglish(card, translation) {
    if (!_conjugatedEnglishData || !card || !translation) return null;
    const morph = card.morphology;
    if (!morph || morph.mood !== "indicativo") return null;
    const tenseKey = _MORPH_TENSE_TO_CONJ_EN[morph.tense];
    const personIdx = _PERSON_TO_INDEX[morph.person];
    if (tenseKey === undefined || personIdx === undefined) return null;
    const lemma = (card.lemma || "").toLowerCase();
    const row = _conjugatedEnglishData?.[lemma]?.[translation]?.[tenseKey];
    return row ? (row[personIdx] || null) : null;
}

function formatMorphMood(mood) {
    const moodMap = {
        indicativo: '',        // indicative is default, omit
        subjuntivo: 'subjunctive',
        imperativo: 'imperative',
        gerundio: 'gerund',
        participio: 'past participle',
        participo: 'past participle',
        'participio-pasado': 'past participle',
        condicional: 'conditional',
        infinitivo: 'infinitive',
    };
    return moodMap[mood] || mood;
}

function formatMorphTense(tense) {
    const tenseMap = {
        presente: 'present',
        afirmativo: 'affirmative',
        negativo: 'negative',
        futuro: 'future',
        'futuro-perfecto': 'future perfect',
        'pretérito-perfecto-simple': 'preterite',
        'pretérito-imperfecto': 'imperfect',
        'pretérito-imperfecto-1': 'imperfect',
        'pretérito-imperfecto-2': 'imperfect',
        'pretérito-perfecto': 'present perfect',
        'pretérito-pluscuamperfecto-1': 'pluperfect',
        'pretérito-pluscuamperfecto-2': 'pluperfect',
        infinitivo: '',        // infinitive is implied by mood, omit
        gerundio: '',
        participo: '',
    };
    const mapped = tenseMap[tense];
    return mapped !== undefined ? mapped : tense;
}

function formatMorphPerson(person) {
    const personMap = {
        '1s': '1sg',
        '2s': '2sg',
        '3s': '3sg',
        '1p': '1pl',
        '2p': '2pl',
        '3p': '3pl',
    };
    return personMap[person] || person;
}

function formatMorphLabel(m) {
    return [
        formatMorphMood(m.mood),
        formatMorphTense(m.tense),
        formatMorphPerson(m.person),
    ].filter(Boolean).join(' · ');
}

async function loadSpanishRanks() {
    if (_spanishRanks || _spanishRanksLoading) return;
    _spanishRanksLoading = true;
    try {
        const resp = await fetch('Data/Spanish/spanish_ranks.json');
        if (resp.ok) _spanishRanks = await resp.json();
    } catch (e) {
        // Non-fatal — falls back to static easiness
    }
    _spanishRanksLoading = false;
}

async function loadConjugationData() {
    if (_conjugationData || _conjugationLoading) return;
    const langConfig = config.languages[selectedLanguage];
    if (!langConfig || !langConfig.conjugationsPath) return;
    _conjugationLoading = true;
    try {
        const resp = await fetch(langConfig.conjugationsPath);
        if (resp.ok) _conjugationData = await resp.json();
    } catch (e) {
        // Non-fatal — conjugation table just won't show
    }
    _conjugationLoading = false;
}

async function loadConjugatedEnglishData() {
    if (_conjugatedEnglishData || _conjugatedEnglishLoading) return;
    const langConfig = config.languages[selectedLanguage];
    if (!langConfig || !langConfig.conjugatedEnglishPath) return;
    _conjugatedEnglishLoading = true;
    try {
        const resp = await fetch(langConfig.conjugatedEnglishPath);
        if (resp.ok) _conjugatedEnglishData = await resp.json();
    } catch (e) {
        // Non-fatal — falls back to infinitive display
    }
    _conjugatedEnglishLoading = false;
}

// --- MWE translation split (JS mirror of pipeline/util_5c_spanishdict.split_mwe_translation) ---
// Applied at render time so existing decks (whose mwe_memberships predate the
// pipeline-side split) still get the two-line layout. New builds set m.context
// directly and skip this parser.
const _MWE_UOTFI_RE = /^\s*Used other than figuratively or idiomatically:\s*see[^.]*\.\s*/i;
const _MWE_USED_PREFIX_RE = /^\s*(Used [^:]+?):\s*/i;

function splitMWETranslation(raw) {
    if (typeof raw !== 'string' || !raw.trim()) return { primary: raw || '', context: '' };
    let s = raw.replace(_MWE_UOTFI_RE, '').trim();
    if (!s) return { primary: '', context: '' };
    let context = '';
    const pm = s.match(_MWE_USED_PREFIX_RE);
    if (pm) {
        context = pm[1].trim();
        s = s.slice(pm[0].length).trim();
        if (!s) return { primary: context, context: '' };
    }
    // Trailing balanced ``(...)`` split.
    if (s.endsWith(')')) {
        let depth = 0, start = -1;
        for (let i = s.length - 1; i >= 0; i--) {
            const c = s[i];
            if (c === ')') depth++;
            else if (c === '(') {
                depth--;
                if (depth === 0) { start = i; break; }
            }
        }
        if (start > 0) {
            const before = s.slice(0, start).trimEnd();
            const inside = s.slice(start + 1, -1).trim();
            if (before && inside) {
                context = context ? context + '; ' + inside : inside;
                s = before;
            }
        }
    }
    return { primary: s, context };
}

// --- Fit-text-to-single-line helper ---
// Shrinks ``el``'s inline font-size until the text fits on one line inside
// its constrained width. Starts from the element's computed (CSS-driven)
// font-size and steps down in 2px increments until the content no longer
// overflows with ``white-space: nowrap`` applied, or ``minPx`` is reached.
// CSS-level ``overflow-wrap: anywhere`` remains the last-resort fallback
// if the text still doesn't fit at ``minPx``.
//
// Called after setting ``textContent`` on front-of-card word + lemma so
// rare long words like "Sandungueo" shrink to fit instead of wrapping.
// Idempotent: clears any prior inline font-size on each call.
function shrinkToFit(el, minPx) {
    if (!el || !el.textContent) return;
    // Reset to CSS-driven baseline so repeated calls start from the same
    // maxPx. Without this, the previous card's shrunk size would become
    // the next card's starting point.
    el.style.fontSize = '';
    const maxPx = parseFloat(getComputedStyle(el).fontSize);
    if (!maxPx || maxPx <= minPx) return;
    const prevWS = el.style.whiteSpace;
    // Disable wrapping to expose intrinsic content width via scrollWidth.
    el.style.whiteSpace = 'nowrap';
    let size = maxPx;
    // scrollWidth is the content's ideal width; clientWidth is the
    // constrained element width (capped by max-width: 100% of parent).
    // When the former exceeds the latter, the text would need to wrap.
    while (size > minPx && el.scrollWidth > el.clientWidth) {
        size -= 2;
        el.style.fontSize = size + 'px';
    }
    el.style.whiteSpace = prevWS;
}

// Cache of known words built from progressData — rebuilt when progress changes
let _knownWordsCache = null;
let _knownWordsCacheSize = -1;

function getKnownWords() {
    const pdSize = Object.keys(progressData).length;
    if (_knownWordsCache && _knownWordsCacheSize === pdSize) return _knownWordsCache;
    _knownWordsCache = new Set();
    for (const p of Object.values(progressData)) {
        if (p.correct > 0 && p.word) _knownWordsCache.add(p.word.toLowerCase());
    }
    _knownWordsCacheSize = pdSize;
    return _knownWordsCache;
}

function computePersonalEasiness(spanishText) {
    if (!_spanishRanks || !spanishText) return 999999;
    // Strip ad-libs/brackets
    const cleaned = spanishText.replace(/\[[^\]]*\]|\([^\)]*\)/g, '').trim();
    if (!cleaned) return 999999;
    const tokens = cleaned.toLowerCase().replace(/[^\w\s']/g, ' ').split(/\s+/).filter(Boolean);
    if (!tokens.length) return 999999;

    // Get level estimate high-water mark
    const lang = selectedLanguage || 'spanish';
    const estimate = (levelEstimates && levelEstimates[lang]) || 0;
    const knownWords = getKnownWords();

    const unknownRanks = [];
    for (const t of tokens) {
        const rank = _spanishRanks[t];
        if (rank === undefined) continue;  // skip unrecognized tokens
        // Known if: rank <= level estimate, or word has been marked correct
        if (rank <= estimate || knownWords.has(t)) continue;
        unknownRanks.push(rank);
    }
    if (!unknownRanks.length) return 999999;  // all known — sort last
    unknownRanks.sort((a, b) => a - b);
    return unknownRanks[Math.floor(unknownRanks.length / 2)];  // median
}

// Compute % of example lines where every vocabulary word is known.
// Returns { understood, total, pct } or null if data not available.
function computeLinesUnderstood() {
    if (!_spanishRanks || !progressData) return null;
    const examplesData = window._cachedExamplesData;
    if (!examplesData) return null;

    const lang = selectedLanguage || 'spanish';
    const estimate = (levelEstimates && levelEstimates[lang]) || 0;
    const knownWords = getKnownWords();

    let understood = 0;
    let total = 0;

    for (const entry of Object.values(examplesData)) {
        if (!entry.m) continue;
        for (const meaningExamples of entry.m) {
            if (!meaningExamples) continue;
            for (const ex of meaningExamples) {
                if (!ex.target) continue;
                total++;
                const cleaned = ex.target.replace(/\[[^\]]*\]|\([^\)]*\)/g, '').trim();
                if (!cleaned) { understood++; continue; }
                const tokens = cleaned.toLowerCase().replace(/[^\w\s']/g, ' ').split(/\s+/).filter(Boolean);
                if (!tokens.length) { understood++; continue; }
                let allKnown = true;
                for (const t of tokens) {
                    const rank = _spanishRanks[t];
                    if (rank === undefined) continue;  // not in vocab — skip
                    if (rank <= estimate || knownWords.has(t)) continue;
                    allKnown = false;
                    break;
                }
                if (allKnown) understood++;
            }
        }
    }

    return { understood, total, pct: total > 0 ? (understood / total * 100) : 0 };
}

// --- Example relevance sorting ---
let _cachedDeckWords = null;
let _cachedDeckId = null;  // track which deck set we computed for

function getDeckWords() {
    // Cache per deck load — flashcards array identity changes on each loadVocabularyData
    const deckId = flashcards.length > 0 ? flashcards[0].fullId : null;
    if (_cachedDeckId === deckId && _cachedDeckWords) return _cachedDeckWords;
    _cachedDeckWords = new Set(flashcards.map(c => c.targetWord.toLowerCase()));
    _cachedDeckId = deckId;
    return _cachedDeckWords;
}

function getRecentWrongWords() {
    const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
    const words = new Set();
    for (const [, data] of Object.entries(progressData)) {
        if (data.wrong > 0 && data.lastWrong && new Date(data.lastWrong).getTime() > sevenDaysAgo) {
            words.add((data.word || '').toLowerCase());
        }
    }
    return words;
}

function sortExamplesByRelevance(examples) {
    const deckWords = getDeckWords();
    const wrongWords = getRecentWrongWords();
    // Score each example — use personal easiness (excludes known words) when available
    const usePersonal = !!_spanishRanks;
    const scored = examples.map(ex => {
        const spanishText = ex.spanish || ex.target || '';
        const tokens = spanishText.toLowerCase().split(/\s+/);
        let deckHits = 0, wrongHits = 0;
        for (const t of tokens) {
            if (wrongWords.has(t)) wrongHits++;
            if (deckWords.has(t)) deckHits++;
        }
        const easiness = usePersonal
            ? computePersonalEasiness(spanishText)
            : (ex.easiness || 999999);
        return { ex, wrongHits, deckHits, easiness };
    });
    // Sort: wrong hits desc, deck hits desc, easiness asc (lower = easier/more relevant)
    scored.sort((a, b) =>
        (b.wrongHits - a.wrongHits) ||
        (b.deckHits - a.deckHits) ||
        (a.easiness - b.easiness)
    );
    return scored.map(s => s.ex);
}

function dedupeExamples(examples) {
    const seen = new Set();
    return examples.filter(ex => {
        const key = (ex.target || ex.spanish || '').trim();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function initializeApp() {
    updateCard();
    updateStats();

    // Ensure modal is hidden on initialization
    document.getElementById('statsModal').classList.add('hidden');

    // Only set up event listeners once
    if (isAppInitialized) {
        return;
    }
    isAppInitialized = true;

    // Event listeners
    // Flip button on front
    document.getElementById('flipBtn').addEventListener('click', function(e) {
        e.stopPropagation();
        flipCard();
    });

    // Flip on back side
    document.getElementById('flashcard').addEventListener('click', function(e) {
        // Don't flip if clicking on buttons, links, or elements with onclick handlers
        if (e.target.closest('.nav-btn-inline') ||
            e.target.closest('.link-btn') ||
            e.target.closest('.ref-icon-btn') ||
            e.target.closest('.card-action-small') ||
            e.target.closest('.breakdown-btn') ||
            e.target.closest('.card-btn-pill') ||
            e.target.closest('.card-control-btn') ||
            e.target.closest('#flipBtn') ||
            e.target.closest('[onclick]')) {
            return;
        }

        // Allow flipping anywhere else on the card (including front/back content)
        flipCard();
    });

    // Arrow buttons on the card faces
    document.getElementById('prevBtnFront').addEventListener('click', function(e) {
        e.stopPropagation();
        previousCard();
    });
    document.getElementById('nextBtnFront').addEventListener('click', function(e) {
        e.stopPropagation();
        nextCard();
    });
    document.getElementById('prevBtnBack').addEventListener('click', function(e) {
        e.stopPropagation();
        previousCard();
    });
    document.getElementById('nextBtnBack').addEventListener('click', function(e) {
        e.stopPropagation();
        nextCard();
    });
    // Top card buttons
    document.getElementById('reverseLangBtn').addEventListener('click', function(e) {
        e.stopPropagation();
        flipDirection();
    });
    document.getElementById('shuffleBtnTop').addEventListener('click', function(e) {
        e.stopPropagation();
        shuffleCards();
    });

    // Lyric breakdown modal
    document.getElementById('closeLyricBreakdown').addEventListener('click', hideLyricBreakdown);
    document.getElementById('lyricBreakdownModal').addEventListener('click', function(e) {
        if (e.target === this) hideLyricBreakdown();
    });

    // Mobile button listeners
    document.getElementById('prevBtnFrontMobile').addEventListener('click', function(e) {
        e.stopPropagation();
        previousCard();
    });
    document.getElementById('nextBtnFrontMobile').addEventListener('click', function(e) {
        e.stopPropagation();
        nextCard();
    });
    document.getElementById('speakBtnMobile').addEventListener('click', function(e) {
        e.stopPropagation();
        toggleAutoSpeak();
    });

    // Floating buttons (desktop sidebar) + on-card mobile copies share handlers.
    // Back uses navigateBack() which falls through to goBackToSetup() when
    // cardNavStack is empty — single smart-back affordance for normal decks
    // and synonym/search/lyrics popup chains alike.
    ['backBtnFloating', 'backBtnFrontMobile', 'backBtnBackMobile'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.addEventListener('click', function(e) {
            e.stopPropagation();
            navigateBack();
        });
    });
    ['statsBtnFloating', 'statsBtnFrontMobile', 'statsBtnBackMobile'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.addEventListener('click', function(e) {
            e.stopPropagation();
            showStatsModal();
        });
    });

    // Desktop speak button — toggles auto-speak
    document.getElementById('speakBtn').addEventListener('click', function(e) {
        e.stopPropagation();
        toggleAutoSpeak();
    });

    document.getElementById('closeStatsModal').addEventListener('click', hideStatsModal);

    // Settings modal interactions

    // Hide single-occurrence words toggle
    document.getElementById('hideSingleOccToggle').addEventListener('click', function() {
        hideSingleOccurrence = !hideSingleOccurrence;
        document.getElementById('hideSingleOccStatus').textContent = hideSingleOccurrence ? 'ON' : 'OFF';
        document.getElementById('hideSingleOccStatus').style.color = hideSingleOccurrence ? 'var(--accent-primary)' : 'var(--text-muted)';

        // Recalculate cumulative percentages with new freq-1 inclusion/exclusion
        recalculateCumulativePercents();

        // Re-render level selector and range selector to reflect new filtering
        const step2Display = document.getElementById('step2').style.display;
        if (selectedLanguage && step2Display !== 'none') {
            renderLevelSelector(selectedLanguage);
            if (selectedLevel) {
                const levelBtn = document.querySelector(`.level-btn[data-level="${selectedLevel}"]`);
                if (levelBtn) {
                    levelBtn.classList.add('selected');
                    levelBtn.textContent = levelBtn.dataset.full;
                }
                renderRangeSelector().catch(err => console.error('Error rendering ranges:', err));
            }
        }
    });

    // Percentage mode toggle
    // Refresh study set - delete progress for words in current set
    document.getElementById('refreshSetToggle').addEventListener('click', async function() {
        if (!currentUser || currentUser.isGuest) {
            alert('You must be logged in to refresh your progress.');
            return;
        }

        if (flashcards.length === 0) {
            alert('No study set is currently loaded.');
            return;
        }

        // Get the word IDs that are in the current flashcard set
        const wordsInSet = flashcards.map(card => ({
            rank: card.rank,
            id: card.id,
            fullId: card.fullId,
            word: card.targetWord
        }));

        const confirmMsg = `This will reset your progress for ${wordsInSet.length} words in the current study set. These words will appear again when you study this set. Continue?`;
        if (!confirm(confirmMsg)) {
            return;
        }

        // Delete progress for each word in the set
        try {
            for (const wordInfo of wordsInSet) {
                // Remove from local progressData
                if (progressData[wordInfo.fullId]) {
                    delete progressData[wordInfo.fullId];
                }

                // Delete from Google Sheets
                await fetch(GOOGLE_SCRIPT_URL, {
                    method: 'POST',
                    body: JSON.stringify({
                        action: 'delete',
                        user: currentUser.initials,
                        wordId: wordInfo.fullId,
                        sheet: activeArtist ? 'Lyrics' : 'UserProgress'
                    })
                });
            }

            alert(`Progress reset for ${wordsInSet.length} words. Go back to the menu and re-select this set to study the refreshed words.`);
            hideSettingsModal();
        } catch (error) {
            console.error('Failed to reset progress:', error);
            alert('Failed to reset progress. Please try again.');
        }
    });

    // Click outside modal to close
    document.getElementById('statsModal').addEventListener('click', function(e) {
        if (e.target === this) {
            hideStatsModal();
        }
    });

    // Deck complete modal buttons
    document.getElementById('restartAllBtn').addEventListener('click', function() {
        hideDeckCompleteModal();
        restartAllCards();
    });

    document.getElementById('continueIncorrectBtn').addEventListener('click', function() {
        if (window.currentIncorrectCards && window.currentIncorrectCards.length > 0) {
            hideDeckCompleteModal();
            restartWithIncorrectCards(window.currentIncorrectCards);
        }
    });

    document.getElementById('markCompleteBtn').addEventListener('click', function() {
        hideDeckCompleteModal();
        // For now, just go back to setup (data storage not implemented)
        goBackToSetup();
    });

    // Click outside deck complete modal to close
    document.getElementById('deckCompleteModal').addEventListener('click', function(e) {
        if (e.target === this) {
            hideDeckCompleteModal();
        }
    });

    // Swipe gestures
    setupSwipeGestures();

    // Keyboard shortcuts
    setupKeyboardShortcuts();
}

function setupSwipeGestures() {
    const card = document.getElementById('flashcard');
    const incorrectIndicator = document.getElementById('incorrectIndicator');
    const correctIndicator = document.getElementById('correctIndicator');
    let touchStartX = 0;
    let touchStartY = 0;
    let currentX = 0;
    let currentY = 0;
    let isDragging = false;
    let hasMoved = false;
    let touchStartTime = 0;
    let maxMovement = 0; // Track maximum movement during touch
    let startedOnCircle = false; // Track if touch started on flip circle
    let touchZone = null; // Track which zone touch started in
    let wasFlippedAtStart = false; // Track flip state at touch start

    // Helper to determine touch zone (center vs edges)
    function getTouchZone(touchX, cardRect) {
        const relativeX = (touchX - cardRect.left) / cardRect.width;
        if (relativeX < 0.25) return 'left-edge';
        if (relativeX > 0.75) return 'right-edge';
        return 'center';
    }

    card.addEventListener('touchstart', function(e) {
        // Don't handle if touch is on buttons, links, or specific interactive elements
        if (e.target.closest('.nav-btn-inline') ||
            e.target.closest('.link-btn') ||
            e.target.closest('.ref-icon-btn') ||
            e.target.closest('.card-control-btn') ||
            e.target.closest('.card-action-small') ||
            e.target.closest('.desktop-answer-btn') ||
            e.target.closest('[onclick]')) {
            return;
        }

        // Check if touch started on flip button or flip-back-area
        startedOnCircle = !!(e.target.closest('#flipBtn') || e.target.closest('.flip-back-area'));

        // Track flip state at start of touch
        wasFlippedAtStart = card.classList.contains('flipped');

        // Get touch zone for zone-based gesture handling
        const cardRect = card.getBoundingClientRect();
        touchZone = getTouchZone(e.touches[0].clientX, cardRect);

        // On back side, allow swiping from card-details area (remove the restriction)
        // Only block actual interactive elements like onclick handlers
        if (wasFlippedAtStart) {
            // Back side: allow swipe from anywhere except buttons/links
            // This enables swiping even from card-details area
        } else {
            // Front side: standard handling
            if (e.target.closest('.card-front') || e.target.closest('#flipBtn')) {
                // Allow touch to proceed
            } else {
                return;
            }
        }

        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
        currentX = touchStartX;
        currentY = touchStartY;
        isDragging = true;
        hasMoved = false;
        maxMovement = 0;
        touchStartTime = Date.now();
        card.classList.add('swiping');
    }, { passive: true });

    card.addEventListener('touchmove', function(e) {
        if (!isDragging) return;

        currentX = e.touches[0].clientX;
        currentY = e.touches[0].clientY;

        const diffX = currentX - touchStartX;
        const diffY = currentY - touchStartY;
        const totalMovement = Math.abs(diffX) + Math.abs(diffY);
        maxMovement = Math.max(maxMovement, totalMovement);

        // Only mark as moved if significant movement (raised threshold)
        if (Math.abs(diffX) > 5 || Math.abs(diffY) > 5) {
            hasMoved = true;
        }

        // Horizontal swipes - move card and show indicators
        if (Math.abs(diffX) > Math.abs(diffY) && hasMoved) {
            const rotation = diffX / 20; // Rotate based on swipe distance

            // Preserve flip state when moving card
            const isFlipped = card.classList.contains('flipped');
            if (isFlipped) {
                card.style.transform = `translateX(${diffX}px) rotate(${rotation}deg) rotateY(180deg)`;
            } else {
                card.style.transform = `translateX(${diffX}px) rotate(${rotation}deg)`;
            }

            // Show indicators based on swipe direction
            if (diffX > 50) {
                correctIndicator.classList.add('visible');
                incorrectIndicator.classList.remove('visible');
            } else if (diffX < -50) {
                incorrectIndicator.classList.add('visible');
                correctIndicator.classList.remove('visible');
            } else {
                correctIndicator.classList.remove('visible');
                incorrectIndicator.classList.remove('visible');
            }
        }
    }, { passive: true });

    card.addEventListener('touchend', function(e) {
        if (!isDragging) return;
        isDragging = false;

        const diffX = currentX - touchStartX;
        const diffY = currentY - touchStartY;
        const touchDuration = Date.now() - touchStartTime;

        // Check if indicator is visible BEFORE removing it
        const indicatorWasVisible = correctIndicator.classList.contains('visible') || incorrectIndicator.classList.contains('visible');
        const swipeDirection = correctIndicator.classList.contains('visible') ? 'correct' : 'incorrect';

        card.classList.remove('swiping');
        correctIndicator.classList.remove('visible');
        incorrectIndicator.classList.remove('visible');

        // Reset card transform
        card.style.transform = '';

        // If indicator was visible, auto-complete the swipe
        if (indicatorWasVisible) {
            handleSwipeAction(swipeDirection);
            return;
        }

        // Tap detection - very strict threshold
        const isTap = touchDuration < 200 && maxMovement < 7.5;
        const isQuickTap = touchDuration < 300 && maxMovement < 15;

        // ========== FRONT SIDE LOGIC (flip priority) ==========
        if (!wasFlippedAtStart) {
            // If touch started on flip circle, only allow flipping
            if (startedOnCircle) {
                if (touchDuration < 500 && maxMovement < 100) {
                    flipCard();
                }
                return;
            }

            // Center zone: flip is priority, ignore swipes
            if (touchZone === 'center') {
                // Only flip on clear taps, not on any small movement
                if (isTap || isQuickTap) {
                    flipCard();
                }
                // Any other movement is ignored (prevents accidental partial swipes)
                return;
            }

            // Edge zones: swipe takes priority
            const edgeSwipeThreshold = 5; // Reduced 75% from 20 for even easier swiping
            const isEdgeSwipe = Math.abs(diffX) > edgeSwipeThreshold && Math.abs(diffX) > Math.abs(diffY);

            if (isEdgeSwipe) {
                handleSwipeAction(diffX > 0 ? 'correct' : 'incorrect');
            } else if (isTap) {
                flipCard(); // Tap on edge still flips
            }
            return;
        }

        // ========== BACK SIDE LOGIC (swipe priority) ==========
        const backSwipeThreshold = 5; // Reduced 75% from 20 for even easier swiping on back
        const isHorizontalSwipe = Math.abs(diffX) > backSwipeThreshold && Math.abs(diffX) > Math.abs(diffY) * 1.2;
        const isVerticalSwipe = Math.abs(diffY) > backSwipeThreshold && Math.abs(diffY) > Math.abs(diffX) * 1.2;

        if (isHorizontalSwipe) {
            // Horizontal swipe - correct/incorrect
            handleSwipeAction(diffX > 0 ? 'correct' : 'incorrect');
        } else if (isVerticalSwipe) {
            // Vertical swipe - cycle through meanings for multi-meaning cards
            const currentCard = flashcards[currentIndex];
            if (currentCard && currentCard.isMultiMeaning) {
                if (diffY < 0) {
                    currentMeaningIndex = (currentMeaningIndex + 1) % currentCard.meanings.length;
                } else {
                    currentMeaningIndex = (currentMeaningIndex - 1 + currentCard.meanings.length) % currentCard.meanings.length;
                }
                updateCard();
                // Auto-speak the new meaning
                const meaning = currentCard.meanings[currentMeaningIndex];
                if (meaning && meaning.meaning) {
                    if (isFlipped) {
                        // English → Target mode: back shows target, speak target
                        speakWord(currentCard.targetWord, false);
                    } else {
                        // Target → English mode: back shows English, speak English
                        speakWord(meaning.meaning, true);
                    }
                }
            } else if (currentCard && currentCard.sentences) {
                if (diffY < 0) {
                    currentSentenceIndex = (currentSentenceIndex + 1) % currentCard.sentences.length;
                } else {
                    currentSentenceIndex = (currentSentenceIndex - 1 + currentCard.sentences.length) % currentCard.sentences.length;
                }
                updateCard();
            }
        } else if (startedOnCircle && maxMovement < 50) {
            // Only flip back if specifically tapping the flip area
            flipCard();
        }
        // Other gestures on back side are ignored (prevents accidental flips)
    }, { passive: true });
}

function pressAnswerBtn(id) {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.classList.remove('pressed');
    // Force reflow to restart animation if pressed rapidly
    void btn.offsetWidth;
    btn.classList.add('pressed');
    btn.addEventListener('animationend', () => btn.classList.remove('pressed'), { once: true });
}

function toggleAutoSpeak() {
    speechEnabled = !speechEnabled;
    updateSpeakIcons();
}

function updateSpeakIcons() {
    // Update both desktop and mobile speaker icons
    ['speakBtnIcon', 'speakBtnMobileIcon'].forEach(id => {
        const svg = document.getElementById(id);
        if (!svg) return;
        svg.querySelectorAll('.speak-on-indicator').forEach(el => {
            el.style.display = speechEnabled ? '' : 'none';
        });
        svg.querySelectorAll('.speak-off-indicator').forEach(el => {
            el.style.display = speechEnabled ? 'none' : '';
        });
    });
}

function setupKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
        // Ignore if typing in an input field
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            return;
        }

        // Left arrow = previous card
        if (e.key === 'ArrowLeft') {
            e.preventDefault();
            previousCard();
        }
        // Right arrow = next card
        else if (e.key === 'ArrowRight') {
            e.preventDefault();
            nextCard();
        }
        // Up arrow = previous meaning
        else if (e.key === 'ArrowUp') {
            e.preventDefault();
            const card = flashcards[currentIndex];
            if (card && card.meanings && card.meanings.length > 1 && currentMeaningIndex > 0) {
                selectMeaning(currentMeaningIndex - 1);
            }
        }
        // Down arrow = next meaning
        else if (e.key === 'ArrowDown') {
            e.preventDefault();
            const card = flashcards[currentIndex];
            if (card && card.meanings && card.meanings.length > 1 && currentMeaningIndex < card.meanings.length - 1) {
                selectMeaning(currentMeaningIndex + 1);
            }
        }
        // Shift+Tab = next card (alternative to right arrow)
        else if (e.key === 'Tab' && e.shiftKey) {
            e.preventDefault();
            nextCard();
        }
        // Tab = cycle examples / MWE expressions
        else if (e.key === 'Tab') {
            e.preventDefault();
            const card = flashcards[currentIndex];
            if (!card || !card.meanings) return;
            const m = card.meanings[currentMeaningIndex];
            if (m && m.allMWEs && m.allMWEs.length > 1) {
                // MWE meaning: cycle expressions
                cycleMWEForward();
            } else {
                // Regular meaning: cycle examples
                cycleExampleForward();
            }
        }
        // Enter = correct
        else if (e.key === 'Enter') {
            e.preventDefault();
            handleSwipeAction('correct');
        }
        // X = incorrect
        else if (e.key === 'x' || e.key === 'X') {
            e.preventDefault();
            handleSwipeAction('incorrect');
        }
        // F = flag erroneous data (debugging — desktop only, no on-screen control)
        else if (e.key === 'f' || e.key === 'F') {
            e.preventDefault();
            handleFlagAction();
        }
        // Space = flip card
        else if (e.key === ' ') {
            e.preventDefault();
            flipCard();
        }
        // Escape = close modal or smart-back (pop nav stack, else return to setup)
        else if (e.key === 'Escape') {
            e.preventDefault();
            const deckModal = document.getElementById('deckCompleteModal');
            const statsModal = document.getElementById('statsModal');
            if (deckModal && !deckModal.classList.contains('hidden')) {
                hideDeckCompleteModal();
            } else if (statsModal && !statsModal.classList.contains('hidden')) {
                hideStatsModal();
            } else {
                navigateBack();
            }
        }
    });
}

function handleFlagAction() {
    const currentCard = flashcards[currentIndex];
    if (!currentCard || !currentCard.rank) return;

    flagWord(currentCard);

    const card = document.getElementById('flashcard');
    card.classList.add('swipe-flag');

    setTimeout(() => {
        card.classList.remove('swipe-flag');
        card.style.transform = '';

        if (cardNavStack.length > 0) {
            navigateBack();
            return;
        }

        if (currentIndex < flashcards.length - 1) {
            currentIndex++;
            currentSentenceIndex = 0;
            currentMeaningIndex = 0;
            currentExampleIndex = 0;
            currentMWEIndex = 0;
            currentGroupSelection = null;
            updateCard();
            document.getElementById('flashcard').classList.remove('flipped');
        } else {
            showEndOfDeckOptions();
        }
    }, 300);
}

function handleSwipeAction(result) {
    const card = document.getElementById('flashcard');
    const isFlipped = card.classList.contains('flipped');

    // Record the result
    recordCardResult(result);

    // Animate the card off screen (maintain flip state during animation)
    if (result === 'correct') {
        card.classList.add('swipe-correct');
    } else {
        card.classList.add('swipe-incorrect');
    }

    // Wait for animation to complete, then move to next card
    setTimeout(() => {
        card.classList.remove('swipe-correct', 'swipe-incorrect');
        card.style.transform = '';

        // If we're on a linked card (nav stack), go back instead of advancing
        if (cardNavStack.length > 0) {
            navigateBack();
            return;
        }

        // Move to next card
        if (currentIndex < flashcards.length - 1) {
            currentIndex++;
            currentSentenceIndex = 0; // Reset sentence index for new card
            currentMeaningIndex = 0; // Reset meaning index for new card
            currentExampleIndex = 0; // Reset example index for new card
            currentMWEIndex = 0;
            currentGroupSelection = null;
            updateCard();
            // Always show front side of next card
            document.getElementById('flashcard').classList.remove('flipped');
        } else {
            // End of deck - show options
            showEndOfDeckOptions();
        }
    }, 300);
}

function showEndOfDeckOptions() {
    const incorrectCards = Object.keys(stats.cardStats)
        .filter(idx => stats.cardStats[idx].incorrect > stats.cardStats[idx].correct)
        .map(Number);

    const totalAttempts = stats.correct + stats.incorrect;
    const accuracy = totalAttempts > 0 ? Math.round((stats.correct / totalAttempts) * 100) : 0;

    // Update modal content
    document.getElementById('completeCorrect').textContent = stats.correct;
    document.getElementById('completeIncorrect').textContent = stats.incorrect;
    document.getElementById('completeAccuracy').textContent = `Accuracy: ${accuracy}%`;

    const continueBtn = document.getElementById('continueIncorrectBtn');
    const messageEl = document.getElementById('completeMessage');

    if (incorrectCards.length > 0) {
        messageEl.textContent = `${incorrectCards.length} card${incorrectCards.length > 1 ? 's' : ''} to review`;
        continueBtn.disabled = false;
        continueBtn.querySelector('span:last-child').textContent = `Review ${incorrectCards.length} Mistake${incorrectCards.length > 1 ? 's' : ''}`;
    } else {
        messageEl.innerHTML = `<span style="color: var(--accent-green); font-weight: 600;">Perfect score! 🎉</span>`;
        continueBtn.disabled = true;
        continueBtn.querySelector('span:last-child').textContent = 'No Mistakes';
    }

    // Store incorrect cards for later use
    window.currentIncorrectCards = incorrectCards;

    // Show the modal
    document.getElementById('deckCompleteModal').classList.remove('hidden');
}

function hideDeckCompleteModal() {
    document.getElementById('deckCompleteModal').classList.add('hidden');
}

function restartWithIncorrectCards(incorrectIndices) {
    // Create new deck with only incorrect cards
    const incorrectFlashcards = incorrectIndices.map(idx => flashcards[idx]);

    // Reset stats
    stats.correct = 0;
    stats.incorrect = 0;
    stats.total = 0;
    stats.studied = new Set();
    stats.cardStats = {};

    // Set new flashcards array
    flashcards = incorrectFlashcards;
    currentIndex = 0;
    currentSentenceIndex = 0;

    updateCard();
    document.getElementById('flashcard').classList.remove('flipped');
}

function restartAllCards() {
    // Reset stats
    stats.correct = 0;
    stats.incorrect = 0;
    stats.total = 0;
    stats.studied = new Set();
    stats.cardStats = {};

    currentIndex = 0;
    currentSentenceIndex = 0;

    updateCard();
    document.getElementById('flashcard').classList.remove('flipped');
}

function recordCardResult(result) {
    const isCorrect = result === 'correct';

    // Skip session stats for peek/stacked cards, but still save progress below
    if (cardNavStack.length === 0) {
        if (!stats.cardStats[currentIndex]) {
            stats.cardStats[currentIndex] = { correct: 0, incorrect: 0 };
        }
        if (isCorrect) {
            stats.correct++;
            stats.cardStats[currentIndex].correct++;
        } else {
            stats.incorrect++;
            stats.cardStats[currentIndex].incorrect++;
        }
        stats.total++;
    }

    // Save progress to Google Sheets or LocalStorage
    const currentCard = flashcards[currentIndex];
    if (currentCard && currentCard.rank) {
        saveWordProgress(currentCard, isCorrect);
    }
}

function showFloatingBtns(show) {
    const btns = document.getElementById('floatingBtns');
    const userInfo = document.getElementById('userInfo');
    if (btns) {
        if (show) {
            btns.classList.add('visible');
            if (userInfo) userInfo.classList.remove('hidden');
        } else {
            btns.classList.remove('visible');
            if (userInfo) userInfo.classList.add('hidden');
        }
    }
}

async function goBackToSetup() {
    // Hide app content, show setup
    const appContent = document.getElementById('appContent');
    const setupPanel = document.getElementById('setupPanel');

    appContent.classList.add('hidden');
    setupPanel.classList.remove('hidden');
    setupPanel.style.display = 'block';

    // Hide mobile floating buttons
    showFloatingBtns(false);

    // Clear nav stack and vocab lookup
    cardNavStack = [];
    fullVocabLookup = null;
    vocabByIdLookup = null;

    // Scroll to top
    document.querySelector('.container').scrollTop = 0;

    // Keep the language selected and show subsequent steps
    // Show inline language pill, hide tabs
    document.getElementById('languageTabs').style.display = 'none';
    const inlinePill = document.getElementById('selectedLanguageInline');
    const langConfig = config.languages[selectedLanguage];
    inlinePill.textContent = langConfig ? langConfig.name : selectedLanguage;
    inlinePill.style.display = 'inline-flex';

    // Show step 2 and keep level selected if one was selected
    document.getElementById('step2').style.display = 'block';
    document.getElementById('step4').style.display = 'none';

    // Reset only the range/set selections, not the level
    document.querySelectorAll('.range-btn').forEach(btn => {
        btn.classList.remove('selected');
    });
    document.querySelectorAll('.range-btn-new').forEach(btn => {
        btn.classList.remove('selected');
    });
    selectedRanges = [];
    flashcards = [];
    currentIndex = 0;
    currentSentenceIndex = 0;
    currentMeaningIndex = 0;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    isFlipped = false;

    // Always load PPM data if available (needed for coverage bar even in CEFR mode)
    if (!ppmData || ppmData.length === 0) {
        await loadPpmData(selectedLanguage);
    }

    // Re-render level selector to show updated progress
    renderLevelSelector(selectedLanguage);

    // If a level was selected, re-select the level button with full text
    // But only if the level still exists in the current mode (CEFR vs percentage)
    if (selectedLevel) {
        const levelBtn = document.querySelector(`.level-btn[data-level="${selectedLevel}"]`);
        if (levelBtn) {
            levelBtn.classList.add('selected');
            levelBtn.textContent = levelBtn.dataset.full;
            // Also show lemma, cognate, and cards steps
            document.getElementById('lemmaToggleContainer').style.display = 'block';
            if (cognateFieldAvailable) {
                document.getElementById('cognateToggleContainer').style.display = 'block';
            }
            // Re-render range selector so "Choose Set" reappears
            renderRangeSelector();
        } else {
            // Level no longer exists (e.g., switched from CEFR to percentage mode)
            // Reset selectedLevel and hide subsequent steps
            selectedLevel = null;
            document.getElementById('lemmaToggleContainer').style.display = 'none';
            document.getElementById('cognateToggleContainer').style.display = 'none';
    
        }
    }

    updateLemmaToggleVisibility();
    updateCognateToggleVisibility();
    updateExclusionBars();

    // Reset card state
    const flashcardEl = document.getElementById('flashcard');
    if (flashcardEl) {
        flashcardEl.classList.remove('flipped');
    }

    stats = {
        studied: new Set(),
        correct: 0,
        incorrect: 0,
        total: 0,
        cardStats: {}
    };
}

/**
 * Build "variant1 | variant2" display string from card.variants,
 * sorted by count descending (most frequent first).
 * Returns null if no variants (single-form word).
 *
 * Low-count variants (count < MIN_VARIANT_COUNT) are suppressed: they're
 * usually colloquial one-offs ("m'le" on the `le` card, "qu'le" on `le`,
 * phonetic slips on subtitled corpora) that add visual noise without
 * teaching value. The primary form always stays regardless of count.
 */
const MIN_VARIANT_COUNT = 2;
function buildVariantDisplay(card) {
    if (!card.variants) return null;
    const entries = Object.entries(card.variants);
    if (entries.length < 2) return null;
    entries.sort((a, b) => b[1] - a[1]);
    // Keep the primary (highest-count) form unconditionally; drop lower
    // entries that fall under the min-count threshold.
    const [primary, ...rest] = entries;
    const kept = [primary, ...rest.filter(([, c]) => c >= MIN_VARIANT_COUNT)];
    if (kept.length < 2) return null;
    return kept.map(e => e[0]).join('<span class="variant-sep">|</span>');
}

function updateCard() {
    const card = flashcards[currentIndex];
    const langConfig = config.languages[selectedLanguage];

    // Update artist album artwork background
    updateArtistBackground();

    // Update reverse button text
    updateReverseButton();

    // Reset meaning index if out of bounds
    if (card.isMultiMeaning && currentMeaningIndex >= card.meanings.length) {
        currentMeaningIndex = 0;
        currentGroupSelection = null;
    }

    // Validate the group selection against the current card. If any member
    // index is out of range, or the anchor's pos+meaning/context no longer
    // matches the stored groupKey (data shifted under us), drop the
    // selection and fall back to per-meaning rendering.
    if (currentGroupSelection) {
        const sel = currentGroupSelection;
        const inRange = card.isMultiMeaning && sel.members && sel.members.length >= 2
            && sel.members.every(i => i >= 0 && i < card.meanings.length);
        if (!inRange) {
            currentGroupSelection = null;
        } else {
            const a = card.meanings[sel.members[0]];
            const expectedKey = sel.axis === 'translation'
                ? `${a.pos}|${a.meaning}`
                : `${a.pos}|${a.context || ''}`;
            if (expectedKey !== sel.groupKey) {
                currentGroupSelection = null;
            }
        }
    }

    // Get the current meaning for multi-meaning cards
    const currentMeaning = card.isMultiMeaning ? card.meanings[currentMeaningIndex] : null;

    // Determine what to show on front and back based on flip direction
    let frontText, backWord, backTranslation, exampleSentence, exampleTranslation;
    let flippedFrontMeanings = null; // structured front for EN→Target multi-meaning

    if (card.isMultiMeaning) {
        // Multi-meaning format
        if (isFlipped) {
            // English → Target language: build structured front with POS badges
            const normalMeanings = card.meanings.filter(m =>
                m.pos !== 'MWE' && m.pos !== 'CLITIC' && m.pos !== 'SENSE_CYCLE');

            // Pick meanings to show: those with frequency, else keyword-assigned, else top per POS
            let frontMeanings = normalMeanings.filter(m => (m.percentage || 0) > 0);
            if (frontMeanings.length === 0) {
                frontMeanings = normalMeanings.filter(m => m.assignment_method && m.assignment_method.includes('keyword'));
            }
            if (frontMeanings.length === 0) {
                // Fall back: one meaning per unique POS
                const seenPOS = new Set();
                for (const m of normalMeanings) {
                    if (!seenPOS.has(m.pos)) {
                        frontMeanings.push(m);
                        seenPOS.add(m.pos);
                    }
                }
            }
            // Deduplicate by translation text
            const seenText = new Set();
            frontMeanings = frontMeanings.filter(m => {
                const key = (m.meaning || '').toLowerCase();
                if (seenText.has(key)) return false;
                seenText.add(key);
                return true;
            });

            const uniquePOS = new Set(frontMeanings.map(m => m.pos));
            const multiPOS = uniquePOS.size > 1;

            flippedFrontMeanings = { meanings: frontMeanings, multiPOS };
            frontText = null; // will use structured display instead
            backWord = card.targetWord;
            backTranslation = currentMeaning.meaning;
            exampleSentence = currentMeaning.englishSentence;
            exampleTranslation = currentMeaning.targetSentence;
        } else {
            // Target language → English (normal)
            frontText = card.targetWord;
            backWord = card.targetWord;
            backTranslation = currentMeaning.meaning;
            exampleSentence = currentMeaning.targetSentence;
            exampleTranslation = currentMeaning.englishSentence;
        }
    } else {
        // Legacy format - get current sentence from sentences array
        const currentSentence = card.sentences && card.sentences.length > 0
            ? card.sentences[currentSentenceIndex % card.sentences.length]
            : { target: card.targetSentence, english: card.englishSentence };

        if (isFlipped) {
            // English → Target language
            frontText = card.translation;
            backWord = card.targetWord;
            backTranslation = card.translation;
            exampleSentence = currentSentence.english;
            exampleTranslation = currentSentence.target;
        } else {
            // Target language → English (normal)
            frontText = card.targetWord;
            backWord = card.targetWord;
            backTranslation = card.translation;
            exampleSentence = currentSentence.target;
            exampleTranslation = currentSentence.english;
        }
    }

    // Build variant display if available (e.g. "la'o | lado")
    const variantDisplay = buildVariantDisplay(card);
    if (variantDisplay && !isFlipped) {
        frontText = variantDisplay;
    }

    const frontWordEl = document.getElementById('frontWord');
    const frontMeaningsEl = document.getElementById('frontMeanings');

    if (flippedFrontMeanings) {
        // EN→Target structured display: meanings with POS badges
        frontWordEl.style.display = 'none';
        const { meanings: fMeanings, multiPOS } = flippedFrontMeanings;
        const fontSize = fMeanings.length > 2 ? 28 : (fMeanings.length > 1 ? 36 : 52);
        let html = '';
        for (const m of fMeanings) {
            const posClass = getPosColorClass(m.pos);
            const posBadge = multiPOS
                ? `<span class="front-meaning-pos ${posClass}">${m.pos}</span>`
                : '';
            html += `<div class="front-meaning-row">
                ${posBadge}
                <span class="front-meaning-text" style="font-size: ${fontSize}px;">${m.meaning}</span>
            </div>`;
        }
        frontMeaningsEl.innerHTML = html;
        frontMeaningsEl.style.display = 'flex';
    } else {
        // Normal single-word/text display
        frontMeaningsEl.innerHTML = '';
        frontMeaningsEl.style.display = 'none';
        frontWordEl.style.display = '';
        frontWordEl.innerHTML = frontText;
        // Auto-shrink the word font so it fits on a single line instead of
        // wrapping. The old heuristic keyed off character count (>13 chars),
        // which missed cases where the chars were wide enough to overflow a
        // narrower container ("Sandungueo" at 10 chars overflows on a phone-
        // width card). shrinkToFit measures intrinsic content width and
        // steps the font-size down until it fits.
        shrinkToFit(frontWordEl, 28);
    }

    // Display part of speech on front with color coding
    const frontPOSEl = document.getElementById('frontPOS');
    // Clear any existing POS color classes
    frontPOSEl.className = 'card-pos';
    if (flippedFrontMeanings) {
        // EN→Target: POS badges are inline with meanings, hide standalone POS pill
        frontPOSEl.style.display = 'none';
    } else if (card.isMultiMeaning && card.meanings && card.meanings.length > 0) {
        // SP→EN: show all unique POS
        const allPOS = [...new Set(card.meanings.filter(m => m.pos !== 'MWE' && m.pos !== 'CLITIC' && m.pos !== 'SENSE_CYCLE').map(m => m.pos))].join(', ');
        frontPOSEl.textContent = allPOS;
        // Apply color of first POS
        const firstPos = card.meanings[0].pos;
        const posClass = getPosColorClass(firstPos);
        if (posClass) frontPOSEl.classList.add(posClass);
        frontPOSEl.style.display = 'inline-block';
    } else if (card.partOfSpeech) {
        frontPOSEl.textContent = card.partOfSpeech;
        const posClass = getPosColorClass(card.partOfSpeech);
        if (posClass) frontPOSEl.classList.add(posClass);
        frontPOSEl.style.display = 'inline-block';
    } else {
        frontPOSEl.style.display = 'none';
    }

    // Build compact multi-row morphology labels
    const morphLabels = card.morphology
        ? [...new Set((Array.isArray(card.morphology) ? card.morphology : [card.morphology]).map(formatMorphLabel))]
        : [];

    // Display lemma on front if different from target word
    const frontLemmaEl = document.getElementById('frontLemma');
    if (!isFlipped && card.lemma && card.lemma !== card.targetWord) {
        frontLemmaEl.textContent = card.lemma;
        frontLemmaEl.style.display = 'block';
        // Same measured shrink as the main word — rare, but e.g. the lemma
        // of a long derived form can exceed the card width at 32px.
        shrinkToFit(frontLemmaEl, 18);
    } else {
        frontLemmaEl.textContent = '';
        frontLemmaEl.style.display = 'none';
    }

    // Show morphology info on both sides (compact, multi-row)
    const frontMorphEl = document.getElementById('frontMorph');
    if (frontMorphEl) {
        if (morphLabels.length > 0) {
            frontMorphEl.innerHTML = morphLabels.map(l =>
                `<span class="morph-tag">${l}</span>`
            ).join('');
            frontMorphEl.style.display = 'flex';
        } else {
            frontMorphEl.innerHTML = '';
            frontMorphEl.style.display = 'none';
        }
    }

    // Store ranking as data attribute on card for console access
    const flashcardEl = document.getElementById('flashcard');
    if (card.rank !== undefined) {
        flashcardEl.setAttribute('data-rank', card.rank);
    } else {
        flashcardEl.setAttribute('data-rank', '');
    }

    // Display ranking and frequency on front card
    const frontRankingEl = document.getElementById('frontRanking');
    if (card.rank !== undefined) {
        frontRankingEl.textContent = card.corpusCount
            ? `Rank: ${card.rank} · Frequency: ${card.corpusCount}`
            : `Rank: ${card.rank}`;
        frontRankingEl.style.display = 'block';
    } else {
        frontRankingEl.style.display = 'none';
    }

    // Build back content with variant display and lemma
    let backWordText = variantDisplay || backWord;
    let wordDisplay = backWordText;
    if (card.isMultiMeaning && card.lemma && card.lemma !== card.targetWord) {
        wordDisplay = `${backWordText} <span style="color: var(--accent-primary); font-size: 28px;">(${card.lemma})</span>`;
    }

    // Build homograph chip HTML if siblings exist
    let homographChipHTML = '';
    if (card.homographIds && card.homographIds.length > 0) {
        const lookup = getVocabByIdLookup();
        const chips = [];
        for (const sibId of card.homographIds) {
            const sib = lookup.get(sibId);
            if (!sib) continue;
            const sibLemma = sib.lemma || sib.word;
            const sibTranslation = (sib.meanings && sib.meanings.length > 0) ? sib.meanings[0].translation : '';
            const label = sibTranslation ? `${sibLemma} (${sibTranslation})` : sibLemma;
            chips.push(`<span class="homograph-chip" onclick="peekHomograph('${sibId}')">also: ${label}</span>`);
        }
        if (chips.length > 0) {
            homographChipHTML = `<div class="homograph-chips">${chips.join('')}</div>`;
        }
    }

    // line-height: 1.1 keeps multi-line wraps tight (long word + lemma
    // on narrow viewports) so the header grows by a reasonable amount
    // rather than adding a full line of whitespace each wrap. Single-line
    // cards are unaffected — line-height only matters when there are two
    // or more rendered lines.
    let backHTML = `
        <div class="back-header" style="text-align: center; margin-bottom: 8px;">
            <div class="flip-back-area" id="flipBackArea">
                <div style="font-size: ${variantDisplay && variantDisplay.length > 16 ? Math.max(26, 42 - (variantDisplay.length - 12) * 1.5) : 42}px; color: white; font-weight: bold; line-height: 1.1;">${wordDisplay}</div>
            </div>
            ${homographChipHTML}
        </div>
    `;

    // For multi-meaning cards, show all meanings on the back
    if (card.isMultiMeaning) {

        // Two accumulators:
        //   - scrollRows: regular meanings + SENSE_CYCLE (these scroll)
        //   - trayRows: MWE + CLITIC (always visible, pinned below the
        //     scroll area so the user doesn't have to hunt for them)
        const scrollRows = [];
        const trayRows = [];

        // Render-side grouping: collapse rows that share either
        // translation OR context into a single "group card" — shared
        // field on one side, list of varying values on the other.
        // POS is intentionally NOT part of the grouping key; cross-POS
        // collisions still merge (e.g. `que` CONJ "that" + REL "that").
        // The renderer detects cross-POS groups and shows per-row POS
        // pills inside the body so the distinction stays visible.
        // Examples:
        //   `dice` → 3 senses share "to say" → translation-axis group
        //            shared = "to say", varying = contexts
        //   `su`   → 5 senses share possessive context → context-axis group
        //            shared = context,  varying = translations
        // Each list item stays an independently clickable selectMeaning
        // target. Pure render layer; data is untouched. Flip to false to
        // revert to flat one-row-per-meaning.
        const GROUP_DUPLICATE_MEANINGS = true;
        // Per-meaning-idx axis assignment: 'translation' | 'context' |
        // 'singleton' | 'special' (MWE/CLITIC/SENSE_CYCLE — opted out).
        // Cached on the card after first compute — meanings don't mutate
        // post-load, so flips/cycles/selects can reuse the same maps.
        let axisOf, groupKeyOf, groupMembers, groupFirstIdx, groupPctSum;
        if (card._grouping) {
            ({ axisOf, groupKeyOf, groupMembers, groupFirstIdx, groupPctSum } = card._grouping);
        } else {
            axisOf = new Map();
            groupKeyOf = new Map();
            groupMembers = new Map();
            groupFirstIdx = new Map();
            groupPctSum = new Map();
            if (GROUP_DUPLICATE_MEANINGS) {
                // Pass 1: tally raw sizes per axis (used only to make the
                // per-meaning axis decision in pass 2). Keys are POS-free so
                // cross-POS collisions can group (e.g. CONJ + REL "that").
                const transRawSize = new Map();
                const ctxRawSize = new Map();
                card.meanings.forEach((m, idx) => {
                    if (m.pos === 'MWE' || m.pos === 'CLITIC' || m.pos === 'SENSE_CYCLE') {
                        axisOf.set(idx, 'special');
                        return;
                    }
                    const tk = m.meaning || '';
                    transRawSize.set(tk, (transRawSize.get(tk) || 0) + 1);
                    if (m.context) {
                        const ck = m.context;
                        ctxRawSize.set(ck, (ctxRawSize.get(ck) || 0) + 1);
                    }
                });
                // Pass 2: pick the dominant axis per meaning. Ties go to
                // translation (the more common failure mode is classifier slop
                // on a single sense, which manifests as duplicate translations).
                card.meanings.forEach((m, idx) => {
                    if (axisOf.get(idx) === 'special') return;
                    const tk = m.meaning || '';
                    const ts = transRawSize.get(tk) || 0;
                    const ck = m.context || null;
                    const cs = ck ? (ctxRawSize.get(ck) || 0) : 0;
                    if (ts > 1 && cs > 1) {
                        if (ts >= cs) { axisOf.set(idx, 'translation'); groupKeyOf.set(idx, tk); }
                        else { axisOf.set(idx, 'context'); groupKeyOf.set(idx, ck); }
                    } else if (ts > 1) {
                        axisOf.set(idx, 'translation'); groupKeyOf.set(idx, tk);
                    } else if (cs > 1) {
                        axisOf.set(idx, 'context'); groupKeyOf.set(idx, ck);
                    } else {
                        axisOf.set(idx, 'singleton');
                    }
                });
                // Pass 3: rebuild effective members per (axis, key). If a
                // group's effective size has shrunk below 2 (because some of
                // its candidates were stolen by the other axis), downgrade
                // those meanings to singletons. Iterate until stable so a
                // chain of demotions converges.
                let changed = true;
                while (changed) {
                    changed = false;
                    groupMembers.clear();
                    groupFirstIdx.clear();
                    groupPctSum.clear();
                    card.meanings.forEach((m, idx) => {
                        const ax = axisOf.get(idx);
                        if (ax !== 'translation' && ax !== 'context') return;
                        const k = groupKeyOf.get(idx);
                        const compKey = `${ax}|${k}`;
                        if (!groupMembers.has(compKey)) groupMembers.set(compKey, []);
                        groupMembers.get(compKey).push(idx);
                        if (!groupFirstIdx.has(compKey)) groupFirstIdx.set(compKey, idx);
                        groupPctSum.set(compKey, (groupPctSum.get(compKey) || 0) + (m.percentage || 0));
                    });
                    for (const [compKey, members] of groupMembers) {
                        if (members.length < 2) {
                            for (const i of members) {
                                axisOf.set(i, 'singleton');
                                groupKeyOf.delete(i);
                            }
                            changed = true;
                        }
                    }
                }
            }
            card._grouping = { axisOf, groupKeyOf, groupMembers, groupFirstIdx, groupPctSum };
        }

        card.meanings.forEach((m, idx) => {
            const isSelected = idx === currentMeaningIndex;
            const bgColor = isSelected ? 'rgba(var(--accent-primary-rgb), 0.6)' : 'rgba(15, 20, 28, 0.82)';
            const textColor = isSelected ? 'var(--text-primary)' : 'var(--text-primary)';
            const borderStyle = (isSelected && !m.unassigned) ? 'border: 3px solid var(--accent-primary);' : '';
            const posColorClass = getPosColorClass(m.pos);
            const isMWE = m.pos === 'MWE';
            const isClitic = m.pos === 'CLITIC';
            const isSenseCycle = m.pos === 'SENSE_CYCLE';
            // Route this row to the pinned tray (MWE/CLITIC) or the scroll
            // region (regular + SENSE_CYCLE).
            const target = (isMWE || isClitic) ? trayRows : scrollRows;
            // For MWE pill, show the current expression/translation based on MWE index
            const mweIdx = (isMWE && isSelected) ? currentMWEIndex % (m.allMWEs ? m.allMWEs.length : 1) : 0;
            const mweExpr = isMWE && m.allMWEs ? m.allMWEs[mweIdx].expression : m.expression;
            const mweMeaning = isMWE && m.allMWEs ? m.allMWEs[mweIdx].translation : m.meaning;
            const mweCount = isMWE && m.allMWEs ? m.allMWEs.length : 0;
            const mweCounter = (isMWE && mweCount > 1) ? ` <span class="example-counter-group"><button class="mwe-cycle-btn desktop-only" onclick="cycleMWEBackward(event)" title="Previous expression">‹</button><span style="opacity: 0.6; font-size: 10px;">${mweIdx + 1}/${mweCount}</span><button class="mwe-cycle-btn desktop-only" onclick="cycleMWEForward(event)" title="Next expression">›</button></span>` : '';
            // For Clitic pill, reuse MWE cycling with allClitics
            const cliticIdx = (isClitic && isSelected) ? currentMWEIndex % (m.allClitics ? m.allClitics.length : 1) : 0;
            const cliticForm = isClitic && m.allClitics ? m.allClitics[cliticIdx].form : '';
            const cliticCount = isClitic && m.allClitics ? m.allClitics.length : 0;
            const cliticCounter = (isClitic && cliticCount > 1) ? ` <span class="example-counter-group"><button class="mwe-cycle-btn desktop-only" onclick="cycleMWEBackward(event)" title="Previous form">‹</button><span style="opacity: 0.6; font-size: 10px;">${cliticIdx + 1}/${cliticCount}</span><button class="mwe-cycle-btn desktop-only" onclick="cycleMWEForward(event)" title="Next form">›</button></span>` : '';
            const cleanMweMeaning = isMWE ? mweMeaning.replace(/\s*\(elided\)/gi, '') : '';
            const displayMeaning = isMWE
                ? (cleanMweMeaning || '<span style="font-style: italic; opacity: 0.5;">Translation unavailable</span>')
                : (getConjugatedEnglish(card, m.meaning) || m.meaning);
            if (isMWE) {
                // MWE row: expression pill (left), translation (middle), counter (right).
                // Two context tiers — renderer prefers real over heuristic:
                //   1. ``context``           — structured data from the
                //      SpanishDict phrase-page scrape (tool_5c_scrape_spanishdict_phrases).
                //      Authoritative — same shape as the sense-level context.
                //   2. ``context_heuristic`` — split off the quickdef string
                //      (tool_5d_build_spanishdict_mwes → split_mwe_translation).
                //      Best-effort regex extraction; the text is real SpanishDict
                //      quickdef content but the paren-split is our guess.
                // The JS splitter at splitMWETranslation() is a render-time
                // fallback for decks whose membership entries predate the
                // pipeline change above.
                const activeMwe = (isMWE && m.allMWEs && m.allMWEs[mweIdx]) || null;
                const realCtx = activeMwe ? (activeMwe.context || '') : '';
                const heurCtx = activeMwe ? (activeMwe.context_heuristic || '') : '';
                let mwePrimary = cleanMweMeaning;
                let mweContext = realCtx || heurCtx;
                let mweContextIsHeuristic = !realCtx && !!heurCtx;
                if (!mweContext && cleanMweMeaning) {
                    // Legacy fallback — no split fields on the membership at all.
                    const sp = splitMWETranslation(cleanMweMeaning);
                    mwePrimary = sp.primary;
                    mweContext = sp.context;
                    mweContextIsHeuristic = !!sp.context;
                } else if (mweContext) {
                    // When we have a split field, recompute the primary by
                    // stripping the trailing paren that contains the heuristic
                    // note (real context never lives inline in the quickdef).
                    if (mweContextIsHeuristic) {
                        const sp = splitMWETranslation(cleanMweMeaning);
                        mwePrimary = sp.primary || cleanMweMeaning;
                    } else {
                        mwePrimary = cleanMweMeaning;
                    }
                }
                const primaryDisplay = mwePrimary || '<span style="font-style: italic; opacity: 0.5;">Translation unavailable</span>';
                // Heuristic context is the same typographic tier as real
                // context — the text is legitimate, only its structural
                // guarantee differs. No visual distinction is exposed to the
                // reader (a subtle one could be added later if needed).
                const bodyHTML = mweContext
                    ? `<div style="flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; text-align: center; line-height: 1.2;">
                           <span style="font-size: 14px; font-weight: 600; color: white;">${primaryDisplay}</span>
                           <span style="font-size: 11px; font-weight: 400; color: rgba(255,255,255,0.55); line-height: 1.25; margin-top: 1px;">${mweContext}</span>
                       </div>`
                    : `<span style="font-size: 14px; font-weight: 600; color: white; flex: 1; text-align: center; min-width: 0;">${primaryDisplay}</span>`;
                target.push(`
                <div class="meaning-row meaning-row-mwe" style="position: relative; display: flex; align-items: center; padding: 6px 8px; margin-bottom: 6px; background: ${bgColor}; ${borderStyle} border-radius: 8px; cursor: pointer; min-height: 36px;" onclick="selectMeaning(${idx})">
                    <span style="font-size: 12px; color: white; padding: 5px 8px; background: rgba(255,255,255,0.22); border-radius: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px; flex-shrink: 0;">${mweExpr}</span>
                    ${bodyHTML}
                    ${mweCounter}
                </div>
                `);
            } else if (isClitic) {
                // Clitic row: form pill (left), translation (middle), counter (right).
                const cliticTrRaw = m.allClitics ? m.allClitics[cliticIdx].translation : '';
                target.push(`
                <div class="meaning-row meaning-row-clitic" style="position: relative; display: flex; align-items: center; padding: 6px 8px; margin-bottom: 6px; background: ${bgColor}; ${borderStyle} border-radius: 8px; cursor: pointer; min-height: 36px;" onclick="selectMeaning(${idx})">
                    <span style="font-size: 12px; color: white; padding: 2px 8px; background: rgba(255,255,255,0.2); border-radius: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px; flex-shrink: 0;">${cliticForm}</span>
                    <span style="font-size: 14px; font-weight: 600; color: white; flex: 1; text-align: center; min-width: 0;">${cliticTrRaw}</span>
                    ${cliticCounter}
                </div>
                `);
            } else if (isSenseCycle) {
                // Sense cycle row: POS badge + all senses pipe-separated (these are unassigned/remainder)
                const cyclePos = m.cycle_pos || 'X';
                const cyclePosClass = getPosColorClass(cyclePos);
                const rawTranslations = m.allSenses ? m.allSenses.map(s => s.translation) : [m.meaning];
                // Prettify the remainder bucket:
                //   1. Split any semicolon-packed gloss into atomic translations
                //      (Wiktionary often bundles synonyms: "to pull out; to remove; to extract").
                //   2. Dedupe exact (case-insensitive) duplicates across senses while preserving order.
                //   3. If every remaining entry starts with "to ", factor the prefix and comma-join.
                //      Otherwise keep the pipe-joined display.
                const splitPieces = [];
                for (const t of rawTranslations) {
                    if (typeof t !== 'string') continue;
                    for (const piece of t.split(';')) {
                        const trimmed = piece.trim();
                        if (trimmed) splitPieces.push(trimmed);
                    }
                }
                const dedupSeen = new Set();
                const dedupedTranslations = [];
                for (const p of splitPieces) {
                    const key = p.toLowerCase();
                    if (!dedupSeen.has(key)) { dedupSeen.add(key); dedupedTranslations.push(p); }
                }
                let allTranslations = dedupedTranslations.length ? dedupedTranslations : rawTranslations;
                let joinSep = ' | ';
                const allToInfinitive = allTranslations.length >= 2 &&
                    allTranslations.every(t => typeof t === 'string' && /^to\s+\S/i.test(t.trim()));
                if (allToInfinitive) {
                    const stripped = allTranslations.map(t => t.trim().replace(/^to\s+/i, ''));
                    // Dedupe again after stripping the prefix (e.g. "to get" + "to get" via semicolons)
                    const seen2 = new Set();
                    const unique = [];
                    for (const s of stripped) {
                        const key = s.toLowerCase();
                        if (!seen2.has(key)) { seen2.add(key); unique.push(s); }
                    }
                    // First piece keeps "to "; subsequent pieces are bare, joined with ", "
                    allTranslations = unique.map((s, i) => i === 0 ? 'to ' + s : s);
                    joinSep = ', ';
                }
                const joinedFull = allTranslations.join(joinSep);
                const MAX_SENSE_CHARS = 120;
                let joinedDisplay = joinedFull;
                let isTruncated = false;
                if (joinedFull.length > MAX_SENSE_CHARS) {
                    // Truncate at a sense boundary
                    let truncated = '';
                    for (let si = 0; si < allTranslations.length; si++) {
                        const candidate = si === 0 ? allTranslations[si] : truncated + joinSep + allTranslations[si];
                        if (candidate.length > MAX_SENSE_CHARS) break;
                        truncated = candidate;
                    }
                    joinedDisplay = truncated;
                    isTruncated = true;
                }
                const ellipsisBtn = isTruncated
                    ? ` <span class="sense-cycle-expand" style="cursor: pointer; opacity: 0.7; font-size: 12px;" onclick="event.stopPropagation(); this.parentElement.querySelector('.sense-cycle-short').style.display='none'; this.parentElement.querySelector('.sense-cycle-full').style.display='inline'; this.style.display='none';" title="Show all senses">…</span>`
                    : '';
                // Same min-width as the regular-meaning pill so cycle + regular
                // rows all share a unified POS-column width.
                // Same min-width philosophy as regular rows (see above): pad
                // short labels up to 46px, let longer ones (PHRASE etc.) expand.
                const cyclePillStyle = 'font-size: 12px; padding: 5px 10px; margin: 0; white-space: nowrap; min-width: 46px; box-sizing: border-box; text-align: center;';
                target.push(`
                <div class="meaning-row meaning-row-cycle" style="display: grid; grid-template-columns: auto 1fr auto; align-items: center; padding: 1px 2px; margin-bottom: 4px; background: ${bgColor}; ${borderStyle} border-radius: 8px; cursor: pointer; min-height: 35px; opacity: 0.75;" onclick="selectMeaning(${idx})">
                    <span class="card-pos ${cyclePosClass}" style="${cyclePillStyle} justify-self: start; cursor: pointer;" onclick="showPOSInfo(event, '${cyclePos}')">${cyclePos}</span>
                    <span style="font-size: 13px; font-weight: 600; color: white; min-width: 0; text-align: center; line-height: 1.4; padding: 0 8px;">${isTruncated ? `<span class="sense-cycle-short">${joinedDisplay}</span><span class="sense-cycle-full" style="display:none">${joinedFull}</span>${ellipsisBtn}` : joinedDisplay}</span>
                    <span class="card-pos ${cyclePosClass}" style="${cyclePillStyle} justify-self: end; visibility: hidden; pointer-events: none;" aria-hidden="true">${cyclePos}</span>
                </div>
                `);
            } else {
                // Regular meaning row. Three layouts:
                //   axis === 'singleton' → flat one-row card (translation
                //                          centred, optional inline context)
                //   axis === 'translation' → group card; shared = translation,
                //                          varying list = contexts
                //   axis === 'context'   → group card; shared = context,
                //                          varying list = translations
                // Continuations of a group are skipped; the leader emits a
                // single card containing all members.
                const pctVal = Math.round(m.percentage * 100);
                const axis = GROUP_DUPLICATE_MEANINGS ? (axisOf.get(idx) || 'singleton') : 'singleton';
                const isGrouped = axis === 'translation' || axis === 'context';
                const groupKey = isGrouped ? groupKeyOf.get(idx) : null;
                const compKey = isGrouped ? `${axis}|${groupKey}` : null;
                if (isGrouped) {
                    const firstIdx = groupFirstIdx.get(compKey);
                    if (firstIdx !== idx) return;
                }
                const pillStyleBase = 'padding: 5px 16px; margin: 0; white-space: nowrap; line-height: 1; min-width: 56px; box-sizing: border-box;';
                // Single POS-pill renderer for both group + singleton: just the
                // POS label (no %; the % lives on the right of the row).
                // Font 12px to match the MWE-expression highlight pill so the
                // two visually pair as the same typographic tier.
                const buildPosPillInner = () => `<span style="display: block; font-size: 12px; font-weight: 700; line-height: 1;">${m.pos}</span>`;
                if (isGrouped) {
                    const members = groupMembers.get(compKey);
                    const pctSumRaw = groupPctSum.get(compKey);
                    const sumPct = Math.round((pctSumRaw || 0) * 100);
                    const isTransAxis = axis === 'translation';
                    const sharedText = isTransAxis
                        ? displayMeaning
                        : String(m.context || '').replace(/"/g, '&quot;');
                    // Group-level selection: clicking the shared field selects
                    // the whole group (examples become union of members);
                    // clicking any sub-item reverts to per-meaning selection.
                    const groupSelected = !!(currentGroupSelection
                        && currentGroupSelection.axis === axis
                        && currentGroupSelection.groupKey === groupKey);
                    // Outer row mirrors singleton: pos column | body | pct.
                    // The body's internal grid stays simple (shared + varying):
                    //   trans-axis: shared trans | varying ctx
                    //   ctx-axis:   varying trans | shared ctx
                    const anyMemberSelected = members.some(mi => mi === currentMeaningIndex);
                    const cardBg = (groupSelected || anyMemberSelected)
                        ? 'rgba(var(--accent-primary-rgb), 0.18)'
                        : 'rgba(15, 20, 28, 0.82)';
                    const sharedBg = groupSelected
                        ? 'rgba(var(--accent-primary-rgb), 0.55)'
                        : 'transparent';
                    const sharedBorder = groupSelected
                        ? 'border: 2px solid var(--accent-primary);'
                        : 'border: 2px solid transparent;';

                    const memberCells = members.map((memberIdx, rowIdx) => {
                        const mm = card.meanings[memberIdx];
                        const isMemberSelected = !groupSelected && memberIdx === currentMeaningIndex;
                        const cellBg = isMemberSelected
                            ? 'rgba(var(--accent-primary-rgb), 0.55)'
                            : 'rgba(255, 255, 255, 0.03)';
                        const cellBorder = (isMemberSelected && !mm.unassigned)
                            ? 'border: 2px solid var(--accent-primary);'
                            : 'border: 2px solid transparent;';
                        const baseCell = `grid-row: ${rowIdx + 1}; padding: 2px 6px; background: ${cellBg}; ${cellBorder} border-radius: 6px; cursor: pointer; min-height: 25px; display: flex; align-items: center; justify-content: center;`;
                        // Varying cell.
                        let varyingHtml;
                        if (isTransAxis) {
                            const ctxRaw = mm.context || '';
                            const ctxSafe = String(ctxRaw).replace(/"/g, '&quot;');
                            varyingHtml = ctxRaw
                                ? `<span class="meaning-context" style="line-height: 1.3; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${ctxSafe}</span>`
                                : `<span style="opacity: 0.4; font-style: italic; font-size: 12px;">—</span>`;
                        } else {
                            const transRaw = getConjugatedEnglish(card, mm.meaning) || mm.meaning || '';
                            const transSafe = String(transRaw).replace(/"/g, '&quot;');
                            varyingHtml = `<span style="font-size: 16px; font-weight: 600; color: var(--text-primary); line-height: 1.25; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${transSafe}</span>`;
                        }
                        const varyingCol = isTransAxis ? 2 : 1;
                        const varyingCell = `<div onclick="event.stopPropagation(); selectMeaning(${memberIdx})" style="${baseCell} grid-column: ${varyingCol}; min-width: 0; overflow: hidden;">${varyingHtml}</div>`;
                        return varyingCell;
                    }).join('');

                    // POS column — one pill per member, stacked on the left edge
                    // of the outer grid (col 1). Each pill's height matches the
                    // corresponding body row's min-height (25px) so pills align
                    // with their member's varying/shared cell.
                    const posStackHtml = members.map((memberIdx) => {
                        const mm = card.meanings[memberIdx];
                        const memberPct = Math.round((mm.percentage || 0) * 100);
                        const memberPosColorClass = getPosColorClass(mm.pos);
                        return `<span class="card-pos ${memberPosColorClass}" style="${pillStyleBase} display: flex; align-items: center; justify-content: center; min-height: 25px; cursor: pointer;" onclick="event.stopPropagation(); showPOSInfo(event, '${mm.pos}', ${memberPct})"><span style="display: block; font-size: 12px; font-weight: 700; line-height: 1;">${mm.pos}</span></span>`;
                    }).join('');
                    const posColumnHtml = `<div class="pos-column" style="display: flex; flex-direction: column; gap: 3px; padding-right: 4px;">${posStackHtml}</div>`;

                    // Pct stack — lives outside the highlight box, in its own
                    // outer-grid column on the right edge of the row, so the
                    // %s align with singleton-card %s.
                    const pctStackHtml = members.map((memberIdx) => {
                        const mm = card.meanings[memberIdx];
                        const memberPct = Math.round((mm.percentage || 0) * 100);
                        if (memberPct >= 100) {
                            return '<div style="min-height: 25px; padding: 2px 6px;"></div>';
                        }
                        return `<div onclick="event.stopPropagation(); selectMeaning(${memberIdx})" style="min-height: 25px; padding: 2px 6px; display: flex; align-items: center; justify-content: flex-end; font-size: 11px; opacity: 0.65; color: var(--text-primary); white-space: nowrap; cursor: pointer;">${memberPct}%</div>`;
                    }).join('');
                    const pctColumnHtml = `<div class="pct-column" style="display: flex; flex-direction: column; gap: 3px; padding-left: 4px;">${pctStackHtml}</div>`;

                    // Shared cell — spans all body rows.
                    const sharedCol = isTransAxis ? 1 : 2;
                    const sharedSpan = `grid-column: ${sharedCol}; grid-row: 1 / span ${members.length}; align-self: center;`;
                    const sharedCellHtml = isTransAxis
                        ? `<div class="group-card-shared" style="${sharedSpan} font-size: 16px; font-weight: 600; color: var(--text-primary); text-align: center; line-height: 1.25; min-width: 0; word-break: break-word;">${sharedText}</div>`
                        : `<div class="group-card-shared" style="${sharedSpan} text-align: center; line-height: 1.25; min-width: 0; word-break: break-word;"><span class="meaning-context">${sharedText}</span></div>`;

                    // Body grid: shared + varying. POS and pct columns live in
                    // the outer grid, so they don't appear here.
                    const gridCols = 'minmax(0, max-content) minmax(0, max-content)';

                    // Outer row mirrors singleton: pos column | body | pct stack.
                    const outerGridCols = 'auto 1fr auto';

                    target.push(`
                    <div class="meaning-row meaning-row-group" data-axis="${axis}" onclick="selectGroup('${axis}', ${idx})" style="display: grid; grid-template-columns: ${outerGridCols}; align-items: center; padding: 1px 2px; margin-bottom: 4px; background: ${cardBg}; border-radius: 8px; cursor: pointer;">
                        ${posColumnHtml}
                        <div class="meaning-row-body group-card-body" style="display: grid; grid-template-columns: ${gridCols}; align-items: center; gap: 3px 6px; min-width: 0; padding: 4px 8px; background: ${sharedBg}; ${sharedBorder} border-radius: 6px; justify-self: center;">
                            ${memberCells}
                            ${sharedCellHtml}
                        </div>
                        ${pctColumnHtml}
                    </div>
                    `);
                } else {
                    // Singleton: flat row. POS pill (no %) | centred translation
                    // with optional inline context | % pinned to the right edge
                    // of the body (absolute, hidden at 100%, click-through).
                    const posPillInner = buildPosPillInner();
                    const posPill = `<span class="card-pos ${posColorClass}" style="${pillStyleBase} justify-self: start; cursor: pointer;" onclick="event.stopPropagation(); showPOSInfo(event, '${m.pos}', ${pctVal})">${posPillInner}</span>`;
                    const posPillMirror = `<span class="card-pos ${posColorClass}" style="${pillStyleBase} justify-self: end; visibility: hidden; pointer-events: none;" aria-hidden="true">${posPillInner}</span>`;
                    let contextInline = '';
                    if (m.context) {
                        const safeFull = String(m.context).replace(/"/g, '&quot;');
                        contextInline = ` <span class="meaning-context">· ${safeFull}</span>`;
                    }
                    // Pct pinned to the row's right edge (not body's), so it
                    // hugs the row outline rather than sitting inside body
                    // padding. pointer-events:none lets the row's selectMeaning
                    // still fire through. right:8px matches the group pct's
                    // effective right offset for vertical alignment.
                    const pctTail = pctVal < 100
                        ? `<span style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%); font-size: 11px; opacity: 0.65; color: var(--text-primary); white-space: nowrap; pointer-events: none;">${pctVal}%</span>`
                        : '';
                    target.push(`
                    <div class="meaning-row meaning-row-regular" style="position: relative; display: grid; grid-template-columns: auto 1fr auto; align-items: center; padding: 1px 2px; margin-bottom: 4px; background: ${bgColor}; ${borderStyle} border-radius: 8px; cursor: pointer; min-height: 35px;" onclick="selectMeaning(${idx})">
                        ${posPill}
                        <div class="meaning-row-body" style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-width: 0; padding: 0 8px;">
                            <span class="meaning-row-translation" style="font-size: 16px; font-weight: 600; color: ${textColor}; text-align: center;">${displayMeaning}${contextInline}</span>
                        </div>
                        ${posPillMirror}
                        ${pctTail}
                    </div>
                    `);
                }
            }
        });
        // Emit the scroll region first, then the pinned tray underneath
        // (MWE/CLITIC rows that stay visible when the user scrolls).
        backHTML += `<div class="meanings-scroll">${scrollRows.join('')}</div>`;
        if (trayRows.length > 0) {
            backHTML += `<div class="meanings-tray">${trayRows.join('')}</div>`;
        }

        // Show current sentence
        // For MWE/Clitic senses, suppress the sentence block entirely when the
        // current expression has no matching examples — otherwise the card
        // keeps showing whatever was rendered for the previous expression.
        const isMWEOrCliticCycle = currentMeaning && (currentMeaning.allMWEs || currentMeaning.allClitics);
        let cycleHasExamples = true;
        if (isMWEOrCliticCycle) {
            const cycleList = currentMeaning.allMWEs || currentMeaning.allClitics;
            const cycleIdx = currentMWEIndex % cycleList.length;
            cycleHasExamples = (cycleList[cycleIdx].examples || []).length > 0;
        }

        if (currentMeaning && currentMeaning.targetSentence && cycleHasExamples) {
            // For MWE senses, get examples from the current MWE expression's own array
            let activeExamples;
            let activeMweIdx = 0;
            if (currentMeaning.allMWEs) {
                activeMweIdx = currentMWEIndex % currentMeaning.allMWEs.length;
                activeExamples = dedupeExamples(currentMeaning.allMWEs[activeMweIdx].examples || []);
            } else if (currentMeaning.allClitics) {
                activeMweIdx = currentMWEIndex % currentMeaning.allClitics.length;
                activeExamples = dedupeExamples(currentMeaning.allClitics[activeMweIdx].examples || []);
            } else if (currentGroupSelection && currentGroupSelection.members) {
                // Group selected: union of every member's allExamples,
                // deduped to avoid the same sentence repeating across senses.
                const merged = [];
                for (const mi of currentGroupSelection.members) {
                    const mm = card.meanings[mi];
                    if (mm && mm.allExamples) merged.push(...mm.allExamples);
                }
                activeExamples = dedupeExamples(merged);
            } else {
                activeExamples = dedupeExamples(currentMeaning.allExamples || []);
            }

            // Dynamic re-sort: boost examples with deck/recently-wrong word overlap
            if (activeExamples.length > 1) {
                activeExamples = sortExamplesByRelevance(activeExamples);
            }

            // For MWE / Clitic rows, examples whose sentence doesn't actually
            // display the expression are useless for this row — they used to
            // render in the box without the accent border, which read as a
            // visual artefact rather than a teaching moment. Filter them out
            // so the cycle only steps through sentences that actually show
            // the expression; when that leaves nothing, the whole sentence
            // block is suppressed further down (the row simply waits until
            // the user moves to an expression whose examples carry it).
            // Regular senses and SENSE_CYCLE remainder rows are unchanged:
            // they keep their non-bordered fallback sentences per the
            // existing sense-cycle behaviour.
            if (currentMeaning.allMWEs) {
                const expr = currentMeaning.allMWEs[activeMweIdx].expression;
                if (expr) {
                    const escaped = expr.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const re = _cachedRegex(escaped, 'i');
                    activeExamples = activeExamples.filter(ex => {
                        const target = ex.target || ex.spanish || '';
                        return re.test(target);
                    });
                }
            } else if (currentMeaning.allClitics) {
                const cliticForm = currentMeaning.allClitics[activeMweIdx].form;
                if (cliticForm) {
                    const escaped = cliticForm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    try {
                        const re = _cachedRegex('(?<![\\p{L}])' + escaped + '(?![\\p{L}])', 'iu');
                        activeExamples = activeExamples.filter(ex => {
                            const target = ex.target || ex.spanish || '';
                            return re.test(target);
                        });
                    } catch (_) {
                        // Older browsers without \p{...} support — skip filter
                    }
                }
            }

            // Nothing left to show? Skip emitting the sentence box below.
            // Same effect as `cycleHasExamples=false`: the row sits in the
            // tray with its expression pill + translation only, until the
            // user advances to an expression with matching evidence.
            // We still complete the variable computation here because
            // nothing in it is expensive or has side-effects — the only
            // suppression point is the `backHTML +=` at the bottom.
            const suppressSentenceBlock = isMWEOrCliticCycle && activeExamples.length === 0;

            const hasMultipleExamples = activeExamples.length > 1;
            const exampleCount = activeExamples.length;

            // Get current example (for cycling through multiple examples)
            let displayTargetSentence = currentMeaning.targetSentence;
            let displayEnglishSentence = currentMeaning.englishSentence;
            let songName = null;
            let currentExample = null;

            let spotifyUrl = null;
            let spotifyTrackId = null;
            let positionMs = 60000;
            if (activeExamples.length > 0) {
                const exIdx = currentExampleIndex % activeExamples.length;
                const example = activeExamples[exIdx];
                currentExample = example;
                const exTarget = example.target || example.spanish || '';
                const exEnglish = example.english || '';
                if (exTarget) {
                    displayTargetSentence = exTarget;
                    displayEnglishSentence = exEnglish;
                }
                songName = example.song_name || null;
                positionMs = example.timestamp_ms || 60000;

                // Look up Spotify track URL for this song
                if (songName && window._spotifyTracks) {
                    // Determine artist display name for lookup
                    let lookupArtist = null;
                    if (example.artist) {
                        const allConfigs = window._allArtistsConfig;
                        if (allConfigs && allConfigs[example.artist]) {
                            lookupArtist = allConfigs[example.artist].name;
                        }
                    }
                    if (!lookupArtist && activeArtist) {
                        lookupArtist = activeArtist.name;
                    }
                    if (lookupArtist) {
                        const trackId = (window._spotifyTracks[lookupArtist] || {})[songName];
                        if (trackId) {
                            spotifyUrl = `https://open.spotify.com/track/${trackId}`;
                            spotifyTrackId = trackId;
                        }
                    }
                }

                if (songName && example.artist) {
                    const allConfigs = window._allArtistsConfig;
                    const selectedSlugs = window._selectedArtistSlugs || [];
                    if (selectedSlugs.length > 1 && allConfigs && allConfigs[example.artist]) {
                        songName = allConfigs[example.artist].name + ' \u2014 ' + songName;
                    }
                }
            }

            // Truncate sentences longer than 20 words
            displayTargetSentence = truncateText(displayTargetSentence, 20);
            displayEnglishSentence = truncateText(displayEnglishSentence, 20);

            // Highlight words in the target sentence with a colored pill + white text
            const pillStyle = 'background: rgba(255,255,255,0.22); color: white; font-weight: 700; padding: 1px 5px; border-radius: 4px;';
            if (currentMeaning.allMWEs) {
                // MWE sense: highlight the current MWE expression
                const expr = currentMeaning.allMWEs[activeMweIdx].expression;
                const escaped = expr.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const regex = _cachedRegex(`(?<![\\p{L}\\p{N}])(${escaped})(?![\\p{L}\\p{N}])`, 'giu');
                displayTargetSentence = displayTargetSentence.replace(regex,
                    `<span style="${pillStyle}">$1</span>`);
            } else {
                // Regular sense: highlight the target word (word boundaries for short words)
                const word = card.targetWord;
                const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const regex = _cachedRegex(`(?<![\\p{L}\\p{N}])(${escaped})(?![\\p{L}\\p{N}])`, 'giu');
                displayTargetSentence = displayTargetSentence.replace(regex,
                    `<span style="${pillStyle}">$1</span>`);
            }

            // Highlight other study set words in the sentence (same style for now)
            const deckWords = getDeckWords();
            const targetLower = card.targetWord.toLowerCase();
            for (const dw of deckWords) {
                if (dw === targetLower || dw.length <= 2) continue;
                // Skip if already inside a <span> tag (already highlighted)
                const dwEscaped = dw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const dwRegex = _cachedRegex(`(?<![\\p{L}\\p{N}])(${dwEscaped})(?![\\p{L}\\p{N}])(?![^<]*>)`, 'giu');
                displayTargetSentence = displayTargetSentence.replace(dwRegex,
                    `<span style="${pillStyle}">$1</span>`);
            }

            // Highlight the English translation in the English sentence for keyword-assigned examples
            const exampleMethod = currentExample && currentExample.assignment_method;
            if (exampleMethod && exampleMethod.includes('keyword') && currentMeaning && currentMeaning.meaning && displayEnglishSentence) {
                // Split on commas/semicolons to try each translation fragment
                const fragments = currentMeaning.meaning.split(/[,;]/).map(f => f.trim()).filter(f => f.length > 1);
                for (const frag of fragments) {
                    const fragEscaped = frag.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const fragRegex = _cachedRegex(`(?<![\\p{L}\\p{N}])(${fragEscaped})(?![\\p{L}\\p{N}])(?![^<]*>)`, 'giu');
                    displayEnglishSentence = displayEnglishSentence.replace(fragRegex,
                        `<span style="${pillStyle}">$1</span>`);
                }
            }

            // Build example counter: shows count for current MWE's examples, not total MWEs
            let exampleCounter = '';
            if (hasMultipleExamples) {
                const exIdx = currentExampleIndex % exampleCount;
                exampleCounter = `<span class="example-counter-group"><button class="example-cycle-btn desktop-only" onclick="cycleExampleBackward(event)" title="Previous example">‹</button><span>${exIdx + 1}/${exampleCount}</span><button class="example-cycle-btn desktop-only" onclick="cycleExampleForward(event)" title="Next example">›</button></span>`;
            }
            // Breakdown button removed — English translation is now clickable instead
            const spotifySvg = `<svg width="40" height="40" viewBox="0 0 24 24" fill="#1DB954"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/></svg>`;
            const spotifyBtn = spotifyTrackId
                ? `<button type="button" class="spotify-btn link-btn" data-track-id="${spotifyTrackId}" data-position-ms="${positionMs}" title="Play in Spotify" style="cursor:pointer; background:none; border:none; margin:0; padding:6px; position:relative; z-index:999;" onclick="event.stopPropagation(); spotifyPlayTrack('${spotifyTrackId}', ${positionMs})" ontouchend="event.stopPropagation(); event.preventDefault(); spotifyPlayTrack('${spotifyTrackId}', ${positionMs})">${spotifySvg}</button>`
                : (spotifyUrl ? `<a href="${spotifyUrl}" target="_blank" class="spotify-btn link-btn" title="Open in Spotify">${spotifySvg}</a>` : '');
            const songNameDisplay = songName ? `
                <div style="display: flex; justify-content: space-between; align-items: center; color: white; font-size: 11px; margin-top: 8px; font-style: italic; opacity: 0.85;">
                    <span style="display: flex; align-items: center; gap: 5px;">— ${songName}</span>
                    <span style="display: flex; align-items: center; gap: 6px;">${spotifyBtn}${exampleCounter}</span>
                </div>
            ` : (exampleCounter ? `
                <div style="display: flex; justify-content: flex-end; align-items: center; color: white; font-size: 11px; margin-top: 8px; opacity: 0.85;">
                    <span style="display: flex; align-items: center; gap: 6px;">${exampleCounter}</span>
                </div>
            ` : '');

            const cycleHandler = hasMultipleExamples ? 'onclick="cycleExample(event)"' : '';
            const cursorStyle = hasMultipleExamples ? 'cursor: pointer;' : '';

            // Determine if this example is genuinely assigned to this sense.
            // Per-example assignment_method is authoritative when present;
            // fall back to per-meaning for non-keyword methods (Gemini/biencoder).
            let exampleAssigned = false;
            if (currentExample && currentExample.assignment_method) {
                exampleAssigned = true;  // this specific example was classified
            } else if (currentMeaning && !currentMeaning.unassigned && !currentMeaning.assignment_method) {
                exampleAssigned = true;  // strong method (Gemini/biencoder) — all examples assigned
            }
            // MWE: check if the expression appears in the example sentence
            if (currentMeaning && currentMeaning.allMWEs && displayTargetSentence) {
                const activeMwe = currentMeaning.allMWEs[currentMWEIndex % currentMeaning.allMWEs.length];
                if (activeMwe && activeMwe.expression) {
                    const escaped = activeMwe.expression.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const re = _cachedRegex(escaped, 'i');
                    exampleAssigned = re.test(displayTargetSentence.replace(/<[^>]*>/g, ''));
                }
            }
            // Clitic: check if the clitic form appears in the example sentence
            if (currentMeaning && currentMeaning.allClitics && displayTargetSentence) {
                const activeClitic = currentMeaning.allClitics[currentMWEIndex % currentMeaning.allClitics.length];
                if (activeClitic && activeClitic.form) {
                    const escaped = activeClitic.form.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const re = _cachedRegex('(?<![\\p{L}])' + escaped + '(?![\\p{L}])', 'iu');
                    exampleAssigned = re.test(displayTargetSentence.replace(/<[^>]*>/g, ''));
                }
            }
            const sentenceStyle = exampleAssigned
                ? 'border: 3px solid var(--accent-primary); box-shadow: 0 0 10px rgba(var(--accent-primary-rgb), 0.25);'
                : 'border-color: transparent;';

            // Only emit the sentence block if we have something worth
            // showing. For MWE / Clitic cycles where the filter left us
            // with zero examples that actually contain the expression,
            // suppressSentenceBlock is true and we skip entirely — the
            // row waits in the tray until the user moves to an expression
            // whose evidence carries a matching sentence.
            if (!suppressSentenceBlock) {
                backHTML += `
                    <div class="sentence" style="text-align: center; ${cursorStyle} ${sentenceStyle}" ${cycleHandler}>
                        <div class="breakdown-trigger" style="margin-bottom: 8px; cursor: pointer;" onclick="showLyricBreakdown(event); event.stopPropagation();" title="Tap for word-by-word breakdown">${displayTargetSentence}</div>
                        <div class="translation">${displayEnglishSentence}</div>
                        ${songNameDisplay}
                    </div>
                `;
            }
        }
    } else {
        // Legacy format
        backHTML += `<div style="font-size: 28px; color: var(--text-primary); margin-top: 12px; font-weight: 600; text-align: center; margin-bottom: 20px;">${backTranslation}</div>`;

        // Show base form if different from displayed word
        if (card.inflectedForm && card.baseForm !== card.targetWord) {
            backHTML += `<div style="margin-bottom: 15px; font-size: 16px; text-align: center; color: #ffffff;"><strong style="color: var(--accent-secondary);">Base form:</strong> ${card.baseForm}</div>`;
        }

        // Show example sentences if available
        const sentenceCount = card.sentences ? card.sentences.length : 1;
        if (sentenceCount > 0) {
            const showEmpty = !exampleSentence && !exampleTranslation;
            const sentenceIndicator = sentenceCount > 1 ? `
                <div style="display: flex; align-items: center; justify-content: center; gap: 10px; margin-bottom: 8px;">
                    <span style="color: var(--accent-primary); font-size: 18px;">↑</span>
                    <span style="color: var(--text-muted); font-size: 12px;">${currentSentenceIndex + 1} / ${sentenceCount}</span>
                    <span style="color: var(--accent-primary); font-size: 18px;">↓</span>
                </div>
            ` : '';

            backHTML += `
                ${sentenceIndicator}
                <div class="sentence" style="min-height: 80px; text-align: center;">
                    ${exampleSentence ? `<div style="margin-bottom: 8px;">${exampleSentence}</div>` : ''}
                    ${exampleTranslation ? `<div class="translation">${exampleTranslation}</div>` : ''}
                    ${showEmpty ? `<div style="color: var(--text-muted); text-align: center; padding: 20px;">(No example sentence)</div>` : ''}
                </div>
            `;
        }
    }

    // Reference links as icon buttons — real favicons via Google's proxy.
    // `conjugation` is not in this map: verb cards always get the unified
    // in-app conjugation toggle (red/yellow AR/ER/IR icon) instead of an
    // external link. The toggle's panel handles the no-data case with a
    // friendly message + SpanishDict link, so there's a single entry
    // point regardless of whether we ship inline conjugations for a
    // given lemma.
    const linkIcons = {
        'spanishDict': `<img src="https://www.google.com/s2/favicons?domain=spanishdict.com&sz=64" width="40" height="40" alt="SpanishDict" style="border-radius:4px">`,
        'reverso': `<img src="https://www.google.com/s2/favicons?domain=reverso.net&sz=64" width="40" height="40" alt="Reverso" style="border-radius:4px">`
    };
    const linkTitles = {
        'spanishDict': 'SpanishDict',
        'reverso': 'Reverso Context',
        'conjugation': 'Conjugate'
    };

    // Determine if current word is a verb
    let isVerb = false;
    if (card.isMultiMeaning && currentMeaning) {
        // For multi-meaning cards, check the current meaning's POS
        const pos = currentMeaning.pos ? currentMeaning.pos.toLowerCase() : '';
        isVerb = pos.includes('verb') || pos === 'v' || pos === 'vb';
    }

    // Check for inline conjugation data — first under the card's own
    // lemma, then (as a fallback) under its `relatedLemma` if one was
    // stamped. The related lemma is SpanishDict's morphological
    // pointer for lexicalised conjugated-form headwords (hay → haber);
    // we use it to surface the related verb's paradigm when the card's
    // own lemma doesn't have one. See buildConjugationTableHTML for
    // the "related paradigm" display treatment.
    let conjEntry = null;
    let conjEntryIsRelated = false;
    if (isVerb && _conjugationData) {
        if (_conjugationData[card.lemma]) {
            conjEntry = _conjugationData[card.lemma];
        } else if (card.relatedLemma && _conjugationData[card.relatedLemma]) {
            conjEntry = _conjugationData[card.relatedLemma];
            conjEntryIsRelated = true;
        }
    }

    backHTML += `<div class="links-section" id="linksSection">`;

    // Unified in-app conjugation button for every verb card (always the
    // same red/yellow AR/ER/IR icon). Clicking opens the conjugation
    // panel, which itself handles the "no inline data" case with a
    // friendly message + SpanishDict link. Single entry point avoids
    // the old "visually-indistinguishable-SpanishDict-favicon" clutter.
    if (isVerb) {
        backHTML += `<button class="ref-icon-btn ref-conj-btn" title="Conjugation Table" onclick="toggleConjugationTable()">
            <svg width="32" height="32" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <rect x="0" y="0" width="32" height="32" rx="5" fill="#ffffff"/>
                <g font-family="system-ui, -apple-system, sans-serif" font-weight="700" font-size="8.2" text-anchor="middle" letter-spacing="0.3" fill="#000000">
                    <text x="16" y="11">-AR</text>
                    <text x="16" y="20">-ER</text>
                    <text x="16" y="29">-IR</text>
                </g>
            </svg>
        </button>`;
    }

    const hasSynonyms = (card.synonyms && card.synonyms.length) || (card.antonyms && card.antonyms.length);
    if (hasSynonyms) {
        backHTML += `<button class="ref-icon-btn ref-syn-btn" title="Synonyms &amp; Antonyms" onclick="toggleSynonymsPanel()">
            <svg width="32" height="32" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <rect x="0" y="0" width="32" height="32" rx="5" fill="#ffffff"/>
                <text x="16" y="23" font-family="system-ui, -apple-system, sans-serif" font-weight="700" font-size="22" text-anchor="middle" fill="#000000">≈</text>
            </svg>
        </button>`;
    }

    for (const [key, url] of Object.entries(card.links)) {
        if (key === 'wordReference') continue; // Skip wordReference
        // Conjugation is handled by the unified in-app toggle above.
        if (key === 'conjugation') continue;
        const icon = linkIcons[key];
        const title = linkTitles[key] || key;
        if (icon) {
            backHTML += `<a href="${url}" target="_blank" class="ref-icon-btn" title="${title}">${icon}</a>`;
        } else {
            backHTML += `<a href="${url}" target="_blank" class="link-btn">${title}</a>`;
        }
    }

    // Card-info button (opens the same metadata popover as the desktop `i` key).
    // JST-gated for now while we shake out the mobile flagging flow.
    if (currentUser && currentUser.initials === 'JST') {
        backHTML += `<button class="ref-icon-btn ref-meta-btn" title="Card info" onclick="event.stopPropagation(); toggleCardMetaPopover();">
            <svg width="32" height="32" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <rect x="0" y="0" width="32" height="32" rx="5" fill="#ffffff"/>
                <text x="16" y="24" font-family="system-ui, -apple-system, sans-serif" font-weight="700" font-size="22" text-anchor="middle" fill="#000000">i</text>
            </svg>
        </button>`;
    }

    backHTML += `</div>`;

    // Conjugation panel — always built for verbs. The builder handles
    // the no-inline-data case itself (returns a "no data" panel + SD
    // link), so the button above always has something to toggle.
    // When we're rendering data for the card's related verb (e.g.
    // showing haber's paradigm for a hay card), we pass that flag
    // through so the panel can label it honestly instead of pretending
    // the paradigm belongs to the card's own word.
    if (isVerb) {
        backHTML += buildConjugationTableHTML(
            conjEntry,
            card.targetWord,
            card.lemma,
            { relatedLemma: card.relatedLemma, isRelatedParadigm: conjEntryIsRelated }
        );
    }

    if (hasSynonyms) {
        backHTML += buildSynonymsPanelHTML(card.synonyms || [], card.antonyms || [], card.lemma || card.targetWord);
    }

    document.getElementById('backContent').innerHTML = backHTML;

    // Post-render layout pass:
    //   1. Flag meaning rows whose translation+context actually overflows the
    //      3-line clamp so the span becomes tap-to-expand. We only flag what
    //      measures as clipped, not everything past an arbitrary char count.
    //   2. If the total (meanings + tray + sentence + links) would overflow
    //      the card's content area, cap .meanings-scroll to the remaining
    //      space so IT scrolls — not the whole card. If everything fits, no
    //      cap is applied and flex-layout centres the block as normal.
    //
    // The cap is measured live: we sum every non-scroll child's rendered
    // height (+ its top/bottom margins) and subtract from backContent's
    // client height. That way the scroll threshold adapts to:
    //   - header wrapping to two lines (long word + lemma)
    //   - example sentence growing with longer lines
    //   - MWE / clitic tray being present or empty
    //   - expanded (tap-to-expand) sense rows taking more vertical space
    //
    // Previously there was a hardcoded "> 3 rows → cap at 3 rows" rule that
    // forced scrolling even when the card had plenty of room; this replaces
    // it with a genuine content-vs-space check.
    {
        const backEl = document.getElementById('backContent');
        if (backEl) {
            // Two-phase: collect overflowing rows in a read-only pass, then
            // add the .is-clamped class in a separate write pass. Mixing
            // reads and writes per row would force layout flush per row;
            // splitting keeps it to one flush total. The click handler
            // lives at module scope as a delegated listener (see bottom of
            // file), so no per-row addEventListener here.
            const toClamp = [];
            backEl.querySelectorAll('.meaning-row-translation').forEach(el => {
                if (el.scrollHeight > el.clientHeight + 1) toClamp.push(el);
            });
            for (const el of toClamp) el.classList.add('is-clamped');

            const scroll = backEl.querySelector('.meanings-scroll');
            if (scroll) {
                // Clear any prior cap so we can measure natural heights
                // before deciding whether a new cap is needed.
                scroll.style.maxHeight = '';
                const availableHeight = backEl.clientHeight;
                let overhead = 0;
                // The conjugation panel is the only known position:absolute
                // direct child of #backContent; skip by class to avoid one
                // getComputedStyle call per render on verb cards. Other
                // direct children are in flow, so we still need the call
                // for their margin values.
                for (const child of backEl.children) {
                    if (child === scroll) continue;
                    if (child.classList.contains('conjugation-panel')) continue;
                    const cs = getComputedStyle(child);
                    if (cs.position === 'absolute' || cs.position === 'fixed') continue;
                    overhead += child.offsetHeight
                        + (parseFloat(cs.marginTop) || 0)
                        + (parseFloat(cs.marginBottom) || 0);
                }
                const availableForScroll = availableHeight - overhead;
                // Cap meanings-scroll whenever its natural content overflows
                // the remaining room. Floor the cap value (not the gate) at
                // 60px so the scroller stays usable even when overhead is
                // tight, instead of silently disabling the cap.
                if (scroll.scrollHeight > availableForScroll) {
                    scroll.style.maxHeight = Math.max(60, availableForScroll) + 'px';
                }
            }
        }
    }

    // Visual cue: this card was opened via search/synonym/lyric breakdown.
    // The .is-stacked class drives a peek-tab pseudo above the card.
    document.getElementById('flashcard').classList.toggle('is-stacked', cardNavStack.length > 0);

    // Update frequency display (skip for peek/stacked cards)
    if (cardNavStack.length === 0) {
        stats.studied.add(currentIndex);
        updateStats();
    }

    // Update disabled state for all nav buttons
    const isPrevDisabled = currentIndex === 0;
    const isNextDisabled = currentIndex === flashcards.length - 1;
    document.getElementById('prevBtnFront').disabled = isPrevDisabled;
    document.getElementById('nextBtnFront').disabled = isNextDisabled;
    document.getElementById('prevBtnBack').disabled = isPrevDisabled;
    document.getElementById('nextBtnBack').disabled = isNextDisabled;
    document.getElementById('prevBtnFrontMobile').disabled = isPrevDisabled;
    document.getElementById('nextBtnFrontMobile').disabled = isNextDisabled;

    // Setup outside nav buttons (desktop)
    const prevBtnOutside = document.getElementById('prevBtnFrontOutside');
    const nextBtnOutside = document.getElementById('nextBtnFrontOutside');
    if (prevBtnOutside) {
        prevBtnOutside.disabled = isPrevDisabled;
        prevBtnOutside.onclick = function(e) {
            e.stopPropagation();
            previousCard();
        };
    }
    if (nextBtnOutside) {
        nextBtnOutside.disabled = isNextDisabled;
        nextBtnOutside.onclick = function(e) {
            e.stopPropagation();
            nextCard();
        };
    }

    // Setup outside answer buttons (desktop only, hidden via CSS on mobile)
    const correctBtnOutside = document.getElementById('correctBtnOutside');
    const incorrectBtnOutside = document.getElementById('incorrectBtnOutside');

    if (correctBtnOutside && incorrectBtnOutside) {
        correctBtnOutside.onclick = function(e) {
            e.stopPropagation();
            handleSwipeAction('correct');
        };
        incorrectBtnOutside.onclick = function(e) {
            e.stopPropagation();
            handleSwipeAction('incorrect');
        };
    }

    // Speak the word if showing target language on front
    if (!isFlipped) {
        speakWord(card.targetWord);
    }

    // Keep the debug metadata popover in sync with the visible card.
    if (typeof window.refreshCardMetaPopoverIfOpen === 'function') {
        window.refreshCardMetaPopoverIfOpen();
    }
}

function flipCard() {
    const flashcardEl = document.getElementById('flashcard');
    const wasFlipped = flashcardEl.classList.contains('flipped');
    flashcardEl.classList.toggle('flipped');
    const isNowFlipped = flashcardEl.classList.contains('flipped');

    const card = flashcards[currentIndex];
    if (!card) return;

    // Auto-speak based on flip state and language direction
    if (isNowFlipped) {
        // Just flipped to BACK of card
        if (isFlipped) {
            // English → Target mode: back shows target word, speak target
            speakWord(card.targetWord, false);
        } else {
            // Target → English mode: back shows English, speak English meaning
            const meaning = card.meanings[currentMeaningIndex];
            if (meaning && meaning.meaning) {
                speakWord(meaning.meaning, true);
            }
        }
    } else {
        // Just flipped to FRONT of card
        if (isFlipped) {
            // English → Target mode: front shows English, speak English
            const meaning = card.meanings[currentMeaningIndex];
            if (meaning && meaning.meaning) {
                speakWord(meaning.meaning, true);
            }
        } else {
            // Target → English mode: front shows target word, speak target
            speakWord(card.targetWord, false);
        }
    }
}

function cycleExample(event) {
    // Don't cycle if tap was on the Spotify button or other interactive elements
    if (event.target.closest('.spotify-btn') || event.target.closest('.breakdown-trigger')) return;
    event.stopPropagation(); // Prevent card flip
    const card = flashcards[currentIndex];
    if (!card || !card.meanings) return;
    const currentMeaning = card.meanings[currentMeaningIndex];
    if (!currentMeaning) return;

    // For MWE senses, cycle within the current MWE's examples
    let examples;
    if (currentMeaning.allMWEs) {
        const mweIdx = currentMWEIndex % currentMeaning.allMWEs.length;
        examples = dedupeExamples(currentMeaning.allMWEs[mweIdx].examples || []);
    } else {
        examples = dedupeExamples(currentMeaning.allExamples || []);
    }

    if (examples.length <= 1) return;

    currentExampleIndex = (currentExampleIndex + 1) % examples.length;
    updateCard();
}

function cycleExampleForward(event) {
    if (event) event.stopPropagation();
    const card = flashcards[currentIndex];
    if (!card || !card.meanings) return;
    const currentMeaning = card.meanings[currentMeaningIndex];
    if (!currentMeaning) return;
    let examples;
    if (currentMeaning.allMWEs) {
        const mweIdx = currentMWEIndex % currentMeaning.allMWEs.length;
        examples = dedupeExamples(currentMeaning.allMWEs[mweIdx].examples || []);
    } else {
        examples = dedupeExamples(currentMeaning.allExamples || []);
    }
    if (examples.length <= 1) return;
    currentExampleIndex = (currentExampleIndex + 1) % examples.length;
    updateCard();
}

function cycleExampleBackward(event) {
    if (event) event.stopPropagation();
    const card = flashcards[currentIndex];
    if (!card || !card.meanings) return;
    const currentMeaning = card.meanings[currentMeaningIndex];
    if (!currentMeaning) return;
    let examples;
    if (currentMeaning.allMWEs) {
        const mweIdx = currentMWEIndex % currentMeaning.allMWEs.length;
        examples = dedupeExamples(currentMeaning.allMWEs[mweIdx].examples || []);
    } else {
        examples = dedupeExamples(currentMeaning.allExamples || []);
    }
    if (examples.length <= 1) return;
    currentExampleIndex = (currentExampleIndex - 1 + examples.length) % examples.length;
    updateCard();
}

function cycleMWEForward(event) {
    if (event) event.stopPropagation();
    const card = flashcards[currentIndex];
    const m = card && card.meanings[currentMeaningIndex];
    const items = m && (m.allMWEs || m.allClitics);
    if (items && items.length > 1) {
        currentMWEIndex = (currentMWEIndex + 1) % items.length;
        currentExampleIndex = 0;
        updateCard();
    }
}

function cycleMWEBackward(event) {
    if (event) event.stopPropagation();
    const card = flashcards[currentIndex];
    const m = card && card.meanings[currentMeaningIndex];
    const items = m && (m.allMWEs || m.allClitics);
    if (items && items.length > 1) {
        currentMWEIndex = (currentMWEIndex - 1 + items.length) % items.length;
        currentExampleIndex = 0;
        updateCard();
    }
}

function selectMeaning(index) {
    if (index === currentMeaningIndex && !currentGroupSelection) {
        // Already selected — cycle if this is a cycling pill (MWE/clitic/sense cycle)
        const card = flashcards[currentIndex];
        const m = card && card.meanings[index];
        if (m && m.allMWEs && m.allMWEs.length > 1) {
            currentMWEIndex = (currentMWEIndex + 1) % m.allMWEs.length;
            currentExampleIndex = 0;
            updateCard();
            return;
        }
        if (m && m.allClitics && m.allClitics.length > 1) {
            currentMWEIndex = (currentMWEIndex + 1) % m.allClitics.length;
            currentExampleIndex = 0;
            updateCard();
            return;
        }
        if (m && m.allSenses && m.allSenses.length > 1) {
            currentMWEIndex = (currentMWEIndex + 1) % m.allSenses.length;
            currentExampleIndex = 0;
            updateCard();
            return;
        }
    }
    // Clicking a sub-row exits group-selection mode and pins the chosen meaning.
    currentGroupSelection = null;
    currentMeaningIndex = index;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    updateCard();
    // Auto-speak the selected meaning
    const card = flashcards[currentIndex];
    if (card && card.meanings[index]) {
        const meaning = card.meanings[index];
        if (isFlipped) {
            // English → Target mode: back shows target, speak target
            speakWord(card.targetWord, false);
        } else {
            // Target → English mode: back shows English, speak English
            speakWord(meaning.meaning, true);
        }
    }
}

// Click handler for the shared field of a group card. Re-derives the member
// set from `axis` + the anchor meaning so the inline onclick stays trivial
// (no JSON-encoded payload in the attribute). The anchor index is the leader
// of the group (firstIdx); we use it as a fallback for currentMeaning so
// downstream code that reads `card.meanings[currentMeaningIndex]` still has
// a valid object.
function selectGroup(axis, anchorIdx) {
    const card = flashcards[currentIndex];
    if (!card || !card.meanings || !card.meanings[anchorIdx]) return;
    const anchor = card.meanings[anchorIdx];
    let groupKey;
    let members;
    if (axis === 'translation') {
        groupKey = `${anchor.pos}|${anchor.meaning}`;
        members = card.meanings
            .map((mm, i) => ({ mm, i }))
            .filter(({ mm }) => mm.pos === anchor.pos && mm.meaning === anchor.meaning)
            .map(({ i }) => i);
    } else {
        groupKey = `${anchor.pos}|${anchor.context || ''}`;
        members = card.meanings
            .map((mm, i) => ({ mm, i }))
            .filter(({ mm }) => mm.pos === anchor.pos && (mm.context || '') === (anchor.context || ''))
            .map(({ i }) => i);
    }
    if (members.length < 2) return;
    currentGroupSelection = { axis, groupKey, members };
    currentMeaningIndex = anchorIdx;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    updateCard();
    // Auto-speak the shared aspect.
    if (axis === 'translation') {
        speakWord(anchor.meaning, true);
    } else {
        speakWord(card.targetWord, false);
    }
}

function previousCard() {
    if (currentIndex > 0) {
        currentIndex--;
        currentMeaningIndex = 0;
        currentExampleIndex = 0;
        currentMWEIndex = 0;
        currentGroupSelection = null;
        updateCard();
        document.getElementById('flashcard').classList.remove('flipped');
    }
}

function nextCard() {
    if (currentIndex < flashcards.length - 1) {
        currentIndex++;
        currentMeaningIndex = 0;
        currentExampleIndex = 0;
        currentMWEIndex = 0;
        currentGroupSelection = null;
        updateCard();
        document.getElementById('flashcard').classList.remove('flipped');
    }
}

function shuffleCards() {
    for (let i = flashcards.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [flashcards[i], flashcards[j]] = [flashcards[j], flashcards[i]];
    }
    currentIndex = 0;
    updateCard();
}

function flipDirection() {
    isFlipped = !isFlipped;
    updateCard();
    document.getElementById('flashcard').classList.remove('flipped');
}

function getPosColorClass(pos) {
    if (!pos) return '';
    const posLower = pos.toLowerCase();
    if (posLower.includes('noun') || posLower === 'n' || posLower === 'nn') return 'pos-noun';
    if (posLower.includes('verb') || posLower === 'v' || posLower === 'vb') return 'pos-verb';
    if (posLower.includes('adj') || posLower === 'a' || posLower === 'jj') return 'pos-adj';
    if (posLower.includes('adv') || posLower === 'rb') return 'pos-adv';
    if (posLower.includes('prep') || posLower === 'in') return 'pos-prep';
    if (posLower.includes('conj') || posLower === 'cc') return 'pos-conj';
    if (posLower.includes('pron') || posLower === 'prp') return 'pos-pron';
    if (posLower.includes('det') || posLower === 'dt') return 'pos-det';
    if (posLower.includes('int') || posLower === 'uh') return 'pos-int';
    if (posLower.includes('num') || posLower === 'cd') return 'pos-num';
    if (posLower === 'mwe') return 'pos-mwe';
    return '';
}

function updateReverseButton() {
    const reverseBtn = document.getElementById('reverseLangBtn');
    if (!reverseBtn) return;

    // Map language codes to flag emojis
    const flagMap = {
        'dutch': '🇳🇱',
        'polish': '🇵🇱',
        'spanish': '🇪🇸',
        'italian': '🇮🇹',
        'french': '🇫🇷',
        'russian': '🇷🇺',
        'swedish': '🇸🇪'
    };

    const targetFlag = flagMap[selectedLanguage] || '🇸🇪';
    const englishFlag = '🇬🇧';

    const fromFlag = isFlipped ? englishFlag : targetFlag;
    const toFlag = isFlipped ? targetFlag : englishFlag;
    reverseBtn.innerHTML = `<span class="reverse-flag-from">${fromFlag}</span><span class="reverse-swap-glyph" aria-hidden="true">⇄</span><span class="reverse-flag-to" aria-hidden="true">${toFlag}</span>`;
    if (isFlipped) {
        reverseBtn.title = `Reverse to ${config.languages[selectedLanguage]?.name || selectedLanguage} → English`;
    } else {
        reverseBtn.title = `Reverse to English → ${config.languages[selectedLanguage]?.name || selectedLanguage}`;
    }
}

function updateStats() {
    // Stats are now displayed in modal only
}

// --- Lyric Breakdown ---

// Module-level cache for full vocab lookup (not in state — doesn't need proxy)
let fullVocabLookup = null;
let vocabByIdLookup = null;

function getVocabByIdLookup() {
    if (vocabByIdLookup) return vocabByIdLookup;
    if (!cachedVocabularyData) return new Map();
    vocabByIdLookup = new Map();
    for (const entry of cachedVocabularyData) {
        if (entry.id) vocabByIdLookup.set(entry.id, entry);
    }
    return vocabByIdLookup;
}

// Common Spanish elisions: elided form → possible full forms
const ELISION_MAP = {
    "pa": ["para"],
    "to": ["todo"],
    "na": ["nada"],
    "ta": ["esta", "estar"],
    "toy": ["estoy"],
    "tan": ["están"],
    "tamo": ["estamos"],
    "pal": ["para el"],
    "po": ["por"],
};

function getFullVocabLookup() {
    if (fullVocabLookup) return fullVocabLookup;
    if (!cachedVocabularyData) return new Map();
    fullVocabLookup = new Map();
    for (const entry of cachedVocabularyData) {
        const w = entry.word.toLowerCase().trim();
        if (!fullVocabLookup.has(w)) fullVocabLookup.set(w, entry);
        if (entry.lemma) {
            const l = entry.lemma.toLowerCase().trim();
            if (!fullVocabLookup.has(l)) fullVocabLookup.set(l, entry);
        }
    }
    return fullVocabLookup;
}

function tokenizeLyricLine(sentence) {
    if (!sentence) return [];
    // Strip any HTML tags (from word highlighting)
    const clean = sentence.replace(/<[^>]+>/g, '');
    const rawTokens = clean.split(/\s+/).filter(t => t.length > 0);
    return rawTokens.map(raw => {
        const match = raw.match(/^([^\p{L}\p{N}]*)([\p{L}\p{N}][\p{L}\p{N}'''-]*)([^\p{L}\p{N}]*)$/u);
        if (match) {
            return { original: raw, clean: match[2], punctBefore: match[1], punctAfter: match[3] };
        }
        // Pure punctuation or unmatched
        return { original: raw, clean: '', punctBefore: '', punctAfter: '' };
    });
}

function resolveToken(token) {
    if (!token.clean) return { token, source: 'unknown', entry: null, deckIndex: null };

    const lower = token.clean.toLowerCase();
    const lookupMap = window._wordLookupMap || new Map();

    // 1. Check current deck
    let deckIdx = lookupMap.get(lower);
    if (deckIdx !== undefined) {
        return { token, source: 'deck', entry: flashcards[deckIdx], deckIndex: deckIdx };
    }

    // 2. Try stripping trailing apostrophe (ere' → eres, etc.)
    if (lower.endsWith("'") || lower.endsWith("\u2019")) {
        const stripped = lower.replace(/['\u2019]+$/, '');
        deckIdx = lookupMap.get(stripped + 's');
        if (deckIdx !== undefined) return { token, source: 'deck', entry: flashcards[deckIdx], deckIndex: deckIdx };
        deckIdx = lookupMap.get(stripped);
        if (deckIdx !== undefined) return { token, source: 'deck', entry: flashcards[deckIdx], deckIndex: deckIdx };
    }

    // 3. Try elision map
    const elisions = ELISION_MAP[lower];
    if (elisions) {
        for (const full of elisions) {
            deckIdx = lookupMap.get(full);
            if (deckIdx !== undefined) return { token, source: 'deck', entry: flashcards[deckIdx], deckIndex: deckIdx };
        }
    }

    // 4. Check full vocabulary
    const fullLookup = getFullVocabLookup();
    let vocabEntry = fullLookup.get(lower);
    if (vocabEntry) return { token, source: 'vocab', entry: vocabEntry, deckIndex: null };

    // 5. Try elision recovery against full vocab
    if (lower.endsWith("'") || lower.endsWith("\u2019")) {
        const stripped = lower.replace(/['\u2019]+$/, '');
        vocabEntry = fullLookup.get(stripped + 's');
        if (vocabEntry) return { token, source: 'vocab', entry: vocabEntry, deckIndex: null };
        vocabEntry = fullLookup.get(stripped);
        if (vocabEntry) return { token, source: 'vocab', entry: vocabEntry, deckIndex: null };
    }
    if (elisions) {
        for (const full of elisions) {
            vocabEntry = fullLookup.get(full);
            if (vocabEntry) return { token, source: 'vocab', entry: vocabEntry, deckIndex: null };
        }
    }

    return { token, source: 'unknown', entry: null, deckIndex: null };
}

// Store current breakdown for popup access
let currentBreakdownResults = [];

function showLyricBreakdown(event) {
    event.stopPropagation();
    event.preventDefault();

    const card = flashcards[currentIndex];
    if (!card) return;

    const currentMeaning = card.meanings[currentMeaningIndex];
    if (!currentMeaning) return;

    // Get the raw (un-truncated) sentence — use MWE-specific examples if applicable
    let targetSentence = '';
    let englishSentence = '';
    let activeExamples;
    if (currentMeaning.allMWEs) {
        const mweIdx = currentMWEIndex % currentMeaning.allMWEs.length;
        activeExamples = dedupeExamples(currentMeaning.allMWEs[mweIdx].examples || []);
    } else {
        activeExamples = dedupeExamples(currentMeaning.allExamples || []);
    }
    if (activeExamples.length > 0) {
        const exIdx = currentExampleIndex % activeExamples.length;
        const example = activeExamples[exIdx];
        targetSentence = example.target || example.spanish || '';
        englishSentence = example.english || '';
    } else {
        targetSentence = currentMeaning.targetSentence || '';
        englishSentence = currentMeaning.englishSentence || '';
    }

    if (!targetSentence) return;

    // Tokenize and resolve each word
    const tokens = tokenizeLyricLine(targetSentence);
    currentBreakdownResults = tokens.map(t => resolveToken(t));

    // Build modal HTML
    let html = `
        <div class="breakdown-header">
            <div class="target-line">${targetSentence}</div>
            <div class="english-line">${englishSentence}</div>
        </div>
    `;

    currentBreakdownResults.forEach((result, idx) => {
        if (!result.token.clean) return; // skip pure punctuation

        const inDeck = result.source === 'deck';
        const rowClass = 'breakdown-word-row' + (inDeck ? ' in-deck' : '');

        let translation = '';
        let pos = '';
        if (result.entry) {
            if (result.source === 'deck') {
                // Flashcard object
                translation = result.entry.meanings?.[0]?.meaning || result.entry.translation || '';
                pos = result.entry.meanings?.[0]?.pos || '';
            } else {
                // Raw vocab entry
                translation = result.entry.meanings?.[0]?.translation || '';
                pos = result.entry.meanings?.[0]?.pos || '';
            }
        }

        const posClass = pos ? getPosColorClass(pos) : '';
        const posHTML = pos ? `<span class="word-pos card-pos ${posClass}">${pos}</span>` : '';

        html += `
            <div class="${rowClass}" onclick="showWordPopup(event, ${idx})">
                <span class="word-spanish">${result.token.clean}</span>
                <span class="word-translation">${translation || '<span style="opacity:0.4;">—</span>'}</span>
                ${posHTML}
            </div>
        `;
    });

    document.getElementById('lyricBreakdownBody').innerHTML = html;
    document.getElementById('lyricBreakdownModal').classList.remove('hidden');
}

function hideLyricBreakdown() {
    document.getElementById('lyricBreakdownModal').classList.add('hidden');
    hideWordPopup();
}

function hideWordPopup() {
    document.getElementById('wordPopup').classList.add('hidden');
}

function showWordPopup(event, tokenIndex) {
    event.stopPropagation();

    const result = currentBreakdownResults[tokenIndex];
    if (!result || !result.entry) return;

    const popup = document.getElementById('wordPopup');
    const inDeck = result.source === 'deck';

    let word, translation, pos, corpusCount;
    if (inDeck) {
        word = result.entry.targetWord;
        translation = result.entry.meanings?.[0]?.meaning || result.entry.translation || '';
        pos = result.entry.meanings?.[0]?.pos || '';
        corpusCount = result.entry.corpusCount;
    } else {
        word = result.entry.word;
        translation = result.entry.meanings?.[0]?.translation || '';
        pos = result.entry.meanings?.[0]?.pos || '';
        corpusCount = result.entry.corpus_count || null;
    }

    let html = `<div class="popup-word">${word}</div>`;
    html += `<div class="popup-translation">${translation || '—'}</div>`;
    if (pos) html += `<div class="popup-detail">POS: ${pos}</div>`;
    if (corpusCount) html += `<div class="popup-detail">Corpus count: ${corpusCount}</div>`;

    if (inDeck) {
        html += `<button class="popup-go-btn" onclick="navigateToCard(${result.deckIndex})">Go to card \u2192</button>`;
    } else if (result.entry) {
        html += `<button class="popup-go-btn" onclick="navigateToVocabCard(${tokenIndex})">Go to card \u2192</button>`;
    }

    popup.innerHTML = html;
    popup.classList.remove('hidden');

    // Position near the clicked row
    const rect = event.currentTarget.getBoundingClientRect();
    const popupWidth = 260;
    let left = rect.right + 8;
    let top = rect.top;

    // If would overflow right, put it to the left
    if (left + popupWidth > window.innerWidth) {
        left = rect.left - popupWidth - 8;
    }
    // If would overflow left, center below
    if (left < 8) {
        left = Math.max(8, (rect.left + rect.right) / 2 - popupWidth / 2);
        top = rect.bottom + 8;
    }
    // Clamp to viewport
    top = Math.max(8, Math.min(top, window.innerHeight - 250));

    popup.style.left = left + 'px';
    popup.style.top = top + 'px';

    // Dismiss on next click anywhere
    setTimeout(() => {
        document.addEventListener('click', function dismiss(e) {
            if (!popup.contains(e.target)) {
                hideWordPopup();
            }
            document.removeEventListener('click', dismiss);
        });
    }, 0);
}

// --- Card Navigation Stack ---

function navigateToCard(targetIndex) {
    // Cap at 1 level deep
    if (cardNavStack.length > 0) return;

    // Push current position onto stack
    cardNavStack.push({
        index: currentIndex,
        meaningIndex: currentMeaningIndex,
        exampleIndex: currentExampleIndex,
        mweIndex: currentMWEIndex,
        tempCard: false
    });

    // Close breakdown modal and popup
    hideLyricBreakdown();

    // Navigate to target card
    currentIndex = targetIndex;
    currentMeaningIndex = 0;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    document.getElementById('flashcard').classList.remove('flipped');
    updateCard();
}

function navigateToVocabCard(tokenIndex) {
    // Cap at 1 level deep
    if (cardNavStack.length > 0) return;

    const result = currentBreakdownResults[tokenIndex];
    if (!result || !result.entry) return;

    const vocabEntry = result.entry;

    // Build a temporary flashcard object from the vocab entry
    const langConfig = config.languages[selectedLanguage] || {};
    const exampleTargetField = langConfig.exampleTargetField || 'example_spanish';
    const exampleEnglishField = langConfig.exampleEnglishField || 'example_english';

    // Merge cached examples (sense, MWE, sense-cycle) before synthesis so
    // the MWE pill has lyric lines to render.
    const examplesData = window._cachedExamplesData;
    if (examplesData && examplesData[vocabEntry.id]) {
        const cached = examplesData[vocabEntry.id];
        if (cached.m && Array.isArray(vocabEntry.meanings)) {
            vocabEntry.meanings.forEach((m, i) => {
                if (!m.examples || m.examples.length === 0) {
                    m.examples = cached.m[i] || [];
                }
            });
        }
        if (cached.w && Array.isArray(vocabEntry.mwe_memberships)) {
            vocabEntry.mwe_memberships.forEach((mwe, i) => {
                if (!mwe.examples || mwe.examples.length === 0) {
                    mwe.examples = cached.w[i] || [];
                }
            });
        }
        if (cached.s && Array.isArray(vocabEntry.sense_cycles)) {
            vocabEntry.sense_cycles.forEach((sc, i) => {
                if (!sc.examples || sc.examples.length === 0) {
                    sc.examples = cached.s[i] || [];
                }
            });
        }
    }

    const meanings = (vocabEntry.meanings || []).map(m => {
        const ex = getExampleFromMeaning(m, exampleTargetField, exampleEnglishField);
        return {
            pos: m.pos,
            meaning: m.translation,
            percentage: parseFloat(m.frequency) || 0,
            targetSentence: ex.targetSentence,
            englishSentence: ex.englishSentence,
            allExamples: ex.allExamples
        };
    });

    // Synthesize MWE / CLITIC / SENSE_CYCLE meanings, mirroring
    // loadVocabularyData. The popup paths previously skipped this and so
    // never showed MWEs on cards reached via lyric-token click-through.
    if (typeof window.synthesizeSpecialMeanings === 'function') {
        window.synthesizeSpecialMeanings(vocabEntry, meanings);
    }

    const firstExample = meanings.length > 0 ? { targetSentence: meanings[0].targetSentence, englishSentence: meanings[0].englishSentence } : { targetSentence: '', englishSentence: '' };

    const tempCard = {
        targetWord: vocabEntry.word,
        lemma: vocabEntry.lemma || '',
        id: vocabEntry.id || '0000',
        fullId: getWordId(vocabEntry),
        rank: vocabEntry.rank || 0,
        corpusCount: vocabEntry.corpus_count || null,
        meanings: meanings,
        translation: meanings.length > 0 ? meanings[0].meaning : '',
        targetSentence: firstExample.targetSentence,
        englishSentence: firstExample.englishSentence,
        links: generateLinks(vocabEntry.word, vocabEntry.lemma || vocabEntry.word, langConfig.referenceLinks || {}),
        isMultiMeaning: true
    };

    // Append temp card to end of flashcards array
    const tempIndex = flashcards.length;
    flashcards.push(tempCard);

    // Push current position onto stack, mark as having a temp card
    cardNavStack.push({
        index: currentIndex,
        meaningIndex: currentMeaningIndex,
        exampleIndex: currentExampleIndex,
        mweIndex: currentMWEIndex,
        tempCard: true,
        tempIndex: tempIndex
    });

    // Close breakdown modal and popup
    hideLyricBreakdown();

    // Navigate to temp card
    currentIndex = tempIndex;
    currentMeaningIndex = 0;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    document.getElementById('flashcard').classList.remove('flipped');
    updateCard();
}

// Open a single vocab card as a popup (used by the find-word search and
// the synonyms panel's tap-to-jump). Pushes the current position onto
// cardNavStack so navigateBack returns to the previous state. Works
// whether or not a deck is currently loaded.
//
// opts.reopenSearchOnBack — when true (default for find-word callers),
// hitting back reopens the find-word search modal. The synonyms panel
// passes false so back returns straight to the originating card.
async function popupFoundWord(entry, opts) {
    if (!entry || !entry.id) return;
    opts = opts || {};
    const reopenSearchOnBack = opts.reopenSearchOnBack !== false;
    const startFlipped = opts.startFlipped === true;

    // Look up the full vocab entry by ID from cached vocab data.
    const vocabSource = (activeArtist && window._cachedMergedIndex)
        ? window._cachedMergedIndex
        : window._cachedJoinedIndex;
    if (!vocabSource) {
        console.warn('popupFoundWord: no cached vocab index available');
        return;
    }
    const vocabEntry = vocabSource.find(it => it.id === entry.id);
    if (!vocabEntry) {
        console.warn('popupFoundWord: entry not found in cached index', entry.id);
        return;
    }

    const langConfig = (config && config.languages && config.languages[selectedLanguage]) || {};

    // Lazy-load examples file if needed and merge into the entry's meanings.
    if (langConfig.examplesPath && !window._cachedExamplesData) {
        try {
            const r = await fetch(langConfig.examplesPath);
            if (r.ok) window._cachedExamplesData = await r.json();
        } catch (e) {
            console.warn('popupFoundWord: failed to fetch examples', e);
        }
    }
    const examplesData = window._cachedExamplesData;
    if (examplesData && examplesData[vocabEntry.id]) {
        const ex = examplesData[vocabEntry.id];
        if (ex.m && Array.isArray(vocabEntry.meanings)) {
            vocabEntry.meanings.forEach((m, i) => {
                if (!m.examples || m.examples.length === 0) {
                    m.examples = ex.m[i] || [];
                }
            });
        }
        // Mirror loadVocabularyData's merge of "w" (MWE examples) and "s"
        // (sense-cycle examples) so the special-meaning synthesis below
        // has examples to render. Without this, MWE pills would render
        // empty even though mwe_memberships is populated.
        if (ex.w && Array.isArray(vocabEntry.mwe_memberships)) {
            vocabEntry.mwe_memberships.forEach((mwe, i) => {
                if (!mwe.examples || mwe.examples.length === 0) {
                    mwe.examples = ex.w[i] || [];
                }
            });
        }
        if (ex.s && Array.isArray(vocabEntry.sense_cycles)) {
            vocabEntry.sense_cycles.forEach((sc, i) => {
                if (!sc.examples || sc.examples.length === 0) {
                    sc.examples = ex.s[i] || [];
                }
            });
        }
    }

    // Build the temp card from the entry (mirrors navigateToVocabCard).
    const exampleTargetField = langConfig.exampleTargetField || 'example_spanish';
    const exampleEnglishField = langConfig.exampleEnglishField || 'example_english';

    const meanings = (vocabEntry.meanings || []).map(m => {
        const ex = getExampleFromMeaning(m, exampleTargetField, exampleEnglishField);
        const meaning = {
            pos: m.pos,
            meaning: m.translation,
            percentage: parseFloat(m.frequency) || 0,
            targetSentence: ex.targetSentence,
            englishSentence: ex.englishSentence,
            allExamples: ex.allExamples
        };
        if (m.unassigned) meaning.unassigned = true;
        if (m.assignment_method) meaning.assignment_method = m.assignment_method;
        if (m.source) meaning.source = m.source;
        if (m.context) meaning.context = m.context;
        if (m.allSenses) meaning.allSenses = m.allSenses;
        if (m.cycle_pos) meaning.cycle_pos = m.cycle_pos;
        return meaning;
    });

    // Synthesize MWE / CLITIC / SENSE_CYCLE meanings — without this the
    // popup would show only sense pills, hiding all MWEs (including
    // curated ones like "no te hagas") that the deck-flow path renders.
    if (typeof window.synthesizeSpecialMeanings === 'function') {
        window.synthesizeSpecialMeanings(vocabEntry, meanings);
    }

    const firstExample = meanings.length > 0
        ? { targetSentence: meanings[0].targetSentence, englishSentence: meanings[0].englishSentence }
        : { targetSentence: '', englishSentence: '' };

    const tempCard = {
        targetWord: vocabEntry.word,
        lemma: vocabEntry.lemma || '',
        id: vocabEntry.id || '0000',
        fullId: getWordId(vocabEntry),
        rank: vocabEntry.rank || 0,
        corpusCount: vocabEntry.corpus_count || null,
        meanings: meanings,
        translation: meanings.length > 0 ? meanings[0].meaning : '',
        targetSentence: firstExample.targetSentence,
        englishSentence: firstExample.englishSentence,
        links: generateLinks(vocabEntry.word, vocabEntry.lemma || vocabEntry.word, langConfig.referenceLinks || {}),
        isMultiMeaning: true,
        variants: vocabEntry.variants || null,
        homographIds: vocabEntry.homograph_ids || null,
        morphology: vocabEntry.morphology || null,
        relatedLemma: vocabEntry.related_lemma || null
    };

    // Hide the search modal while the card is being viewed.
    const findModal = document.getElementById('findWordModal');
    if (findModal) findModal.classList.add('hidden');

    const noDeckLoaded = !flashcards || flashcards.length === 0;
    const wasOnSetup = !document.getElementById('setupPanel').classList.contains('hidden');

    if (noDeckLoaded) {
        // No deck — build a one-card temp deck and show the app panel.
        cardNavStack.push({
            popupOnly: true,
            wasOnSetup: wasOnSetup,
            reopenSearchOnBack: reopenSearchOnBack
        });
        flashcards.length = 0;
        flashcards.push(tempCard);
        currentIndex = 0;
        currentMeaningIndex = 0;
        currentExampleIndex = 0;
        currentMWEIndex = 0;
        document.getElementById('setupPanel').classList.add('hidden');
        document.getElementById('appContent').classList.remove('hidden');
        showFloatingBtns(true);
        const fc = document.getElementById('flashcard');
        if (startFlipped) fc.classList.add('flipped'); else fc.classList.remove('flipped');
        initializeApp();
    } else {
        // Deck loaded — append temp card and push current position onto nav stack.
        const tempIndex = flashcards.length;
        flashcards.push(tempCard);
        cardNavStack.push({
            index: currentIndex,
            meaningIndex: currentMeaningIndex,
            exampleIndex: currentExampleIndex,
            mweIndex: currentMWEIndex,
            tempCard: true,
            tempIndex: tempIndex,
            reopenSearchOnBack: reopenSearchOnBack
        });
        currentIndex = tempIndex;
        currentMeaningIndex = 0;
        currentExampleIndex = 0;
        currentMWEIndex = 0;
        const fc = document.getElementById('flashcard');
        if (startFlipped) fc.classList.add('flipped'); else fc.classList.remove('flipped');
        updateCard();
    }
}

function navigateBack() {
    if (cardNavStack.length === 0) {
        goBackToSetup();
        return;
    }

    const prev = cardNavStack.pop();

    // Popup-only state: no deck was loaded when the temp card was opened.
    // Tear down the temp deck and restore the setup panel.
    if (prev.popupOnly) {
        flashcards.length = 0;
        currentIndex = 0;
        currentMeaningIndex = 0;
        currentExampleIndex = 0;
        currentMWEIndex = 0;
        if (prev.wasOnSetup) {
            document.getElementById('appContent').classList.add('hidden');
            document.getElementById('setupPanel').classList.remove('hidden');
            showFloatingBtns(false);
        }
        if (prev.reopenSearchOnBack) {
            const modal = document.getElementById('findWordModal');
            if (modal) modal.classList.remove('hidden');
            setTimeout(() => {
                const input = document.getElementById('findWordInput');
                if (input) input.focus();
            }, 50);
        }
        return;
    }

    // Remove temp card if one was created
    if (prev.tempCard && prev.tempIndex !== undefined) {
        flashcards.splice(prev.tempIndex, 1);
    }

    currentIndex = prev.index;
    currentMeaningIndex = prev.meaningIndex;
    currentExampleIndex = prev.exampleIndex;
    currentMWEIndex = prev.mweIndex || 0;
    document.getElementById('flashcard').classList.remove('flipped');
    updateCard();

    if (prev.reopenSearchOnBack) {
        const modal = document.getElementById('findWordModal');
        if (modal) modal.classList.remove('hidden');
        setTimeout(() => {
            const input = document.getElementById('findWordInput');
            if (input) input.focus();
        }, 50);
    }
}

// ---------------------------------------------------------------------------
// Homograph peek
// ---------------------------------------------------------------------------

function peekHomograph(siblingId) {
    if (cardNavStack.length > 0) return;

    const lookup = getVocabByIdLookup();
    const vocabEntry = lookup.get(siblingId);
    if (!vocabEntry) return;

    // Attach examples from cached examples data (they aren't on cachedVocabularyData entries)
    const examplesData = window._cachedExamplesData;
    if (examplesData && examplesData[siblingId]) {
        const ex = examplesData[siblingId];
        (vocabEntry.meanings || []).forEach((m, i) => {
            if (!m.examples || m.examples.length === 0) {
                m.examples = ex.m[i] || [];
            }
        });
    }

    const langConfig = config.languages[selectedLanguage] || {};
    const exampleTargetField = langConfig.exampleTargetField || 'example_spanish';
    const exampleEnglishField = langConfig.exampleEnglishField || 'example_english';

    const meanings = (vocabEntry.meanings || []).map(m => {
        const ex = getExampleFromMeaning(m, exampleTargetField, exampleEnglishField);
        return {
            pos: m.pos,
            meaning: m.translation,
            percentage: parseFloat(m.frequency) || 0,
            targetSentence: ex.targetSentence,
            englishSentence: ex.englishSentence,
            allExamples: ex.allExamples
        };
    });

    const firstExample = meanings.length > 0
        ? { targetSentence: meanings[0].targetSentence, englishSentence: meanings[0].englishSentence }
        : { targetSentence: '', englishSentence: '' };

    const tempCard = {
        targetWord: vocabEntry.word,
        lemma: vocabEntry.lemma || '',
        id: vocabEntry.id || '0000',
        fullId: getWordId(vocabEntry),
        rank: vocabEntry.rank || 0,
        corpusCount: vocabEntry.corpus_count || null,
        meanings: meanings,
        translation: meanings.length > 0 ? meanings[0].meaning : '',
        targetSentence: firstExample.targetSentence,
        englishSentence: firstExample.englishSentence,
        links: generateLinks(vocabEntry.word, vocabEntry.lemma || vocabEntry.word, langConfig.referenceLinks || {}),
        isMultiMeaning: true,
        homographIds: vocabEntry.homograph_ids || null,
        isPeekCard: true
    };

    const tempIndex = flashcards.length;
    flashcards.push(tempCard);

    cardNavStack.push({
        index: currentIndex,
        meaningIndex: currentMeaningIndex,
        exampleIndex: currentExampleIndex,
        mweIndex: currentMWEIndex,
        tempCard: true,
        tempIndex: tempIndex
    });

    currentIndex = tempIndex;
    currentMeaningIndex = 0;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    document.getElementById('flashcard').classList.remove('flipped');
    updateCard();
}
window.peekHomograph = peekHomograph;

// ---------------------------------------------------------------------------
// Conjugation table rendering
// ---------------------------------------------------------------------------
const CONJ_PRONOUNS_FULL = ['yo', 'tú', 'él / ella', 'nosotros', 'vosotros', 'ellos / ellas'];

// Tense → mood mapping. Tenses we currently ship are just the first six;
// the Imperative + compound entries are scaffolded so future data slots in
// without a renderer change. Unknown tenses fall under "Other".
//
// Mood keys are display labels (English). Tense keys must match the Spanish
// labels in `conjEntry.tenses` (the conjugation data is keyed by Spanish
// tense names from verbecc). `CONJ_TENSE_DISPLAY` below maps each Spanish
// key to a short English label for the toggle buttons.
const CONJ_MOOD_GROUPS = {
    'Indicative': {
        tenses: ['Presente', 'Pretérito', 'Imperfecto', 'Futuro', 'Condicional'],
        accent: 'rgba(74, 158, 255, 0.6)',   // blue
    },
    'Subjunctive': {
        tenses: ['Subj. Presente', 'Subj. Imperfecto', 'Subj. Futuro'],
        accent: 'rgba(168, 85, 247, 0.6)',   // purple
    },
    'Imperative': {
        tenses: ['Imperativo', 'Imp. Negativo'],
        accent: 'rgba(236, 72, 153, 0.6)',   // pink
    },
};
const CONJ_MOOD_ORDER = ['Indicative', 'Subjunctive', 'Imperative'];

const CONJ_TENSE_DISPLAY = {
    'Presente': 'pres',
    'Pretérito': 'pret',
    'Imperfecto': 'imperf',
    'Futuro': 'fut',
    'Condicional': 'cond',
    'Subj. Presente': 'pres',
    'Subj. Imperfecto': 'imperf',
    'Subj. Futuro': 'fut',
    'Imperativo': 'affirm',
    'Imp. Negativo': 'neg',
};

// Split a form into (stem, ending) using longest-common-prefix vs the
// infinitive's STEM (infinitive minus the -ar/-er/-ir ending). For regular
// verbs this gives the expected pattern ("habl|o", "habl|as", "habl|a"...).
// For stem-changing irregulars the shared prefix stops earlier, so more
// of the word lands in the accent-colored "ending" span — which surfaces
// the stem change (e.g. "t|engo" from "tener", showing only the "t" as
// the preserved stem).
//
// Using the full infinitive as the reference was wrong: the "a" in the
// middle of "hablar" matched the "a" ending of "habla", stealing it into
// the stem.
function splitStemEnding(form, infinitive) {
    if (!form) return { stem: '', ending: '' };
    const src = (infinitive || '').toLowerCase();
    const dst = form.toLowerCase();
    // Spanish infinitives always end in -ar / -er / -ir. Strip those two
    // chars to get the stem reference; fall back to the full infinitive if
    // it's shorter than 2 chars (defensive — shouldn't happen in practice).
    const stemLen = src.length >= 2 ? src.length - 2 : src.length;
    let i = 0;
    while (i < stemLen && i < dst.length && src[i] === dst[i]) i++;
    return { stem: form.slice(0, i), ending: form.slice(i) };
}

function buildConjugationTableHTML(conjEntry, targetWord, lemma, opts) {
    opts = opts || {};
    const relatedLemma = opts.relatedLemma || null;
    const isRelatedParadigm = !!opts.isRelatedParadigm;

    // No inline data (conjEntry absent or empty): render a small
    // "no-data" panel with the card's own lemma + a prominent SpanishDict
    // link. If the card has a `relatedLemma` pointer (SpanishDict flagged
    // it as a conjugation of another verb), surface that relationship so
    // the user knows where to go for the paradigm.
    const hasData = conjEntry && Object.keys(conjEntry.tenses || {}).length > 0;
    if (!hasData) {
        const displayLemma = (lemma || targetWord || '').toLowerCase();
        const sdTarget = relatedLemma || displayLemma;
        const sdUrl = `https://www.spanishdict.com/conjugate/${encodeURIComponent(sdTarget)}`;
        const emptyMsg = relatedLemma
            ? `<strong>${displayLemma}</strong> is a lexicalised form related to <strong>${relatedLemma}</strong>. We don't have its conjugation inline.`
            : `No conjugation data available for this verb.`;
        const sdLabel = relatedLemma
            ? `Conjugate ${relatedLemma} on SpanishDict`
            : `Conjugate on SpanishDict`;
        return `
            <div id="conjugationTable" class="conjugation-panel">
                <button class="conj-close-btn" onclick="toggleConjugationTable()" aria-label="Close">&times;</button>
                <div class="conj-header">
                    <div class="conj-title">
                        <span class="conj-infinitive">${displayLemma}</span>
                    </div>
                </div>
                <div class="conj-empty-msg">
                    ${emptyMsg}
                </div>
                <a href="${sdUrl}" target="_blank" class="conj-sd-link conj-sd-link-prominent" title="${sdLabel}">
                    <img src="https://www.google.com/s2/favicons?domain=spanishdict.com&sz=64" width="18" height="18" alt="" style="border-radius:3px">
                    <span>${sdLabel}</span>
                </a>
            </div>
        `;
    }
    const tenses = conjEntry.tenses;
    const tenseNames = Object.keys(tenses);
    const targetLower = targetWord.toLowerCase();
    // Prefer an explicit infinitive on the conj entry; fall back to
    // the lemma (or relatedLemma when we're rendering a related
    // verb's paradigm), then targetWord as a last resort.
    const conjOwnerLemma = isRelatedParadigm ? (relatedLemma || lemma || targetWord || '') : (lemma || targetWord || '');
    const infinitive = (conjEntry.infinitive || conjOwnerLemma).toLowerCase();

    // Pick the tense containing targetWord as the default; Presente otherwise.
    let defaultTense = tenses['Presente'] ? 'Presente' : tenseNames[0];
    for (const [tenseName, forms] of Object.entries(tenses)) {
        if (forms.some(f => f.toLowerCase() === targetLower)) {
            defaultTense = tenseName;
            break;
        }
    }

    // Group tenses by mood (Indicativo / Subjuntivo / Imperativo / Otras).
    // Tenses not covered by the known groups slot under "Otras" so the UI
    // never drops data on the floor.
    const grouped = [];
    const seen = new Set();
    for (const moodName of CONJ_MOOD_ORDER) {
        const cfg = CONJ_MOOD_GROUPS[moodName];
        const present = cfg.tenses.filter(t => tenses[t]);
        if (!present.length) continue;
        grouped.push({ mood: moodName, accent: cfg.accent, tenses: present });
        present.forEach(t => seen.add(t));
    }
    const orphanTenses = tenseNames.filter(t => !seen.has(t));
    if (orphanTenses.length) {
        grouped.push({ mood: 'Other', accent: 'rgba(255,255,255,0.3)', tenses: orphanTenses });
    }

    // The mood that owns the default tense is the one we open on.
    const defaultMood = (grouped.find(g => g.tenses.includes(defaultTense)) || grouped[0] || {}).mood;

    // Mood toggle — segmented control, rendered only when more than one
    // mood is present. When there's just one (e.g. only Indicativo tenses
    // shipped), the toggle is redundant and hidden.
    const moodToggleHTML = grouped.length > 1 ? `
        <div class="conj-mood-toggle">
            ${grouped.map(g => {
                const active = g.mood === defaultMood ? ' conj-mood-toggle-active' : '';
                return `<button class="conj-mood-toggle-btn${active}" data-mood="${g.mood}" style="--mood-accent: ${g.accent};" onclick="switchConjMood('${g.mood}')">${g.mood}</button>`;
            }).join('')}
        </div>` : '';

    // One tense-toggle row per mood; only the active mood's row is
    // visible (display toggled by switchConjMood). This keeps the tense
    // list to a single horizontal row instead of stacking a label +
    // buttons for every mood.
    //
    // The hide-inactive-rows logic merges into one style attribute:
    // putting `display:none` in a second `style` silently drops it
    // (browsers take the first `style` attribute only), which is why
    // subjunctive tenses were showing at initial render.
    const tenseToggleHTML = grouped.map(g => {
        const isActiveMood = g.mood === defaultMood;
        const styleStr = `--mood-accent: ${g.accent};${isActiveMood ? '' : ' display: none;'}`;
        const btns = g.tenses.map(t => {
            const active = t === defaultTense ? ' conj-tense-active' : '';
            const display = CONJ_TENSE_DISPLAY[t] || t;
            return `<button class="conj-tense-btn${active}" data-tense="${t}" onclick="switchConjTense('${t}')">${display}</button>`;
        }).join('');
        return `<div class="conj-tense-toggle" data-mood="${g.mood}" style="${styleStr}">${btns}</div>`;
    }).join('');

    // Per-tense table. Each form is split stem/ending so the pattern pops.
    let tenseTables = '';
    for (const [tenseName, forms] of Object.entries(tenses)) {
        const hidden = tenseName !== defaultTense ? ' style="display:none"' : '';
        let rows = '';
        for (let i = 0; i < forms.length; i++) {
            const form = forms[i];
            const isActive = form.toLowerCase() === targetLower;
            const cls = isActive ? ' conj-active' : '';
            const { stem, ending } = splitStemEnding(form, infinitive);
            // Stem is muted; ending is accent-colored — makes regular
            // patterns rhyme and irregular stems stand out.
            const formHTML = stem
                ? `<span class="conj-stem">${stem}</span><span class="conj-ending">${ending}</span>`
                : `<span class="conj-ending conj-ending-full">${ending}</span>`;
            rows += `<tr class="${cls}"><td class="conj-pronoun">${CONJ_PRONOUNS_FULL[i]}</td><td class="conj-form">${formHTML}</td></tr>`;
        }
        tenseTables += `<table class="conj-table" data-tense="${tenseName}"${hidden}>${rows}</table>`;
    }

    // --- Header block ---
    // Infinitive + translation on top; -ar/-er/-ir type badge on the right;
    // non-finite forms (gerund + past participle) pinned underneath so
    // they're visible regardless of which tense is currently showing.
    const infEnd = infinitive.slice(-2).toUpperCase();
    const typeBadge = ['AR', 'ER', 'IR'].includes(infEnd)
        ? `<span class="conj-type-badge">-${infEnd}</span>`
        : '';
    const translation = conjEntry.translation || '';
    const gerActive = conjEntry.gerund && conjEntry.gerund.toLowerCase() === targetLower ? ' is-active' : '';
    const ppActive = conjEntry.past_participle && conjEntry.past_participle.toLowerCase() === targetLower ? ' is-active' : '';
    const nonFiniteHTML = (conjEntry.gerund || conjEntry.past_participle) ? `
        <div class="conj-nonfinite">
            ${conjEntry.gerund ? `<div class="conj-nf-item${gerActive}">
                <span class="conj-nf-label">gerund</span>
                <span class="conj-nf-form">${conjEntry.gerund}</span>
            </div>` : ''}
            ${conjEntry.past_participle ? `<div class="conj-nf-item${ppActive}">
                <span class="conj-nf-label">past participle</span>
                <span class="conj-nf-form">${conjEntry.past_participle}</span>
            </div>` : ''}
        </div>` : '';

    // Link to SpanishDict's full paradigm page — the in-app panel covers
    // the high-frequency tenses; this covers "I want to see every tense
    // incl. compound + imperative forms we don't ship locally".
    const sdUrl = `https://www.spanishdict.com/conjugate/${encodeURIComponent(infinitive)}`;
    const sdLinkHTML = `
        <a href="${sdUrl}" target="_blank" class="conj-sd-link" title="Full paradigm on SpanishDict">
            <img src="https://www.google.com/s2/favicons?domain=spanishdict.com&sz=64" width="16" height="16" alt="" style="border-radius:3px">
            <span>Full paradigm on SpanishDict</span>
        </a>`;

    // When we're rendering a related verb's paradigm (e.g. haber for a
    // hay card), add a note above the header so the user knows the
    // table isn't the card's own verb. Keeps the panel honest: the
    // paradigm belongs to the related verb, not the lexicalised word
    // on the card.
    const relatedNoteHTML = isRelatedParadigm && lemma && relatedLemma ? `
        <div class="conj-related-note">
            <strong>${lemma.toLowerCase()}</strong> is a lexicalised form related to <strong>${relatedLemma.toLowerCase()}</strong>. Showing <strong>${relatedLemma.toLowerCase()}</strong>'s full paradigm below.
        </div>` : '';

    return `
        <div id="conjugationTable" class="conjugation-panel">
            <button class="conj-close-btn" onclick="toggleConjugationTable()" aria-label="Close">&times;</button>
            ${relatedNoteHTML}
            <div class="conj-header">
                <div class="conj-title">
                    <span class="conj-infinitive">${infinitive}</span>
                    ${typeBadge}
                </div>
                ${translation ? `<div class="conj-translation">${translation}</div>` : ''}
                ${nonFiniteHTML}
            </div>
            ${moodToggleHTML}
            <div class="conj-tense-toggles">
                ${tenseToggleHTML}
            </div>
            <div class="conj-tables-wrap">
                ${tenseTables}
            </div>
            ${sdLinkHTML}
        </div>
    `;
}

function switchConjTense(tenseName) {
    const panel = document.getElementById('conjugationTable');
    if (!panel) return;
    // Match tables + buttons by data-tense (button text now has the
    // "Subj."/"Imp." prefix stripped for display under the mood label, so
    // text-based matching no longer works).
    panel.querySelectorAll('.conj-table').forEach(t => {
        t.style.display = t.dataset.tense === tenseName ? '' : 'none';
    });
    panel.querySelectorAll('.conj-tense-btn').forEach(b => {
        b.classList.toggle('conj-tense-active', b.dataset.tense === tenseName);
    });
}

function switchConjMood(moodName) {
    const panel = document.getElementById('conjugationTable');
    if (!panel) return;
    // Swap mood-toggle active state.
    panel.querySelectorAll('.conj-mood-toggle-btn').forEach(b => {
        b.classList.toggle('conj-mood-toggle-active', b.dataset.mood === moodName);
    });
    // Show only the active mood's tense-toggle row.
    panel.querySelectorAll('.conj-tense-toggle').forEach(t => {
        t.style.display = t.dataset.mood === moodName ? '' : 'none';
    });
    // Switch the visible tense to the mood's first (or already-active) one.
    const activeRow = panel.querySelector(`.conj-tense-toggle[data-mood="${moodName}"]`);
    if (activeRow) {
        const active = activeRow.querySelector('.conj-tense-active') || activeRow.querySelector('.conj-tense-btn');
        if (active) switchConjTense(active.dataset.tense);
    }
}
window.switchConjMood = switchConjMood;

function toggleConjugationTable() {
    const panel = document.getElementById('conjugationTable');
    if (panel) {
        panel.classList.toggle('visible');
    }
}

// Scan the cached vocab index for a card matching the given Spanish word.
// Matches surface or lemma, case-insensitive. Returns the entry's id or null.
// Used by the synonyms panel: tap-a-synonym should jump to its card if we
// have one, otherwise fall back to SpanishDict.
function findCardIdForWord(word) {
    const target = (word || '').toLowerCase();
    if (!target) return null;
    const source = (activeArtist && window._cachedMergedIndex)
        ? window._cachedMergedIndex
        : window._cachedJoinedIndex;
    if (!source) return null;
    for (const it of source) {
        const w = (it.word || it.targetWord || '').toLowerCase();
        const l = (it.lemma || '').toLowerCase();
        if (w === target || l === target) {
            return it.id || (window.getWordId ? window.getWordId(it) : null);
        }
    }
    return null;
}

function jumpToSynonym(word) {
    const id = findCardIdForWord(word);
    if (id && window.popupFoundWord) {
        // Close the panel before navigating so back-button returns cleanly.
        const panel = document.getElementById('synonymsPanel');
        if (panel) panel.classList.remove('visible');
        // reopenSearchOnBack: false — back should return to the originating
        // card, not pop up the find-word search modal.
        // startFlipped: true — synonyms panel lives on the back, so land on
        // the back of the new card (where ↩ lives) for continuity.
        window.popupFoundWord({ id }, { reopenSearchOnBack: false, startFlipped: true });
        return;
    }
    // No card available — open SpanishDict in a new tab.
    const url = `https://www.spanishdict.com/translate/${encodeURIComponent((word || '').toLowerCase())}`;
    window.open(url, '_blank', 'noopener');
}

function buildSynonymsPanelHTML(synonyms, antonyms, headword) {
    const headwordLower = (headword || '').toLowerCase();
    function renderItem(item) {
        const word = item && item.word ? item.word : '';
        if (!word) return '';
        const strength = item.strength === 2 ? 'syn-strong' : 'syn-weak';
        const inDeck = !!findCardIdForWord(word);
        const inDeckCls = inDeck ? ' syn-in-deck' : ' syn-external';
        const escaped = word.replace(/'/g, "\\'");
        const ctx = item.context ? `<span class="syn-context">${item.context}</span>` : '';
        return `<a class="syn-item ${strength}${inDeckCls}" href="javascript:void(0)" onclick="jumpToSynonym('${escaped}')">
            <span class="syn-word">${word}</span>${ctx}
        </a>`;
    }
    const synBlock = synonyms.length
        ? `<div class="syn-section">
                <div class="syn-section-title">Synonyms</div>
                <div class="syn-list">${synonyms.map(renderItem).join('')}</div>
            </div>`
        : '';
    const antBlock = antonyms.length
        ? `<div class="syn-section">
                <div class="syn-section-title">Antonyms</div>
                <div class="syn-list">${antonyms.map(renderItem).join('')}</div>
            </div>`
        : '';
    return `
        <div id="synonymsPanel" class="synonyms-panel">
            <button class="conj-close-btn" onclick="toggleSynonymsPanel()" aria-label="Close">&times;</button>
            <div class="conj-header">
                <div class="conj-title">
                    <span class="conj-infinitive">${headwordLower}</span>
                </div>
            </div>
            <div class="syn-body">
                ${synBlock}
                ${antBlock}
            </div>
        </div>
    `;
}

function toggleSynonymsPanel() {
    const panel = document.getElementById('synonymsPanel');
    if (panel) {
        panel.classList.toggle('visible');
    }
}

window.computeLinesUnderstood = computeLinesUnderstood;
window.loadSpanishRanks = loadSpanishRanks;
window.loadConjugationData = loadConjugationData;
window.loadConjugatedEnglishData = loadConjugatedEnglishData;
window.toggleConjugationTable = toggleConjugationTable;
window.toggleSynonymsPanel = toggleSynonymsPanel;
window.jumpToSynonym = jumpToSynonym;
window.switchConjTense = switchConjTense;
window.initializeApp = initializeApp;
window.setupSwipeGestures = setupSwipeGestures;
window.setupKeyboardShortcuts = setupKeyboardShortcuts;
window.handleSwipeAction = handleSwipeAction;
window.showEndOfDeckOptions = showEndOfDeckOptions;
window.hideDeckCompleteModal = hideDeckCompleteModal;
window.restartWithIncorrectCards = restartWithIncorrectCards;
window.restartAllCards = restartAllCards;
window.recordCardResult = recordCardResult;
window.showFloatingBtns = showFloatingBtns;
window.goBackToSetup = goBackToSetup;
window.updateCard = updateCard;
window.flipCard = flipCard;
window.cycleExample = cycleExample;
window.cycleExampleForward = cycleExampleForward;
window.cycleExampleBackward = cycleExampleBackward;
window.cycleMWEForward = cycleMWEForward;
window.cycleMWEBackward = cycleMWEBackward;
window.selectMeaning = selectMeaning;
window.selectGroup = selectGroup;
window.previousCard = previousCard;
window.nextCard = nextCard;
window.shuffleCards = shuffleCards;
window.flipDirection = flipDirection;
window.getPosColorClass = getPosColorClass;
window.updateReverseButton = updateReverseButton;
window.updateStats = updateStats;
window.showLyricBreakdown = showLyricBreakdown;
window.hideLyricBreakdown = hideLyricBreakdown;
window.showWordPopup = showWordPopup;
window.hideWordPopup = hideWordPopup;
window.navigateToCard = navigateToCard;
window.navigateToVocabCard = navigateToVocabCard;
window.navigateBack = navigateBack;
window.popupFoundWord = popupFoundWord;

// ---------------------------------------------------------------------------
// Card metadata popover button wiring — eager, button is in DOM from boot.
// The popover implementation lives in flashcards-modals.js; the lazy stub
// for window.toggleCardMetaPopover triggers the dynamic import on first
// click. Other popover handlers (close, outside-click, flag button) wire
// themselves at module-load time inside flashcards-modals.js — they only
// need to fire when the popover is open, which can only happen after the
// modals module has loaded.
// ---------------------------------------------------------------------------
(function _initCardMetaButton() {
    function attach() {
        const btn = document.getElementById('cardMetaBtn');
        if (!btn) return;
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            window.toggleCardMetaPopover();
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attach, { once: true });
    } else {
        attach();
    }
})();

// Delegated tap-to-expand for clamped meaning rows. One listener at the
// document root replaces the per-row addEventListener that updateCard()
// used to attach inside its post-render layout pass — saves ~5-15 listener
// registrations per card flip.
document.addEventListener('click', (e) => {
    const el = e.target.closest && e.target.closest('.meaning-row-translation.is-clamped');
    if (!el) return;
    e.stopPropagation();
    el.classList.remove('is-clamped');
    el.classList.add('is-expanded');
}, true);

// Keyboard-shortcut guide: collapse/expand with localStorage persistence.
(function _initKbGuideCollapse() {
    const LS_KEY = 'fluency.kbGuideCollapsed';
    function attach() {
        const guide = document.getElementById('desktopKeyboardGuide');
        const btn = document.getElementById('kbCollapseBtn');
        if (!guide || !btn) return;
        const setCollapsed = (collapsed) => {
            guide.classList.toggle('collapsed', collapsed);
            btn.title = collapsed ? 'Show shortcuts' : 'Hide shortcuts';
            btn.setAttribute('aria-label', btn.title);
            try { localStorage.setItem(LS_KEY, collapsed ? '1' : '0'); } catch (e) {}
        };
        let initial = false;
        try { initial = localStorage.getItem(LS_KEY) === '1'; } catch (e) {}
        setCollapsed(initial);
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            setCollapsed(!guide.classList.contains('collapsed'));
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attach, { once: true });
    } else {
        attach();
    }
})();

// ===========================================================================
// Lazy-load stubs for extras modules
// ===========================================================================
//
// flashcards-modals.js holds card-meta popover, lyric breakdown, POS popup,
// nav stack, homograph peek, and end-of-deck modal — all event-driven, none
// needed at boot. These stubs install on boot; the dynamic import resolves
// on first user interaction; the loaded module's top-level `window.X = X`
// overwrites each stub with the real function. Subsequent calls hit the
// real function directly.
//
// On rejection (e.g. transient network failure) the cached promise is nulled
// so the next click retries — a flaky cellular connection shouldn't lock
// the user out of card-meta for the session.
//
// The STUB symbol marker + post-resolve assertion catches the case where a
// name in the stub list isn't actually exported by the lazy module (typo /
// drift); without it, the stub would infinite-recurse into itself.

const ASSET_VERSION = '20260427i';

let _modalsModulePromise = null;
const lazyModals = () => _modalsModulePromise || (_modalsModulePromise =
    import('./flashcards-modals.js?v=' + ASSET_VERSION).catch(err => {
        _modalsModulePromise = null;
        throw err;
    }));

const STUB = Symbol('lazyStub');
const stubFor = (name, loader) => {
    const fn = (...args) => loader().then(() => {
        if (window[name] === fn) {
            console.error('Lazy module loaded but did not export', name);
            return;
        }
        return window[name](...args);
    }).catch(err => {
        console.error('Lazy load failed for', name, err);
    });
    fn[STUB] = true;
    window[name] = fn;
};

['toggleCardMetaPopover', 'showCardMetaPopover', 'hideCardMetaPopover',
 'showPOSInfo']
    .forEach(name => stubFor(name, lazyModals));

// Special: refreshCardMetaPopoverIfOpen runs on every updateCard(). If we
// triggered the lazy load on every card flip we'd defeat the lazy pattern.
// Instead, no-op when modals isn't loaded — the popover can't be open.
window.refreshCardMetaPopoverIfOpen = () => {
    if (_modalsModulePromise) {
        _modalsModulePromise.then(() => window.refreshCardMetaPopoverIfOpen());
    }
};
