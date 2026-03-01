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

// Update exclusion progress bars for lemma and cognate steps
async function updateExclusionBars() {
    const langConfig = config.languages[selectedLanguage];
    if (!langConfig || !langConfig.dataPath) return;

    let vocabularyData = [];
    try {
        const response = await fetch(langConfig.dataPath);
        if (response.ok) {
            vocabularyData = await response.json();
        }
    } catch (error) {
        console.error('Failed to load vocabulary for exclusion bars:', error);
        return;
    }

    // Assign ranks
    vocabularyData.forEach((item, index) => { item.rank = index + 1; });

    // Base filter: non-blank, non-duplicate, has meanings
    let baseVocab = vocabularyData.filter(item =>
        item.word && item.word.trim() !== '' && !item.duplicate && item.meanings && item.meanings.length > 0
    );

    // Bad Bunny mode exclusions
    if (isBadBunnyMode) {
        baseVocab = baseVocab.filter(item =>
            !item.is_english && !item.is_interjection && !item.is_propernoun
        );
    }

    // Hide single-occurrence words if enabled
    if (hideSingleOccurrence && baseVocab.length > 0 && baseVocab[0].hasOwnProperty('corpus_count')) {
        baseVocab = baseVocab.filter(item => item.corpus_count > 1);
    }

    const totalBeforeLemma = baseVocab.length;

    // Count after lemma filter
    let afterLemma = baseVocab;
    if (useLemmaMode && lemmaFieldAvailable) {
        afterLemma = baseVocab.filter(item => item.most_frequent_lemma_instance === true);
    }
    const totalAfterLemma = afterLemma.length;

    // Count after cognate filter (applied on top of lemma)
    let afterCognate = afterLemma;
    if (excludeCognates && cognateFieldAvailable) {
        afterCognate = afterLemma.filter(item => !item.is_transparent_cognate);
    }
    const totalAfterCognate = afterCognate.length;

    // Update lemma exclusion bar
    const lemmaWrapper = document.getElementById('lemmaExclusionBarWrapper');
    const lemmaFill = document.getElementById('lemmaExclusionBarFill');
    const lemmaLabel = document.getElementById('lemmaExclusionBarLabel');
    if (lemmaWrapper && lemmaFill && lemmaLabel) {
        const lemmaExcluded = totalBeforeLemma - totalAfterLemma;
        if (useLemmaMode && lemmaFieldAvailable && lemmaExcluded > 0) {
            const remainPercent = (totalAfterLemma / totalBeforeLemma) * 100;
            lemmaWrapper.style.display = 'block';
            lemmaWrapper.classList.remove('visible');
            lemmaFill.style.transition = 'none';
            lemmaFill.style.width = '0%';
            lemmaLabel.textContent = `${totalAfterLemma.toLocaleString()} / ${totalBeforeLemma.toLocaleString()} words (${lemmaExcluded.toLocaleString()} forms excluded)`;
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    lemmaFill.style.transition = 'width 0.8s ease-out';
                    lemmaFill.style.width = remainPercent + '%';
                    lemmaWrapper.classList.add('visible');
                });
            });
        } else {
            lemmaWrapper.style.display = 'none';
        }
    }

    // Update cognate exclusion bar
    const cognateWrapper = document.getElementById('cognateExclusionBarWrapper');
    const cognateFill = document.getElementById('cognateExclusionBarFill');
    const cognateLabel = document.getElementById('cognateExclusionBarLabel');
    if (cognateWrapper && cognateFill && cognateLabel) {
        const cognateExcluded = totalAfterLemma - totalAfterCognate;
        if (excludeCognates && cognateFieldAvailable && cognateExcluded > 0) {
            const remainPercent = (totalAfterCognate / totalAfterLemma) * 100;
            cognateWrapper.style.display = 'block';
            cognateWrapper.classList.remove('visible');
            cognateFill.style.transition = 'none';
            cognateFill.style.width = '0%';
            cognateLabel.textContent = `${totalAfterCognate.toLocaleString()} / ${totalAfterLemma.toLocaleString()} words (${cognateExcluded.toLocaleString()} cognates excluded)`;
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    cognateFill.style.transition = 'width 0.8s ease-out';
                    cognateFill.style.width = remainPercent + '%';
                    cognateWrapper.classList.add('visible');
                });
            });
        } else {
            cognateWrapper.style.display = 'none';
        }
    }
}

// Setup tooltip handlers (needs to run early, before any set is picked)

window.calculateCoveragePercent = calculateCoveragePercent;
window.updateCoverageProgressBar = updateCoverageProgressBar;
window.updateExclusionBars = updateExclusionBars;
