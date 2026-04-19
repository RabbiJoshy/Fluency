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

function formatMorphMood(mood) {
    const moodMap = {
        indicativo: '',        // indicative is default, omit
        subjuntivo: 'subj',
        imperativo: 'imp',
        gerundio: 'ger',
        participio: 'part',
        participo: 'part',
        'participio-pasado': 'past part',
        condicional: 'cond',
        infinitivo: 'inf',
    };
    return moodMap[mood] || mood;
}

function formatMorphTense(tense) {
    const tenseMap = {
        presente: 'pres',
        afirmativo: 'aff',
        negativo: 'neg',
        futuro: 'fut',
        'futuro-perfecto': 'fut perf',
        'pretérito-perfecto-simple': 'pret',
        'pretérito-imperfecto': 'imperf',
        'pretérito-imperfecto-1': 'imperf',
        'pretérito-imperfecto-2': 'imperf',
        'pretérito-perfecto': 'pres perf',
        'pretérito-pluscuamperfecto-1': 'pluperf',
        'pretérito-pluscuamperfecto-2': 'pluperf',
        infinitivo: 'inf',
        gerundio: 'ger',
        participo: 'part',
    };
    return tenseMap[tense] || tense;
}

function formatMorphPerson(person) {
    const personMap = {
        '1s': '1s',
        '2s': '2s',
        '3s': '3s',
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

    // Nav stack back button
    document.getElementById('navBackBtn').addEventListener('click', function(e) {
        e.stopPropagation();
        navigateBack();
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

    // Floating buttons (outside the card, for both mobile and desktop)
    document.getElementById('backBtnFloating').addEventListener('click', function(e) {
        e.stopPropagation();
        goBackToSetup();
    });
    document.getElementById('statsBtnFloating').addEventListener('click', function(e) {
        e.stopPropagation();
        showStatsModal();
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
        // Space = flip card
        else if (e.key === ' ') {
            e.preventDefault();
            flipCard();
        }
        // Escape = close modal or return to setup
        else if (e.key === 'Escape') {
            e.preventDefault();
            const deckModal = document.getElementById('deckCompleteModal');
            const statsModal = document.getElementById('statsModal');
            if (deckModal && !deckModal.classList.contains('hidden')) {
                hideDeckCompleteModal();
            } else if (statsModal && !statsModal.classList.contains('hidden')) {
                hideStatsModal();
            } else {
                goBackToSetup();
            }
        }
    });
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
    return kept.map(e => e[0]).join(' | ');
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
        frontWordEl.textContent = frontText;
        // Auto-shrink the word font for long strings so they don't overflow
        // or wrap awkwardly. Applies to any long displayed text (variant
        // display OR plain long words like "encantadísimo"), not just
        // variant strings. word-break in CSS is the final safety net.
        const displayedLen = (frontText || '').length;
        if (!isFlipped && displayedLen > 13) {
            frontWordEl.style.fontSize = Math.max(32, 64 - (displayedLen - 12) * 2.2) + 'px';
        } else {
            frontWordEl.style.fontSize = '';
        }
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
            const displayMeaning = isMWE ? (cleanMweMeaning || '<span style="font-style: italic; opacity: 0.5;">Translation unavailable</span>') : m.meaning;
            if (isMWE) {
                // MWE row: expression in a light pill (same font size as translation), counter — no POS badge
                target.push(`
                <div class="meaning-row meaning-row-mwe" style="position: relative; display: flex; align-items: center; padding: 10px 15px; margin-bottom: 8px; background: ${bgColor}; ${borderStyle} border-radius: 8px; cursor: pointer; min-height: 44px;" onclick="selectMeaning(${idx})">
                    <span style="font-size: 12px; color: white; padding: 2px 8px; background: rgba(255,255,255,0.22); border-radius: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 120px; flex-shrink: 0;">${mweExpr}</span>
                    <span style="font-size: 14px; font-weight: 600; color: white; flex: 1; text-align: center;">${displayMeaning}</span>
                    ${mweCounter}
                </div>
                `);
            } else if (isClitic) {
                // Clitic row: form in a light pill, translation centered, cycling counter
                target.push(`
                <div class="meaning-row meaning-row-clitic" style="position: relative; display: flex; align-items: center; padding: 10px 15px; margin-bottom: 8px; background: ${bgColor}; ${borderStyle} border-radius: 8px; cursor: pointer; min-height: 44px;" onclick="selectMeaning(${idx})">
                    <span style="font-size: 12px; color: white; padding: 2px 8px; background: rgba(255,255,255,0.2); border-radius: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px; flex-shrink: 0;">${cliticForm}</span>
                    <span style="font-size: 14px; font-weight: 600; color: white; flex: 1; text-align: center;">${m.allClitics ? m.allClitics[cliticIdx].translation : ''}</span>
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
                const cyclePillStyle = 'font-size: 10px; padding: 4px 10px; margin: 0; white-space: nowrap;';
                target.push(`
                <div class="meaning-row meaning-row-cycle" style="display: grid; grid-template-columns: auto 1fr auto; align-items: center; padding: 6px 12px; margin-bottom: 6px; background: ${bgColor}; ${borderStyle} border-radius: 8px; cursor: pointer; min-height: 36px; opacity: 0.75;" onclick="selectMeaning(${idx})">
                    <span class="card-pos ${cyclePosClass}" style="${cyclePillStyle} justify-self: start;">${cyclePos}</span>
                    <span style="font-size: 13px; font-weight: 600; color: white; min-width: 0; text-align: center; line-height: 1.4; padding: 0 8px;">${isTruncated ? `<span class="sense-cycle-short">${joinedDisplay}</span><span class="sense-cycle-full" style="display:none">${joinedFull}</span>${ellipsisBtn}` : joinedDisplay}</span>
                    <span class="card-pos ${cyclePosClass}" style="${cyclePillStyle} justify-self: end; visibility: hidden; pointer-events: none;" aria-hidden="true">${cyclePos}</span>
                </div>
                `);
            } else {
                // Regular meaning row: POS pill in left grid column, translation centered in middle column.
                // A visibility:hidden mirror of the pill sits in col 3 so col widths auto-size together;
                // this keeps the body symmetrically centred without hard-coding a side-column width.
                const pctVal = Math.round(m.percentage * 100);
                const posPillInner = pctVal >= 100
                    ? `${m.pos}`
                    : `${m.pos} <span style="opacity: 0.6;">|</span> ${pctVal}%`;
                const pillStyleBase = 'font-size: 10px; padding: 4px 10px; margin: 0; white-space: nowrap;';
                const posPill = `<span class="card-pos ${posColorClass}" style="${pillStyleBase} justify-self: start;">${posPillInner}</span>`;
                const posPillMirror = `<span class="card-pos ${posColorClass}" style="${pillStyleBase} justify-self: end; visibility: hidden; pointer-events: none;" aria-hidden="true">${posPillInner}</span>`;
                // Inline context: rendered on the same line as the translation
                // in a smaller, dimmer typeface. Always full; a post-render
                // overflow check marks the row `.is-clamped` when the 3-line
                // clamp actually hides content, so it becomes tap-to-expand.
                let contextInline = '';
                if (m.context) {
                    const safeFull = String(m.context).replace(/"/g, '&quot;');
                    contextInline = ` <span class="meaning-context">· ${safeFull}</span>`;
                }
                target.push(`
                <div class="meaning-row meaning-row-regular" style="display: grid; grid-template-columns: auto 1fr auto; align-items: center; padding: 6px 12px; margin-bottom: 6px; background: ${bgColor}; ${borderStyle} border-radius: 8px; cursor: pointer; min-height: 36px;" onclick="selectMeaning(${idx})">
                    ${posPill}
                    <div class="meaning-row-body" style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-width: 0; padding: 0 8px;">
                        <span class="meaning-row-translation" style="font-size: 16px; font-weight: 600; color: ${textColor}; text-align: center;">${displayMeaning}${contextInline}</span>
                    </div>
                    ${posPillMirror}
                </div>
                `);
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
            } else {
                activeExamples = dedupeExamples(currentMeaning.allExamples || []);
            }

            // Dynamic re-sort: boost examples with deck/recently-wrong word overlap
            if (activeExamples.length > 1) {
                activeExamples = sortExamplesByRelevance(activeExamples);
            }

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
                const regex = new RegExp(`(?<![\\p{L}\\p{N}])(${escaped})(?![\\p{L}\\p{N}])`, 'giu');
                displayTargetSentence = displayTargetSentence.replace(regex,
                    `<span style="${pillStyle}">$1</span>`);
            } else {
                // Regular sense: highlight the target word (word boundaries for short words)
                const word = card.targetWord;
                const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const regex = new RegExp(`(?<![\\p{L}\\p{N}])(${escaped})(?![\\p{L}\\p{N}])`, 'giu');
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
                const dwRegex = new RegExp(`(?<![\\p{L}\\p{N}])(${dwEscaped})(?![\\p{L}\\p{N}])(?![^<]*>)`, 'giu');
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
                    const fragRegex = new RegExp(`(?<![\\p{L}\\p{N}])(${fragEscaped})(?![\\p{L}\\p{N}])(?![^<]*>)`, 'giu');
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
                    const re = new RegExp(escaped, 'i');
                    exampleAssigned = re.test(displayTargetSentence.replace(/<[^>]*>/g, ''));
                }
            }
            // Clitic: check if the clitic form appears in the example sentence
            if (currentMeaning && currentMeaning.allClitics && displayTargetSentence) {
                const activeClitic = currentMeaning.allClitics[currentMWEIndex % currentMeaning.allClitics.length];
                if (activeClitic && activeClitic.form) {
                    const escaped = activeClitic.form.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const re = new RegExp('(?<![\\p{L}])' + escaped + '(?![\\p{L}])', 'iu');
                    exampleAssigned = re.test(displayTargetSentence.replace(/<[^>]*>/g, ''));
                }
            }
            const sentenceStyle = exampleAssigned
                ? 'border: 3px solid var(--accent-primary); box-shadow: 0 0 10px rgba(var(--accent-primary-rgb), 0.25);'
                : 'border-color: transparent;';

            backHTML += `
                <div class="sentence" style="text-align: center; ${cursorStyle} ${sentenceStyle}" ${cycleHandler}>
                    <div class="breakdown-trigger" style="margin-bottom: 8px; cursor: pointer;" onclick="showLyricBreakdown(event); event.stopPropagation();" title="Tap for word-by-word breakdown">${displayTargetSentence}</div>
                    <div class="translation">${displayEnglishSentence}</div>
                    ${songNameDisplay}
                </div>
            `;
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

    // Reference links as icon buttons — real favicons via Google's proxy
    const linkIcons = {
        'spanishDict': `<img src="https://www.google.com/s2/favicons?domain=spanishdict.com&sz=64" width="40" height="40" alt="SpanishDict" style="border-radius:4px">`,
        'reverso': `<img src="https://www.google.com/s2/favicons?domain=reverso.net&sz=64" width="40" height="40" alt="Reverso" style="border-radius:4px">`,
        'conjugation': `<img src="https://www.google.com/s2/favicons?domain=spanishdict.com&sz=64" width="32" height="32" alt="Conjugate" style="border-radius:4px"><span style="font-size:9px;color:rgba(255,255,255,0.7);margin-left:2px">verb</span>`
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

    // Check for inline conjugation data
    const conjEntry = isVerb && _conjugationData ? _conjugationData[card.lemma] : null;

    backHTML += `<div class="links-section" id="linksSection">`;

    for (const [key, url] of Object.entries(card.links)) {
        if (key === 'wordReference') continue; // Skip wordReference
        // Skip conjugation link for non-verbs
        if (key === 'conjugation' && !isVerb) continue;
        // Replace external conjugation link with inline toggle when we have data
        if (key === 'conjugation' && conjEntry) {
            backHTML += `<button class="ref-icon-btn" title="Conjugation Table" onclick="toggleConjugationTable()">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/>
                </svg>
                <span style="font-size:9px;color:rgba(255,255,255,0.7);margin-left:2px">verb</span>
            </button>`;
            continue;
        }
        const icon = linkIcons[key];
        const title = linkTitles[key] || key;
        if (icon) {
            backHTML += `<a href="${url}" target="_blank" class="ref-icon-btn" title="${title}">${icon}</a>`;
        } else {
            backHTML += `<a href="${url}" target="_blank" class="link-btn">${title}</a>`;
        }
    }

    backHTML += `</div>`;

    // Conjugation table (hidden by default, toggled by button)
    if (conjEntry) {
        backHTML += buildConjugationTableHTML(conjEntry, card.targetWord);
    }

    document.getElementById('backContent').innerHTML = backHTML;

    // Post-render layout pass:
    //   1. Flag meaning rows whose translation+context actually overflows the
    //      3-line clamp so the span becomes tap-to-expand. We only flag what
    //      measures as clipped, not everything past an arbitrary char count.
    //   2. When the scroll region holds more than 3 rows, cap its max-height
    //      to the sum of the first 3 row heights so it scrolls rather than
    //      stealing vertical space from the example sentence below. Fewer
    //      rows -> no cap, the region keeps its current flex-fill behaviour.
    // Run synchronously — scrollHeight triggers reflow so the numbers are
    // valid without waiting for the next frame. We intentionally avoid
    // requestAnimationFrame here because rAF is paused in background tabs
    // and hidden iframes, which would leave the clamp state stale.
    {
        const backEl = document.getElementById('backContent');
        if (backEl) {
            backEl.querySelectorAll('.meaning-row-translation').forEach(el => {
                if (el.scrollHeight > el.clientHeight + 1) {
                    el.classList.add('is-clamped');
                    el.addEventListener('click', function(e) {
                        e.stopPropagation();
                        el.classList.remove('is-clamped');
                        el.classList.add('is-expanded');
                    }, { once: true });
                }
            });
            const scroll = backEl.querySelector('.meanings-scroll');
            if (scroll) {
                const rows = scroll.querySelectorAll('.meaning-row');
                if (rows.length > 3) {
                    let cap = 0;
                    for (let i = 0; i < 3; i++) cap += rows[i].offsetHeight + 8;
                    scroll.style.maxHeight = cap + 'px';
                } else {
                    scroll.style.maxHeight = '';
                }
            }
        }
    }

    // Toggle back button for nav stack
    const navBackBtn = document.getElementById('navBackBtn');
    if (navBackBtn) navBackBtn.classList.toggle('hidden', cardNavStack.length === 0);

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
    if (index === currentMeaningIndex) {
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

function previousCard() {
    if (currentIndex > 0) {
        currentIndex--;
        currentMeaningIndex = 0;
        currentExampleIndex = 0;
        currentMWEIndex = 0;
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

    if (isFlipped) {
        // English → Target language
        reverseBtn.innerHTML = `${englishFlag} → ${targetFlag}`;
        reverseBtn.title = `Reverse to ${config.languages[selectedLanguage]?.name || selectedLanguage} → English`;
    } else {
        // Target language → English (normal)
        reverseBtn.innerHTML = `${targetFlag} → ${englishFlag}`;
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

function navigateBack() {
    if (cardNavStack.length === 0) return;

    const prev = cardNavStack.pop();

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

function buildConjugationTableHTML(conjEntry, targetWord) {
    const tenses = conjEntry.tenses || {};
    const tenseNames = Object.keys(tenses);
    if (tenseNames.length === 0) return '';

    const targetLower = targetWord.toLowerCase();

    // Find which tense contains the target word (default to Presente)
    let defaultTense = 'Presente';
    for (const [tenseName, forms] of Object.entries(tenses)) {
        if (forms.some(f => f.toLowerCase() === targetLower)) {
            defaultTense = tenseName;
            break;
        }
    }

    // Build tense toggle buttons
    const tenseButtons = tenseNames.map(t => {
        const active = t === defaultTense ? ' conj-tense-active' : '';
        return `<button class="conj-tense-btn${active}" onclick="switchConjTense('${t}')">${t}</button>`;
    }).join('');

    // Build a table per tense (only default is visible)
    let tenseTables = '';
    for (const [tenseName, forms] of Object.entries(tenses)) {
        const hidden = tenseName !== defaultTense ? ' style="display:none"' : '';
        let rows = '';
        for (let i = 0; i < forms.length; i++) {
            const isActive = forms[i].toLowerCase() === targetLower;
            const cls = isActive ? ' conj-active' : '';
            rows += `<tr class="${cls}">
                <td class="conj-pronoun">${CONJ_PRONOUNS_FULL[i]}</td>
                <td class="conj-form">${forms[i]}</td>
            </tr>`;
        }
        tenseTables += `<table class="conj-table" data-tense="${tenseName}"${hidden}>${rows}</table>`;
    }

    // Gerund and participle at the bottom
    let extras = '';
    if (conjEntry.gerund) {
        const gActive = conjEntry.gerund.toLowerCase() === targetLower ? ' conj-active' : '';
        extras += `<div class="conj-extra-row${gActive}"><span class="conj-extra-label">Gerundio</span><span class="conj-extra-form">${conjEntry.gerund}</span></div>`;
    }
    if (conjEntry.past_participle) {
        const pActive = conjEntry.past_participle.toLowerCase() === targetLower ? ' conj-active' : '';
        extras += `<div class="conj-extra-row${pActive}"><span class="conj-extra-label">Participio</span><span class="conj-extra-form">${conjEntry.past_participle}</span></div>`;
    }

    return `
        <div id="conjugationTable" class="conjugation-panel">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <span style="font-size: 16px; font-weight: 700; color: var(--text-primary);">${conjEntry.translation || targetWord}</span>
                <button onclick="toggleConjugationTable()" style="background: none; border: none; color: var(--text-muted); font-size: 22px; cursor: pointer; padding: 4px 8px; line-height: 1;">&times;</button>
            </div>
            <div class="conj-tense-toggle">${tenseButtons}</div>
            ${tenseTables}
            ${extras ? `<div class="conj-extras-bottom">${extras}</div>` : ''}
        </div>
    `;
}

function switchConjTense(tenseName) {
    const panel = document.getElementById('conjugationTable');
    if (!panel) return;
    // Hide all tense tables, show the selected one
    panel.querySelectorAll('.conj-table').forEach(t => {
        t.style.display = t.dataset.tense === tenseName ? '' : 'none';
    });
    // Update active button
    panel.querySelectorAll('.conj-tense-btn').forEach(b => {
        b.classList.toggle('conj-tense-active', b.textContent === tenseName);
    });
}

function toggleConjugationTable() {
    const panel = document.getElementById('conjugationTable');
    if (panel) {
        panel.classList.toggle('visible');
    }
}

window.computeLinesUnderstood = computeLinesUnderstood;
window.loadSpanishRanks = loadSpanishRanks;
window.loadConjugationData = loadConjugationData;
window.toggleConjugationTable = toggleConjugationTable;
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

// ---------------------------------------------------------------------------
// Card metadata popover (debug info — per-sense source + per-example method)
// ---------------------------------------------------------------------------

function _escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
}

function _renderCardMetaBody(card) {
    if (!card) return '<div class="card-meta-empty">No card selected.</div>';
    const lines = [];
    const id = card.fullId || card.id || '';
    lines.push('<div class="card-meta-section">');
    lines.push('<dl class="card-meta-kv">');
    lines.push(`<dt>word</dt><dd>${_escapeHtml(card.targetWord || card.word || '')}</dd>`);
    if (card.lemma && card.lemma !== (card.targetWord || card.word)) {
        lines.push(`<dt>lemma</dt><dd>${_escapeHtml(card.lemma)}</dd>`);
    }
    if (id) lines.push(`<dt>id</dt><dd>${_escapeHtml(id)}</dd>`);
    if (card.rank) lines.push(`<dt>rank</dt><dd>${_escapeHtml(card.rank)}</dd>`);
    if (card.corpusCount != null) lines.push(`<dt>corpus</dt><dd>${_escapeHtml(card.corpusCount)}</dd>`);
    lines.push('</dl></div>');

    const meanings = card.meanings || [];
    lines.push('<div class="card-meta-section"><h4>Meanings</h4>');
    if (!meanings.length) {
        lines.push('<div class="card-meta-empty">No meanings.</div>');
    } else {
        lines.push('<ul class="card-meta-list">');
        meanings.forEach((m, i) => {
            const isCurrent = (typeof currentMeaningIndex === 'number' && i === currentMeaningIndex);
            const tags = [];
            if (m.source) tags.push(`<span class="card-meta-tag source">src: ${_escapeHtml(m.source)}</span>`);
            if (m.assignment_method) tags.push(`<span class="card-meta-tag method">m: ${_escapeHtml(m.assignment_method)}</span>`);
            if (m.unassigned) tags.push('<span class="card-meta-tag flag">unassigned</span>');
            if (m.pos === 'SENSE_CYCLE') tags.push('<span class="card-meta-tag flag">SENSE_CYCLE</span>');
            const pctText = (typeof m.percentage === 'number') ? (m.percentage * 100).toFixed(0) + '%' : '';
            const label = `${_escapeHtml(m.pos || '?')} · ${_escapeHtml(m.meaning || m.translation || '')}${pctText ? ' · ' + pctText : ''}`;
            lines.push(`<li${isCurrent ? ' class="card-meta-current"' : ''}>${label}<div>${tags.join(' ') || '<span class="card-meta-empty">no tags</span>'}</div></li>`);
        });
        lines.push('</ul>');
    }
    lines.push('</div>');

    // Per-example methods for the currently displayed meaning.
    const curMeaning = meanings[currentMeaningIndex] || meanings[0];
    const exs = (curMeaning && curMeaning.allExamples) || [];
    lines.push('<div class="card-meta-section"><h4>Examples (current meaning)</h4>');
    if (!exs.length) {
        lines.push('<div class="card-meta-empty">No examples.</div>');
    } else {
        lines.push('<ul class="card-meta-list">');
        exs.forEach((ex, i) => {
            const isCurrent = (typeof currentExampleIndex === 'number' && i === (currentExampleIndex % exs.length));
            const method = ex.assignment_method ? `<span class="card-meta-tag method">m: ${_escapeHtml(ex.assignment_method)}</span>` : '<span class="card-meta-empty">no method</span>';
            const tsrc = ex.translation_source ? `<span class="card-meta-tag source">t: ${_escapeHtml(ex.translation_source)}</span>` : '';
            const spanish = ex.spanish || ex.targetSentence || ex.original || '';
            lines.push(`<li${isCurrent ? ' class="card-meta-current"' : ''}>${method} ${tsrc}<div class="card-meta-ex">${_escapeHtml(spanish)}</div></li>`);
        });
        lines.push('</ul>');
    }
    lines.push('</div>');

    return lines.join('');
}

function showCardMetaPopover() {
    const pop = document.getElementById('cardMetaPopover');
    const body = document.getElementById('cardMetaBody');
    const title = document.getElementById('cardMetaTitle');
    if (!pop || !body) return;
    const card = (typeof flashcards !== 'undefined' && flashcards) ? flashcards[currentIndex] : null;
    if (title) title.textContent = card ? `${card.targetWord || card.word || 'Card'} — info` : 'Card info';
    body.innerHTML = _renderCardMetaBody(card);
    pop.hidden = false;
    pop.setAttribute('aria-hidden', 'false');
}

function hideCardMetaPopover() {
    const pop = document.getElementById('cardMetaPopover');
    if (!pop) return;
    pop.hidden = true;
    pop.setAttribute('aria-hidden', 'true');
}

function toggleCardMetaPopover() {
    const pop = document.getElementById('cardMetaPopover');
    if (!pop) return;
    if (pop.hidden) showCardMetaPopover();
    else hideCardMetaPopover();
}

function refreshCardMetaPopoverIfOpen() {
    const pop = document.getElementById('cardMetaPopover');
    if (!pop || pop.hidden) return;
    showCardMetaPopover();
}
window.refreshCardMetaPopoverIfOpen = refreshCardMetaPopoverIfOpen;

// Wire up the button + outside-click dismiss + refresh on card change.
(function _initCardMetaPopover() {
    function attach() {
        const btn = document.getElementById('cardMetaBtn');
        const pop = document.getElementById('cardMetaPopover');
        const closeBtn = document.getElementById('cardMetaClose');
        if (!btn || !pop) return;
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleCardMetaPopover();
        });
        if (closeBtn) closeBtn.addEventListener('click', hideCardMetaPopover);
        document.addEventListener('click', (e) => {
            if (pop.hidden) return;
            if (pop.contains(e.target) || btn.contains(e.target)) return;
            hideCardMetaPopover();
        });
        // Refresh contents when the popover is open and the card changes.
        // (Driven by refreshCardMetaPopoverIfOpen() calls inside updateCard.)
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attach, { once: true });
    } else {
        attach();
    }
})();

window.toggleCardMetaPopover = toggleCardMetaPopover;
window.showCardMetaPopover = showCardMetaPopover;
window.hideCardMetaPopover = hideCardMetaPopover;

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
