import './state.js';

function setupTooltipHandlers() {
    // Step help tooltip handlers
    document.querySelectorAll('.step-help-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            const tooltipId = this.dataset.tooltip;
            const tooltip = document.getElementById(tooltipId);

            // Close all other tooltips first
            document.querySelectorAll('.step-info-tooltip').forEach(t => {
                if (t.id !== tooltipId) {
                    t.classList.remove('visible');
                }
            });

            // Toggle this tooltip
            tooltip.classList.toggle('visible');
        });
    });

    // Close tooltips when clicking outside
    document.addEventListener('click', function(e) {
        if (!e.target.closest('.step-help-btn') && !e.target.closest('.step-info-tooltip')) {
            document.querySelectorAll('.step-info-tooltip').forEach(t => {
                t.classList.remove('visible');
            });
        }
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
    // Click handler for the language selection pill (to change language)
    document.getElementById('selectedLanguagePill').addEventListener('click', function() {
        // Hide the pill and show the tabs again
        this.classList.remove('visible');
        document.getElementById('languageTabs').style.display = 'flex';
        // Hide subsequent steps
        document.getElementById('estimateLevelBlock').style.display = 'none';
        document.getElementById('step2').style.display = 'none';
        document.getElementById('lemmaToggleContainer').style.display = 'none';
        document.getElementById('cognateToggleContainer').style.display = 'none';

        document.getElementById('step4').style.display = 'none';
        // Reset selections
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

            applyLanguageColorTheme();

            // Update and show the selection pill, hide the tabs
            const langConfig = config.languages[selectedLanguage];
            document.getElementById('selectedLanguageName').textContent = langConfig ? langConfig.name : selectedLanguage;
            document.getElementById('languageTabs').style.display = 'none';
            document.getElementById('selectedLanguagePill').classList.add('visible');

            // Hide all subsequent steps and their pills while loading
            document.getElementById('step2').style.display = 'none';
            document.getElementById('lemmaToggleContainer').style.display = 'none';
            document.getElementById('cognateToggleContainer').style.display = 'none';
    
            document.getElementById('step4').style.display = 'none';
            hideAllSelectionPills();
            document.getElementById('selectedLanguagePill').classList.add('visible'); // Keep language pill visible

            // Show loading indicator
            const loadingIndicator = document.getElementById('dataLoadingIndicator');
            loadingIndicator.classList.add('visible');

            // Refresh progress data from Google Sheets
            if (currentUser && !currentUser.isGuest) {
                await loadUserProgressFromSheet();
            }

            // Always load PPM data if available (needed for coverage bar even in CEFR mode)
            const langPpmPath = config.languages[selectedLanguage] && config.languages[selectedLanguage].ppmDataPath;
            if (!ppmData && langPpmPath) {
                await loadPpmData(selectedLanguage);
            }

            // Hide loading indicator and show step 2
            loadingIndicator.classList.remove('visible');
            document.getElementById('step2').style.display = 'block';
            updateEstimateLevelBlock();

            // Update step 2 title, tooltip, and % Mode button based on current mode
            document.getElementById('step2Title').textContent = percentageMode ? 'Choose Corpus Coverage' : 'Choose CEFR level';
            updatePercentModeButton();
            updateEstimateLevelButton();
            updateStep2Tooltip();
            updateStep5Tooltip();

            renderLevelSelector(selectedLanguage);
            updateCoverageProgressBar();
            updateLemmaToggleVisibility();
            updateCognateToggleVisibility();
            updateExclusionBars();
            updateIncorrectButtonVisibility();
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
    const btn = document.getElementById('percentModeBtn');
    if (percentageMode) {
        btn.classList.add('active');
    } else {
        btn.classList.remove('active');
    }
}

function updateStep2Tooltip() {
    const tooltip = document.getElementById('step2Tooltip');
    if (isBadBunnyMode) {
        tooltip.innerHTML = `
            <p><strong>Lyrics Coverage</strong> shows what percentage of Bad Bunny's lyrics you'll understand.</p>
            <p>For example, learning words up to 80% coverage means you'll recognize ~80% of words across his songs.</p>
            <p>Words are ranked by how often they appear in his discography.</p>
        `;
    } else if (percentageMode) {
        tooltip.innerHTML = `
            <p><strong>Corpus Coverage</strong> shows what percentage of real-world text you'll understand.</p>
            <p>For example, learning words up to 80% coverage means you'll recognize ~80% of words in typical movies, TV shows, and conversations.</p>
            <p>This is based on word frequency data from subtitle corpora.</p>
        `;
    } else {
        tooltip.innerHTML = `
            <p><strong>CEFR Levels</strong> indicate proficiency from beginner (A1) to proficient (C2).</p>
            <p>Words are ranked by frequency. Lower levels cover the most common words needed for basic comprehension.</p>
        `;
    }
}

function updateStep5Tooltip() {
    const tooltip = document.getElementById('step5Tooltip');
    if (isBadBunnyMode) {
        tooltip.innerHTML = `
            <p>Each set contains words ranked by frequency in Bad Bunny's lyrics (e.g., 1-25 = most common words).</p>
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

function renderLevelSelector(language) {
    const container = document.getElementById('levelSelector');

    // Debug logging
    console.log('renderLevelSelector called:', { percentageMode, ppmDataLength: ppmData ? ppmData.length : 0, language });

    // Use percentage levels if in percentage mode with PPM data
    if (percentageMode && ppmData && ppmData.length > 0) {
        const percentageRanges = getPercentageLevelRanges();
        console.log('Using percentage levels:', percentageRanges);
        const coverageType = isBadBunnyMode ? 'lyrics coverage' : 'language coverage';
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
    // Hide the % Mode button in Bad Bunny mode (always percentage mode)
    if (isBadBunnyMode) {
        document.getElementById('percentModeBtn').style.display = 'none';
    }
    document.getElementById('percentModeBtn').addEventListener('click', async function() {
        const langConfig = config.languages[selectedLanguage];
        if (!langConfig || !langConfig.ppmDataPath) {
            alert('Percentage mode is not available for this language yet.');
            return;
        }

        percentageMode = !percentageMode;

        // Update button appearance
        updatePercentModeButton();

        // Sync settings modal toggle
        document.getElementById('percentageModeStatus').textContent = percentageMode ? 'ON' : 'OFF';
        document.getElementById('percentageModeStatus').style.color = percentageMode ? 'var(--accent-primary)' : 'var(--text-muted)';

        // Load PPM data if enabling percentage mode
        if (percentageMode && !ppmData) {
            await loadPpmData(selectedLanguage);
        }

        // Update the title text and tooltip
        document.getElementById('step2Title').textContent = percentageMode ? 'Choose Corpus Coverage' : 'Choose CEFR level';
        updateStep2Tooltip();
        updateStep5Tooltip();

        // Re-render the level selector
        selectedLevel = null;
        renderLevelSelector(selectedLanguage);
        updateCoverageProgressBar();
        document.getElementById('lemmaToggleContainer').style.display = 'none';
        document.getElementById('cognateToggleContainer').style.display = 'none';

        document.getElementById('step4').style.display = 'none';

        updateStatsTab();
    });
}

function setupEstimateLevelButton() {
    // Update visibility based on language
    updateEstimateLevelButton();

    // Open modal when clicked (step 2 button)
    document.getElementById('estimateLevelBtn').addEventListener('click', function() {
        openEstimationModal();
    });

    // Step 1 Estimate Level button (for Bad Bunny mode)
    document.getElementById('step1EstimateLevelBtn').addEventListener('click', function() {
        openEstimationModal();
    });

    // Estimate Level block button (shown between step 1 and step 2 when no estimate set)
    document.getElementById('estimateLevelBlockBtn').addEventListener('click', function() {
        openEstimationModal();
    });

    // Close modal
    document.getElementById('closeEstimationModal').addEventListener('click', closeEstimationModal);

    // Quick estimate button
    document.getElementById('quickEstimateBtn').addEventListener('click', function() {
        startEstimation('quick');
    });

    // Detailed estimate button
    document.getElementById('detailedEstimateBtn').addEventListener('click', function() {
        startEstimation('detailed');
    });

    // Know/Don't Know buttons
    document.getElementById('estimationKnowBtn').addEventListener('click', estimationKnow);
    document.getElementById('estimationDontKnowBtn').addEventListener('click', estimationDontKnow);

    // Use estimated level
    document.getElementById('useEstimatedLevelBtn').addEventListener('click', useEstimatedLevel);

    // Retry
    document.getElementById('retryEstimationBtn').addEventListener('click', function() {
        document.getElementById('estimationResult').style.display = 'none';
        document.getElementById('estimationIntro').style.display = 'block';
    });
}

async function updateLemmaToggleVisibility() {
    const langConfig = config.languages[selectedLanguage];
    const lemmaContainer = document.getElementById('lemmaToggleContainer');
    const lemmaSelector = document.getElementById('lemmaToggleSelector');
    const rangeStepNumber = document.getElementById('rangeStepNumber');

    // Check if vocabulary has most_frequent_lemma_instance field
    lemmaFieldAvailable = false;
    if (langConfig && langConfig.dataPath) {
        try {
            const response = await fetch(langConfig.dataPath);
            if (response.ok) {
                const vocabData = await response.json();
                // Check if at least one entry has the most_frequent_lemma_instance field
                lemmaFieldAvailable = vocabData.some(item =>
                    item.hasOwnProperty('most_frequent_lemma_instance')
                );
            }
        } catch (error) {
            console.error('Error checking lemma field availability:', error);
        }
    }

    // Always show the container (step 3), but disable the "1" option if field not available
    lemmaContainer.style.display = 'block';
    rangeStepNumber.textContent = '5';

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

    // Check if vocabulary has is_transparent_cognate field
    cognateFieldAvailable = false;
    if (langConfig && langConfig.dataPath) {
        try {
            const response = await fetch(langConfig.dataPath);
            if (response.ok) {
                const vocabData = await response.json();
                // Check if at least one entry has the is_transparent_cognate field
                cognateFieldAvailable = vocabData.some(item =>
                    item.hasOwnProperty('is_transparent_cognate')
                );
            }
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

    // Always use the regular data path
    const dataPath = langConfig.dataPath;

    // Load the vocabulary data to check which ranks exist
    let vocabularyData = [];
    try {
        if (dataPath) {
            const response = await fetch(dataPath);
            if (response.ok) {
                vocabularyData = await response.json();
            }
        }
    } catch (error) {
        console.error('Failed to load vocabulary data:', error);
    }

    const { vocab: lemmaFilteredVocab } = buildFilteredVocab(vocabularyData);

    // Now slice to this level's range
    const wordsInLevel = lemmaFilteredVocab.filter(item =>
        item.rank >= minWord && item.rank < maxWord
    );

    if (wordsInLevel.length === 0) {
        container.innerHTML = '';
        return;
    }

    const minDisplayRank = wordsInLevel[0].displayRank;
    const maxDisplayRank = wordsInLevel[wordsInLevel.length - 1].displayRank;

    // Generate range buttons using corpus-wide display ranks
    const ranges = [];
    for (let i = minDisplayRank; i <= maxDisplayRank; i += groupSize) {
        const rangeEnd = Math.min(i + groupSize, maxDisplayRank + 1);
        const wordsInRange = wordsInLevel.filter(item => item.displayRank >= i && item.displayRank < rangeEnd);
        const hasData = wordsInRange.length > 0;

        // Check mastery and attempted status
        let isMastered = false;
        let isAttempted = false;
        if (hasData && currentUser && !currentUser.isGuest && progressData) {
            const estimate = levelEstimates[selectedLanguage] || 0;
            isMastered = wordsInRange.every(item => {
                if (item.rank <= estimate) return true;
                const progress = progressData[getWordId(item)];
                return progress && progress.correct > 0 && progress.language === selectedLanguage;
            });

            if (!isMastered) {
                isAttempted = wordsInRange.some(item => {
                    const progress = progressData[getWordId(item)];
                    return progress && progress.language === selectedLanguage &&
                           ((progress.correct && progress.correct > 0) || (progress.wrong && progress.wrong > 0));
                });
            }
        }

        ranges.push({
            range: `${i}-${rangeEnd}`,
            available: hasData,
            mastered: isMastered,
            attempted: isAttempted
        });
    }

    // Generate HTML with disabled state for unavailable ranges, mastered state for completed ranges, and attempted state
    const rangesHTML = ranges.map(r => {
        const disabledAttr = !r.available ? 'disabled' : '';
        const disabledClass = !r.available ? 'disabled' : '';
        const masteredClass = r.mastered ? 'mastered' : '';
        const attemptedClass = r.attempted ? 'attempted' : '';
        let title = 'Load ' + r.range;
        if (!r.available) {
            title = 'Greyed out because no vocabulary data exists for this range yet';
        } else if (r.mastered) {
            title = 'All words in this set answered correctly at least once';
        } else if (r.attempted) {
            title = 'Some words in this set have been practiced';
        }
        return `
            <button class="range-btn-new ${disabledClass} ${masteredClass} ${attemptedClass}"
                    data-range="${r.range}"
                    ${disabledAttr}
                    title="${title}">
                ${r.range}
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
    // Update settings tab
    document.getElementById('autoSpeakStatus').textContent = speechEnabled ? 'ON' : 'OFF';
    document.getElementById('autoSpeakStatus').style.color = speechEnabled ? 'var(--accent-primary)' : 'var(--text-muted)';

    // Update percentage mode toggle visibility and state
    const percentageModeToggle = document.getElementById('percentageModeToggle');
    const langConfig = config.languages[selectedLanguage];
    // Hide toggle in Bad Bunny mode (always percentage mode)
    if (isBadBunnyMode) {
        percentageModeToggle.style.display = 'none';
    } else if (langConfig && langConfig.ppmDataPath) {
        percentageModeToggle.style.display = 'flex';
        document.getElementById('percentageModeStatus').textContent = percentageMode ? 'ON' : 'OFF';
        document.getElementById('percentageModeStatus').style.color = percentageMode ? 'var(--accent-primary)' : 'var(--text-muted)';
    } else {
        percentageModeToggle.style.display = 'none';
    }

    // Show/hide single-occurrence toggle (only in Bad Bunny mode)
    const hideSingleOccToggle = document.getElementById('hideSingleOccToggle');
    if (isBadBunnyMode) {
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

    // Update stats tab
    updateStatsTab();

    // Switch to specified tab
    document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.settings-tab[data-tab="${tabName}"]`).classList.add('active');
    document.querySelectorAll('.settings-tab-content').forEach(c => c.classList.remove('active'));
    const tabContentId = tabName === 'settings' ? 'settingsTabContent' :
                         tabName === 'stats' ? 'statsTabContent' : 'accountTabContent';
    document.getElementById(tabContentId).classList.add('active');

    document.getElementById('settingsModal').classList.remove('hidden');
}

function updateStatsTab() {
    // Update language name
    const langConfig = config.languages[selectedLanguage];
    const langName = langConfig ? langConfig.name : selectedLanguage;
    document.getElementById('statsTabLanguage').textContent = langName;

    // Calculate total stats from progressData for the selected language
    let wordsCorrect = 0;
    let wordsSeen = 0;

    if (progressData) {
        Object.values(progressData).forEach(data => {
            if (data.language === selectedLanguage) {
                wordsSeen++;
                if (data.correct > 0) {
                    wordsCorrect++;
                }
            }
        });
    }

    document.getElementById('statsTabWordsCorrect').textContent = wordsCorrect;
    document.getElementById('statsTabWordsSeen').textContent = wordsSeen;

    // Update coverage percentage if PPM data is available
    const coverageRow = document.getElementById('coverageStatRow');
    if (ppmData && ppmData.length > 0) {
        const coveragePercent = calculateCoveragePercent();
        document.getElementById('statsTabCoverage').textContent = coveragePercent.toFixed(1) + '%';
        coverageRow.style.display = 'flex';
    } else {
        coverageRow.style.display = 'none';
    }
}

function hideSettingsModal() {
    document.getElementById('settingsModal').classList.add('hidden');
}

function showTotalStatsModal() {
    // Update language name in the header
    const langConfig = config.languages[selectedLanguage];
    const langName = langConfig ? langConfig.name : selectedLanguage;
    document.getElementById('totalStatsLanguage').textContent = langName;

    // Calculate total stats from progressData for the selected language
    let wordsCorrect = 0;
    let wordsSeen = 0;

    if (progressData) {
        Object.values(progressData).forEach(data => {
            if (data.language === selectedLanguage) {
                wordsSeen++;
                if (data.correct > 0) {
                    wordsCorrect++;
                }
            }
        });
    }

    document.getElementById('totalWordsCorrect').textContent = wordsCorrect;
    document.getElementById('totalWordsSeen').textContent = wordsSeen;

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
window.setupLemmaToggle = setupLemmaToggle;
window.setupPercentModeButton = setupPercentModeButton;
window.setupEstimateLevelButton = setupEstimateLevelButton;
window.updateLemmaToggleVisibility = updateLemmaToggleVisibility;
window.updateCognateToggleVisibility = updateCognateToggleVisibility;
window.applyLanguageColorTheme = applyLanguageColorTheme;
window.renderRangeSelector = renderRangeSelector;
window.showStatsModal = showStatsModal;
window.hideStatsModal = hideStatsModal;
window.showSettingsModal = showSettingsModal;
window.showSettingsModalWithTab = showSettingsModalWithTab;
window.updateStatsTab = updateStatsTab;
window.hideSettingsModal = hideSettingsModal;
window.showTotalStatsModal = showTotalStatsModal;
window.hideTotalStatsModal = hideTotalStatsModal;
window.updateTotalStatsButtonVisibility = updateTotalStatsButtonVisibility;
window.updateStatsModal = updateStatsModal;
