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

    // Cognate rules modal
    document.getElementById('cognateRulesBtn').addEventListener('click', function(e) {
        e.stopPropagation();
        document.getElementById('cognateTooltip').classList.remove('visible');
        document.getElementById('cognateRulesModal').classList.remove('hidden');
    });

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

    tabsContainer.innerHTML = tabsHTML;

    // Setup event listeners for tabs
    setupLanguageTabs();
}

function setupLanguageTabs() {
    const inlinePill = document.getElementById('selectedLanguageInline');

    // Click handler for the inline language pill (to re-expand tabs)
    inlinePill.addEventListener('click', function() {
        this.style.display = 'none';
        document.getElementById('languageTabs').style.display = 'flex';
        // Hide subsequent steps
        document.getElementById('step2').style.display = 'none';
        document.getElementById('lemmaToggleContainer').style.display = 'none';
        document.getElementById('cognateToggleContainer').style.display = 'none';
        document.getElementById('step4').style.display = 'none';
        hideAllSelectionPills();
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

            // Only reset percentage mode when switching to a different language
            if (newLanguage !== selectedLanguage) {
                percentageMode = false;
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
    const toggle = document.getElementById('levelModeToggle');
    if (!toggle) return;
    const activeMode = percentageMode ? 'percent' : 'cefr';
    toggle.querySelectorAll('.level-mode-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === activeMode);
    });
}

function updateStep2Tooltip() {
    const tooltip = document.getElementById('step2Tooltip');
    if (!tooltip) return;
    const inner = tooltip.querySelector('.step-info-tooltip-inner') || tooltip;
    if (activeArtist) {
        // Artist mode is always % coverage of lyrics — explain that
        // specifically and don't reference the CEFR/% toggle (it's hidden).
        const name = activeArtist.name;
        inner.innerHTML = `
            <p><strong>Lyrics Coverage</strong> shows what percentage of ${name}'s lyrics you'll understand at each level.</p>
            <p>For example, learning words up to 80% coverage means you'll recognize ~80% of words across the songs.</p>
            <p>Words are ranked by how often they appear in the discography.</p>
        `;
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
    const vocabularyData = await fetchAndJoinIndex(langConfig);
    const { vocab: filteredVocab } = buildFilteredVocab(vocabularyData);
    const estimate = levelEstimates[language] || 0;
    const wordKnown = (item) => (item.rank <= estimate) || isWordKnown(getWordId(item));

    for (const btn of buttons) {
        let minWord, maxWord;
        if (percentageMode && ppmData && ppmData.length > 0) {
            minWord = parseInt(btn.dataset.startRank);
            maxWord = parseInt(btn.dataset.endRank);
        } else {
            const cefrLevels = getCefrLevels(language);
            const lv = cefrLevels.find(l => l.level === btn.dataset.level);
            if (!lv) continue;
            [minWord, maxWord] = lv.wordCount.split('-').map(Number);
        }
        const wordsInLevel = filteredVocab.filter(it => it.rank >= minWord && it.rank < maxWord);
        if (wordsInLevel.length === 0) continue;
        if (!wordsInLevel.every(wordKnown)) return btn;
    }
    return buttons[buttons.length - 1];
}

async function renderLevelSelector(language) {
    const container = document.getElementById('levelSelector');

    // Debug logging
    console.log('renderLevelSelector called:', { percentageMode, ppmDataLength: ppmData ? ppmData.length : 0, language });

    // Use percentage levels if in percentage mode with PPM data
    if (percentageMode && ppmData && ppmData.length > 0) {
        const percentageRanges = getPercentageLevelRanges();
        console.log('Using percentage levels:', percentageRanges);
        const coverageType = activeArtist ? 'lyrics comprehension' : 'speech comprehension';
        const levelsHTML = percentageRanges.map(level => {
            const description = `${level.level} ${coverageType}`;
            return `
            <button class="level-btn" data-level="${level.level}" data-short="${level.level}" data-full="${description}" data-start-rank="${level.startRank}" data-end-rank="${level.endRank}" title="${description}">
                ${level.level}
            </button>
        `}).join('');
        container.innerHTML = levelsHTML;
    } else {
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
        });
    });

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

function updateLevelInfoLine(btn) {
    const infoLine = document.getElementById('levelInfoLine');
    if (!infoLine) return;

    if (!percentageMode || !ppmData || ppmData.length === 0) {
        infoLine.style.display = 'none';
        return;
    }

    const endRank = parseInt(btn.dataset.endRank, 10);
    if (!endRank) {
        infoLine.style.display = 'none';
        return;
    }

    // Find the ppm (corpus frequency) at the endRank position
    const entry = ppmData.find(p => p.rank === endRank);
    const minFreq = entry ? Math.round(entry.ppm) : '?';
    const freqLabel = activeArtist ? 'corpus count' : 'frequency';

    if (activeArtist) {
        infoLine.innerHTML = 'Most common ' + endRank.toLocaleString() + ' words<br>Words appear ' + minFreq + '+ times';
    } else {
        infoLine.innerHTML = 'Most common ' + endRank.toLocaleString() + ' words<br>Frequency \u2265 ' + minFreq;
    }
    infoLine.style.display = 'block';
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

            // Show/hide threshold slider
            const sliderRow = document.getElementById('cognateThresholdRow');
            if (sliderRow) sliderRow.style.display = excludeCognates ? '' : 'none';

            _refreshAfterCognateChange();
        });
    });

    // Threshold slider
    const slider = document.getElementById('cognateThresholdSlider');
    const label = document.getElementById('cognateThresholdLabel');
    if (slider) {
        slider.value = String(cognateThreshold);
        if (label) label.textContent = Number(cognateThreshold).toFixed(2);
        slider.addEventListener('input', function() {
            cognateThreshold = parseFloat(this.value);
            if (label) label.textContent = cognateThreshold.toFixed(2);
            _refreshAfterCognateChange();
        });
    }
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
        btn.addEventListener('click', function() {
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
            renderLevelSelector(selectedLanguage);
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

    toggle.querySelectorAll('.level-mode-btn').forEach(btn => {
        btn.addEventListener('click', async function() {
            const targetMode = this.dataset.mode;  // 'cefr' or 'percent'
            const wantPercent = targetMode === 'percent';
            if (wantPercent === percentageMode) return;  // already there

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
            const vocabData = await fetchAndJoinIndex(langConfig);
            lemmaFieldAvailable = vocabData.some(item =>
                item.hasOwnProperty('most_frequent_lemma_instance')
            );
        } catch (error) {
            console.error('Error checking lemma field availability:', error);
        }
    }

    // Always show the container (step 3), but disable the "1" option if field not available
    lemmaContainer.style.display = 'block';
    rangeStepNumber.textContent = activeArtist ? '4' : '5';

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
            const vocabData = await fetchAndJoinIndex(langConfig);
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

    // Get min/max based on mode
    if (percentageMode && ppmData && ppmData.length > 0) {
        // In percentage mode, get ranks from selected level button's data attributes
        const selectedBtn = document.querySelector('.level-btn.selected');
        if (!selectedBtn) return;
        minWord = parseInt(selectedBtn.dataset.startRank);
        maxWord = parseInt(selectedBtn.dataset.endRank);
    } else {
        const cefrLevels = getCefrLevels(selectedLanguage);
        const level = cefrLevels.find(l => l.level === selectedLevel);
        if (!level) return;
        // Parse the wordCount range for this level (e.g., "1-800" -> 1, 800)
        [minWord, maxWord] = level.wordCount.split('-').map(Number);
    }

    // Load vocabulary data, joined with master if needed
    let vocabularyData = [];
    try {
        vocabularyData = await fetchAndJoinIndex(langConfig);
    } catch (error) {
        console.error('Failed to load vocabulary data:', error);
    }

    const { vocab: lemmaFilteredVocab, counts: filterCounts } = buildFilteredVocab(vocabularyData);

    // Update lemma info line with exclusion count
    const lemmaInfo = document.getElementById('lemmaInfoLine');
    if (lemmaInfo) {
        if (filterCounts.lemma > 0) {
            lemmaInfo.textContent = filterCounts.lemma.toLocaleString() + ' flashcards excluded';
            lemmaInfo.style.display = '';
        } else {
            lemmaInfo.style.display = 'none';
        }
    }

    // Slice to this level's range using original rank (pre-filter position)
    // to determine which display-rank span this level covers
    const wordsInLevel = lemmaFilteredVocab.filter(item =>
        item.rank >= minWord && item.rank < maxWord
    );

    if (wordsInLevel.length === 0) {
        container.innerHTML = '';
        return;
    }

    const minDisplayRank = wordsInLevel[0].displayRank;
    const maxDisplayRank = wordsInLevel[wordsInLevel.length - 1].displayRank;

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
        levels = percentageLevels;
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

    // Show/hide refresh set option based on whether a study set is loaded and user is logged in
    const refreshSetToggle = document.getElementById('refreshSetToggle');
    if (currentUser && !currentUser.isGuest && flashcards.length > 0) {
        refreshSetToggle.style.display = 'flex';
    } else {
        refreshSetToggle.style.display = 'none';
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

    document.getElementById('settingsModal').classList.remove('hidden');
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
            const vocab = await fetchAndJoinIndex(langConfig);
            vocab.forEach((item, index) => { item.rank = index + 1; });
            cachedVocabularyData = vocab;
        } catch (e) {
            console.warn('Could not load vocab for stats:', e);
        }
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

    // Lines fully understood
    const linesEl = document.getElementById('totalStatsLinesUnderstood');
    const linesRow = document.getElementById('totalStatsLinesRow');
    const linesResult = activeArtist ? computeLinesUnderstood() : null;
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
    document.getElementById('cardsStudied').textContent = stats.studied.size;
    document.getElementById('totalCardsStats').textContent = flashcards.length;
    const progress = flashcards.length > 0 ? Math.round((stats.studied.size / flashcards.length) * 100) : 0;
    document.getElementById('progressPercent').textContent = progress + '%';

    document.getElementById('correctCount').textContent = stats.correct;
    document.getElementById('incorrectCount').textContent = stats.incorrect;

    const totalAttempts = stats.correct + stats.incorrect;
    const accuracy = totalAttempts > 0 ? Math.round((stats.correct / totalAttempts) * 100) : 0;
    document.getElementById('accuracyPercent').textContent = totalAttempts > 0 ? accuracy + '%' : '-';
}


window.setupTooltipHandlers = setupTooltipHandlers;
window.updateIncorrectButtonVisibility = updateIncorrectButtonVisibility;
window.renderLanguageTabs = renderLanguageTabs;
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

        // Secondary section: toggles for non-primary artists
        if (!isPrimary) {
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
