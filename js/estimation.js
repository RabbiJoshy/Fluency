import './state.js?v=20260817i';

const ESTIMATION_QUESTION_LIMIT = 30;
const ESTIMATION_BAND_TARGET = 10;
const ESTIMATION_CONFIDENCE_Z = 1.645; // Approximate 90% interval.
const ESTIMATION_PRIOR = 0.5;          // Jeffreys prior for adaptive selection.

// Always use the normal-mode vocabulary for placement. Artist ordering measures
// familiarity with one corpus, not general vocabulary size.
function getEstimationLangConfig() {
    const langConfig = config.languages[selectedLanguage];
    if (!activeArtist) return langConfig;
    return window._normalModeLangConfigs?.[selectedLanguage] || langConfig;
}

function createEstimationState() {
    return {
        active: false,
        vocabularyData: null,
        validWords: [],
        bands: [],
        coverageOrder: [],
        maxLevel: 0,
        wordsTestedCount: 0,
        shownWordIds: new Set(),
        shownLemmaKeys: new Set(),
        currentWord: null,
        currentBandIndex: null,
        translationRevealed: false,
        estimatedLevel: null,
        estimateInterval: null,
        autoAdvanceTimer: null
    };
}

// Open estimation modal
function openEstimationModal() {
    document.getElementById('estimationModal').classList.remove('hidden');
    document.getElementById('estimationIntro').style.display = 'block';
    document.getElementById('estimationTest').style.display = 'none';
    document.getElementById('estimationResult').style.display = 'none';
    estimationState = createEstimationState();
}

// Close estimation modal
function closeEstimationModal() {
    document.getElementById('estimationModal').classList.add('hidden');
    estimationState.active = false;
    if (estimationState.autoAdvanceTimer) {
        clearTimeout(estimationState.autoAdvanceTimer);
    }
}

// Keep the estimator independent of optional pipeline enrichments. It uses the
// same broad exclusions as before, but does not require CEFR labels, calibrated
// item difficulty, morphology, or sense-assignment metadata.
function buildEstimationWordList() {
    const vocabData = estimationState.vocabularyData;
    if (!vocabData) return [];

    const valid = vocabData.filter(item =>
        item.word && item.word.trim() !== '' &&
        !item.duplicate &&
        item.meanings && item.meanings.length > 0 &&
        (item.cognate_score ?? 0) < 0.83 &&
        !item.is_noise && !item.is_interjection &&
        !item.is_propernoun &&
        !item.is_english &&
        (!hideSingleOccurrence || !item.hasOwnProperty('corpus_count') || item.corpus_count > 1)
    );

    // Preserve the source frequency order without overwriting the rank used by
    // the actual deck. The saved estimate remains a compatible rank high-water
    // mark for existing progress and level selection code.
    return valid.map((item, index) => ({
        ...item,
        estimationRank: index + 1
    }));
}

function buildCoverageOrder(count) {
    const order = [];
    const queue = [[0, count - 1]];
    while (queue.length > 0) {
        const [start, end] = queue.shift();
        if (start > end) continue;
        const middle = Math.floor((start + end) / 2);
        order.push(middle);
        queue.push([start, middle - 1], [middle + 1, end]);
    }
    return order;
}

function buildEstimationBands(words) {
    if (!words.length) return [];
    const bandCount = Math.max(1, Math.min(
        ESTIMATION_BAND_TARGET,
        Math.floor(words.length / 40) || 1
    ));

    return Array.from({ length: bandCount }, (_, index) => {
        const start = Math.floor(index * words.length / bandCount);
        const end = Math.floor((index + 1) * words.length / bandCount);
        return {
            index,
            start,
            end,
            size: end - start,
            answers: 0,
            known: 0
        };
    });
}

function getWordKey(word) {
    return String(word.id || `${word.word}|${word.lemma || ''}|${word.estimationRank}`);
}

function getLemmaKey(word) {
    return String(word.lemma || word.word || '').trim().toLocaleLowerCase();
}

// Pool adjacent violations so estimated knowledge cannot rise as words become
// less frequent. Each returned value corresponds to one frequency band.
function fitMonotonicProbabilities(values, weights) {
    const blocks = values.map((value, index) => ({
        start: index,
        end: index,
        value,
        weight: Math.max(Number(weights[index]) || 0, 0.0001)
    }));

    for (let index = 0; index < blocks.length - 1;) {
        if (blocks[index].value >= blocks[index + 1].value) {
            index++;
            continue;
        }

        const left = blocks[index];
        const right = blocks[index + 1];
        const weight = left.weight + right.weight;
        blocks.splice(index, 2, {
            start: left.start,
            end: right.end,
            value: ((left.value * left.weight) + (right.value * right.weight)) / weight,
            weight
        });
        if (index > 0) index--;
    }

    const fitted = new Array(values.length);
    blocks.forEach(block => {
        for (let index = block.start; index <= block.end; index++) {
            fitted[index] = block.value;
        }
    });
    return fitted;
}

function getPosteriorBandProbabilities(bands) {
    const values = bands.map(band =>
        (band.known + ESTIMATION_PRIOR) /
        (band.answers + (2 * ESTIMATION_PRIOR))
    );
    const weights = bands.map(band => band.answers + (2 * ESTIMATION_PRIOR));
    return fitMonotonicProbabilities(values, weights);
}

function chooseNextBandIndex() {
    const bands = estimationState.bands;
    if (!bands.length) return null;

    // First cover the whole frequency distribution in a centre-out order. A
    // learner is never estimated from a narrow run of unusually easy/hard words.
    const untested = estimationState.coverageOrder.find(index => bands[index].answers === 0);
    if (untested !== undefined) return untested;

    const fitted = getPosteriorBandProbabilities(bands);
    const rawPosterior = bands.map(band =>
        (band.known + ESTIMATION_PRIOR) /
        (band.answers + (2 * ESTIMATION_PRIOR))
    );
    const firstMostlyUnknown = fitted.findIndex(probability => probability < 0.5);
    let boundaryIndex;
    if (firstMostlyUnknown < 0) {
        boundaryIndex = fitted.length - 1;
    } else if (firstMostlyUnknown === 0) {
        boundaryIndex = 0;
    } else {
        const knownSide = firstMostlyUnknown - 1;
        boundaryIndex = Math.abs(fitted[knownSide] - 0.5) <=
            Math.abs(fitted[firstMostlyUnknown] - 0.5)
            ? knownSide
            : firstMostlyUnknown;
    }

    let bestIndex = 0;
    let bestScore = -Infinity;
    bands.forEach((band, index) => {
        const alpha = band.known + ESTIMATION_PRIOR;
        const beta = (band.answers - band.known) + ESTIMATION_PRIOR;
        const total = alpha + beta;
        const variance = (alpha * beta) / ((total * total) * (total + 1));
        const probability = alpha / total;
        const uncertainty = 1 + (1 - Math.min(1, Math.abs(probability - 0.5) * 2));
        const boundaryProximity = 1 + (1.5 / (1 + Math.abs(index - boundaryIndex)));

        // Recheck local reversals instead of allowing one anomalous response to
        // pull a whole stretch of the fitted curve in the wrong direction.
        const left = index > 0 ? rawPosterior[index - 1] : rawPosterior[index];
        const right = index < rawPosterior.length - 1
            ? rawPosterior[index + 1]
            : rawPosterior[index];
        const reversalBonus = (left < rawPosterior[index] || rawPosterior[index] < right)
            ? 1.35
            : 1;
        const score = variance * uncertainty * boundaryProximity * reversalBonus * band.size;

        if (score > bestScore) {
            bestScore = score;
            bestIndex = index;
        }
    });
    return bestIndex;
}

function pickWordFromBand(bandIndex) {
    const band = estimationState.bands[bandIndex];
    if (!band) return null;

    const words = estimationState.validWords.slice(band.start, band.end);
    const unused = words.filter(word => !estimationState.shownWordIds.has(getWordKey(word)));
    if (!unused.length) return null;

    // Never test the same lemma twice unless this band has no other unused
    // vocabulary left. Surface forms are otherwise sampled without pipeline-
    // specific preferences so the check reflects the deck it will place into.
    const freshLemmas = unused.filter(word =>
        !estimationState.shownLemmaKeys.has(getLemmaKey(word))
    );
    const candidates = freshLemmas.length ? freshLemmas : unused;
    return candidates[Math.floor(Math.random() * candidates.length)];
}

function findAvailableWord(preferredBandIndex) {
    const bandCount = estimationState.bands.length;
    for (let distance = 0; distance < bandCount; distance++) {
        const indices = distance === 0
            ? [preferredBandIndex]
            : [preferredBandIndex - distance, preferredBandIndex + distance];
        for (const index of indices) {
            if (index < 0 || index >= bandCount) continue;
            const word = pickWordFromBand(index);
            if (word) return { word, bandIndex: index };
        }
    }
    return null;
}

// Get translation for a word
function getWordTranslation(word) {
    if (!word?.meanings?.length) return '';
    return word.meanings.map(meaning => {
        const pos = meaning.pos ? `(${meaning.pos}) ` : '';
        return meaning.translation ? pos + meaning.translation : '';
    }).filter(Boolean).join(', ');
}

// Start the estimation test
async function startEstimation() {
    estimationState = createEstimationState();

    try {
        estimationState.vocabularyData = await fetchAndJoinIndex(getEstimationLangConfig());
    } catch (error) {
        alert('Failed to load vocabulary for estimation.');
        return;
    }

    estimationState.validWords = buildEstimationWordList();
    estimationState.maxLevel = estimationState.validWords.length;
    estimationState.bands = buildEstimationBands(estimationState.validWords);
    estimationState.coverageOrder = buildCoverageOrder(estimationState.bands.length);

    if (!estimationState.validWords.length) {
        alert('There are not enough vocabulary entries to run the level check.');
        return;
    }

    estimationState.active = true;
    document.getElementById('estimationIntro').style.display = 'none';
    document.getElementById('estimationTest').style.display = 'flex';
    document.getElementById('estimationResult').style.display = 'none';
    showNextWord();
}

// Show the next word
function showNextWord() {
    if (!estimationState.active) return;

    if (estimationState.wordsTestedCount >= ESTIMATION_QUESTION_LIMIT) {
        showEstimationResult();
        return;
    }

    const preferredBand = chooseNextBandIndex();
    const selection = findAvailableWord(preferredBand);
    if (!selection) {
        showEstimationResult();
        return;
    }

    const { word, bandIndex } = selection;
    estimationState.currentWord = word;
    estimationState.currentBandIndex = bandIndex;
    estimationState.translationRevealed = false;
    estimationState.shownWordIds.add(getWordKey(word));
    estimationState.shownLemmaKeys.add(getLemmaKey(word));

    document.getElementById('estimationWord').textContent = word.word;
    const lemmaEl = document.getElementById('estimationLemma');
    const lemma = word.lemma || '';
    if (lemma && lemma !== word.word) {
        lemmaEl.textContent = lemma;
        lemmaEl.style.visibility = 'visible';
    } else {
        lemmaEl.textContent = '';
        lemmaEl.style.visibility = 'hidden';
    }

    document.getElementById('estimationPOS').textContent = word.meanings?.[0]?.pos || '';
    const translationEl = document.getElementById('estimationTranslation');
    translationEl.textContent = getWordTranslation(word);
    translationEl.classList.remove('visible');
    document.getElementById('estimationReveal').style.display = 'block';
    document.getElementById('estimationButtons').style.display = 'none';
    updateEstimationProgress();
}

// Reveal first, then self-score whether the meaning was known before reveal.
function revealTranslation() {
    if (!estimationState.active || estimationState.translationRevealed) return;
    estimationState.translationRevealed = true;
    document.getElementById('estimationTranslation').classList.add('visible');
    document.getElementById('estimationReveal').style.display = 'none';
    document.getElementById('estimationButtons').style.display = 'flex';
}

// Handle answer
function handleAnswer(known) {
    if (!estimationState.active || !estimationState.translationRevealed) return;
    const band = estimationState.bands[estimationState.currentBandIndex];
    if (!band) return;

    band.answers++;
    if (known) band.known++;
    estimationState.wordsTestedCount++;
    showNextWord();
}

function roundEstimate(value, maxLevel) {
    const increment = maxLevel >= 2000 ? 100 : 50;
    return Math.max(0, Math.min(maxLevel, Math.round(value / increment) * increment));
}

function calculateEstimationResult(bands, maxLevel) {
    if (!bands.length || !bands.some(band => band.answers > 0)) {
        return { point: 0, low: 0, high: 0 };
    }

    // Every band is sampled before adaptive repeats begin. Empirical rates keep
    // the point estimate capable of reaching the genuine endpoints; the prior is
    // reserved for selection and uncertainty rather than forcing every learner
    // toward 50%.
    const empirical = bands.map(band => band.answers ? band.known / band.answers : 0.5);
    const weights = bands.map(band => Math.max(1, band.answers));
    const fitted = fitMonotonicProbabilities(empirical, weights);
    const pointRaw = bands.reduce((total, band, index) =>
        total + (band.size * fitted[index]), 0);

    // Sum independent beta-binomial band uncertainty. It is intentionally a
    // conservative approximation: the result is presented as a useful range,
    // not as calibrated IRT precision that Fluency does not yet possess.
    const variance = bands.reduce((totalVariance, band) => {
        const alpha = band.known + ESTIMATION_PRIOR;
        const beta = (band.answers - band.known) + ESTIMATION_PRIOR;
        const total = alpha + beta;
        const probabilityVariance = (alpha * beta) /
            ((total * total) * (total + 1));
        return totalVariance + (band.size * band.size * probabilityVariance);
    }, 0);
    const margin = ESTIMATION_CONFIDENCE_Z * Math.sqrt(variance);

    return {
        point: roundEstimate(pointRaw, maxLevel),
        low: roundEstimate(Math.max(0, pointRaw - margin), maxLevel),
        high: roundEstimate(Math.min(maxLevel, pointRaw + margin), maxLevel)
    };
}

// Update progress display. Avoid presenting a volatile pseudo-precise rank while
// the sample is still being collected.
function updateEstimationProgress() {
    document.getElementById('estimationLevel').textContent = 'Finding your range';
    document.getElementById('estimationCount').textContent =
        `${estimationState.wordsTestedCount}/${ESTIMATION_QUESTION_LIMIT}`;
}

// Show the estimation result
function showEstimationResult() {
    estimationState.active = false;
    const result = calculateEstimationResult(
        estimationState.bands,
        estimationState.maxLevel
    );
    estimationState.estimatedLevel = result.point;
    estimationState.estimateInterval = result;

    if (estimationState.autoAdvanceTimer) {
        clearTimeout(estimationState.autoAdvanceTimer);
        estimationState.autoAdvanceTimer = null;
    }

    document.getElementById('estimationTest').style.display = 'none';
    document.getElementById('estimationResult').style.display = 'block';

    const levelEl = document.getElementById('estimationResultLevel');
    const descEl = document.getElementById('estimationResultDesc');
    if (result.point <= 0) {
        levelEl.textContent = 'Start at the beginning';
        descEl.textContent = 'This sample did not find a reliable known range yet.';
    } else {
        levelEl.textContent = `${result.low.toLocaleString()}–${result.high.toLocaleString()} words`;
        descEl.textContent =
            `Best estimate: about ${result.point.toLocaleString()} receptive words. ` +
            'The range reflects uncertainty from a short check.';
    }
}

// Apply the point estimate. The interval remains explanatory UI; the existing
// progress contract intentionally stores one backwards-compatible rank value.
function useEstimatedLevel() {
    const level = estimationState.estimatedLevel;
    levelEstimates[selectedLanguage] = level;
    saveLevelEstimateToSheet(level);
    closeEstimationModal();

    if (level === 0) {
        document.querySelector('.level-btn')?.click();
    } else {
        selectLevelForRank(level);
    }
}

function retryEstimation() {
    estimationState = createEstimationState();
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

    if (!targetLevel) return;

    const buttons = Array.from(document.querySelectorAll(
        '.level-selector-buttons .level-btn, #levelSelector > .level-btn'
    ));
    let targetIndex = buttons.findIndex(button => button.dataset.level === targetLevel.level);
    if (targetIndex < 0) {
        targetIndex = buttons.findIndex(button => {
            const start = Number(button.dataset.startRank);
            const end = Number(button.dataset.endRank);
            return Number.isFinite(start) && Number.isFinite(end) && rank >= start && rank < end;
        });
    }
    if (targetIndex < 0) return;

    const originalButton = buttons[targetIndex];
    const levelBtn = buttons.slice(targetIndex)
        .find(button => !window.isLevelMarkedDone?.(button.dataset.level))
        || buttons.slice().reverse()
            .find(button => !window.isLevelMarkedDone?.(button.dataset.level))
        || originalButton;
    levelBtn.click();
    // Only select the exact sub-range when the estimate's containing level
    // remains eligible. If it was explicitly skipped, the chosen next level's
    // normal first-unseen-set routing should take over.
    if (levelBtn === originalButton) setTimeout(() => selectRangeForRank(rank), 100);
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
            if (prevBtn?.classList.contains('range-btn')) {
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

// Pure helpers are exported for lightweight regression checks without a DOM.
export {
    buildCoverageOrder,
    buildEstimationBands,
    fitMonotonicProbabilities,
    calculateEstimationResult
};
