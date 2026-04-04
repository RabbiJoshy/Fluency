import './state.js';

// Compute max level for estimation, accounting for multi-artist mode
function getEstimationMaxLevel() {
    if (!activeArtist) return 11000;
    const selectedSlugs = window._selectedArtistSlugs || [];
    const allConfigs = window._allArtistsConfig;
    if (selectedSlugs.length > 1 && allConfigs) {
        return Math.max(...selectedSlugs.map(slug => {
            const cfg = allConfigs[slug];
            return cfg ? (cfg.maxLevel || 8500) : 0;
        }));
    }
    return activeArtist.maxLevel || 8500;
}

// Show/hide estimate level button based on language
function updateEstimateLevelButton() {
    const btn = document.getElementById('estimateLevelBtn');
    // Only show for Spanish (regular or artist mode)
    if (selectedLanguage === 'spanish' || activeArtist) {
        btn.classList.remove('hidden');
    } else {
        btn.classList.add('hidden');
    }
}

function updateEstimateLevelBlock() {
    const block = document.getElementById('estimateLevelBlock');
    const hasEstimate = (levelEstimates[selectedLanguage] || 0) > 0;
    const show = !activeArtist && selectedLanguage === 'spanish' && !hasEstimate;
    block.style.display = show ? 'block' : 'none';
}

// Open estimation modal
function openEstimationModal() {
    const modal = document.getElementById('estimationModal');
    modal.classList.remove('hidden');

    // Reset state
    document.getElementById('estimationIntro').style.display = 'block';
    document.getElementById('estimationTest').style.display = 'none';
    document.getElementById('estimationResult').style.display = 'none';

    // Reset estimation state
    estimationState = {
        active: false,
        currentLevel: 500,
        minStride: 100,
        wordIndex: 0,
        correct: 0,
        wrong: 0,
        checkpointCorrect: 0,
        checkpointWrong: 0,
        currentWords: [],
        estimatedLevel: null,
        vocabularyData: null,
        history: [],
        maxLevel: getEstimationMaxLevel(),
        lowerBound: 0,
        upperBound: getEstimationMaxLevel(),
        confirmationLevel: null
    };
}

// Close estimation modal
function closeEstimationModal() {
    const modal = document.getElementById('estimationModal');
    modal.classList.add('hidden');
    estimationState.active = false;
}

// Start the estimation test
async function startEstimation() {
    // Load vocabulary data
    const langConfig = config.languages[selectedLanguage];
    try {
        const response = await fetch(langConfig.indexPath || langConfig.dataPath);
        const vocabData = await response.json();
        // Assign ranks
        vocabData.forEach((item, index) => {
            item.rank = index + 1;
        });
        estimationState.vocabularyData = vocabData;
    } catch (error) {
        alert('Failed to load vocabulary for estimation.');
        return;
    }

    // Determine max level based on mode
    const maxLevel = getEstimationMaxLevel();

    // Initialize state — binary search for highest level where user scores ≥4/5
    estimationState.active = true;
    estimationState.maxLevel = maxLevel;
    estimationState.wordIndex = 0;
    estimationState.correct = 0;
    estimationState.wrong = 0;
    estimationState.checkpointCorrect = 0;
    estimationState.checkpointWrong = 0;
    estimationState.history = [];
    estimationState.estimatedLevel = null;
    estimationState.lowerBound = 0;
    estimationState.upperBound = maxLevel;
    estimationState.confirmationLevel = null;
    estimationState.minStride = 100;
    estimationState.currentLevel = Math.floor(maxLevel / 2);

    // Show test UI
    document.getElementById('estimationIntro').style.display = 'none';
    document.getElementById('estimationTest').style.display = 'block';
    document.getElementById('estimationResult').style.display = 'none';

    // Load words for current level
    loadEstimationLevel();
}

// Get 5 test words for a given level (words around that rank)
function getWordsForLevel(level) {
    const vocabData = estimationState.vocabularyData;
    if (!vocabData) return [];

    // Always exclude cognates, interjections, proper nouns, and English words from
    // estimation — these aren't genuine vocabulary tests and would inflate the result
    let validWords = vocabData.filter(item =>
        item.word && item.word.trim() !== '' &&
        !item.duplicate &&
        item.meanings && item.meanings.length > 0 &&
        !item.is_transparent_cognate &&
        !item.is_interjection &&
        !item.is_propernoun &&
        !item.is_english
    );

    // Hide single-occurrence words if enabled
    if (hideSingleOccurrence && validWords.length > 0 && validWords[0].hasOwnProperty('corpus_count')) {
        validWords = validWords.filter(item => item.corpus_count > 1);
    }

    // Get words in range [level-25, level+25] and pick 5
    const rangeStart = Math.max(1, level - 25);
    const rangeEnd = level + 25;
    const wordsInRange = validWords.filter(w => w.rank >= rangeStart && w.rank <= rangeEnd);

    // Shuffle and pick 5
    const shuffled = wordsInRange.sort(() => Math.random() - 0.5);
    return shuffled.slice(0, 5);
}

// Load words for current level
function loadEstimationLevel() {
    // Reset checkpoint scores
    estimationState.checkpointCorrect = 0;
    estimationState.checkpointWrong = 0;
    estimationState.wordIndex = 0;

    // Get words for this level
    estimationState.currentWords = getWordsForLevel(estimationState.currentLevel);

    if (estimationState.currentWords.length === 0) {
        // No words at this level - finish
        showEstimationResult(estimationState.currentLevel);
        return;
    }

    // Update UI
    document.getElementById('estimationCheckpoint').textContent = `Testing ~${estimationState.currentLevel}`;
    updateEstimationWord();
}

// Update the displayed word
function updateEstimationWord() {
    const word = estimationState.currentWords[estimationState.wordIndex];
    if (!word) return;

    document.getElementById('estimationWord').textContent = word.word;

    // Get POS from meanings
    let pos = '';
    if (word.meanings && word.meanings.length > 0) {
        pos = word.meanings[0].pos || '';
    }
    document.getElementById('estimationPOS').textContent = pos;

    // Update count
    document.getElementById('estimationWordCount').textContent =
        `${estimationState.wordIndex + 1}/${estimationState.currentWords.length}`;

    // Update totals
    document.getElementById('estimationCorrect').textContent = estimationState.correct;
    document.getElementById('estimationWrong').textContent = estimationState.wrong;
}

// Handle "Know" button
function estimationKnow() {
    estimationState.correct++;
    estimationState.checkpointCorrect++;
    nextEstimationWord();
}

// Handle "Don't Know" button
function estimationDontKnow() {
    estimationState.wrong++;
    estimationState.checkpointWrong++;
    nextEstimationWord();
}

// Move to next word or checkpoint
function nextEstimationWord() {
    estimationState.wordIndex++;

    if (estimationState.wordIndex >= estimationState.currentWords.length) {
        // Checkpoint complete - evaluate performance
        evaluateCheckpoint();
    } else {
        updateEstimationWord();
    }
}

// Evaluate checkpoint performance and decide next action
function evaluateCheckpoint() {
    const correct = estimationState.checkpointCorrect;
    const currentLevel = estimationState.currentLevel;

    estimationState.history.push({ level: currentLevel, correct });

    evaluateCheckpointDetailed(correct, currentLevel);
}

// Detailed mode: binary search with confirmation step for 4/5
function evaluateCheckpointDetailed(correct, currentLevel) {
    const { lowerBound, upperBound, minStride, confirmationLevel } = estimationState;

    if (confirmationLevel !== null) {
        // Resolving a pending 4/5 confirmation
        estimationState.confirmationLevel = null;
        if (correct >= 4) {
            // Confirmed — accept the level we were confirming
            estimationState.lowerBound = confirmationLevel;
        } else {
            // Didn't confirm — that 4/5 was noise
            estimationState.upperBound = confirmationLevel;
        }
        advanceDetailedSearch();
        return;
    }

    if (correct === 5) {
        // Solid mastery — accept this level and search higher
        estimationState.lowerBound = currentLevel;
        advanceDetailedSearch();
    } else if (correct === 4) {
        // Probably fine, but retest lower to confirm before accepting
        const gap = currentLevel - lowerBound;
        if (gap > minStride * 2) {
            // Enough room to confirm — test a third of the way back down
            const confirmAt = Math.max(lowerBound + 1, currentLevel - Math.floor(gap / 3));
            estimationState.confirmationLevel = currentLevel;
            estimationState.currentLevel = confirmAt;
            loadEstimationLevel();
        } else {
            // Too close to confirmed territory — accept 4/5 as sufficient
            estimationState.lowerBound = currentLevel;
            advanceDetailedSearch();
        }
    } else {
        // ≤3/5 — not at this level
        estimationState.upperBound = currentLevel;
        advanceDetailedSearch();
    }
}

// Move to the midpoint of remaining search space, or stop if converged
function advanceDetailedSearch() {
    const { lowerBound, upperBound, minStride } = estimationState;
    const gap = upperBound - lowerBound;
    if (gap <= minStride) {
        // Converged — estimate is the highest confirmed good level
        showEstimationResult(lowerBound);
        return;
    }
    estimationState.currentLevel = Math.floor((lowerBound + upperBound) / 2);
    loadEstimationLevel();
}

// Show the estimation result
function showEstimationResult(level) {
    estimationState.active = false;
    estimationState.estimatedLevel = level;

    document.getElementById('estimationTest').style.display = 'none';
    document.getElementById('estimationResult').style.display = 'block';

    if (level === 0) {
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
    levelEstimates[selectedLanguage] = level; // update in-memory immediately
    saveLevelEstimateToSheet(level); // fire-and-forget
    updateEstimateLevelBlock(); // hide the block now that an estimate is set
    closeEstimationModal();

    if (level === 0) {
        // Select first level
        const firstLevelBtn = document.querySelector('.level-btn');
        if (firstLevelBtn) {
            firstLevelBtn.click();
        }
    } else {
        // Find the appropriate CEFR level or percentage level for this rank
        // and select it, then select the appropriate range
        selectLevelForRank(level);
    }
}

// Select the appropriate level and range for a given rank
function selectLevelForRank(rank) {
    // Find which level contains this rank
    const levels = getCefrLevels(selectedLanguage);

    let targetLevel = null;
    for (const level of levels) {
        if (rank >= level.minRank && rank <= level.maxRank) {
            targetLevel = level;
            break;
        }
        // If rank is below this level's max, use this level
        if (rank <= level.maxRank) {
            targetLevel = level;
            break;
        }
    }

    if (!targetLevel && levels.length > 0) {
        // Use the highest level
        targetLevel = levels[levels.length - 1];
    }

    if (targetLevel) {
        // Click the level button
        const levelBtn = document.querySelector(`.level-btn[data-level="${targetLevel.level}"]`);
        if (levelBtn) {
            levelBtn.click();

            // After level is selected, try to select the range containing this rank
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
        // If rank is less than start, select previous range or first
        if (rank < start) {
            // Select the previous button or this one if it's the first
            const prevBtn = btn.previousElementSibling;
            if (prevBtn && prevBtn.classList.contains('range-btn')) {
                prevBtn.click();
            } else {
                btn.click();
            }
            return;
        }
    }
    // If no range found, select the last one
    if (rangeButtons.length > 0) {
        rangeButtons[rangeButtons.length - 1].click();
    }
}

// ========== END LEVEL ESTIMATION ==========

// Load configuration

window.updateEstimateLevelButton = updateEstimateLevelButton;
window.updateEstimateLevelBlock = updateEstimateLevelBlock;
window.openEstimationModal = openEstimationModal;
window.closeEstimationModal = closeEstimationModal;
window.startEstimation = startEstimation;
window.getWordsForLevel = getWordsForLevel;
window.loadEstimationLevel = loadEstimationLevel;
window.updateEstimationWord = updateEstimationWord;
window.estimationKnow = estimationKnow;
window.estimationDontKnow = estimationDontKnow;
window.nextEstimationWord = nextEstimationWord;
window.evaluateCheckpoint = evaluateCheckpoint;
window.evaluateCheckpointDetailed = evaluateCheckpointDetailed;
window.advanceDetailedSearch = advanceDetailedSearch;
window.showEstimationResult = showEstimationResult;
window.useEstimatedLevel = useEstimatedLevel;
window.selectLevelForRank = selectLevelForRank;
window.selectRangeForRank = selectRangeForRank;
