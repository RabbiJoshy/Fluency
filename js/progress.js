import './state.js?v=20260815b';

const SRS_DAY_MS = 24 * 60 * 60 * 1000;
const SRS_INTERVAL_DAYS = [1, 3, 7, 14, 30, 60, 120];

function parseProgressTimestamp(value) {
    if (!value) return 0;
    const timestamp = new Date(value).getTime();
    return Number.isFinite(timestamp) ? timestamp : 0;
}

// A compact, transparent v1 schedule: successful recalls graduate through
// 1, 3, 7, 14, 30, 60, and 120 days. New writes persist an explicit stage;
// legacy rows derive a conservative initial stage from their lifetime totals.
function getSrsStage(progress) {
    const explicit = Number(progress?.srsStage);
    if (progress?.srsStage !== null && progress?.srsStage !== ''
            && Number.isFinite(explicit) && explicit >= 0) {
        return Math.min(Math.floor(explicit), SRS_INTERVAL_DAYS.length);
    }
    const correct = Math.max(0, Number(progress?.correct) || 0);
    const wrong = Math.max(0, Number(progress?.wrong) || 0);
    if (correct === 0) return 0;
    return Math.min(Math.max(1, correct - wrong), SRS_INTERVAL_DAYS.length);
}

function getSrsIntervalDays(progress) {
    const stage = getSrsStage(progress);
    return stage > 0 ? SRS_INTERVAL_DAYS[stage - 1] : null;
}

function advanceSrsStage(progress, isCorrect) {
    if (!isCorrect) return 0;
    return Math.min(getSrsStage(progress) + 1, SRS_INTERVAL_DAYS.length);
}

// The learner's current relationship with a card. Counts preserve history;
// timestamps decide the latest outcome and whether a resolved card is due.
// Older rows can lack timestamps, so a recorded correct is treated as current
// until a dated answer establishes a review schedule.
function getProgressState(progress, now = Date.now()) {
    const correct = Math.max(0, Number(progress?.correct) || 0);
    const wrong = Math.max(0, Number(progress?.wrong) || 0);
    const lastCorrect = parseProgressTimestamp(progress?.lastCorrect);
    const lastWrong = parseProgressTimestamp(progress?.lastWrong);
    const lastSeen = parseProgressTimestamp(progress?.lastSeen);
    const seen = correct > 0 || wrong > 0 || lastCorrect > 0 || lastWrong > 0 || lastSeen > 0;

    if (!seen) {
        return {
            status: 'unseen', seen: false, needsReview: false, learned: false,
            known: false, isDue: false, reviewReason: null, intervalDays: null,
            nextReviewAt: 0, reviewAt: 0, lastCorrect, lastWrong, lastSeen
        };
    }

    let needsReview = false;
    if (wrong > 0 || lastWrong > 0) {
        if (lastWrong > 0 || lastCorrect > 0) {
            needsReview = lastWrong > lastCorrect;
        } else {
            // Legacy count-only rows cannot reveal answer order. A card that
            // was never correct is unresolved; any recorded correct resolves
            // it until a newer dated wrong arrives.
            needsReview = correct === 0;
        }
    }

    const unresolved = needsReview;
    const intervalDays = !unresolved && lastCorrect > 0
        ? getSrsIntervalDays(progress)
        : null;
    const nextReviewAt = intervalDays ? lastCorrect + intervalDays * SRS_DAY_MS : 0;
    const nowTime = Number.isFinite(Number(now)) ? Number(now) : Date.now();
    // The schedule can be paused while the app/content are under active
    // development. Pausing suppresses only time-based due status: explicit
    // mistakes still need review, and stages/timestamps remain intact so the
    // same schedule resumes when the learner turns it back on.
    const scheduleEnabled = typeof spacedRepetitionEnabled === 'undefined'
        ? true
        : spacedRepetitionEnabled;
    const isDue = scheduleEnabled && !unresolved && nextReviewAt > 0 && nowTime >= nextReviewAt;
    needsReview = unresolved || isDue;

    return {
        status: needsReview ? 'review' : 'learned',
        seen: true,
        needsReview,
        learned: !needsReview,
        // `known` preserves coverage after a card becomes due; `learned`
        // means currently up to date and drives the green/amber set state.
        known: !unresolved && correct > 0,
        isDue,
        reviewReason: unresolved ? 'incorrect' : (isDue ? 'due' : null),
        intervalDays,
        nextReviewAt,
        reviewAt: unresolved ? (lastWrong || lastSeen) : (isDue ? nextReviewAt : 0),
        lastCorrect,
        lastWrong,
        lastSeen
    };
}

function getWordProgressState(fullId) {
    return getProgressState(progressData?.[fullId]);
}

function calculateCoveragePercent() {
    if (!ppmData || ppmData.length === 0 || !progressData) return { pct: 0, wordsCovered: 0, totalWords: 0 };

    // Build compositeId→ppmEntry lookup once for performance.
    // ppmData entries have raw hex IDs (e.g. "91c4e7") but progressData keys
    // are composite IDs (e.g. "es191c4e7"), so we must build composite keys.
    const lang = (window.LANG_CODES || {})[selectedLanguage] || selectedLanguage.slice(0, 2);
    const mode = activeArtist ? '1' : '0';
    const idToPpm = {};
    let totalWords = 0;
    for (const entry of ppmData) {
        if (entry.id) {
            if (hideSingleOccurrence && entry.ppm <= 1) continue;
            const compositeId = `${lang}${mode}${entry.id}`;
            idToPpm[compositeId] = entry;
            totalWords++;
        }
    }

    let coveredPpm = 0;
    let wordsCovered = 0;
    const coveredIds = new Set(); // track already-counted IDs to avoid double-counting cross-mode
    for (const [wordId, data] of Object.entries(progressData)) {
        if (data.language === selectedLanguage && getProgressState(data).known) {
            // Check direct match first, then cross-mode match
            let ppmEntry = idToPpm[wordId];
            let matchedId = wordId;
            if (!ppmEntry) {
                const crossId = getCrossModeId(wordId);
                if (crossId) {
                    ppmEntry = idToPpm[crossId];
                    matchedId = crossId;
                }
            }
            if (ppmEntry && !coveredIds.has(matchedId)) {
                coveredPpm += ppmEntry.ppm;
                wordsCovered++;
                coveredIds.add(matchedId);
            }
        }
    }

    const pct = totalPpm > 0 ? (coveredPpm / totalPpm) * 100 : 0;
    return { pct, wordsCovered, totalWords };
}


// Update inline info text for lemma and cognate exclusion counts
async function updateExclusionBars() {
    const langConfig = config.languages[selectedLanguage];
    if (!langConfig || (!langConfig.dataPath && !langConfig.indexPath)) return;

    let vocabularyData = cachedVocabularyData;
    if (!vocabularyData) {
        try {
            vocabularyData = await fetchActiveVocabularyData(langConfig);
        } catch (error) {
            console.error('Failed to load vocabulary for exclusion info:', error);
            return;
        }
    }

    // Assign ranks if needed
    vocabularyData.forEach((item, index) => { if (!item.rank) item.rank = index + 1; });

    const prepared = window.getPreparedSetupVocabulary?.(selectedLanguage, vocabularyData);
    const { vocab: afterCognate, counts } = prepared || buildFilteredVocab(vocabularyData);

    // Update lemma info line
    const lemmaInfo = document.getElementById('lemmaInfoLine');
    if (lemmaInfo) {
        const lemmaExcluded = counts.lemma || 0;
        if (useLemmaMode && lemmaFieldAvailable && lemmaExcluded > 0) {
            lemmaInfo.textContent = `${afterCognate.length.toLocaleString()} cards · ${lemmaExcluded.toLocaleString()} forms merged`;
            lemmaInfo.style.display = '';
        } else {
            lemmaInfo.style.display = 'none';
        }
    }

    // Update cognate info line
    const cognateInfo = document.getElementById('cognateInfoLine');
    if (cognateInfo) {
        const cognateExcluded = counts.cognates || 0;
        if (excludeCognates && cognateFieldAvailable && cognateExcluded > 0) {
            cognateInfo.innerHTML = `${afterCognate.length.toLocaleString()} cards<br>(${cognateExcluded.toLocaleString()} cognates excluded)`;
            cognateInfo.style.display = '';
        } else {
            cognateInfo.style.display = 'none';
        }
    }

    // Update personal coverage bar
    updatePersonalCoverage(afterCognate);
}

// Show the "Estimate your level" CTA in the same slot where the coverage bar
// lives — only when the user has no progress yet AND no prior level estimate
// for the current language. Hidden as soon as either exists (coverage bar
// takes over in that case).
function _toggleLevelEstimateCTA(hasCoverage) {
    const cta = document.getElementById('levelEstimateCTA');
    if (!cta) return;
    if (hasCoverage) { cta.style.display = 'none'; return; }
    const hasEstimate = typeof levelEstimates === 'object'
        && levelEstimates
        && levelEstimates[selectedLanguage]
        && levelEstimates[selectedLanguage] > 0;
    cta.style.display = (!hasEstimate && selectedLanguage) ? 'flex' : 'none';
}

// Personal coverage bar: what % of the lyrics the user has covered,
// weighted by word frequency (corpus_count). A common word contributes
// more to coverage than a rare one, matching the "% lyrics coverage" logic.
function updatePersonalCoverage(filteredVocab) {
    const wrapper = document.getElementById('personalCoverageWrapper');
    const fill = document.getElementById('personalCoverageFill');
    const label = document.getElementById('personalCoverageLabel');
    if (!wrapper || !fill || !label) return;

    const showEmptyStandardSummary = () => {
        const merged = !activeArtist && document.getElementById('step1')?.classList.contains('language-summary-active');
        if (merged) {
            wrapper.style.display = 'block';
            wrapper.classList.add('personal-coverage-wrapper--empty', 'visible');
            fill.style.width = '0%';
            label.innerHTML = '';
        } else {
            wrapper.style.display = 'none';
        }
    };

    if (!progressData || !filteredVocab || filteredVocab.length === 0) {
        if (activeArtist && artistVocabularyScope === 'main') window.updateArtistExtraUnlock?.(0);
        showEmptyStandardSummary();
        _toggleLevelEstimateCTA(false);
        return;
    }

    // Frequency-weighted coverage: sum corpus_count of mastered words / total corpus_count
    let coveredFreq = 0;
    let totalFreq = 0;
    let coveredCount = 0;
    for (const item of filteredVocab) {
        const freq = item.corpus_count || 1;
        totalFreq += freq;
        const fullId = getWordId(item);
        // Check progress in both current mode and cross-mode
        const progress = progressData[fullId] || (getCrossModeId(fullId) ? progressData[getCrossModeId(fullId)] : null);
        if (progress && progress.language === selectedLanguage) {
            const lastCorrect = progress.lastCorrect ? new Date(progress.lastCorrect).getTime() : 0;
            const lastWrong = progress.lastWrong ? new Date(progress.lastWrong).getTime() : 0;
            if (lastCorrect > 0 && lastCorrect >= lastWrong) {
                coveredFreq += freq;
                coveredCount++;
            }
        }
    }

    if (coveredCount === 0) {
        if (activeArtist && artistVocabularyScope === 'main') window.updateArtistExtraUnlock?.(0);
        showEmptyStandardSummary();
        _toggleLevelEstimateCTA(false);
        return;
    }

    const coveragePct = (coveredFreq / totalFreq) * 100;
    if (activeArtist && artistVocabularyScope === 'main') {
        window.updateArtistExtraUnlock?.(coveragePct);
    }

    // Animate the bar
    _toggleLevelEstimateCTA(true);
    wrapper.style.display = 'block';
    wrapper.classList.remove('personal-coverage-wrapper--empty');
    wrapper.classList.remove('visible');
    fill.style.transition = 'none';
    fill.style.width = '0%';

    const coverageType = activeArtist
        ? (artistVocabularyScope === 'extra' ? `${activeArtist.name || 'Artist'} Extra explored` : 'lyrics understood')
        : 'speech understood';
    const wordPct = (coveredCount / filteredVocab.length * 100).toFixed(1);
    // Two-column rows so the percentages right-align to the same edge —
    // labels on the left, numbers stacked on the right. Drops the italic
    // styling for a cleaner read.
    label.innerHTML = `
        <span class="ppi-row"><span class="ppi-label">${coverageType}</span><span class="ppi-value">${coveragePct.toFixed(1)}%</span></span>
        <span class="ppi-row"><span class="ppi-label">flashcards learned</span><span class="ppi-value">${wordPct}%</span></span>
    `;

    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            fill.style.transition = 'width 1s ease-out';
            fill.style.width = Math.min(coveragePct, 100) + '%';
            wrapper.classList.add('visible');
        });
    });
}

// Setup tooltip handlers (needs to run early, before any set is picked)

window.calculateCoveragePercent = calculateCoveragePercent;
window.parseProgressTimestamp = parseProgressTimestamp;
window.getSrsStage = getSrsStage;
window.getSrsIntervalDays = getSrsIntervalDays;
window.advanceSrsStage = advanceSrsStage;
window.getProgressState = getProgressState;
window.getWordProgressState = getWordProgressState;
window.updateExclusionBars = updateExclusionBars;
window.updatePersonalCoverage = updatePersonalCoverage;
