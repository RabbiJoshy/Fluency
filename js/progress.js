import './state.js';

function calculateCoveragePercent() {
    if (!ppmData || ppmData.length === 0 || !progressData) return 0;

    // Build id→ppmEntry lookup once for performance
    const idToPpm = {};
    for (const entry of ppmData) {
        if (entry.id) idToPpm[entry.id] = entry;
    }

    let coveredPpm = 0;
    for (const [wordId, data] of Object.entries(progressData)) {
        if (data.language === selectedLanguage && data.correct > 0) {
            const ppmEntry = idToPpm[wordId];
            if (ppmEntry) {
                if (hideSingleOccurrence && ppmEntry.ppm <= 1) continue;
                coveredPpm += ppmEntry.ppm;
            }
        }
    }

    return totalPpm > 0 ? (coveredPpm / totalPpm) * 100 : 0;
}

// Show/update animated coverage progress bar on the setup page
function updateCoverageProgressBar() {
    const wrapper = document.getElementById('coverageBarWrapper');
    const fill = document.getElementById('coverageBarFill');
    const label = document.getElementById('coverageBarLabel');
    if (!wrapper || !fill || !label) return;

    // Only show if ppmData is available and user has progress
    if (!ppmData || ppmData.length === 0 || !progressData) {
        wrapper.style.display = 'none';
        return;
    }

    const coverage = calculateCoveragePercent();
    if (coverage <= 0) {
        wrapper.style.display = 'none';
        return;
    }

    // Reset animation — start from 0 width
    wrapper.style.display = 'block';
    wrapper.classList.remove('visible');
    fill.style.transition = 'none';
    fill.style.width = '0%';

    const coverageLabel = isBadBunnyMode ? 'lyrics coverage' : 'corpus coverage';
    label.textContent = `${coverage.toFixed(1)}% ${coverageLabel}`;

    // Trigger animation after a frame
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            fill.style.transition = 'width 1.2s ease-out';
            fill.style.width = Math.min(coverage, 100) + '%';
            wrapper.classList.add('visible');
        });
    });
}

// Update inline info text for lemma and cognate exclusion counts
async function updateExclusionBars() {
    const langConfig = config.languages[selectedLanguage];
    if (!langConfig || !langConfig.dataPath) return;

    let vocabularyData = cachedVocabularyData;
    if (!vocabularyData) {
        try {
            const response = await fetch(langConfig.dataPath);
            if (response.ok) {
                vocabularyData = await response.json();
            }
        } catch (error) {
            console.error('Failed to load vocabulary for exclusion info:', error);
            return;
        }
    }

    // Assign ranks if needed
    vocabularyData.forEach((item, index) => { if (!item.rank) item.rank = index + 1; });

    // Base filter: non-blank, non-duplicate, has meanings
    let baseVocab = vocabularyData.filter(item =>
        item.word && item.word.trim() !== '' && !item.duplicate && item.meanings && item.meanings.length > 0
    );

    if (isBadBunnyMode) {
        baseVocab = baseVocab.filter(item =>
            !item.is_english && !item.is_interjection && !item.is_propernoun
        );
    }

    if (hideSingleOccurrence && baseVocab.length > 0 && baseVocab[0].hasOwnProperty('corpus_count')) {
        baseVocab = baseVocab.filter(item => item.corpus_count > 1);
    }

    const totalBeforeLemma = baseVocab.length;

    let afterLemma = baseVocab;
    if (useLemmaMode && lemmaFieldAvailable) {
        afterLemma = baseVocab.filter(item => item.most_frequent_lemma_instance === true);
    }
    const totalAfterLemma = afterLemma.length;

    let afterCognate = afterLemma;
    if (excludeCognates && cognateFieldAvailable) {
        afterCognate = afterLemma.filter(item => !item.is_transparent_cognate);
    }
    const totalAfterCognate = afterCognate.length;

    // Update lemma info line
    const lemmaInfo = document.getElementById('lemmaInfoLine');
    if (lemmaInfo) {
        const lemmaExcluded = totalBeforeLemma - totalAfterLemma;
        if (useLemmaMode && lemmaFieldAvailable && lemmaExcluded > 0) {
            lemmaInfo.textContent = `${totalAfterLemma.toLocaleString()} / ${totalBeforeLemma.toLocaleString()} words`;
            lemmaInfo.style.display = '';
        } else {
            lemmaInfo.style.display = 'none';
        }
    }

    // Update cognate info line
    const cognateInfo = document.getElementById('cognateInfoLine');
    if (cognateInfo) {
        const cognateExcluded = totalAfterLemma - totalAfterCognate;
        if (excludeCognates && cognateFieldAvailable && cognateExcluded > 0) {
            cognateInfo.textContent = `${totalAfterCognate.toLocaleString()} words (${cognateExcluded.toLocaleString()} cognates excluded)`;
            cognateInfo.style.display = '';
        } else {
            cognateInfo.style.display = 'none';
        }
    }

    // Update personal coverage bar
    updatePersonalCoverage(afterCognate);
}

// Personal coverage bar: what % of the full eligible corpus the user has
// correctly answered, where "correct" means the last answer was correct.
function updatePersonalCoverage(filteredVocab) {
    const wrapper = document.getElementById('personalCoverageWrapper');
    const fill = document.getElementById('personalCoverageFill');
    const label = document.getElementById('personalCoverageLabel');
    if (!wrapper || !fill || !label) return;

    if (!progressData || !filteredVocab || filteredVocab.length === 0) {
        wrapper.style.display = 'none';
        return;
    }

    // Count how many words in the full filtered corpus were last answered correctly
    let coveredCount = 0;
    for (const item of filteredVocab) {
        const fullId = getWordId(item);
        const progress = progressData[fullId];
        if (progress && progress.language === selectedLanguage) {
            // "Last answer correct": lastCorrect is more recent than lastWrong
            const lastCorrect = progress.lastCorrect ? new Date(progress.lastCorrect).getTime() : 0;
            const lastWrong = progress.lastWrong ? new Date(progress.lastWrong).getTime() : 0;
            if (lastCorrect > 0 && lastCorrect >= lastWrong) {
                coveredCount++;
            }
        }
    }

    if (coveredCount === 0) {
        wrapper.style.display = 'none';
        return;
    }

    const coveragePct = (coveredCount / filteredVocab.length) * 100;

    // Animate the bar
    wrapper.style.display = 'block';
    wrapper.classList.remove('visible');
    fill.style.transition = 'none';
    fill.style.width = '0%';

    const coverageType = isBadBunnyMode ? 'lyrics' : 'words';
    label.textContent = `${coveredCount.toLocaleString()} / ${filteredVocab.length.toLocaleString()} ${coverageType} practiced`;

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
window.updateCoverageProgressBar = updateCoverageProgressBar;
window.updateExclusionBars = updateExclusionBars;
window.updatePersonalCoverage = updatePersonalCoverage;
