import './state.js';

// Compute max level for estimation, accounting for multi-artist mode
function getEstimationMaxLevel() {
    // Always use normal-mode vocab size as ceiling (set after loading in startEstimation)
    if (!activeArtist) return 11000;
    return 11000;
}

// Return the normal-mode lang config for estimation (unbiased by artist corpus ordering)
function getEstimationLangConfig() {
    const langConfig = config.languages[selectedLanguage];
    if (!activeArtist) return langConfig;
    const normalConfig = window._normalModeLangConfigs?.[selectedLanguage];
    return normalConfig || langConfig;
}

// Open estimation modal
function openEstimationModal() {
    const modal = document.getElementById('estimationModal');
    modal.classList.remove('hidden');

    document.getElementById('estimationIntro').style.display = 'block';
    document.getElementById('estimationTest').style.display = 'none';
    document.getElementById('estimationResult').style.display = 'none';

    estimationState = {
        active: false,
        vocabularyData: null,
        validWords: null,
        maxLevel: getEstimationMaxLevel(),
        // Staircase state
        currentRank: 0,
        stepSize: 0,
        direction: 0,        // 1 = going up, -1 = going down, 0 = initial
        streak: 0,           // consecutive correct
        wordsTestedCount: 0,
        shownWordIds: new Set(),
        currentWord: null,
        estimatedLevel: null,
        previousEstimate: null,  // for retest seeding
        autoAdvanceTimer: null
    };
}

// Close estimation modal
function closeEstimationModal() {
    const modal = document.getElementById('estimationModal');
    modal.classList.add('hidden');
    estimationState.active = false;
    if (estimationState.autoAdvanceTimer) {
        clearTimeout(estimationState.autoAdvanceTimer);
    }
}

// Build filtered word list (reuses same filters as old getWordsForLevel)
function buildEstimationWordList() {
    const vocabData = estimationState.vocabularyData;
    if (!vocabData) return [];

    let valid = vocabData.filter(item =>
        item.word && item.word.trim() !== '' &&
        !item.duplicate &&
        item.meanings && item.meanings.length > 0 &&
        (item.cognate_score ?? 0) < 0.83 &&
        !item.is_noise && !item.is_interjection &&  // schema_v2 alias
        !item.is_propernoun &&
        !item.is_english
    );

    if (hideSingleOccurrence && valid.length > 0 && valid[0].hasOwnProperty('corpus_count')) {
        valid = valid.filter(item => item.corpus_count > 1);
    }

    // Assign ranks based on filtered position
    valid.forEach((item, index) => {
        item.rank = index + 1;
    });

    return valid;
}

// Pick a random word near a target rank, avoiding repeats
function pickWordNearRank(targetRank) {
    const valid = estimationState.validWords;
    if (!valid || valid.length === 0) return null;

    const clampedRank = Math.max(1, Math.min(targetRank, valid.length));
    const rangeStart = Math.max(0, clampedRank - 26);
    const rangeEnd = Math.min(valid.length, clampedRank + 25);

    const candidates = [];
    for (let i = rangeStart; i < rangeEnd; i++) {
        const word = valid[i];
        if (!estimationState.shownWordIds.has(word.id || word.word)) {
            candidates.push(word);
        }
    }

    if (candidates.length === 0) {
        // All nearby words shown — expand range
        for (let i = 0; i < valid.length; i++) {
            if (!estimationState.shownWordIds.has(valid[i].id || valid[i].word)) {
                candidates.push(valid[i]);
                if (candidates.length >= 10) break;
            }
        }
    }

    if (candidates.length === 0) return null;
    return candidates[Math.floor(Math.random() * candidates.length)];
}

// Get translation for a word
function getWordTranslation(word) {
    if (!word || !word.meanings || word.meanings.length === 0) return '';
    return word.meanings.map(m => {
        const pos = m.pos ? `(${m.pos}) ` : '';
        return pos + (m.translation || '');
    }).filter(t => t).join(', ');
}

// Start the estimation test
async function startEstimation() {
    const langConfig = getEstimationLangConfig();
    try {
        estimationState.vocabularyData = await fetchAndJoinIndex(langConfig);
    } catch (error) {
        alert('Failed to load vocabulary for estimation.');
        return;
    }

    estimationState.validWords = buildEstimationWordList();
    const maxLevel = estimationState.validWords.length;
    estimationState.maxLevel = maxLevel;

    // Seed starting position
    const prevEstimate = estimationState.previousEstimate;
    if (prevEstimate && prevEstimate > 0) {
        // Retest: start near previous estimate
        estimationState.currentRank = prevEstimate;
    } else {
        estimationState.currentRank = Math.floor(maxLevel / 2);
    }

    estimationState.stepSize = Math.max(50, Math.floor(maxLevel / 6));
    estimationState.active = true;
    estimationState.direction = 0;
    estimationState.streak = 0;
    estimationState.wordsTestedCount = 0;
    estimationState.shownWordIds = new Set();
    estimationState.estimatedLevel = null;

    // Show test UI
    document.getElementById('estimationIntro').style.display = 'none';
    document.getElementById('estimationTest').style.display = 'flex';
    document.getElementById('estimationResult').style.display = 'none';

    showNextWord();
}

// Show the next word
function showNextWord() {
    if (!estimationState.active) return;

    // Clear any previous auto-advance timer
    if (estimationState.autoAdvanceTimer) {
        clearTimeout(estimationState.autoAdvanceTimer);
        estimationState.autoAdvanceTimer = null;
    }

    const word = pickWordNearRank(estimationState.currentRank);
    if (!word) {
        showEstimationResult(estimationState.currentRank);
        return;
    }

    estimationState.currentWord = word;
    estimationState.shownWordIds.add(word.id || word.word);

    // Update UI
    document.getElementById('estimationWord').textContent = word.word;
    const lemmaEl = document.getElementById('estimationLemma');
    if (lemmaEl) {
        const lemma = word.lemma || '';
        // Only display the lemma when it adds information (differs from the surface form).
        if (lemma && lemma !== word.word) {
            lemmaEl.textContent = lemma;
            lemmaEl.style.visibility = 'visible';
        } else {
            lemmaEl.textContent = '';
            lemmaEl.style.visibility = 'hidden';
        }
    }
    let pos = '';
    if (word.meanings && word.meanings.length > 0) {
        pos = word.meanings[0].pos || '';
    }
    document.getElementById('estimationPOS').textContent = pos;

    // Hide translation until user taps to reveal
    const translationEl = document.getElementById('estimationTranslation');
    translationEl.textContent = getWordTranslation(word);
    translationEl.classList.remove('visible');

    // Show reveal button and answer buttons
    document.getElementById('estimationReveal').style.display = 'block';
    document.getElementById('estimationButtons').style.display = 'flex';

    // Update progress
    updateEstimationProgress();
}

// Reveal the translation so user can confirm before answering
function revealTranslation() {
    document.getElementById('estimationTranslation').classList.add('visible');
    document.getElementById('estimationReveal').style.display = 'none';
}

// Handle answer
function handleAnswer(known) {
    if (!estimationState.active) return;

    estimationState.wordsTestedCount++;

    const newDirection = known ? 1 : -1;

    // Check for reversal (direction change)
    if (estimationState.direction !== 0 && newDirection !== estimationState.direction) {
        estimationState.stepSize = Math.max(50, Math.floor(estimationState.stepSize / 2));
    }
    estimationState.direction = newDirection;

    // Update streak
    if (known) {
        estimationState.streak++;
    } else {
        estimationState.streak = 0;
    }

    // Move rank
    if (known) {
        estimationState.currentRank = Math.min(
            estimationState.maxLevel,
            estimationState.currentRank + estimationState.stepSize
        );
    } else {
        estimationState.currentRank = Math.max(
            0,
            estimationState.currentRank - estimationState.stepSize
        );
    }

    // Check convergence
    if (checkConvergence()) {
        showEstimationResult(estimationState.currentRank);
        return;
    }

    showNextWord();
}

// Check convergence
function checkConvergence() {
    // Safety cap
    if (estimationState.wordsTestedCount >= 30) return true;

    // Converged: small step + streak of 5
    if (estimationState.stepSize <= 50 && estimationState.streak >= 5) return true;

    // Hit the bottom
    if (estimationState.currentRank <= 0) return true;

    return false;
}

// Update progress display
function updateEstimationProgress() {
    document.getElementById('estimationLevel').textContent = `~${estimationState.currentRank}`;
    document.getElementById('estimationCount').textContent =
        `${estimationState.wordsTestedCount}/30`;
}

// Show the estimation result
function showEstimationResult(level) {
    estimationState.active = false;
    estimationState.estimatedLevel = Math.max(0, level);

    if (estimationState.autoAdvanceTimer) {
        clearTimeout(estimationState.autoAdvanceTimer);
        estimationState.autoAdvanceTimer = null;
    }

    document.getElementById('estimationTest').style.display = 'none';
    document.getElementById('estimationResult').style.display = 'block';

    if (level <= 0) {
        document.getElementById('estimationResultLevel').textContent = 'Beginner';
        document.getElementById('estimationResultDesc').textContent =
            'Start from the beginning to build your vocabulary foundation.';
    } else {
        document.getElementById('estimationResultLevel').textContent = `~${level} words`;
        document.getElementById('estimationResultDesc').textContent =
            `You likely know vocabulary up to rank ${level}. Start studying from there!`;
    }
}

// Apply the estimated level
function useEstimatedLevel() {
    const level = estimationState.estimatedLevel;
    levelEstimates[selectedLanguage] = level;
    saveLevelEstimateToSheet(level);
    closeEstimationModal();

    if (level === 0) {
        const firstLevelBtn = document.querySelector('.level-btn');
        if (firstLevelBtn) firstLevelBtn.click();
    } else {
        selectLevelForRank(level);
    }
}

// Retry estimation — seed near previous result
function retryEstimation() {
    estimationState.previousEstimate = estimationState.estimatedLevel;
    document.getElementById('estimationResult').style.display = 'none';
    startEstimation();
}

// Select the appropriate level and range for a given rank
function selectLevelForRank(rank) {
    const levels = getCefrLevels(selectedLanguage);

    let targetLevel = null;
    for (const level of levels) {
        if (rank >= level.minRank && rank <= level.maxRank) {
            targetLevel = level;
            break;
        }
        if (rank <= level.maxRank) {
            targetLevel = level;
            break;
        }
    }

    if (!targetLevel && levels.length > 0) {
        targetLevel = levels[levels.length - 1];
    }

    if (targetLevel) {
        const levelBtn = document.querySelector(`.level-btn[data-level="${targetLevel.level}"]`);
        if (levelBtn) {
            levelBtn.click();
            setTimeout(() => {
                selectRangeForRank(rank);
            }, 100);
        }
    }
}

// Select the range containing a given rank
function selectRangeForRank(rank) {
    const rangeButtons = document.querySelectorAll('.range-btn');
    for (const btn of rangeButtons) {
        const start = parseInt(btn.dataset.start);
        const end = parseInt(btn.dataset.end);
        if (rank >= start && rank <= end) {
            btn.click();
            return;
        }
        if (rank < start) {
            const prevBtn = btn.previousElementSibling;
            if (prevBtn && prevBtn.classList.contains('range-btn')) {
                prevBtn.click();
            } else {
                btn.click();
            }
            return;
        }
    }
    if (rangeButtons.length > 0) {
        rangeButtons[rangeButtons.length - 1].click();
    }
}

window.openEstimationModal = openEstimationModal;
window.closeEstimationModal = closeEstimationModal;
window.startEstimation = startEstimation;
window.handleAnswer = handleAnswer;
window.revealTranslation = revealTranslation;
window.showEstimationResult = showEstimationResult;
window.useEstimatedLevel = useEstimatedLevel;
window.retryEstimation = retryEstimation;
window.selectLevelForRank = selectLevelForRank;
window.selectRangeForRank = selectRangeForRank;
