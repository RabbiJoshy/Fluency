// Setup panel UI: language tabs, CEFR level selector, range/set buttons.
// Key functions: renderLanguageTabs(), renderLevelSelector(), renderRangeSelector().
import './state.js';

function setupTooltipHandlers() {
    // Step help tooltip handlers — open as modal
    document.querySelectorAll('.step-help-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            const tooltipId = this.dataset.tooltip;
            const tooltip = document.getElementById(tooltipId);

            // Close all other tooltips first
            document.querySelectorAll('.step-info-tooltip').forEach(t => {
                if (t.id !== tooltipId) t.classList.remove('visible');
            });

            tooltip.classList.toggle('visible');
        });
    });

    // Close tooltip modal on backdrop click (click on outer overlay, not inner content)
    document.querySelectorAll('.step-info-tooltip').forEach(tooltip => {
        tooltip.addEventListener('click', function(e) {
            if (e.target === this) this.classList.remove('visible');
        });
    });

    // Cognate rules modal — opens from the "More Detail →" button inside
    // the Cognates tab of the step2 help tooltip. The standalone
    // #cognateTooltip element is gone (its content was folded into
    // step2Tooltip's tabbed layout), so we close step2Tooltip instead.
    document.getElementById('cognateRulesBtn').addEventListener('click', function(e) {
        e.stopPropagation();
        const step2Tip = document.getElementById('step2Tooltip');
        if (step2Tip) step2Tip.classList.remove('visible');
        document.getElementById('cognateRulesModal').classList.remove('hidden');
    });

    // Wire tab switching inside the step2 help tooltip (Choose Level /
    // Cards per Lemma / Cognates). Reuses the generic setupTabSwitching
    // helper used by the settings + help modals.
    const step2Tip = document.getElementById('step2Tooltip');
    if (step2Tip) setupTabSwitching(step2Tip);

    document.getElementById('closeCognateRulesModal').addEventListener('click', function() {
        document.getElementById('cognateRulesModal').classList.add('hidden');
    });

    // Button info icon handlers
    document.querySelectorAll('.btn-info-icon').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            const infoId = this.dataset.info;
            const tooltip = document.getElementById(infoId);

            // Close all other btn-info-tooltips first
            document.querySelectorAll('.btn-info-tooltip').forEach(t => {
                if (t.id !== infoId) {
                    t.classList.remove('visible');
                }
            });

            // Toggle this tooltip
            tooltip.classList.toggle('visible');
        });
    });

    // Close btn-info-tooltips when clicking outside
    document.addEventListener('click', function(e) {
        if (!e.target.closest('.btn-info-icon') && !e.target.closest('.btn-info-tooltip')) {
            document.querySelectorAll('.btn-info-tooltip').forEach(t => {
                t.classList.remove('visible');
            });
        }
    });
}

// Update incorrect button visibility - now handled by renderRangeSelector
function updateIncorrectButtonVisibility() {
    // This function is now a no-op since incorrect button is rendered dynamically
    // in renderRangeSelector. Keeping for backwards compatibility.
    if (selectedLevel) {
        renderRangeSelector().catch(err => console.error('Error refreshing ranges:', err));
    }
}

function setActiveSetupStep(stepId) {
    document.querySelectorAll('#step1 .step-number, #step2 .step-number, #step4 .step-number')
        .forEach(number => number.classList.toggle('--active', number.closest('.setup-step')?.id === stepId));
}

function mergeStandardProgressIntoLanguageStep() {
    if (activeArtist) return;
    const step = document.getElementById('step1');
    const header = document.getElementById('step1Header');
    const wrapper = document.getElementById('personalCoverageWrapper');
    const progressHeader = wrapper && wrapper.querySelector('.personal-progress-header');
    const inlinePill = document.getElementById('selectedLanguageInline');
    if (!step || !header || !wrapper || !progressHeader || !inlinePill) return;

    progressHeader.prepend(inlinePill);
    header.appendChild(wrapper);
    step.classList.add('language-summary-active');
    wrapper.classList.add('personal-coverage-wrapper--merged', 'personal-coverage-wrapper--empty', 'visible');
    wrapper.style.display = 'block';
}

function unmergeStandardProgressFromLanguageStep() {
    if (activeArtist) return;
    const step = document.getElementById('step1');
    const header = document.getElementById('step1Header');
    const title = document.getElementById('step1Title');
    const wrapper = document.getElementById('personalCoverageWrapper');
    const inlinePill = document.getElementById('selectedLanguageInline');
    const cta = document.getElementById('levelEstimateCTA');
    if (!step || !header || !title || !wrapper || !inlinePill || !cta) return;

    title.after(inlinePill);
    cta.after(wrapper);
    step.classList.remove('language-summary-active');
    wrapper.classList.remove('personal-coverage-wrapper--merged', 'personal-coverage-wrapper--empty', 'visible');
    wrapper.style.display = 'none';
}

function renderLanguageTabs() {
    const tabsContainer = document.getElementById('languageTabs');

    // Define custom language order (Polish before grayed-out French and Russian)
    const languageOrder = ['spanish', 'swedish', 'italian', 'dutch', 'polish', 'french', 'russian'];
    const languages = languageOrder.filter(lang => config.languages[lang]);

    // Map language keys to 2-letter codes
    const langCodeMap = {
        'dutch': 'NL',
        'polish': 'PL',
        'spanish': 'ES',
        'italian': 'IT',
        'french': 'FR',
        'russian': 'RU',
        'swedish': 'SE'
    };

    // Generate language tabs dynamically - no active state initially
    const tabsHTML = languages.map((langKey, index) => {
        const langCode = langCodeMap[langKey] || langKey.substring(0, 2).toUpperCase();
        const langConfig = config.languages[langKey];
        const hasData = langConfig.hasData !== false;
        // Don't pre-select any language - user must click to select
        const activeClass = '';
        const disabledClass = !hasData ? 'disabled' : '';
        const disabledAttr = !hasData ? 'disabled' : '';
        const title = !hasData ? `${langConfig.name} - Data coming soon` : '';
        return `<button class="lang-tab ${activeClass} ${disabledClass}" data-lang="${langKey}" ${disabledAttr} title="${title}">${langCode}</button>`;
    }).join('');

    tabsContainer.innerHTML = `
        <button type="button" id="languagePickerBtn" class="language-picker-btn" aria-haspopup="dialog">
            <span class="language-picker-btn-icon" aria-hidden="true">🌐</span>
            <span class="language-picker-btn-label">Choose a language</span>
            <span class="language-picker-btn-arrow" aria-hidden="true">›</span>
        </button>
        <div class="language-picker-options" aria-hidden="true">${tabsHTML}</div>
    `;

    document.getElementById('languagePickerBtn').addEventListener('click', () => {
        if (window.showLanguagePicker) window.showLanguagePicker(config.languages);
    });

    setActiveSetupStep('step1');

    // Setup event listeners for tabs
    setupLanguageTabs();
}

function setupLanguageTabs() {
    const inlinePill = document.getElementById('selectedLanguageInline');

    // Click handler for the inline language pill (to re-expand tabs)
    inlinePill.addEventListener('click', function() {
        unmergeStandardProgressFromLanguageStep();
        this.style.display = 'none';
        document.getElementById('languageTabs').style.display = 'flex';
        // Hide subsequent steps
        document.getElementById('step2').style.display = 'none';
        document.getElementById('lemmaToggleContainer').style.display = 'none';
        document.getElementById('cognateToggleContainer').style.display = 'none';
        document.getElementById('step4').style.display = 'none';
        hideAllSelectionPills();
        setActiveSetupStep('step1');
    });

    document.querySelectorAll('.lang-tab').forEach(tab => {
        tab.addEventListener('click', async function() {
            // Prevent clicking on disabled tabs
            if (this.disabled || this.classList.contains('disabled')) {
                return;
            }
            document.querySelectorAll('.lang-tab').forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            const newLanguage = this.dataset.lang;

            // Drop cached frequency data when switching languages — new
            // language will reload its own ppm. percentageMode is the user's
            // preference and persists across language switches.
            if (newLanguage !== selectedLanguage) {
                ppmData = null;
                totalPpm = 0;
            }

            selectedLanguage = newLanguage;
            selectedLevel = null;

            // Mirror the boot-time Spanish-only fetches in main.js so users
            // who land on a non-Spanish first language and switch to Spanish
            // still get rank + conjugation data. Idempotent — no-ops if
            // already loaded.
            if (newLanguage === 'spanish') {
                if (window.loadSpanishRanks) window.loadSpanishRanks();
                if (window.loadConjugationData) window.loadConjugationData();
                if (window.loadConjugatedEnglishData) window.loadConjugatedEnglishData();
            }

            applyLanguageColorTheme();

            // Show inline pill in the header, hide the tabs
            const langConfig = config.languages[selectedLanguage];
            inlinePill.textContent = langConfig ? langConfig.name : selectedLanguage;
            document.getElementById('languageTabs').style.display = 'none';
            inlinePill.style.display = 'inline-flex';
            mergeStandardProgressIntoLanguageStep();

            // Hide all subsequent steps while loading
            document.getElementById('step2').style.display = 'none';
            document.getElementById('lemmaToggleContainer').style.display = 'none';
            document.getElementById('cognateToggleContainer').style.display = 'none';
            document.getElementById('step4').style.display = 'none';
            hideAllSelectionPills();

            // Show loading indicator
            const loadingIndicator = document.getElementById('dataLoadingIndicator');
            loadingIndicator.classList.add('visible');

            // Start refreshing progress from Sheets (cache loads synchronously inside)
            let progressRefresh = Promise.resolve(false);
            if (currentUser && !currentUser.isGuest) {
                progressRefresh = loadUserProgressFromSheet();
            }

            // Always load PPM data if available (needed for coverage bar even in CEFR mode)
            const langPpmPath = config.languages[selectedLanguage] && config.languages[selectedLanguage].ppmDataPath;
            if (!ppmData && langPpmPath) {
                await loadPpmData(selectedLanguage);
            }

            // Hide loading indicator and show step 2 immediately (using cached progress)
            loadingIndicator.classList.remove('visible');
            document.getElementById('step2').style.display = 'block';
            setActiveSetupStep('step2');
            // Step 2 title is fixed ("Choose level"); refresh the toggle's
            // active pill + tooltip in case the language switch implies a
            // different mode (e.g. artist mode forces % mode).
            updatePercentModeButton();
            updateStep2Tooltip();
            updateStep5Tooltip();

            renderLevelSelector(selectedLanguage);
            updateLemmaToggleVisibility();
            updateCognateToggleVisibility();
            updateExclusionBars();
            updateIncorrectButtonVisibility();

            // When Sheets refresh completes, re-render set badges if data changed
            progressRefresh.then(changed => {
                if (changed) renderRangeSelector();
            }).catch(() => {});
            updateTotalStatsButtonVisibility();
        });
    });
}

function hideAllSelectionPills() {
    document.querySelectorAll('.selection-pill').forEach(pill => {
        pill.classList.remove('visible');
    });
}

function updatePercentModeButton() {
    // CEFR is now a single on/off toggle. "Off" (the default) means
    // percentage mode — the standard experience. "On" lights up the button
    // and switches the level selector to CEFR pills.
    const toggle = document.getElementById('levelModeToggle');
    if (!toggle) return;
    toggle.classList.toggle('active', !percentageMode);
}

function updateStep2Tooltip() {
    const tooltip = document.getElementById('step2Tooltip');
    if (!tooltip) return;
    if (activeArtist) {
        // Artist mode is always % coverage of lyrics. Keep the TABBED help
        // (Level / Lemma / Cognates) intact — only swap the Level tab's copy
        // to the lyrics-coverage explanation (no CEFR/% toggle reference).
        // Overwriting the whole tooltip here used to delete the Lemma and
        // Cognate tabs entirely, so artist mode lost those explanations.
        const name = activeArtist.name;
        const levelTab = document.getElementById('step2LevelTabContent');
        if (levelTab) {
            levelTab.innerHTML = `
                <p><strong>Lyrics coverage</strong> — each segment is how much of ${name}'s lyrics you'd recognise at that level (e.g. ~80% coverage = you know ~80% of the words across the songs).</p>
                <p><strong>Drag the scrubber</strong> to pick how many words you want; the centred segment is your level. Its label is the minimum frequency it includes (e.g. <em>≥10</em> = words appearing at least 10 times in the discography).</p>
                <p>Lower segments are the most common words; higher segments add rarer vocabulary that adds less coverage.</p>
            `;
        }
    }
    // Non-artist modes: leave the static HTML in place (it explains both
    // CEFR and % alongside the toggle that switches between them).
}

function updateStep5Tooltip() {
    const tooltip = document.getElementById('step5Tooltip');
    if (activeArtist) {
        const name = activeArtist.name;
        tooltip.innerHTML = `
            <p>Each set contains words ranked by frequency in ${name}'s lyrics (e.g., 1-25 = most common words).</p>
            <p><strong>Set size toggle (25/50)</strong> controls how many cards per set.</p>
            <p><strong>Example sentences</strong> are designed to use words from nearby ranks, so practicing set 1-25 means sentences mostly use words from that same group.</p>
        `;
    } else {
        tooltip.innerHTML = `
            <p>Each set contains words ranked by frequency (e.g., 1-25 = most common words).</p>
            <p><strong>Example sentences</strong> are designed to use words from nearby ranks (within ~20 positions), so practicing set 1-25 means sentences mostly use words from that same group.</p>
            <p><strong>Set size toggle (25/50)</strong> controls how many cards per set.</p>
        `;
    }
}

// Returns the first .level-btn whose level isn't fully completed, using the
// same per-word "known" check the range buttons use (rank inside the user's
// level estimate OR ≥1 correct attempt). Returns the LAST button if every
// level is complete (you've maxed out — land on the most-advanced level so
// you don't bounce off into nothing). Returns null on data-load failure;
// caller falls back to the first button.
async function findFirstIncompleteLevelBtn(language, buttons) {
    const langConfig = config.languages[language];
    if (!langConfig) return null;
    const vocabularyData = await fetchActiveVocabularyData(langConfig);
    const { vocab: filteredVocab } = buildFilteredVocab(vocabularyData);
    const estimate = levelEstimates[language] || 0;
    const wordKnown = (item) => (item.rank <= estimate) || isWordKnown(getWordId(item));

    for (const btn of buttons) {
        let minWord, maxWord;
        let rankBasis = 'source';
        if (percentageMode && ppmData && ppmData.length > 0) {
            minWord = parseInt(btn.dataset.startRank);
            maxWord = parseInt(btn.dataset.endRank);
            rankBasis = btn.dataset.rankBasis || 'source';
        } else {
            const cefrLevels = getCefrLevels(language);
            const lv = cefrLevels.find(l => l.level === btn.dataset.level);
            if (!lv) continue;
            [minWord, maxWord] = lv.wordCount.split('-').map(Number);
        }
        const wordsInLevel = filteredVocab.filter(it => {
            const rank = rankBasis === 'display' ? it.displayRank : it.rank;
            return rank >= minWord && rank < maxWord;
        });
        if (wordsInLevel.length === 0) continue;
        if (!wordsInLevel.every(wordKnown)) return btn;
    }
    return buttons[buttons.length - 1];
}

async function renderLevelSelector(language) {
    const container = document.getElementById('levelSelector');

    if (useLemmaMode) {
        await ensureLemmaPoolingData(config.languages[language]);
    }
    if (!selectedLevel) setActiveSetupStep('step2');

    // Debug logging
    console.log('renderLevelSelector called:', { percentageMode, ppmDataLength: ppmData ? ppmData.length : 0, language });

    // Use percentage levels if in percentage mode with PPM data.
    // In percentage mode the user picks a level via a log-spaced slider:
    // each snap point is one of the percentageLevels (70%, 80%, …, 100%).
    // The level buttons are still rendered (hidden) because renderRangeSelector
    // and other code paths read .level-btn.selected for startRank/endRank.
    if (percentageMode && ppmData && ppmData.length > 0) {
        // Smart segment boundaries (both modes): pick snap points that
        // target ~equal cards-per-segment with frequency-cliff labels
        // where the cliffs exist in the data. Algorithm auto-scales —
        // artist mode (raw counts 2–500) gets cliffs like ≥50/≥20/…/≥2;
        // normal mode (occurrences_ppm 1–50000) gets cliffs in the
        // thousands. Falls back to the legacy coverage-threshold ranges
        // if the vocab cache isn't available yet.
        _smartLevelRangesCache = null;
        await _loadLevelSliderSamples(selectedLanguage);
        const _raw = _levelSliderRawCache[selectedLanguage];
        if (_raw) {
            const { vocab: filtered } = buildFilteredVocab(_raw);
            _smartLevelRangesCache = computeSmartLevelRanges(filtered);
        }
        const percentageRanges = getActiveLevelRanges();
        console.log('Using percentage levels:', percentageRanges);
        const coverageType = activeArtist ? 'lyrics comprehension' : 'speech comprehension';
        const buttonsHTML = percentageRanges.map(level => {
            const description = level.description || `${level.level} ${coverageType}`;
            return `
            <button class="level-btn" data-level="${level.level}" data-short="${level.level}" data-full="${description}" data-start-rank="${level.startRank}" data-end-rank="${level.endRank}" data-rank-basis="${level.rankBasis || 'source'}" title="${description}">
                ${level.level}
            </button>
        `}).join('');

        const fmtRank = n => n >= 1000 ? (n/1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, '') + 'k' : String(n);
        // Tick labels: smart ranges supply their own (e.g. "≥10", "1.5k");
        // legacy ranges fall back to formatted endRank.
        const ticksHTML = percentageRanges.map((lv, i) => {
            const label = lv.tickLabel || fmtRank(lv.endRank);
            const tooltip = lv.description || `${lv.level} coverage → top ${lv.endRank.toLocaleString()} words`;
            return `<span data-i="${i}" title="${tooltip}">${label}</span>`;
        }).join('');

        const lastIdx = percentageRanges.length - 1;
        // Restore slider position from selectedLevel if a level is already
        // chosen — otherwise re-renders (lemma toggle, etc.) would snap the
        // thumb back to the rightmost snap and visually disagree with the
        // hidden .level-btn.selected.
        let savedIdx = selectedLevel
            ? percentageRanges.findIndex(r => r.level === selectedLevel)
            : -1;
        // Filter toggles (lemma / cognate) change the card counts, so the
        // level id `c<cardCount>` shifts and the exact match fails. Fall
        // back to the segment with the nearest card count so the scrubber
        // holds its place instead of jumping to the far right — and adopt
        // that level id so the toggle handler's re-select + renderRangeSelector
        // read a button that actually exists.
        if (savedIdx < 0 && selectedLevel && /^c\d+$/.test(selectedLevel)) {
            const targetCards = parseInt(selectedLevel.slice(1), 10);
            let bestD = Infinity;
            percentageRanges.forEach((r, i) => {
                const d = Math.abs((r.cardCount || 0) - targetCards);
                if (d < bestD) { bestD = d; savedIdx = i; }
            });
            if (savedIdx >= 0) selectedLevel = percentageRanges[savedIdx].level;
        }
        const initialIdx = savedIdx >= 0 ? savedIdx : lastIdx;
        const initial = percentageRanges[initialIdx];
        // Headline value: post-filter card count for smart ranges, raw
        // endRank for legacy ranges.
        const initialHeadline = (initial.cardCount != null ? initial.cardCount : initial.endRank).toLocaleString();
        // Coverage display: use threshold for smart ranges, level string for legacy.
        const initialCoverage = initial.threshold != null
            ? `${(initial.threshold * 100).toFixed(1)}%`
            : initial.level;
        container.classList.add('level-selector--slider');
        container.innerHTML = `
            <div class="level-slider-wrap">
                <div class="lsw-readout">
                    <span class="lsw-rank">Most common <strong id="lswRankVal">${initialHeadline}</strong> words</span>
                    <span class="lsw-coverage">~<strong id="lswCovVal">${initialCoverage}</strong> ${coverageType}</span>
                </div>
                <div id="lswSlider" class="lsw-segments lsw-scrubber" role="radiogroup" aria-label="Level scrubber" data-value="${initialIdx}">
                    ${percentageRanges.map((lv, i) => {
                        const segLabel = lv.tickLabel || fmtRank(lv.endRank);
                        return `<button type="button" class="lsw-seg${i <= initialIdx ? ' filled' : ''}${i === initialIdx ? ' selected' : ''}" data-i="${i}" role="radio" aria-checked="${i === initialIdx}"><span class="lsw-seg-label">${segLabel}</span></button>`;
                    }).join('')}
                </div>
                <div class="lsw-ticks lsw-ticks--hidden">${ticksHTML}</div>
                <div class="lsw-examples" id="lswExamples">&nbsp;</div>
            </div>
            <div class="level-selector-buttons" style="display:none">${buttonsHTML}</div>
        `;
    } else {
        container.classList.remove('level-selector--slider');
        const cefrLevels = getCefrLevels(language);
        const levelsHTML = cefrLevels.map(level => `
            <button class="level-btn" data-level="${level.level}" data-short="${level.level}" data-full="${level.level}" title="${level.description}">
                ${level.level}
            </button>
        `).join('');
        container.innerHTML = levelsHTML;
    }

    // Add click handlers for level buttons
    document.querySelectorAll('.level-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            // Reset all buttons to short text
            document.querySelectorAll('.level-btn').forEach(b => {
                b.classList.remove('selected');
                b.textContent = b.dataset.short;
            });
            // Set selected button to full text
            this.classList.add('selected');
            this.textContent = this.dataset.full;
            selectedLevel = this.dataset.level;

            // Show coverage info line with word count and frequency threshold
            updateLevelInfoLine(this);

            // Show steps 3 (lemma), 3b (cognate if available), 4 (cards per set), and 5 (range) with staggered timing
            document.getElementById('lemmaToggleContainer').style.display = 'block';

            // Show cognate toggle after lemma toggle (if available)
            setTimeout(() => {
                if (cognateFieldAvailable) {
                    document.getElementById('cognateToggleContainer').style.display = 'block';
                }
            }, 75);

            renderRangeSelector().catch(err => console.error('Error rendering ranges:', err));

            // Keep the segmented bar in sync when a (hidden) level button
            // is chosen programmatically — e.g. auto-select on first load,
            // or the "Next Level" range button. Segment-driven clicks are
            // a no-op here because the bar already matches.
            const segBar = document.getElementById('lswSlider');
            if (segBar) {
                const buttons = Array.from(document.querySelectorAll('.level-selector-buttons .level-btn'));
                const idx = buttons.indexOf(this);
                if (idx >= 0) {
                    if (+segBar.dataset.value !== idx) setLevelSegmentSelection(idx);
                    _scrollLevelSegToCenter(idx, false); // keep the scrubber centered on the picked level
                }
            }
        });
    });

    // Wire the segmented level bar: each segment = one snap point. Clicking
    // a segment selects the range from start through that segment (the
    // "line within the line" fill) and clicks the matching hidden level
    // button, which runs the existing level-selection flow.
    const segBar = document.getElementById('lswSlider');
    if (segBar) {
        const buttons = Array.from(document.querySelectorAll('.level-selector-buttons .level-btn'));
        wireLevelScrubber(segBar, buttons);
        // Prime the readout (examples need vocab to be loaded async).
        updateLevelSliderReadout(parseInt(segBar.dataset.value || '0', 10));
        // Center the scrubber on the initial selection once layout has settled.
        requestAnimationFrame(() =>
            _scrollLevelSegToCenter(parseInt(segBar.dataset.value || '0', 10), false));
    }

    // Auto-select first time only (preserves manual picks across re-renders).
    // Pick the first level that isn't fully completed so the user lands on
    // actionable work — finishing the 70% level should auto-open 80%, not
    // sit on a maxed-out set with all-100% range buttons. Falls back to the
    // first button on data-load failure or if there are no buttons.
    if (!selectedLevel) {
        const buttons = Array.from(document.querySelectorAll('.level-btn'));
        if (buttons.length === 0) return;
        let target = buttons[0];
        try {
            const incomplete = await findFirstIncompleteLevelBtn(language, buttons);
            if (incomplete) target = incomplete;
        } catch (err) {
            console.warn('Level auto-pick failed, using first', err);
        }
        // Re-check: the user may have clicked a level during the await above.
        if (!selectedLevel) target.click();
    }
}

// Smart-range cache: computed snap points for the active language under
// the active filter set. Cleared on every renderLevelSelector run so it
// always reflects current filters (re-render is the natural invalidator).
let _smartLevelRangesCache = null;

// Build ten usable study bands. Each boundary starts at an equal-card
// quantile, then snaps to a genuine frequency cliff when one is nearby.
// If no cliff is close, keeping the quantile deliberately subdivides a
// large tied tail (2x/3x in artist decks) instead of collapsing it into one
// enormous final band.
//
// In lemma mode the effective frequency is the corrected unique-example
// pool. Form mode uses corpus_count. buildFilteredVocab() has already sorted
// and assigned displayRank on that same basis, so smart ranges must retain
// displayRank all the way through selection and deck loading.
function computeSmartLevelRanges(filteredVocab) {
    if (!filteredVocab || filteredVocab.length === 0) return [];
    const items = filteredVocab;
    const total = items.length;
    const frequencyOf = (item) => {
        const raw = useLemmaMode ? item.pooled_frequency : item.corpus_count;
        const value = Number(raw);
        return Number.isFinite(value) ? Math.max(0, value) : 0;
    };
    const fmtCompact = (n) => n >= 1000
        ? (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, '') + 'k'
        : String(Math.round(n));

    const segmentCount = Math.min(10, total);
    const idealBandSize = total / segmentCount;
    const snapWindow = Math.max(2, Math.round(idealBandSize * 0.25));
    const minBandSize = Math.max(1, Math.round(idealBandSize * 0.5));

    // A cliff count is the number of cards included immediately before the
    // effective frequency drops. Counts are exclusive endpoints, matching
    // the range loader's displayRank >= start && displayRank < end contract.
    const cliffCounts = [];
    for (let count = 1; count < total; count++) {
        if (frequencyOf(items[count - 1]) !== frequencyOf(items[count])) {
            cliffCounts.push(count);
        }
    }

    const boundaryCounts = [];
    let previousCount = 0;
    for (let segment = 1; segment < segmentCount; segment++) {
        const remainingBands = segmentCount - segment;
        const minCount = previousCount + minBandSize;
        const maxCount = total - remainingBands * minBandSize;
        const idealCount = Math.round(total * segment / segmentCount);
        const targetCount = Math.max(minCount, Math.min(maxCount, idealCount));
        const nearbyCliffs = cliffCounts.filter(count =>
            count >= minCount
            && count <= maxCount
            && Math.abs(count - targetCount) <= snapWindow
        );
        const count = nearbyCliffs.length > 0
            ? nearbyCliffs.reduce((best, candidate) =>
                Math.abs(candidate - targetCount) < Math.abs(best - targetCount) ? candidate : best)
            : targetCount;
        boundaryCounts.push(count);
        previousCount = count;
    }
    boundaryCounts.push(total);

    let totalFreq = 0;
    for (const item of items) totalFreq += frequencyOf(item);

    const ranges = [];
    let cumFreq = 0;
    let previousBoundary = 0;
    for (const cardCount of boundaryCounts) {
        const endIdx = cardCount - 1;
        for (let j = previousBoundary; j <= endIdx; j++) cumFreq += frequencyOf(items[j]);
        const coverage = totalFreq > 0 ? cumFreq / totalFreq : 0;
        const freqMin = frequencyOf(items[endIdx]);
        const splitTier = cardCount < total && frequencyOf(items[cardCount]) === freqMin;
        const startRank = previousBoundary + 1;
        const endRank = cardCount + 1;

        // Level identifier — keyed by cardCount so selectedLevel round-trips
        // stably across re-renders even when several cuts share a frequency.
        const level = `c${cardCount}`;
        const tickLabel = splitTier
            ? `${fmtCompact(freqMin)}× · ${fmtCompact(cardCount)}`
            : `≥${fmtCompact(freqMin)}`;
        const basisDescription = useLemmaMode ? 'unique pooled example lines' : 'corpus occurrences';
        const description = splitTier
            ? `Top ${cardCount.toLocaleString()} cards · cutoff partway through the ${fmtCompact(freqMin)}× tier · ${(coverage * 100).toFixed(1)}% coverage by ${basisDescription}`
            : `Top ${cardCount.toLocaleString()} cards · frequency ≥${fmtCompact(freqMin)} · ${(coverage * 100).toFixed(1)}% coverage by ${basisDescription}`;

        ranges.push({
            level,
            startRank,
            endRank,
            rankBasis: 'display',
            cardCount,
            threshold: coverage,
            kind: splitTier ? 'tie-split' : 'freq-cliff',
            freqMin,
            splitTier,
            tickLabel,
            description,
        });
        previousBoundary = cardCount;
    }
    return ranges;
}

// Synchronous accessor used by updateLevelSliderReadout and friends.
// Returns the cached smart ranges if renderLevelSelector has computed
// them, otherwise falls back to the coverage-based legacy ranges.
function getActiveLevelRanges() {
    return _smartLevelRangesCache && _smartLevelRangesCache.length > 0
        ? _smartLevelRangesCache
        : getPercentageLevelRanges();
}

// Raw-vocab cache (network fetch is the slow part). Keyed by language;
// the filter pass runs fresh every call so toggling lemma/cognate/proper
// noun/noise/single-occurrence immediately reflects in the slider's
// rank counts and tick labels — no stale cache shows pre-toggle numbers.
const _levelSliderRawCache = {};

function _samplesFromRaw(rawVocab) {
    const { vocab: filtered } = buildFilteredVocab(rawVocab);
    return filtered.map(item => ({
        rank: item.rank,
        displayRank: item.displayRank,
        word: item.lemma || item.targetWord || item.word || ''
    })).filter(s => s.word);
}

// Synchronous fast path used by the slider readout/tick labels — returns
// post-filter samples if the raw vocab is already cached, otherwise null
// so the caller can fall back to raw rank numbers until the async load
// resolves.
function _levelSliderSamplesSync(language) {
    const raw = _levelSliderRawCache[language];
    return raw ? _samplesFromRaw(raw) : null;
}

async function _loadLevelSliderSamples(language) {
    let raw = _levelSliderRawCache[language];
    if (!raw) {
        const langConfig = config.languages[language];
        if (!langConfig) return null;
        try {
            raw = await fetchActiveVocabularyData(langConfig);
            _levelSliderRawCache[language] = raw;
        } catch (err) {
            console.warn('Slider sample fetch failed:', err);
            return null;
        }
    }
    return _samplesFromRaw(raw);
}

// Count post-filter items whose original rank is ≤ endRank — i.e. how
// many cards the user actually gets at this coverage threshold given the
// active filter set.
function _filteredCountUpTo(samples, endRank) {
    let n = 0;
    for (const s of samples) if (s.rank <= endRank) n++;
    return n;
}

function _formatTickRank(n) {
    if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, '') + 'k';
    return String(n);
}

// Patch the rank readout + tick labels with post-filter counts. Called
// both synchronously (with cached samples) and asynchronously after a
// fresh load, so the rank counts stay accurate across filter toggles.
//
// For smart ranges (artist mode) the snap points are already computed
// from the post-filter vocab, so cardCount is authoritative — we use it
// directly. For legacy coverage-based ranges we still need to count
// items at runtime to convert raw rank → filtered count.
function _applyFilteredRankCounts(samples) {
    if (!samples) return;
    const ranges = getActiveLevelRanges();
    const segBar = document.getElementById('lswSlider');
    const rankEl = document.getElementById('lswRankVal');
    if (segBar && rankEl && ranges.length > 0) {
        const i = parseInt(segBar.dataset.value || '0', 10);
        const lv = ranges[i];
        if (lv) {
            const n = lv.cardCount != null ? lv.cardCount : _filteredCountUpTo(samples, lv.endRank);
            rankEl.textContent = n.toLocaleString();
        }
    }
    document.querySelectorAll('#levelSelector .lsw-ticks span').forEach((el) => {
        const i = parseInt(el.dataset.i, 10);
        const lv = ranges[i];
        if (!lv) return;
        const n = lv.cardCount != null ? lv.cardCount : _filteredCountUpTo(samples, lv.endRank);
        el.textContent = lv.tickLabel || _formatTickRank(n);
        el.title = lv.description || `${lv.level} coverage → top ${n.toLocaleString()} words`;
    });
}

// Update the segmented level bar's selection state. Highlights all
// segments up to (and including) the chosen index — the "line within
// the line" fill — and stores the value on the bar's dataset so other
// code can read it back synchronously the way it used to read
// slider.value. Also re-runs the readout so headline + tick labels
// follow the new selection.
function setLevelSegmentSelection(idx) {
    const segBar = document.getElementById('lswSlider');
    if (!segBar) return;
    segBar.dataset.value = String(idx);
    segBar.querySelectorAll('.lsw-seg').forEach(seg => {
        const i = parseInt(seg.dataset.i, 10);
        seg.classList.toggle('filled', i <= idx);
        seg.classList.toggle('selected', i === idx);
        seg.setAttribute('aria-checked', i === idx ? 'true' : 'false');
    });
    updateLevelSliderReadout(idx);
}

// --- Horizontal level scrubber ---------------------------------------------
// The level segments render as a horizontal scroll-snap "ruler": you scrub
// left→right (touch swipe / trackpad) and the CENTERED segment is the selected
// level (magnified). It reuses setLevelSegmentSelection + the hidden .level-btn,
// so all downstream selection logic is unchanged — only the presentation is.
let _levelProgrammaticScroll = false;

function _levelCenteredIdx(bar) {
    const mid = bar.scrollLeft + bar.clientWidth / 2;
    let best = 0, bestD = Infinity;
    bar.querySelectorAll('.lsw-seg').forEach(s => {
        const i = parseInt(s.dataset.i, 10);
        const c = s.offsetLeft + s.offsetWidth / 2;
        const d = Math.abs(c - mid);
        if (d < bestD) { bestD = d; best = i; }
    });
    return best;
}

function _scrollLevelSegToCenter(idx, smooth) {
    const bar = document.getElementById('lswSlider');
    if (!bar) return;
    const seg = bar.querySelector('.lsw-seg[data-i="' + idx + '"]');
    if (!seg) return;
    _levelProgrammaticScroll = true;
    const target = seg.offsetLeft + seg.offsetWidth / 2 - bar.clientWidth / 2;
    bar.scrollTo({ left: Math.max(0, target), behavior: smooth ? 'smooth' : 'auto' });
    setTimeout(() => { _levelProgrammaticScroll = false; }, smooth ? 420 : 90);
}

function wireLevelScrubber(segBar, buttons) {
    let commitTimer = null;
    const commit = () => {
        const btn = buttons[_levelCenteredIdx(segBar)];
        if (btn) btn.click(); // → renderRangeSelector (resets the set options)
    };
    segBar.addEventListener('scroll', () => {
        const i = _levelCenteredIdx(segBar);
        if (+segBar.dataset.value !== i) setLevelSegmentSelection(i); // live magnify + readout
        if (_levelProgrammaticScroll) return;
        clearTimeout(commitTimer);
        commitTimer = setTimeout(commit, 150); // fallback for browsers without scrollend
    }, { passive: true });
    // scrollend fires once the snap animation settles — the reliable commit.
    segBar.addEventListener('scrollend', () => {
        if (_levelProgrammaticScroll) return;
        clearTimeout(commitTimer);
        commit();
    }, { passive: true });
    // Tapping a segment commits it directly. We must NOT rely on the scroll
    // handler to commit here: _scrollLevelSegToCenter marks the scroll as
    // programmatic, and both scroll listeners early-return on programmatic
    // scrolls — so a tap would magnify the segment but never refresh the set
    // options. The .level-btn click both re-renders the ranges AND re-centres
    // the scrubber (via the sync block in the button handler).
    segBar.querySelectorAll('.lsw-seg').forEach(seg => {
        seg.addEventListener('click', () => {
            const idx = parseInt(seg.dataset.i, 10);
            if (!Number.isNaN(idx) && buttons[idx]) buttons[idx].click();
        });
    });
}

// Update the slider's rank/coverage text + example words for snap index `i`.
// Examples are loaded lazily; the readout updates synchronously and examples
// fill in when the vocab fetch resolves.
function updateLevelSliderReadout(i) {
    const ranges = getActiveLevelRanges();
    const lv = ranges[i];
    if (!lv) return;
    const rankEl = document.getElementById('lswRankVal');
    const covEl  = document.getElementById('lswCovVal');
    const exEl   = document.getElementById('lswExamples');
    // Synchronous rank count: smart ranges already carry cardCount; for
    // legacy ranges we count post-filter items at runtime if the raw
    // vocab cache is warm. Cold cache → fall back to raw ppm rank; the
    // .then() below replaces it once the load resolves.
    const _syncSamples = _levelSliderSamplesSync(selectedLanguage);
    if (rankEl) {
        let display;
        if (lv.cardCount != null) display = lv.cardCount;
        else if (_syncSamples) display = _filteredCountUpTo(_syncSamples, lv.endRank);
        else display = lv.endRank;
        rankEl.textContent = display.toLocaleString();
    }
    if (covEl) {
        covEl.textContent = lv.threshold != null
            ? `${(lv.threshold * 100).toFixed(1)}%`
            : lv.level;
    }

    // Patch tick labels too if the cache is warm — keeps the row of
    // "100, 300, 700, 1.5k…" honest about how many cards each snap point
    // actually yields under the current filters.
    if (_syncSamples) _applyFilteredRankCounts(_syncSamples);

    if (!exEl) return;

    // Frequency at this rank ceiling — the actual corpus_count of the
    // rarest card in this segment. Smart ranges carry it directly on
    // lv.freqMin; legacy normal-mode ranges derive it from ppmData.
    // Rendered as a plain sentence (no ≥ sign), with the examples for
    // this level on their own line beneath it.
    let freqValue = null;
    let freqUnit = '';
    if (lv.freqMin != null) {
        freqValue = lv.freqMin;
        freqUnit = activeArtist ? 'times in the lyrics' : 'times per million words';
    } else if (ppmData && ppmData.length > 0) {
        const _e = ppmData.find(p => p.rank === lv.endRank);
        if (_e) {
            freqValue = Math.round(_e.ppm);
            freqUnit = activeArtist ? 'times in the lyrics' : 'times per million words';
        }
    }

    const _renderLine = (examplesText) => {
        // Frequency as a full sentence on its own line, then the example
        // words for this level on a new line underneath (stacked via the
        // .lsw-examples column layout in CSS).
        const freqHTML = freqValue !== null
            ? (lv.splitTier
                ? `<div class="lsw-freq-sentence">Fine split within words appearing <strong>${freqValue.toLocaleString()}</strong> ${freqUnit}</div>`
                : `<div class="lsw-freq-sentence">Words appearing at least <strong>${freqValue.toLocaleString()}</strong> ${freqUnit}</div>`)
            : '';
        const egHTML = examplesText ? `<div class="lsw-egs">${examplesText}</div>` : '';
        exEl.innerHTML = freqHTML + egHTML;
    };
    _renderLine('');

    _loadLevelSliderSamples(selectedLanguage).then(samples => {
        if (!samples || samples.length === 0) { _renderLine(''); return; }
        // Replace any raw-rank fallback with the real filtered count now
        // that we've actually loaded the vocab.
        _applyFilteredRankCounts(samples);
        // Pick 5 words from the upper portion of this level's range — the
        // ones that just qualified at this coverage threshold are the most
        // illustrative of "what you'll be learning here".
        const rankOf = lv.rankBasis === 'display' ? s => s.displayRank : s => s.rank;
        const start = Math.max(1, Math.floor(lv.startRank + (lv.endRank - lv.startRank) * 0.6));
        const inRange = samples.filter(s => rankOf(s) >= start && rankOf(s) < lv.endRank);
        const pick = (inRange.length ? inRange : samples.filter(s => rankOf(s) < lv.endRank))
            .slice(-12);
        const out = [];
        const n = Math.min(5, pick.length);
        for (let k = 0; k < n; k++) out.push(pick[Math.floor(k * pick.length / n)].word);
        const examples = out.length ? 'e.g. ' + out.join(', ') : '';
        _renderLine(examples);
    });
}

function updateLevelInfoLine(btn) {
    // Step 2 used to render a separate "Most common N words / Words appear
    // N+ times" line in the header. The slider readout now covers the rank
    // count, and the frequency is rendered inline with the example words
    // (see updateLevelSliderReadout). This stays as a no-op so legacy
    // callers don't break.
    const infoLine = document.getElementById('levelInfoLine');
    if (infoLine) infoLine.style.display = 'none';
}

function setupCognateToggle() {
    document.querySelectorAll('.cognate-toggle-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            // Don't allow selecting "exclude" mode if cognate field not available
            if (this.dataset.cognate === 'exclude' && !cognateFieldAvailable) {
                return;
            }
            // Reset all buttons to short text
            document.querySelectorAll('.cognate-toggle-btn').forEach(b => {
                b.classList.remove('selected');
                b.textContent = b.dataset.short;
            });
            // Set selected button to full text
            this.classList.add('selected');
            this.textContent = this.dataset.full;
            excludeCognates = this.dataset.cognate === 'exclude';

            _refreshAfterCognateChange();
        });
    });
    // Cognate sensitivity (Loose / Default / Strict) lives in the
    // Advanced settings tab. Higher threshold = only the most obvious
    // cognates excluded; lower threshold = more aggressive exclusion.
    document.querySelectorAll('#cognateSensitivitySelector .cognate-sens-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const t = parseFloat(this.dataset.threshold);
            if (Number.isNaN(t)) return;
            cognateThreshold = t;
            document.querySelectorAll('#cognateSensitivitySelector .cognate-sens-btn')
                .forEach(b => b.classList.toggle('selected', b === this));
            if (excludeCognates) _refreshAfterCognateChange();
        });
    });
}

function _refreshAfterCognateChange() {
    renderLevelSelector(selectedLanguage);
    if (selectedLevel) {
        const levelBtn = document.querySelector(`.level-btn[data-level="${selectedLevel}"]`);
        if (levelBtn) {
            levelBtn.classList.add('selected');
            levelBtn.textContent = levelBtn.dataset.full;
        }
        renderRangeSelector().catch(err => console.error('Error rendering ranges:', err));
    }
    updateExclusionBars();
}

function setupGroupSizeSelector() {
    document.querySelectorAll('.group-size-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            // Reset all buttons to short text
            document.querySelectorAll('.group-size-btn').forEach(b => {
                b.classList.remove('selected');
                b.textContent = b.dataset.short;
            });
            // Set selected button to full text
            this.classList.add('selected');
            this.textContent = this.dataset.full;
            groupSize = parseInt(this.dataset.size);

            // Re-render range selector if a level is selected
            if (selectedLevel) {
                renderRangeSelector().catch(err => console.error('Error rendering ranges:', err));
            }
        });
    });
}

function setupLemmaToggle() {
    document.querySelectorAll('.lemma-toggle-btn').forEach(btn => {
        btn.addEventListener('click', async function() {
            // Don't allow selecting "1" mode if lemma field not available
            if (this.dataset.lemma === 'on' && !lemmaFieldAvailable) {
                return;
            }
            // Reset all buttons to short text
            document.querySelectorAll('.lemma-toggle-btn').forEach(b => {
                b.classList.remove('selected');
                b.textContent = b.dataset.short;
            });
            // Set selected button to full text
            this.classList.add('selected');
            this.textContent = this.dataset.full;
            useLemmaMode = this.dataset.lemma === 'on';

            // Re-render level selector with new word counts, and re-render range selector if a level is selected
            const loadingIndicator = document.getElementById('dataLoadingIndicator');
            if (useLemmaMode) loadingIndicator?.classList.add('visible');
            try {
                await renderLevelSelector(selectedLanguage);
            } finally {
                loadingIndicator?.classList.remove('visible');
            }
            // Re-select the current level if one was selected
            if (selectedLevel) {
                const levelBtn = document.querySelector(`.level-btn[data-level="${selectedLevel}"]`);
                if (levelBtn) {
                    levelBtn.classList.add('selected');
                    levelBtn.textContent = levelBtn.dataset.full;
                }
                renderRangeSelector().catch(err => console.error('Error rendering ranges:', err));
            }
            updateExclusionBars();
        });
    });
}

function setupPercentModeButton() {
    const toggle = document.getElementById('levelModeToggle');
    if (!toggle) return;

    // Hide the toggle entirely in artist mode — artist mode is always
    // % coverage of lyrics, so there's no choice to expose.
    if (activeArtist) {
        toggle.style.display = 'none';
        return;
    }

    toggle.addEventListener('click', async function() {
        // Tapping the CEFR button flips between "% coverage" (default, off)
        // and "CEFR pills" (on). It's a binary switch — same behavior the
        // old segmented two-button control had, just collapsed into one.
        const wantPercent = !percentageMode;  // currently in CEFR? → switch to %
        const langConfig = config.languages[selectedLanguage];
        if (wantPercent && (!langConfig || !langConfig.ppmDataPath)) {
            alert('Percentage mode is not available for this language yet.');
            return;
        }

        percentageMode = wantPercent;
        updatePercentModeButton();

        if (percentageMode && !ppmData) {
            await loadPpmData(selectedLanguage);
        }

        updateStep2Tooltip();
        updateStep5Tooltip();

        // Hide level info line (re-shown on level click)
        const infoLine = document.getElementById('levelInfoLine');
        if (infoLine) infoLine.style.display = 'none';

        // Re-render the level selector for the new mode
        selectedLevel = null;
        renderLevelSelector(selectedLanguage);
        document.getElementById('lemmaToggleContainer').style.display = 'none';
        document.getElementById('cognateToggleContainer').style.display = 'none';
        document.getElementById('step4').style.display = 'none';
    });
}

function setupEstimationModal() {
    // Close modal
    document.getElementById('closeEstimationModal').addEventListener('click', closeEstimationModal);

    // Start estimation button
    document.getElementById('startEstimationBtn').addEventListener('click', function() {
        startEstimation();
    });

    // Use estimated level
    document.getElementById('useEstimatedLevelBtn').addEventListener('click', useEstimatedLevel);
}

async function updateLemmaToggleVisibility() {
    const langConfig = config.languages[selectedLanguage];
    const lemmaContainer = document.getElementById('lemmaToggleContainer');
    const lemmaSelector = document.getElementById('lemmaToggleSelector');
    const rangeStepNumber = document.getElementById('rangeStepNumber');

    // Check if vocabulary has most_frequent_lemma_instance field
    lemmaFieldAvailable = false;
    if (langConfig) {
        try {
            const vocabData = await fetchActiveVocabularyData(langConfig);
            lemmaFieldAvailable = vocabData.some(item =>
                item.hasOwnProperty('most_frequent_lemma_instance')
            );
        } catch (error) {
            console.error('Error checking lemma field availability:', error);
        }
    }

    // Always show the container (step 3), but disable the "1" option if field not available
    lemmaContainer.style.display = 'block';
    rangeStepNumber.textContent = activeArtist ? '2' : '3';

    if (lemmaFieldAvailable) {
        // Enable both options
        lemmaSelector.classList.remove('lemma-toggle-unavailable');
    } else {
        // Disable the "1" option, force "1+" mode
        lemmaSelector.classList.add('lemma-toggle-unavailable');
        useLemmaMode = false;
        document.querySelectorAll('.lemma-toggle-btn').forEach(b => b.classList.remove('selected'));
        document.querySelector('.lemma-toggle-btn[data-lemma="off"]').classList.add('selected');
    }
}

async function updateCognateToggleVisibility() {
    const langConfig = config.languages[selectedLanguage];
    const cognateContainer = document.getElementById('cognateToggleContainer');
    const cognateSelector = document.getElementById('cognateToggleSelector');

    // Check if vocabulary has cognate_score field
    cognateFieldAvailable = false;
    if (langConfig) {
        try {
            const vocabData = await fetchActiveVocabularyData(langConfig);
            cognateFieldAvailable = vocabData.some(item =>
                (item.cognate_score > 0) || item.cognet_cognate || item.is_transparent_cognate
            );
        } catch (error) {
            console.error('Error checking cognate field availability:', error);
        }
    }

    if (cognateFieldAvailable) {
        // Show the container and enable both options
        cognateContainer.style.display = 'block';
        cognateSelector.classList.remove('cognate-toggle-unavailable');
    } else {
        // Hide the container entirely if field not available
        cognateContainer.style.display = 'none';
        excludeCognates = false;
    }
}

function applyLanguageColorTheme() {
    const langConfig = config.languages[selectedLanguage];
    if (langConfig && langConfig.colorTheme) {
        const root = document.documentElement;
        root.style.setProperty('--accent-primary', langConfig.colorTheme.primary);
        root.style.setProperty('--accent-secondary', langConfig.colorTheme.secondary);

        // Convert hex to RGB for opacity usage
        const hexToRgb = (hex) => {
            const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
            return result ? `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}` : '0, 0, 0';
        };

        // WCAG relative luminance — returns 0 (black) to 1 (white)
        const luminance = (hex) => {
            const [r, g, b] = hex.replace('#', '').match(/.{2}/g).map(x => {
                const c = parseInt(x, 16) / 255;
                return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
            });
            return 0.2126 * r + 0.7152 * g + 0.0722 * b;
        };

        const bgPrimary = getComputedStyle(root).getPropertyValue('--bg-primary').trim() || '#0f0f1a';
        root.style.setProperty('--accent-primary-text', luminance(langConfig.colorTheme.primary) < 0.4 ? '#ffffff' : bgPrimary);
        root.style.setProperty('--accent-secondary-text', luminance(langConfig.colorTheme.secondary) < 0.4 ? '#ffffff' : bgPrimary);

        root.style.setProperty('--accent-primary-rgb', hexToRgb(langConfig.colorTheme.primary));
        root.style.setProperty('--accent-secondary-rgb', hexToRgb(langConfig.colorTheme.secondary));
    }
}

// Shared vocabulary filter pipeline used by renderRangeSelector and loadVocabularyData.
// Applies all active exclusions in the correct order and assigns corpus-wide display ranks.
// Returns { vocab: filteredArray, counts: { english, cognates, singleOcc, lemma } }


async function renderRangeSelector() {
    const langConfig = config.languages[selectedLanguage];
    const container = document.getElementById('rangeSelector');

    let minWord, maxWord;
    let rankBasis = 'source';

    // Get min/max based on mode
    if (percentageMode && ppmData && ppmData.length > 0) {
        // In percentage mode, get ranks from selected level button's data attributes
        const selectedBtn = document.querySelector('.level-btn.selected');
        if (!selectedBtn) return;
        minWord = parseInt(selectedBtn.dataset.startRank);
        maxWord = parseInt(selectedBtn.dataset.endRank);
        rankBasis = selectedBtn.dataset.rankBasis || 'source';
    } else {
        const cefrLevels = getCefrLevels(selectedLanguage);
        const level = cefrLevels.find(l => l.level === selectedLevel);
        if (!level) return;
        // Parse the wordCount range for this level (e.g., "1-800" -> 1, 800)
        [minWord, maxWord] = level.wordCount.split('-').map(Number);
    }

    // Defensive guard — if the dataset values failed to parse (selected
    // button rewritten with stale/missing attrs after a smart-range
    // recompute, etc.) bail with an empty container rather than emitting
    // "1 to NaN" range buttons that break the deck loader downstream.
    if (!Number.isFinite(minWord) || !Number.isFinite(maxWord)) {
        console.warn('renderRangeSelector: bad min/max from selected level button', { minWord, maxWord, selectedLevel });
        container.innerHTML = '';
        return;
    }

    // Load vocabulary data, joined with master if needed
    let vocabularyData = [];
    try {
        vocabularyData = await fetchActiveVocabularyData(langConfig);
    } catch (error) {
        console.error('Failed to load vocabulary data:', error);
    }

    const { vocab: lemmaFilteredVocab, counts: filterCounts } = buildFilteredVocab(vocabularyData);

    // Per-step exclusion counts. Cognates and lemma are SEPARATE filter
    // stages — cognate runs first, items it excludes don't count toward
    // the lemma filter, so each info-line reports only its own stage's
    // exclusions instead of an aggregated total.
    const lemmaInfo = document.getElementById('lemmaInfoLine');
    if (lemmaInfo) {
        if (filterCounts.lemma > 0) {
            lemmaInfo.textContent = filterCounts.lemma.toLocaleString() + ' flashcards excluded';
            lemmaInfo.style.display = '';
        } else {
            lemmaInfo.style.display = 'none';
        }
    }
    const cognateInfo = document.getElementById('cognateInfoLine');
    if (cognateInfo) {
        if (filterCounts.cognates > 0) {
            cognateInfo.textContent = filterCounts.cognates.toLocaleString() + ' flashcards excluded';
            cognateInfo.style.display = '';
        } else {
            cognateInfo.style.display = 'none';
        }
    }

    // Smart frequency bands are built from the post-filter order and use
    // displayRank. Legacy coverage/CEFR levels continue to use source rank.
    const wordsInLevel = lemmaFilteredVocab.filter(item => {
        const rank = rankBasis === 'display' ? item.displayRank : item.rank;
        return rank >= minWord && rank < maxWord;
    });

    if (wordsInLevel.length === 0) {
        container.innerHTML = '';
        return;
    }

    const minDisplayRank = wordsInLevel[0].displayRank;
    const maxDisplayRank = wordsInLevel[wordsInLevel.length - 1].displayRank;
    if (!Number.isFinite(minDisplayRank) || !Number.isFinite(maxDisplayRank)) {
        console.warn('renderRangeSelector: bad displayRank on filtered items', { minDisplayRank, maxDisplayRank });
        container.innerHTML = '';
        return;
    }

    // Generate range buttons using corpus-wide display ranks.
    // Mastery checks must use the same displayRank-based selection that
    // loadVocabularyData() uses when the button is clicked.
    const ranges = [];
    for (let i = minDisplayRank; i <= maxDisplayRank; i += groupSize) {
        const rangeEnd = Math.min(i + groupSize, maxDisplayRank + 1);
        const wordsInRange = lemmaFilteredVocab.filter(item => item.displayRank >= i && item.displayRank < rangeEnd);
        const hasData = wordsInRange.length > 0;

        // Per-word "completed" criterion (same as the old isMastered check):
        // a word is completed if its rank sits inside the user's level
        // estimate OR has been answered correctly at least once. The
        // resulting percentage drives the partial-fill bar on the button.
        let pct = 0;
        if (hasData && currentUser && !currentUser.isGuest && progressData) {
            const estimate = levelEstimates[selectedLanguage] || 0;
            const knownCount = wordsInRange.filter(item => {
                if (item.rank <= estimate) return true;
                return isWordKnown(getWordId(item));
            }).length;
            pct = Math.round(100 * knownCount / wordsInRange.length);
        }

        ranges.push({
            range: `${i}-${rangeEnd}`,
            label: `${i}-${rangeEnd - 1}`,
            available: hasData,
            pct: pct
        });
    }

    // Generate HTML — partial-fill bar based on completion percentage. The
    // button bg is a left-to-right gradient with a hard transition at
    // var(--rb-pct); the inner span uses the same gradient on its text via
    // background-clip:text so the label colour switches at the same X. See
    // .range-btn-new and .rb-label CSS for the trick.
    const rangesHTML = ranges.map(r => {
        const disabledAttr = !r.available ? 'disabled' : '';
        const disabledClass = !r.available ? 'disabled' : '';
        const progressClass = r.pct > 0 ? 'has-progress' : '';
        let title = 'Load ' + r.label;
        if (!r.available) {
            title = 'Greyed out because no vocabulary data exists for this range yet';
        } else if (r.pct === 100) {
            title = 'All words in this set answered correctly at least once';
        } else if (r.pct > 0) {
            title = `${r.pct}% complete — keep going`;
        }
        return `
            <button class="range-btn-new ${disabledClass} ${progressClass}"
                    data-range="${r.range}"
                    style="--rb-pct: ${r.pct}%"
                    ${disabledAttr}
                    title="${title}">
                ${r.label}
            </button>
        `;
    }).join('');

    // Add "Next Level" button at the end
    let nextLevelHTML = '';
    let levels, currentLevelIndex, nextLevel;

    if (percentageMode && ppmData && ppmData.length > 0) {
        levels = getActiveLevelRanges();
        currentLevelIndex = levels.findIndex(l => l.level === selectedLevel);
        nextLevel = currentLevelIndex < levels.length - 1 ? levels[currentLevelIndex + 1] : null;
    } else {
        levels = getCefrLevels(selectedLanguage);
        currentLevelIndex = levels.findIndex(l => l.level === selectedLevel);
        nextLevel = currentLevelIndex < levels.length - 1 ? levels[currentLevelIndex + 1] : null;
    }

    if (nextLevel) {
        nextLevelHTML = `
            <button class="range-btn-new next-level-btn"
                    data-next-level="${nextLevel.level}"
                    title="Go to ${nextLevel.level}">
                Next Level
            </button>
        `;
    } else {
        // At the last level, show placeholder box
        nextLevelHTML = `
            <button class="range-btn-new disabled"
                    disabled
                    title="Completed all levels">
                ${selectedLevel}
            </button>
        `;
    }

    // Add "Incorrect" button if user has incorrect words
    let incorrectHTML = '';
    if (currentUser && !currentUser.isGuest && progressData) {
        const incorrectCount = Object.values(progressData).filter(
            data => data.wrong > 0 && data.language === selectedLanguage
        ).length;
        if (incorrectCount > 0) {
            incorrectHTML = `
                <button class="range-btn-new incorrect-range-btn"
                        data-incorrect="true"
                        title="Study words you've previously marked incorrect">
                    Incorrect (${incorrectCount})
                </button>
            `;
        }
    }

    container.innerHTML = rangesHTML + incorrectHTML + nextLevelHTML;
    document.getElementById('step4').style.display = 'block';
    setActiveSetupStep('step4');

    // Add click handlers to ALL buttons
    document.querySelectorAll('.range-btn-new').forEach(btn => {
        btn.addEventListener('click', async function(e) {
            // Handle "Incorrect" button
            if (this.classList.contains('incorrect-range-btn')) {
                loadIncorrectWordsSet();
                return;
            }

            // Handle "Next Level" button
            if (this.classList.contains('next-level-btn')) {
                const nextLevelValue = this.dataset.nextLevel;
                if (nextLevelValue) {
                    selectedLevel = nextLevelValue;
                    // Update level selector UI - reset all buttons and select the next one
                    document.querySelectorAll('.level-btn').forEach(b => {
                        b.classList.remove('selected');
                        b.textContent = b.dataset.short;
                    });
                    const nextLevelBtn = document.querySelector(`.level-btn[data-level="${nextLevelValue}"]`);
                    if (nextLevelBtn) {
                        nextLevelBtn.classList.add('selected');
                        nextLevelBtn.textContent = nextLevelBtn.dataset.full;
                    }
                    // Re-render range selector for the new level
                    await renderRangeSelector();
                }
                return;
            }

            // Prevent disabled buttons from being clicked
            if (this.disabled || this.classList.contains('disabled')) {
                e.preventDefault();
                e.stopPropagation();
                // Show tooltip message for unavailable datasets
                const loadingMsg = document.getElementById('loadingMessage');
                loadingMsg.style.display = 'block';
                loadingMsg.style.color = 'var(--warning)';
                loadingMsg.textContent = 'Data not available, pick another set';
                setTimeout(() => {
                    loadingMsg.style.display = 'none';
                    loadingMsg.style.color = 'var(--accent-green)';
                }, 2000);
                return;
            }

            const selectedRange = this.dataset.range;

            document.getElementById('loadingMessage').style.display = 'block';
            document.getElementById('loadingMessage').textContent = `Loading ${selectedRange}...`;

            await loadVocabularyData(selectedRange);
        });
    });
}


function showStatsModal() {
    document.getElementById('statsModal').classList.remove('hidden');
    updateStatsModal();
}

function hideStatsModal() {
    document.getElementById('statsModal').classList.add('hidden');
}

function showSettingsModal() {
    showSettingsModalWithTab('settings');
}

function showSettingsModalWithTab(tabName) {
    // Show/hide single-occurrence toggle (only in artist mode)
    const hideSingleOccToggle = document.getElementById('hideSingleOccToggle');
    if (activeArtist) {
        hideSingleOccToggle.style.display = 'flex';
        document.getElementById('hideSingleOccStatus').textContent = hideSingleOccurrence ? 'ON' : 'OFF';
        document.getElementById('hideSingleOccStatus').style.color = hideSingleOccurrence ? 'var(--accent-primary)' : 'var(--text-muted)';
    } else {
        hideSingleOccToggle.style.display = 'none';
    }

    // Artist-mode toggles for proper nouns and noise/interjections.
    // Mirror the hideSingleOccurrence pattern: only visible in artist
    // mode (the underlying flags are pipeline outputs that only artist
    // entries carry).
    const propnToggle = document.getElementById('excludePropernounsToggle');
    if (propnToggle) {
        propnToggle.style.display = activeArtist ? 'flex' : 'none';
        const status = document.getElementById('excludePropernounsStatus');
        status.textContent = excludeProperNouns ? 'ON' : 'OFF';
        status.style.color = excludeProperNouns ? 'var(--accent-primary)' : 'var(--text-muted)';
    }
    const noiseToggle = document.getElementById('excludeNoiseToggle');
    if (noiseToggle) {
        noiseToggle.style.display = activeArtist ? 'flex' : 'none';
        const status = document.getElementById('excludeNoiseStatus');
        status.textContent = excludeNoise ? 'ON' : 'OFF';
        status.style.color = excludeNoise ? 'var(--accent-primary)' : 'var(--text-muted)';
    }
    const loanwordToggle = document.getElementById('excludeEnglishLoanwordsToggle');
    if (loanwordToggle) {
        loanwordToggle.style.display = activeArtist ? 'flex' : 'none';
        const status = document.getElementById('excludeEnglishLoanwordsStatus');
        status.textContent = excludeEnglishLoanwords ? 'ON' : 'OFF';
        status.style.color = excludeEnglishLoanwords ? 'var(--accent-primary)' : 'var(--text-muted)';
    }

    // Show/hide refresh set option based on whether a study set is loaded and user is logged in
    const refreshSetToggle = document.getElementById('refreshSetToggle');
    if (currentUser && !currentUser.isGuest && flashcards.length > 0) {
        refreshSetToggle.style.display = 'flex';
    } else {
        refreshSetToggle.style.display = 'none';
    }

    // Show cognate sensitivity row only when the active language has
    // cognate-score data — otherwise the threshold is meaningless.
    const cognateSensRow = document.getElementById('cognateSensitivityRow');
    if (cognateSensRow) {
        cognateSensRow.style.display = cognateFieldAvailable ? 'flex' : 'none';
        // Reflect current threshold in the segmented control.
        document.querySelectorAll('#cognateSensitivitySelector .cognate-sens-btn').forEach(b => {
            b.classList.toggle('selected', Math.abs(parseFloat(b.dataset.threshold) - cognateThreshold) < 1e-6);
        });
    }

    // Update account tab with current user
    const userBadge = currentUser ? (currentUser.isGuest ? 'GUEST' : currentUser.initials) : 'GUEST';
    document.getElementById('accountUserBadge').textContent = userBadge;

    // Show/hide clear level estimate row
    const estimate = levelEstimates[selectedLanguage] || 0;
    const clearRow = document.getElementById('clearLevelEstimateRow');
    if (currentUser && !currentUser.isGuest && estimate > 0) {
        document.getElementById('levelEstimateDisplay').textContent = `~${estimate} words`;
        clearRow.style.display = 'flex';
    } else {
        clearRow.style.display = 'none';
    }

    // Switch to specified tab
    document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.settings-tab[data-tab="${tabName}"]`).classList.add('active');
    document.querySelectorAll('.settings-tab-content').forEach(c => c.classList.remove('active'));
    const tabContentId = tabName === 'settings' ? 'settingsTabContent' :
                         tabName === 'artists' ? 'artistsTabContent' :
                         tabName === 'stats' ? 'statsTabContent' : 'accountTabContent';
    document.getElementById(tabContentId).classList.add('active');

    // Data-freshness footer: newest Last-Modified across the vocab files
    // (set in vocab.js trackDataFreshness). An old date = the service
    // worker served cached data; "not loaded yet" = no deck fetched.
    // The JST account additionally gets a verbose dev block (per-file
    // dates, app version, latest Claude changelog entry).
    const freshnessEl = document.getElementById('dataFreshnessFooter');
    if (freshnessEl) {
        if (window._vocabDataLastModified) {
            const upd = new Date(window._vocabDataLastModified).toLocaleString(undefined,
                { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
            const loaded = window._vocabDataLoadedAt
                ? new Date(window._vocabDataLoadedAt).toLocaleTimeString(undefined,
                    { hour: '2-digit', minute: '2-digit' })
                : null;
            freshnessEl.textContent = `Data last refreshed ${upd}` +
                (loaded ? ` · fetched ${loaded}` : '');
        } else {
            freshnessEl.textContent = 'Data not loaded yet';
        }
        if (currentUser && currentUser.initials === 'JST') {
            renderDevFooter(freshnessEl);   // async, appends below basic line
        }
    }

    document.getElementById('settingsModal').classList.remove('hidden');
}

// Verbose data-provenance block for the JST (dev) account only: per-file
// Last-Modified dates, the running asset version, and the latest entries
// from config/dev_changelog.json (which Claude appends to when deck data
// changes). Everyone else just sees the one-line freshness note above.
async function renderDevFooter(freshnessEl) {
    let devEl = document.getElementById('devFooterDetail');
    if (!devEl) {
        devEl = document.createElement('div');
        devEl.id = 'devFooterDetail';
        devEl.className = 'dev-footer-detail';
        freshnessEl.insertAdjacentElement('afterend', devEl);
    }

    const fmt = t => new Date(t).toLocaleString(undefined,
        { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    const lines = [];

    // Per-file freshness (which file is stale, not just the newest).
    const perFile = window._vocabDataFreshness || {};
    const fileNames = Object.keys(perFile).sort((a, b) => perFile[b] - perFile[a]);
    if (fileNames.length) {
        lines.push('<div class="dev-footer-label">Loaded data files (Last-Modified)</div>');
        for (const f of fileNames.slice(0, 6)) {
            lines.push(`<div class="dev-footer-row"><span>${f}</span><span>${fmt(perFile[f])}</span></div>`);
        }
    }

    // Running asset version, from the modulepreload tags (single source of
    // truth is service-worker.js ASSET_VERSION; the tags mirror it).
    const pre = document.querySelector('link[rel="modulepreload"]');
    const vMatch = pre && pre.href.match(/[?&]v=([\w.-]+)/);
    if (vMatch) {
        lines.push(`<div class="dev-footer-row"><span>app version</span><span>${vMatch[1]}</span></div>`);
    }

    // Latest Claude changelog entries.
    try {
        if (!window._devChangelog) {
            const resp = await fetch('config/dev_changelog.json');
            if (resp.ok) window._devChangelog = await resp.json();
        }
        const entries = (window._devChangelog && window._devChangelog.entries) || [];
        if (entries.length) {
            lines.push('<div class="dev-footer-label">Recent Claude changes</div>');
            for (const e of entries.slice(0, 2)) {
                lines.push(`<div class="dev-footer-entry"><b>${e.date}</b> · ${e.summary}` +
                    (e.commit ? ` <span class="dev-footer-commit">(${e.commit})</span>` : '') + '</div>');
                for (const d of (e.details || []).slice(0, 4)) {
                    lines.push(`<div class="dev-footer-bullet">– ${d}</div>`);
                }
            }
        }
    } catch (e) { /* changelog missing is fine — dev-only nicety */ }

    devEl.innerHTML = lines.join('');
}


function hideSettingsModal() {
    document.getElementById('settingsModal').classList.add('hidden');
}

async function showTotalStatsModal() {
    // Update language name in the header
    const langConfig = config.languages[selectedLanguage];
    const langName = langConfig ? langConfig.name : selectedLanguage;
    document.getElementById('totalStatsLanguage').textContent = langName;

    // Ensure vocabulary index is loaded (needed for comprehension + words understood)
    if (!cachedVocabularyData && langConfig) {
        try {
            const vocab = await fetchActiveVocabularyData(langConfig);
            vocab.forEach((item, index) => { item.rank = index + 1; });
            cachedVocabularyData = vocab;
        } catch (e) {
            console.warn('Could not load vocab for stats:', e);
        }
    }

    // Lazy-load the examples corpus + Spanish ranks needed for the
    // "Full sentences / Full lyric lines" row. Both files are normally
    // pulled when the user picks a set; the stats button can be tapped
    // before that, so fetch them here on demand. Failures are non-fatal —
    // the row just stays hidden.
    if (langConfig && langConfig.examplesPath && !window._cachedExamplesData) {
        try {
            const r = await fetch(langConfig.examplesPath);
            if (r.ok) window._cachedExamplesData = await r.json();
        } catch (e) {
            console.warn('Could not load examples for stats:', e);
        }
    }
    // loadSpanishRanks() is idempotent (internal guard); call unconditionally
    // for Spanish so the lines/sentences metric has rank data to work with.
    if (selectedLanguage === 'spanish' && window.loadSpanishRanks) {
        try { await window.loadSpanishRanks(); } catch (e) { /* ignore */ }
    }

    // Calculate all stats in a single pass
    // "Words understood" = last answer was correct (current knowledge, cross-mode)
    // "Correct" / "Incorrect" = all-time totals from progressData
    // "Comprehension" = frequency-weighted % based on current knowledge
    const vocab = cachedVocabularyData;
    const coverageEl = document.getElementById('totalStatsCoverage');
    const wordsEl = document.getElementById('totalStatsWords');

    // Check if a word is currently understood (most recent answer was correct)
    // across both modes, using timestamps. Falls back to correct > 0 if no timestamps.
    const isCurrentlyUnderstood = (id) => {
        const crossId = getCrossModeId(id);
        const entries = [progressData[id], crossId ? progressData[crossId] : null].filter(Boolean);
        let bestLc = 0, bestLw = 0;
        for (const p of entries) {
            if (p.language !== selectedLanguage) continue;
            const lc = p.lastCorrect ? new Date(p.lastCorrect).getTime() : 0;
            const lw = p.lastWrong ? new Date(p.lastWrong).getTime() : 0;
            if (lc > bestLc) bestLc = lc;
            if (lw > bestLw) bestLw = lw;
        }
        if (bestLc > 0 || bestLw > 0) return bestLc >= bestLw;
        return isWordKnown(id);
    };

    if (vocab && vocab.length > 0 && progressData) {
        let coveredFreq = 0, totalFreq = 0, coveredCount = 0;
        for (const item of vocab) {
            const freq = item.corpus_count || 1;
            totalFreq += freq;
            const id = getWordId(item);
            if (isCurrentlyUnderstood(id)) {
                coveredFreq += freq;
                coveredCount++;
            }
        }
        const coverageType = activeArtist ? 'lyrics' : 'speech';
        if (coveredCount > 0) {
            const pct = (coveredFreq / totalFreq * 100).toFixed(1);
            coverageEl.textContent = `${pct}% ${coverageType}`;
            const wordPct = (coveredCount / vocab.length * 100).toFixed(1);
            wordsEl.textContent = `${wordPct}% (${coveredCount} / ${vocab.length})`;
        } else {
            coverageEl.textContent = '—';
            wordsEl.textContent = '—';
        }
    } else {
        coverageEl.textContent = '—';
        wordsEl.textContent = '—';
    }

    // Correct / Incorrect: all-time totals across both modes, deduped
    let totalCorrect = 0, totalIncorrect = 0;
    if (progressData) {
        const counted = new Set();
        for (const [id, data] of Object.entries(progressData)) {
            if (data.language !== selectedLanguage) continue;
            const baseId = id.length >= 4 && id[2] === '1'
                ? id.slice(0, 2) + '0' + id.slice(3) : id;
            if (counted.has(baseId)) continue;
            counted.add(baseId);
            totalCorrect += Number(data.correct) || 0;
            totalIncorrect += Number(data.wrong) || 0;
        }
    }
    document.getElementById('totalWordsCorrect').textContent = totalCorrect;
    document.getElementById('totalWordsIncorrect').textContent = totalIncorrect;

    // Two comprehension rows. The first row shows frequency-weighted word
    // comprehension (set above). The second row shows what fraction of full
    // sentences/lines are 100% known — a stricter, more practical measure
    // ("how often will I read a whole line and understand every word").
    //
    // Labels switch by mode:
    //   artist mode  → "Lyrics word comprehension" + "Full lyric lines"
    //   normal mode  → "Comprehension: speech"     + "Full sentences"
    const coverageLabelEl = document.getElementById('totalStatsCoverageLabel');
    const linesLabelEl    = document.getElementById('totalStatsLinesLabel');
    const linesEl         = document.getElementById('totalStatsLinesUnderstood');
    const linesRow        = document.getElementById('totalStatsLinesRow');
    if (coverageLabelEl) {
        coverageLabelEl.textContent = activeArtist ? 'Lyrics word comprehension:' : 'Comprehension: speech';
    }
    if (linesLabelEl) {
        linesLabelEl.textContent = activeArtist ? 'Full lyric lines:' : 'Full sentences:';
    }

    // Both modes share the same computation: walk every example sentence in
    // _cachedExamplesData and count the lines where every in-vocab token is
    // either in the user's known set or below their level estimate.
    // computeLinesUnderstood() handles the iteration; we lazy-loaded the
    // examples corpus and rank data above so it has what it needs.
    let linesResult = computeLinesUnderstood();
    if (linesResult && linesResult.total > 0) {
        linesRow.style.display = '';
        linesEl.textContent = `${linesResult.pct.toFixed(1)}% (${linesResult.understood} / ${linesResult.total})`;
    } else {
        linesRow.style.display = 'none';
    }

    document.getElementById('totalStatsModal').classList.remove('hidden');
}

function hideTotalStatsModal() {
    document.getElementById('totalStatsModal').classList.add('hidden');
}

function updateTotalStatsButtonVisibility() {
    // No longer needed - stats are in settings modal
}

function updateStatsModal() {
    // Set size = picked range (e.g. 25); previouslyKnown = filtered out as
    // already mastered (e.g. 21); flashcards.length = active deck (e.g. 4).
    const setSize = stats.setSize || flashcards.length;
    const previouslyKnown = stats.previouslyKnown || 0;

    // Card position: 1-based index into the active deck. previouslyKnown
    // cards were filtered out before the session, so they sit "before" card 1.
    const cardPosition = flashcards.length > 0
        ? previouslyKnown + Math.min(currentIndex + 1, flashcards.length)
        : previouslyKnown;
    document.getElementById('cardPosition').textContent = cardPosition;
    document.getElementById('totalCardsStats').textContent = setSize;

    const labelEl = document.getElementById('statsSetLabel');
    if (labelEl) labelEl.textContent = stats.setLabel ? `· ${stats.setLabel}` : '';

    const prevRow = document.getElementById('previouslyKnownRow');
    if (prevRow) {
        if (previouslyKnown > 0) {
            prevRow.style.display = '';
            document.getElementById('previouslyKnownCount').textContent = previouslyKnown;
        } else {
            prevRow.style.display = 'none';
        }
    }

    // Unique-card answer counts. correct/incorrect = unique cards that got an
    // answer this session. skipped = cards the user navigated AWAY from without
    // answering (visited but no answer, and not the card currently on screen).
    // Cards never visited at all aren't counted as skipped — they're just
    // remaining work.
    let correctCards = 0;
    let incorrectCards = 0;
    const answered = new Set();
    Object.entries(stats.cardStats || {}).forEach(([idx, cs]) => {
        if (cs.correct > 0) {
            correctCards++;
            answered.add(Number(idx));
        } else if (cs.incorrect > 0) {
            incorrectCards++;
            answered.add(Number(idx));
        }
    });
    let skipped = 0;
    if (stats.studied && stats.studied.forEach) {
        stats.studied.forEach(idx => {
            if (idx !== currentIndex && !answered.has(idx)) skipped++;
        });
    }

    document.getElementById('correctCount').textContent = correctCards;
    document.getElementById('incorrectCount').textContent = incorrectCards;
    document.getElementById('skippedCount').textContent = skipped;

    const answeredCards = correctCards + incorrectCards;
    const accuracy = answeredCards > 0 ? Math.round((correctCards / answeredCards) * 100) : 0;
    document.getElementById('accuracyPercent').textContent = answeredCards > 0 ? accuracy + '%' : '-';

    renderStatsWordList(answered);
}

function renderStatsWordList(answeredIndexSet) {
    const body = document.getElementById('wordListBody');
    const details = document.getElementById('wordListDetails');
    if (!body || !details) return;

    const words = stats.allWords || [];
    if (words.length === 0) {
        details.style.display = 'none';
        return;
    }
    details.style.display = '';

    // Active deck ids → flashcards index, so we can flag which item is the
    // current card and which session-answered cards correspond.
    const activeIdToIndex = new Map();
    flashcards.forEach((c, i) => {
        if (c && c.id) activeIdToIndex.set(c.id, i);
        if (c && c.fullId) activeIdToIndex.set(c.fullId, i);
    });

    body.innerHTML = '';
    for (const w of words) {
        const li = document.createElement('li');
        li.style.padding = '3px 0';
        const inDeckIdx = activeIdToIndex.has(w.id) ? activeIdToIndex.get(w.id) : -1;

        let marker = '';
        let color = '';
        if (inDeckIdx === -1) {
            // Not in active deck → previously mastered (filtered out).
            marker = '✓';
            color = 'var(--text-muted)';
        } else if (inDeckIdx === currentIndex) {
            marker = '▶';
            color = 'var(--accent-primary)';
        } else {
            const cs = (stats.cardStats || {})[inDeckIdx];
            if (cs && cs.correct > 0) { marker = '✓'; color = 'var(--accent-green)'; }
            else if (cs && cs.incorrect > 0) { marker = '✗'; color = 'var(--error)'; }
            else if (answeredIndexSet && answeredIndexSet.has && answeredIndexSet.has(inDeckIdx)) {
                marker = '·'; color = '';
            } else if (stats.studied && stats.studied.has && stats.studied.has(inDeckIdx)) {
                marker = '⊘'; color = 'var(--text-muted)';
            } else {
                marker = '·'; color = '';
            }
        }
        if (color) li.style.color = color;
        const translation = w.translation ? ` — ${w.translation}` : '';
        li.textContent = `${marker} ${w.word}${translation}`;
        body.appendChild(li);
    }
}


window.setupTooltipHandlers = setupTooltipHandlers;
window.updateIncorrectButtonVisibility = updateIncorrectButtonVisibility;
window.renderLanguageTabs = renderLanguageTabs;
window.setActiveSetupStep = setActiveSetupStep;
window.mergeStandardProgressIntoLanguageStep = mergeStandardProgressIntoLanguageStep;
window.setupLanguageTabs = setupLanguageTabs;
window.hideAllSelectionPills = hideAllSelectionPills;
window.updatePercentModeButton = updatePercentModeButton;
window.updateStep2Tooltip = updateStep2Tooltip;
window.updateStep5Tooltip = updateStep5Tooltip;
window.renderLevelSelector = renderLevelSelector;
window.setupCognateToggle = setupCognateToggle;
window.setupGroupSizeSelector = setupGroupSizeSelector;
// Open the help modal — always reset to About tab, update content for mode
function openHelpModal() {
    const modal = document.getElementById('helpModal');
    modal.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
    modal.querySelectorAll('.settings-tab-content').forEach(c => c.classList.remove('active'));
    const aboutTab = modal.querySelector('[data-tab="helpAbout"]');
    if (aboutTab) aboutTab.classList.add('active');
    const aboutContent = document.getElementById('helpAboutTabContent');
    if (aboutContent) {
        aboutContent.classList.add('active');
        const helpContent = aboutContent.querySelector('.help-content');
        if (helpContent) helpContent.innerHTML = activeArtist ? getArtistHelpContent() : getNormalHelpContent();
    }
    // Show/hide the lyrics-specific line in the study tab
    const lyricsLine = document.getElementById('helpStudyLyricsLine');
    if (lyricsLine) lyricsLine.style.display = activeArtist ? '' : 'none';
    modal.classList.remove('hidden');
}

function get70pctWordCount() {
    const ranges = getPercentageLevelRanges();
    const level70 = ranges.find(r => r.level === '70%');
    if (level70) {
        return `With only ${level70.endRank.toLocaleString()} words, you know enough to understand roughly 70% of the words in any song. That's what's meant by 70% coverage.`;
    }
    return `For example, at 70% coverage you know enough words to understand roughly 70% of the words in any song. That's what's meant by 70% coverage.`;
}

function getArtistHelpContent() {
    const name = activeArtist.name || 'this artist';
    return `
        <p><strong>What is this?</strong></p>
        <p>This app teaches you Spanish vocabulary from ${name}'s lyrics, starting with the most common words and working toward the least common.</p>
        <p><strong>Why frequency order?</strong></p>
        <p>Language follows a power law: a small number of words make up the vast majority of speech. By learning the most frequent words first, you understand more lyrics faster.</p>
        <p><strong>How are percentages calculated?</strong></p>
        <p>The coverage percentage tells you what fraction of all words in the lyrics you'd recognize. ${get70pctWordCount()} The remaining 30% are rarer words that appear less often.</p>
        <p><strong>How does it work?</strong></p>
        <p>Each word is ranked by how many times it appears across the entire discography. The app groups these into sets of 25. You work through sets in order, and each card shows the word with real lyric examples from songs where it appears.</p>
        <p>The progress bar tracks your coverage based on the frequency of words you've learned — learning a common word contributes more to your coverage than a rare one.</p>
    `;
}

function getNormalHelpContent() {
    return `
        <p><strong>What is this?</strong></p>
        <p>This app teaches you vocabulary by its frequency in speech.</p>
        <p><strong>Why frequency order?</strong></p>
        <p>Language follows a power law: a small number of words make up the vast majority of everyday speech. In Spanish, the top 1,000 words cover roughly 81% of spoken language, and the top 3,000 cover around 91%. By learning frequent words first, you build practical comprehension faster.</p>
        <p><strong>How does it work?</strong></p>
        <p>Words are ranked by how often they appear in real-world sources like movies, TV, and conversations. The app groups them into sets of 25 and each card includes example sentences to show the word in context.</p>
        <p>The progress bar tracks your coverage based on the frequency of words you've learned — learning a common word contributes more to your coverage than a rare one.</p>
    `;
}

// Generic tab switching for any modal that uses .settings-tab / .settings-tab-content pattern
function setupTabSwitching(modalEl) {
    const tabs = modalEl.querySelectorAll('.settings-tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Deactivate all tabs and contents within this modal
            modalEl.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
            modalEl.querySelectorAll('.settings-tab-content').forEach(c => c.classList.remove('active'));
            // Activate clicked tab
            tab.classList.add('active');
            const tabName = tab.dataset.tab;
            const contentId = tabName + 'TabContent';
            const content = document.getElementById(contentId);
            if (content) content.classList.add('active');
        });
    });
}

window.openHelpModal = openHelpModal;
window.setupTabSwitching = setupTabSwitching;
window.setupLemmaToggle = setupLemmaToggle;
window.setupPercentModeButton = setupPercentModeButton;
window.setupEstimationModal = setupEstimationModal;
window.updateLemmaToggleVisibility = updateLemmaToggleVisibility;
window.updateCognateToggleVisibility = updateCognateToggleVisibility;
window.applyLanguageColorTheme = applyLanguageColorTheme;
window.renderRangeSelector = renderRangeSelector;
window.showStatsModal = showStatsModal;
window.hideStatsModal = hideStatsModal;
window.showSettingsModal = showSettingsModal;
window.showSettingsModalWithTab = showSettingsModalWithTab;
window.hideSettingsModal = hideSettingsModal;
window.showTotalStatsModal = showTotalStatsModal;
window.hideTotalStatsModal = hideTotalStatsModal;
window.updateTotalStatsButtonVisibility = updateTotalStatsButtonVisibility;
window.updateStatsModal = updateStatsModal;
window.setupArtistSelection = setupArtistSelection;

// Multi-artist selection UI in the settings modal (Artists tab)
function setupArtistSelection() {
    const primaryContainer = document.getElementById('artistPrimarySection');
    const secondaryContainer = document.getElementById('artistSecondarySection');
    const tabBtn = document.getElementById('artistsTabBtn');
    if (!primaryContainer || !secondaryContainer || !activeArtist) return;

    const artists = window._allArtistsConfig;
    if (!artists) return;

    // Show the Artists tab
    if (tabBtn) tabBtn.style.display = '';

    primaryContainer.innerHTML = '';
    secondaryContainer.innerHTML = '';

    const urlArtistSlug = window._urlArtistSlug;

    for (const [slug, cfg] of Object.entries(artists)) {
        const isPrimary = slug === urlArtistSlug;

        if (isPrimary) {
            // Primary: highlighted row, not clickable
            const row = document.createElement('div');
            row.className = 'stat-row artist-primary-row';
            row.innerHTML = `<span>${cfg.name}</span>`;
            primaryContainer.appendChild(row);
        } else {
            // Other artists: tappable to switch primary
            const row = document.createElement('div');
            row.className = 'stat-row artist-switch-row';
            row.style.cursor = 'pointer';
            row.innerHTML = `<span>${cfg.name}</span>`;
            row.addEventListener('click', () => switchPrimaryArtist(slug));
            primaryContainer.appendChild(row);
        }

        // Secondary section: toggles for non-primary artists.
        // Only show artists in the SAME language as the primary — mixing
        // a French playlist into a Spanish deck doesn't make sense, and
        // the rest of the app assumes a single active language.
        const sameLanguage = (cfg.language || 'spanish') === (activeArtist.language || 'spanish');
        if (!isPrimary && sameLanguage) {
            const toggleRow = document.createElement('div');
            toggleRow.className = 'stat-row';
            toggleRow.style.cursor = 'pointer';

            const label = document.createElement('span');
            label.textContent = cfg.name;

            const toggle = document.createElement('span');
            const isSelected = window._selectedArtistSlugs.includes(slug);
            toggle.style.color = isSelected ? 'var(--accent-primary)' : 'var(--text-muted)';
            toggle.textContent = isSelected ? 'ON' : 'OFF';
            toggle.dataset.slug = slug;

            toggleRow.appendChild(label);
            toggleRow.appendChild(toggle);
            toggleRow.addEventListener('click', () => {
                const nowSelected = !window._selectedArtistSlugs.includes(slug);
                if (nowSelected) {
                    window._selectedArtistSlugs.push(slug);
                } else {
                    window._selectedArtistSlugs = window._selectedArtistSlugs.filter(s => s !== slug);
                }
                toggle.textContent = nowSelected ? 'ON' : 'OFF';
                toggle.style.color = nowSelected ? 'var(--accent-primary)' : 'var(--text-muted)';
                onArtistSelectionChange();
            });
            secondaryContainer.appendChild(toggleRow);
        }
    }
}

function switchPrimaryArtist(newSlug) {
    const allConfigs = window._allArtistsConfig;
    const newConfig = allConfigs[newSlug];
    if (!newConfig) return;

    // Update the primary artist globals
    window._urlArtistSlug = newSlug;
    activeArtist = newConfig;

    // Reset to only the new primary (clear secondaries)
    window._selectedArtistSlugs = [newSlug];

    // Update URL without reload
    const url = new URL(window.location);
    url.searchParams.set('artist', newSlug);
    history.replaceState(null, '', url);

    // Update config with new artist's paths and colors
    const lang = newConfig.language || 'spanish';
    config.languages[lang] = {
        ...config.languages[lang],
        name: `${config.languages[lang].name.replace(/\s*\(.*\)$/, '')} (${newConfig.name})`,
        dataPath: newConfig.dataPath,
        indexPath: newConfig.indexPath || newConfig.dataPath,
        examplesPath: newConfig.examplesPath || null,
        masterPath: newConfig.masterPath || null,
        ppmDataPath: null,
        colorTheme: newConfig.colorTheme || config.languages[lang].colorTheme
    };
    document.title = `${newConfig.name} Vocabulary`;

    // Re-apply color theme and re-render checkboxes
    applyLanguageColorTheme();
    setupArtistSelection();

    // Trigger full vocabulary reload (cache invalidation + UI reset)
    onArtistSelectionChange();
}

function onArtistSelectionChange() {
    const urlArtistSlug = window._urlArtistSlug;
    const checkboxes = document.querySelectorAll('#artistCheckboxes input[type="checkbox"]');

    // Primary (URL) artist is always first; add any checked secondary artists after
    const selected = [urlArtistSlug];
    checkboxes.forEach(cb => {
        if (cb.checked && cb.dataset.slug !== urlArtistSlug) {
            selected.push(cb.dataset.slug);
        }
    });

    window._selectedArtistSlugs = selected;
    localStorage.setItem('selected_artists', JSON.stringify(selected));

    // Invalidate all cached vocabulary data
    window._cachedMergedIndex = null;
    window._cachedMergedExamples = null;
    window._cachedExamplesData = null;
    window._cachedJoinedIndex = null;
    window._cachedJoinedIndexPath = null;
    delete _levelSliderRawCache[selectedLanguage];

    // Reload albums dictionary for multi-artist mode
    loadMultiArtistAlbumsDictionaries(selected, window._allArtistsConfig);

    // If we're currently viewing flashcards, go back to setup so user re-picks a set
    // with the merged vocabulary
    const appContent = document.getElementById('appContent');
    const setupPanel = document.getElementById('setupPanel');
    if (appContent && !appContent.classList.contains('hidden')) {
        appContent.classList.add('hidden');
        setupPanel.classList.remove('hidden');
        setupPanel.style.display = 'block';
        showFloatingBtns(false);
        // Re-render level selector with new merged data
        renderLevelSelector(selectedLanguage);
    }
}
