// Setup panel UI: language tabs, stable level selector, and automatic set progress.
// Key functions: renderLanguageTabs(), renderLevelSelector(), renderRangeSelector().
import './state.js?v=20260816n';

const GLOBAL_STUDY_DEFAULTS_KEY = 'fluency_global_study_defaults_v1';
let _setupLevelSelectionWasManual = false;

function readGlobalStudyDefaults() {
    try {
        const saved = JSON.parse(localStorage.getItem(GLOBAL_STUDY_DEFAULTS_KEY) || 'null');
        return saved && typeof saved === 'object' ? saved : {};
    } catch (_) {
        return {};
    }
}

function applyGlobalStudyDefaults() {
    const saved = readGlobalStudyDefaults();
    useLemmaMode = saved.mergeLemmas === true;
    excludeCognates = saved.excludeCognates === true;
    isFlipped = saved.directionFlipped === true;
    speechEnabled = saved.speechEnabled !== false;
    spacedRepetitionEnabled = saved.spacedRepetitionEnabled === true;
    phrasesModeEnabled = saved.phrasesMode !== false;
    extraExamplesEnabled = saved.extraExamples !== false;
    syncStudyPreferenceControls();
}

function syncStudyPreferenceControls() {
    document.querySelectorAll('.lemma-toggle-btn').forEach(button =>
        button.classList.toggle('selected', (button.dataset.lemma === 'on') === useLemmaMode));
    document.querySelectorAll('.cognate-toggle-btn').forEach(button =>
        button.classList.toggle('selected', (button.dataset.cognate === 'exclude') === excludeCognates));

    const saved = readGlobalStudyDefaults();
    const effective = {
        mergeLemmas: saved.mergeLemmas === true,
        excludeCognates: saved.excludeCognates === true,
        directionFlipped: saved.directionFlipped === true,
        speechEnabled: saved.speechEnabled !== false,
        spacedRepetitionEnabled: saved.spacedRepetitionEnabled === true,
        phrasesMode: saved.phrasesMode !== false,
        extraExamples: saved.extraExamples !== false
    };
    document.querySelectorAll('.global-study-default-btn').forEach(button => {
        const value = button.dataset.value === 'on';
        const selected = value === effective[button.dataset.setting];
        button.classList.toggle('selected', selected);
        button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
    updateCognateSensitivityVisibility();
}

// The sensitivity threshold only means anything while cognates are actually
// being excluded, and only for languages that carry cognate scores. Hide the
// whole row (and any explanation it had open) otherwise.
function updateCognateSensitivityVisibility() {
    const row = document.getElementById('cognateSensitivityRow');
    if (!row) return;
    const visible = Boolean(cognateFieldAvailable && excludeCognates);
    row.style.display = visible ? 'flex' : 'none';
    document.querySelectorAll('#cognateSensitivitySelector .cognate-sens-btn').forEach(b => {
        b.classList.toggle('selected', Math.abs(parseFloat(b.dataset.threshold) - cognateThreshold) < 1e-6);
    });
    if (!visible) closeSettingExplanation(document.getElementById('cognateSensitivityInfoBtn'));
}

function closeSettingExplanation(infoBtn) {
    if (!infoBtn) return;
    infoBtn.setAttribute('aria-expanded', 'false');
    const inline = infoBtn.closest('.settings-default-row')?.querySelector('.settings-row-explanation');
    if (inline) inline.hidden = true;
    const controlled = infoBtn.getAttribute('aria-controls');
    const extra = controlled ? document.getElementById(controlled) : null;
    if (extra) extra.hidden = true;
}

// One "?" per study preference. It reveals that setting's one-line
// description in place; rows that also point at a longer block via
// aria-controls open both together.
function setupSettingExplanations() {
    document.querySelectorAll('.settings-default-row .settings-info-btn').forEach(btn => {
        btn.addEventListener('click', function(event) {
            event.stopPropagation();
            const row = this.closest('.settings-default-row');
            const inline = row?.querySelector('.settings-row-explanation');
            const controlled = this.getAttribute('aria-controls');
            const extra = controlled ? document.getElementById(controlled) : null;
            const shouldOpen = this.getAttribute('aria-expanded') !== 'true';
            if (inline) inline.hidden = !shouldOpen;
            if (extra) extra.hidden = !shouldOpen;
            this.setAttribute('aria-expanded', String(shouldOpen));
        });
    });
}

function saveGlobalStudyPreference(setting, value) {
    const saved = readGlobalStudyDefaults();
    saved[setting] = !!value;
    try {
        localStorage.setItem(GLOBAL_STUDY_DEFAULTS_KEY, JSON.stringify(saved));
    } catch (_) {
        return false;
    }
    syncStudyPreferenceControls();
    return true;
}

async function refreshAfterGlobalStudyDefaultChange() {
    syncStudyPreferenceControls();
    const step2 = document.getElementById('step2');
    if (!selectedLanguage || !step2 || step2.style.display === 'none') return;
    const loadingIndicator = document.getElementById('dataLoadingIndicator');
    if (useLemmaMode) loadingIndicator?.classList.add('visible');
    try {
        await renderLevelSelector(selectedLanguage);
        if (selectedLevel) await renderRangeSelector();
        await updateExclusionBars();
    } finally {
        loadingIndicator?.classList.remove('visible');
    }
}

function setupGlobalStudyDefaults() {
    syncStudyPreferenceControls();
    setupSettingExplanations();
    document.querySelectorAll('.global-study-default-btn').forEach(button => {
        button.addEventListener('click', async function() {
            const setting = this.dataset.setting;
            const enabled = this.dataset.value === 'on';
            if (!saveGlobalStudyPreference(setting, enabled)) return;
            applyGlobalStudyDefaults();
            if (setting === 'mergeLemmas' || setting === 'excludeCognates') {
                await refreshAfterGlobalStudyDefaultChange();
            } else if (setting === 'spacedRepetitionEnabled') {
                const setupPanel = document.getElementById('setupPanel');
                if (selectedLevel && setupPanel && !setupPanel.classList.contains('hidden')) {
                    await renderRangeSelector();
                }
            } else {
                document.getElementById('flashcard')?.classList.remove('flipped');
                window.updateSpeakIcons?.();
                if (flashcards.length > 0) window.updateCard?.();
            }
        });
    });
}

// Defaults must be present before either mode renders its first level.
applyGlobalStudyDefaults();

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
    const title = document.getElementById('step1Title');
    const wrapper = document.getElementById('personalCoverageWrapper');
    const progressHeader = wrapper && wrapper.querySelector('.personal-progress-header');
    const inlinePill = document.getElementById('selectedLanguageInline');
    const sourcePill = document.getElementById('selectedSourceInline');
    const sourceCard = document.getElementById('standardSourceCard');
    const progressSlot = document.getElementById('standardSourceProgress');
    const languageName = document.getElementById('standardSourceLanguageName');
    const languageIcon = document.getElementById('standardSourceLanguageIcon');
    if (!step || !header || !title || !wrapper || !progressHeader || !inlinePill || !sourcePill
        || !sourceCard || !progressSlot || !languageName || !languageIcon) return;

    const flagMap = {
        spanish: '🇪🇸', swedish: '🇸🇪', italian: '🇮🇹', dutch: '🇳🇱',
        polish: '🇵🇱', french: '🇫🇷', russian: '🇷🇺'
    };
    languageName.textContent = config.languages[selectedLanguage]?.name || selectedLanguage;
    languageIcon.textContent = flagMap[selectedLanguage] || selectedLanguage.slice(0, 2).toUpperCase();
    progressSlot.appendChild(wrapper);
    title.textContent = 'Language';
    step.classList.add('language-summary-active');
    header.removeAttribute('role');
    header.removeAttribute('tabindex');
    header.removeAttribute('aria-haspopup');
    wrapper.classList.add('personal-coverage-wrapper--merged', 'personal-coverage-wrapper--empty', 'visible');
    wrapper.style.display = 'block';
    inlinePill.style.display = 'none';
    sourcePill.style.display = 'none';
    sourceCard.style.display = 'grid';
}

function unmergeStandardProgressFromLanguageStep() {
    if (activeArtist) return;
    const step = document.getElementById('step1');
    const header = document.getElementById('step1Header');
    const title = document.getElementById('step1Title');
    const wrapper = document.getElementById('personalCoverageWrapper');
    const inlinePill = document.getElementById('selectedLanguageInline');
    const sourcePill = document.getElementById('selectedSourceInline');
    const cta = document.getElementById('levelEstimateCTA');
    const sourceCard = document.getElementById('standardSourceCard');
    if (!step || !header || !title || !wrapper || !inlinePill || !sourcePill || !cta || !sourceCard) return;

    title.after(inlinePill);
    cta.after(wrapper);
    title.textContent = 'Choose language';
    step.classList.remove('language-summary-active');
    header.setAttribute('role', 'button');
    header.setAttribute('tabindex', '0');
    header.setAttribute('aria-haspopup', 'dialog');
    wrapper.classList.remove('personal-coverage-wrapper--merged', 'personal-coverage-wrapper--empty', 'visible');
    wrapper.style.display = 'none';
    sourcePill.style.display = 'none';
    sourceCard.style.display = 'none';
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

    tabsContainer.innerHTML = `<div class="language-picker-options" aria-hidden="true">${tabsHTML}</div>`;

    const step = document.getElementById('step1');
    const header = document.getElementById('step1Header');
    const openLanguagePicker = () => window.showLanguagePicker?.(config.languages);
    header.setAttribute('role', 'button');
    header.setAttribute('tabindex', '0');
    header.setAttribute('aria-haspopup', 'dialog');
    header.onclick = () => {
        if (!step.classList.contains('language-summary-active')) openLanguagePicker();
    };
    header.onkeydown = event => {
        if (!step.classList.contains('language-summary-active')
            && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            openLanguagePicker();
        }
    };

    setActiveSetupStep('step1');

    // Setup event listeners for tabs
    setupLanguageTabs();
}

function setupLanguageTabs() {
    const inlinePill = document.getElementById('selectedLanguageInline');
    const sourcePill = document.getElementById('selectedSourceInline');
    const sourceLabel = document.getElementById('selectedSourceInlineLabel');
    const languageCardButton = document.getElementById('standardSourceLanguageBtn');
    const sourceCardButton = document.getElementById('standardSourcePickerBtn');

    // The compact language summary reopens the radial picker directly.
    const reopenLanguagePicker = function(event) {
        event.stopPropagation();
        window.closeRadialPicker?.('learningSourceRadialPicker');
        window.closeRadialPicker?.('artistRadialPicker');
        unmergeStandardProgressFromLanguageStep();
        inlinePill.style.display = 'none';
        document.getElementById('languageTabs').style.display = 'flex';
        // Hide subsequent steps
        document.getElementById('step2').style.display = 'none';
        document.getElementById('lemmaToggleContainer').style.display = 'none';
        document.getElementById('cognateToggleContainer').style.display = 'none';
        document.getElementById('step4').style.display = 'none';
        hideAllSelectionPills();
        setActiveSetupStep('step1');
        window.showLanguagePicker?.(config.languages);
    };
    inlinePill.onclick = reopenLanguagePicker;
    languageCardButton.onclick = reopenLanguagePicker;

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
            _setupLevelSelectionWasManual = false;
            applyGlobalStudyDefaults();

            // Mirror the boot-time Spanish-only fetches in main.js so users
            // who land on a non-Spanish first language and switch to Spanish
            // still get rank + conjugated-English data. Full paradigms remain
            // lazy until the conjugation panel opens. Idempotent — no-ops if
            // already loaded.
            if (newLanguage === 'spanish') {
                if (window.loadSpanishRanks) window.loadSpanishRanks();
                if (window.loadConjugatedEnglishData) window.loadConjugatedEnglishData();
            }

            applyLanguageColorTheme();

            // Show inline pill in the header, hide the tabs
            const langConfig = config.languages[selectedLanguage];
            inlinePill.textContent = langConfig ? langConfig.name : selectedLanguage;
            document.getElementById('languageTabs').style.display = 'none';
            inlinePill.style.display = 'inline-flex';
            sourceLabel.textContent = 'Choose source';
            sourcePill.classList.add('source-pill-inline--pending');
            mergeStandardProgressIntoLanguageStep();

            // Hide all subsequent steps while loading
            document.getElementById('step2').style.display = 'none';
            document.getElementById('lemmaToggleContainer').style.display = 'none';
            document.getElementById('cognateToggleContainer').style.display = 'none';
            document.getElementById('step4').style.display = 'none';
            hideAllSelectionPills();

            const continueToSpeech = async () => {
                if (selectedLanguage !== newLanguage) return;
                window.showAppLoading?.('Preparing Speech', 'Loading levels and your progress…');
                try {
                    sourceLabel.textContent = 'Speech';
                    sourcePill.classList.remove('source-pill-inline--pending');
                    const loadingIndicator = document.getElementById('dataLoadingIndicator');
                    loadingIndicator.classList.add('visible');

                    // Start refreshing progress from Sheets (cache loads synchronously inside).
                    let progressRefresh = Promise.resolve(false);
                    if (currentUser && !currentUser.isGuest) {
                        progressRefresh = loadUserProgressFromSheet();
                    }

                    // Always load PPM data if available (needed for coverage bar even in CEFR mode).
                    const langPpmPath = config.languages[selectedLanguage] && config.languages[selectedLanguage].ppmDataPath;
                    if (!ppmData && langPpmPath) {
                        await loadPpmData(selectedLanguage);
                    }

                    loadingIndicator.classList.remove('visible');
                    document.getElementById('step2').style.display = 'block';
                    setActiveSetupStep('step2');
                    updatePercentModeButton();
                    updateStep2Tooltip();
                    updateStep5Tooltip();

                    await renderLevelSelector(selectedLanguage);
                    await updateLemmaToggleVisibility();
                    await updateCognateToggleVisibility();
                    await updateExclusionBars();
                    updateIncorrectButtonVisibility();

                    progressRefresh.then(changed => {
                        const setupPanel = document.getElementById('setupPanel');
                        if (changed && setupPanel && !setupPanel.classList.contains('hidden')) {
                            window.refreshSetupAfterProgress?.();
                        }
                    }).catch(() => {});
                    updateTotalStatsButtonVisibility();
                } finally {
                    document.getElementById('dataLoadingIndicator')?.classList.remove('visible');
                    window.hideAppLoading?.();
                }
            };

            // Speech setup keeps the source choice reachable. Choosing Lyrics
            // from this same clock opens the artist picker for this language.
            sourcePill.onclick = event => {
                event.stopPropagation();
                window.showLearningSourcePicker?.(newLanguage, continueToSpeech);
            };
            sourceCardButton.onclick = sourcePill.onclick;

            // Source is the next decision. A deliberate return from an artist
            // card skips the clock and resumes Speech in the same language.
            if (sessionStorage.getItem('fluencyPendingSpeechLanguage') === newLanguage) {
                sessionStorage.removeItem('fluencyPendingSpeechLanguage');
                await continueToSpeech();
            } else {
                window.showLearningSourcePicker?.(newLanguage, continueToSpeech);
            }
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
                <p><strong>Choose a numbered level.</strong> Level 1 starts with ${name}'s most frequent words; each later level adds rarer vocabulary.</p>
                <p>The summary shows the vocabulary ranks and share of the lyrics covered under your current settings.</p>
                <p>The note below says how many words are in that level and how often its least frequent words appear, followed by a few examples.</p>
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
            <p>Each level is divided into stable sets of about 20 frequency positions in ${name}'s lyrics. The first set with unseen cards is selected automatically.</p>
            <p>Settings may shorten a set, but they never move a card into a different level or set.</p>
            <p><strong>Example sentences</strong> favour nearby-frequency words, helping the cards in a set reinforce one another.</p>
        `;
    } else {
        tooltip.innerHTML = `
            <p>Each level is divided into stable sets of about 20 frequency positions. The first set with unseen cards is selected automatically.</p>
            <p>Settings may shorten a set, but they never move a card into a different level or set.</p>
            <p><strong>Subtitle examples</strong> already favour nearby-frequency words, so each small set forms a useful learning neighbourhood.</p>
        `;
    }
}

// Annotates every level control with its completion percentage and returns
// the first level that still has work. The visible scrubber gets a small
// partial-progress bar; its hidden .level-btn keeps the same data for setup
// logic and the non-slider fallback.
async function findFirstIncompleteLevelBtn(language, buttons) {
    const langConfig = config.languages[language];
    if (!langConfig) return null;
    const vocabularyData = await fetchActiveVocabularyData(langConfig);
    const filteredVocab = getPreparedSetupVocabulary(language, vocabularyData)?.vocab || [];
    const estimate = levelEstimates[language] || 0;
    const estimatedIds = activeArtist && currentUser && !currentUser.isGuest
        ? await buildEstimatedKnownIds(estimate)
        : null;
    const wordSeen = item => {
        if (!currentUser || currentUser.isGuest || !progressData) return false;
        const wordId = getWordId(item);
        const recorded = getWordProgressState(wordId);
        // Review is a separate route. Once a card has been encountered, it
        // must not hold new-set progression on this level indefinitely.
        if (recorded.seen || wordHasKnowledgeProgress(wordId)) return true;
        if (activeArtist) {
            if (item.id && estimatedIds?.has(item.id)) return true;
        } else if (item.rank <= estimate) {
            return true;
        }
        return false;
    };

    let firstIncomplete = null;
    let lastAvailable = null;
    let lastSuggestionLevel = null;

    for (let buttonIndex = 0; buttonIndex < buttons.length; buttonIndex++) {
        const btn = buttons[buttonIndex];
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
            const rank = _levelRankAccessor(rankBasis)(it);
            return rank >= minWord && rank < maxWord;
        });
        if (wordsInLevel.length === 0) continue;
        lastAvailable = btn;
        const suggestionSkipped = window.isLevelMarkedDone?.(btn.dataset.level) || false;
        if (!suggestionSkipped) lastSuggestionLevel = btn;
        const seenCount = wordsInLevel.filter(wordSeen).length;
        const completion = Math.round(100 * seenCount / wordsInLevel.length);
        const hasUnseen = seenCount < wordsInLevel.length;
        const isPartial = seenCount > 0 && hasUnseen;
        btn.dataset.progressPct = String(completion);
        btn.classList.toggle('has-partial-progress', isPartial);
        btn.classList.toggle('is-suggestion-skipped', suggestionSkipped);
        btn.style.setProperty('--level-progress', `${completion}%`);

        const visibleSegment = document.querySelector(`#lswSlider .lsw-seg[data-i="${buttonIndex}"]`);
        if (visibleSegment) {
            visibleSegment.dataset.progressPct = String(completion);
            visibleSegment.classList.toggle('has-partial-progress', isPartial);
            visibleSegment.classList.toggle('is-suggestion-skipped', suggestionSkipped);
            visibleSegment.style.setProperty('--level-progress', `${completion}%`);
            visibleSegment.setAttribute(
                'aria-label',
                `Level ${buttonIndex + 1}, ${completion}% complete${suggestionSkipped ? ', skipped in suggestions' : ''}`
            );
        }
        if (!firstIncomplete && hasUnseen && !suggestionSkipped) firstIncomplete = btn;
    }
    return firstIncomplete || lastSuggestionLevel || lastAvailable || buttons[buttons.length - 1];
}

async function renderLevelSelector(language, { preferActionable = false } = {}) {
    const container = document.getElementById('levelSelector');
    if (preferActionable) _setupLevelSelectionWasManual = false;

    if (useLemmaMode) {
        await ensureLemmaPoolingData(config.languages[language]);
    }
    if (!selectedLevel) setActiveSetupStep('step2');

    // Artist Extra replaces frequency levels with category groups.
    if (activeArtist && artistVocabularyScope === 'extra') {
        await renderExtraCategorySelector(container, language, { preferActionable });
        return;
    }

    // Debug logging
    console.log('renderLevelSelector called:', { percentageMode, ppmDataLength: ppmData ? ppmData.length : 0, language });

    // Use percentage levels if in percentage mode with PPM data.
    // In percentage mode the user picks a level via a log-spaced slider:
    // each snap point is one of the percentageLevels (70%, 80%, …, 100%).
    // The level buttons are still rendered (hidden) because renderRangeSelector
    // and other code paths read .level-btn.selected for startRank/endRank.
    if (percentageMode && ppmData && ppmData.length > 0) {
        // Smart segment boundaries (both modes): pick stable baseline snap
        // points that target ~equal cards-per-segment with frequency-cliff labels
        // where the cliffs exist in the data. Algorithm auto-scales —
        // artist mode (raw counts 2–500) gets cliffs like ≥50/≥20/…/≥2;
        // normal mode (occurrences_ppm 1–50000) gets cliffs in the
        // thousands. Falls back to the legacy coverage-threshold ranges
        // if the vocab cache isn't available yet.
        _smartLevelRangesCache = null;
        const preparedSamples = await _loadLevelSliderSamples(selectedLanguage);
        const _raw = _levelSliderRawCache[selectedLanguage];
        if (_raw) {
            // Level boundaries are built from the stable baseline before any
            // optional filters. Filters change the eligible card count inside
            // a level, never the level's identity or rank span.
            const prepared = getPreparedSetupVocabulary(selectedLanguage, _raw);
            _smartLevelRangesCache = computeSmartLevelRanges(prepared?.stableBaseline || []);
            const eligible = prepared?.vocab || [];
            const lastEligibleRank = eligible.reduce((maxRank, item) =>
                Math.max(maxRank, Number(item.stableRank) || 0), 0);
            // Hide only empty trailing levels (most notably the reserved 1×
            // tail while single-occurrence words are hidden). Re-enabling a
            // filter appends those levels without changing any earlier cut.
            _smartLevelRangesCache = _smartLevelRangesCache.filter(range =>
                range.startRank <= lastEligibleRank);
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

        // The partition remains frequency-aware, but its controls use stable,
        // plain numbered levels. Frequency details live in the explanatory
        // line below instead of competing with navigation labels.
        const ticksHTML = percentageRanges.map((lv, i) => {
            const label = `Level ${i + 1}`;
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
        // Older saved selections may use a level id from the pre-stable
        // partition. Adopt the nearest baseline boundary once; current filter
        // toggles keep the exact stable id thereafter.
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
        const initialMetrics = _levelBandMetrics(initial, preparedSamples);
        // Coverage display: use threshold for smart ranges, level string for legacy.
        const initialCoverage = initial.threshold != null
            ? `${(initial.threshold * 100).toFixed(1)}%`
            : initial.level;
        container.classList.add('level-selector--slider');
        container.innerHTML = `
            <div class="level-slider-wrap">
                <div class="lsw-readout">
                    <span class="lsw-rank"><strong id="lswLevelVal">Level ${initialIdx + 1}</strong></span>
                    <span class="lsw-range">Ranks <strong id="lswRankVal">${initialMetrics.start.toLocaleString()}–${initialMetrics.end.toLocaleString()}</strong></span>
                    <span class="lsw-coverage">~<strong id="lswCovVal">${initialCoverage}</strong> ${coverageType}</span>
                </div>
                <div id="lswSlider" class="lsw-segments lsw-scrubber" role="radiogroup" aria-label="Level scrubber" data-value="${initialIdx}">
                    ${percentageRanges.map((lv, i) => {
                        const segLabel = `Level ${i + 1}`;
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
        btn.addEventListener('click', function(event) {
            if (event.isTrusted) _setupLevelSelectionWasManual = true;
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

            // Reveal optional filters and the automatic next-set panel.
            document.getElementById('lemmaToggleContainer').style.display = 'block';

            // Show cognate toggle after lemma toggle (if available)
            setTimeout(() => {
                if (cognateFieldAvailable) {
                    document.getElementById('cognateToggleContainer').style.display = 'block';
                }
            }, 75);

            this._rangeRenderPromise = renderRangeSelector();
            this._rangeRenderPromise.catch(err => console.error('Error rendering ranges:', err));

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

    const levelButtons = Array.from(document.querySelectorAll('.level-btn'));
    const levelProgressPromise = levelButtons.length > 0
        ? findFirstIncompleteLevelBtn(language, levelButtons)
        : Promise.resolve(null);

    // Auto-select first time only (preserves manual picks across re-renders).
    // Pick the first level that isn't fully completed so the user lands on
    // actionable work — finishing the 70% level should auto-open 80%, not
    // sit on a level whose sets are already complete. Falls back to the
    // first button on data-load failure or if there are no buttons.
    if (!selectedLevel || preferActionable) {
        if (levelButtons.length === 0) return;
        let target = levelButtons[0];
        try {
            const incomplete = await levelProgressPromise;
            if (incomplete) target = incomplete;
        } catch (err) {
            console.warn('Level auto-pick failed, using first', err);
        }
        // Re-check: the user may have clicked a level during the await above.
        if (!_setupLevelSelectionWasManual && (!selectedLevel || preferActionable)) {
            target.click();
            await target._rangeRenderPromise;
        }
    } else {
        levelProgressPromise.catch(err =>
            console.warn('Level progress indicators unavailable', err));
    }
}

function _escapeAttr(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// Artist Extra category picker. Replaces the frequency slider with one pickable
// group per distinct `extra_category` value. Each category is backed by a
// hidden `.level-btn` carrying its category rank block, so the existing
// renderRangeSelector()/study-set machinery pages through it unchanged. If the
// data has no categories yet, buildFilteredVocab() returns a single "All Extra"
// group and this renders one chip.
async function renderExtraCategorySelector(container, language, { preferActionable = false } = {}) {
    const langConfig = config.languages[language];
    let vocabularyData = [];
    try {
        vocabularyData = await fetchActiveVocabularyData(langConfig);
    } catch (error) {
        console.error('Failed to load vocabulary data for Extra categories:', error);
    }
    // Populate categoryRank + the ordered group metadata.
    buildFilteredVocab(vocabularyData);
    const groups = (window.getExtraCategoryGroups?.() || []);

    container.classList.remove('level-selector--slider');

    if (groups.length === 0) {
        container.innerHTML = '<div class="study-set-empty">No Extra vocabulary is available with the current settings.</div>';
        return;
    }

    const chipsHTML = groups.map((group, index) => `
        <button type="button" class="extra-category-chip" data-cat-index="${index}"
                role="radio" aria-checked="false"
                aria-label="${_escapeAttr(group.label)}, ${group.count} word${group.count === 1 ? '' : 's'}">
            <span class="extra-category-chip-label">${_escapeAttr(group.label)}</span>
            <span class="extra-category-chip-count">${group.count.toLocaleString()}</span>
        </button>
    `).join('');

    const hiddenButtonsHTML = groups.map(group => `
        <button class="level-btn" data-level="cat:${_escapeAttr(group.key)}"
                data-short="${_escapeAttr(group.label)}" data-full="${_escapeAttr(group.label)}"
                data-start-rank="${group.startRank}" data-end-rank="${group.endRank}"
                data-rank-basis="category" title="${_escapeAttr(group.label)}">
            ${_escapeAttr(group.label)}
        </button>
    `).join('');

    container.innerHTML = `
        <div class="extra-category-selector">
            <p class="extra-category-intro">Extra vocabulary is grouped by kind, not by how often it appears. Pick a group to study.</p>
            <div class="extra-category-chips" role="radiogroup" aria-label="Extra vocabulary categories">
                ${chipsHTML}
            </div>
        </div>
        <div class="level-selector-buttons" style="display:none">${hiddenButtonsHTML}</div>
    `;

    const hiddenButtons = Array.from(container.querySelectorAll('.level-selector-buttons .level-btn'));
    const chips = Array.from(container.querySelectorAll('.extra-category-chip'));

    const selectCategory = async index => {
        hiddenButtons.forEach((btn, i) => btn.classList.toggle('selected', i === index));
        chips.forEach((chip, i) => {
            const selected = i === index;
            chip.classList.toggle('selected', selected);
            chip.setAttribute('aria-checked', selected ? 'true' : 'false');
        });
        selectedLevel = hiddenButtons[index].dataset.level;
        // Merge Lemmas and Exclude Cognates are meaningless in Extra (Exclude
        // Cognates only changes which category cognates land in), so hide both.
        document.getElementById('lemmaToggleContainer').style.display = 'none';
        document.getElementById('cognateToggleContainer').style.display = 'none';
        await renderRangeSelector();
    };

    // Wire hidden buttons so getNextStudyLevelMeta()/startNextStudyLevelFirstSet()
    // (which .click() the next .level-btn) reuse this exact selection path.
    hiddenButtons.forEach((btn, index) => {
        btn.addEventListener('click', () => {
            btn._rangeRenderPromise = selectCategory(index);
            btn._rangeRenderPromise.catch(err => console.error('Error rendering Extra ranges:', err));
        });
    });
    chips.forEach((chip, index) => {
        chip.addEventListener('click', () => {
            _setupLevelSelectionWasManual = true;
            hiddenButtons[index].click();
        });
    });

    // Preserve an explicit category choice; on landing/return, route to the
    // first category that still contains unseen cards and is not skipped.
    let initialIndex = 0;
    if (selectedLevel && !preferActionable) {
        const saved = hiddenButtons.findIndex(btn => btn.dataset.level === selectedLevel);
        if (saved >= 0) initialIndex = saved;
        else selectedLevel = null;
    }
    if ((!selectedLevel || preferActionable) && !_setupLevelSelectionWasManual) {
        try {
            const actionable = await findFirstIncompleteLevelBtn(language, hiddenButtons);
            const actionableIndex = hiddenButtons.indexOf(actionable);
            if (actionableIndex >= 0) initialIndex = actionableIndex;
        } catch (error) {
            console.warn('Extra category auto-pick failed, using first', error);
        }
    }
    hiddenButtons[initialIndex].click();
    await hiddenButtons[initialIndex]._rangeRenderPromise;
}

// Smart-range cache: computed snap points for the active source baseline.
// Filters can change the eligible count shown inside each cached range but
// cannot change these boundaries.
let _smartLevelRangesCache = null;

// Build an adaptive number of finishable study bands: roughly one per 200
// cards, with ten bands for small decks and a ceiling of 80 for very large
// ones. Each level is subdivided into stable 20-position study sets.
// Each boundary starts at an equal-card quantile, then snaps to a genuine
// frequency cliff when one is nearby.
// If no cliff is close, keeping the quantile deliberately subdivides a
// large tied tail (2x/3x in artist decks) instead of collapsing it into one
// enormous final band.
//
// Boundaries always use the form-level corpus frequency baseline. Merge
// Lemmas anchors a merged card to its highest-frequency form, and every
// optional exclusion simply leaves a hole inside the fixed region.
function computeSmartLevelRanges(filteredVocab) {
    if (!filteredVocab || filteredVocab.length === 0) return [];
    const items = filteredVocab;
    const total = items.length;
    const frequencyOf = (item) => {
        const raw = item.corpus_count;
        const value = Number(raw);
        return Number.isFinite(value) ? Math.max(0, value) : 0;
    };
    const fmtCompact = (n) => n >= 1000
        ? (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, '') + 'k'
        : String(Math.round(n));

    const targetCardsPerLevel = 200;
    const minimumLevelCount = 10;
    const maximumLevelCount = 80;
    const segmentCount = Math.min(
        total,
        maximumLevelCount,
        Math.max(minimumLevelCount, Math.ceil(total / targetCardsPerLevel))
    );
    const idealBandSize = total / segmentCount;
    const snapWindow = Math.max(2, Math.round(idealBandSize * 0.25));
    const minBandSize = Math.max(1, Math.round(idealBandSize * 0.5));

    // A cliff count is the number of cards included immediately before the
    // effective frequency drops. Counts are exclusive endpoints, matching
    // the range loader's stableRank >= start && stableRank < end contract.
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
        const bandCardCount = cardCount - previousBoundary;

        // Level identifier — keyed by cardCount so selectedLevel round-trips
        // stably across re-renders even when several cuts share a frequency.
        const level = `c${cardCount}`;
        const tickLabel = splitTier
            ? `${fmtCompact(freqMin)}× · ${fmtCompact(cardCount)}`
            : `≥${fmtCompact(freqMin)}`;
        const basisDescription = 'baseline corpus occurrences';
        const rankDescription = `Ranks ${startRank.toLocaleString()}–${cardCount.toLocaleString()} · ${bandCardCount.toLocaleString()} cards`;
        const description = splitTier
            ? `${rankDescription} · cutoff partway through the ${fmtCompact(freqMin)}× tier · ${(coverage * 100).toFixed(1)}% cumulative coverage by ${basisDescription}`
            : `${rankDescription} · frequency ≥${fmtCompact(freqMin)} · ${(coverage * 100).toFixed(1)}% cumulative coverage by ${basisDescription}`;

        ranges.push({
            level,
            startRank,
            endRank,
            rankBasis: 'stable',
            cardCount,
            bandCardCount,
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

// Filtering restores/clones sense menus, assigns stable ranks and (in lemma
// mode) scans the examples corpus. Setup previously repeated that full pass in
// the slider, progress annotation, range selector and exclusion summary. Keep
// one prepared result until the source/settings/examples identity changes.
let _preparedSetupVocabulary = null;

function _setupVocabularySignature(language) {
    const langConfig = config.languages[language] || {};
    return [
        language,
        langConfig.indexPath || langConfig.dataPath || '',
        (window._selectedArtistSlugs || []).slice().sort().join(','),
        activeArtist ? artistVocabularyScope : 'speech',
        percentageMode,
        useLemmaMode,
        excludeCognates,
        cognateThreshold,
        hideSingleOccurrence,
        excludeProperNouns,
        excludeNoise,
        excludeEnglishLoanwords,
    ].join('|');
}

function getPreparedSetupVocabulary(language, rawVocab) {
    if (!rawVocab) return null;
    const signature = _setupVocabularySignature(language);
    if (_preparedSetupVocabulary
        && _preparedSetupVocabulary.raw === rawVocab
        && _preparedSetupVocabulary.signature === signature
        && _preparedSetupVocabulary.examples === window._cachedExamplesData) {
        return _preparedSetupVocabulary.result;
    }
    const result = buildFilteredVocab(rawVocab);
    result.samples = result.vocab.map(item => ({
        rank: item.rank,
        displayRank: item.displayRank,
        stableRank: item.stableRank,
        word: item.lemma || item.targetWord || item.word || ''
    })).filter(sample => sample.word);
    _preparedSetupVocabulary = {
        raw: rawVocab,
        signature,
        examples: window._cachedExamplesData,
        result,
    };
    return result;
}

function invalidatePreparedSetupVocabulary() {
    _preparedSetupVocabulary = null;
}

window.getPreparedSetupVocabulary = getPreparedSetupVocabulary;
window.invalidatePreparedSetupVocabulary = invalidatePreparedSetupVocabulary;

function _samplesFromRaw(rawVocab, language = selectedLanguage) {
    return getPreparedSetupVocabulary(language, rawVocab)?.samples || [];
}

// Synchronous fast path used by the slider readout/tick labels — returns
// post-filter samples if the raw vocab is already cached, otherwise null
// so the caller can fall back to raw rank numbers until the async load
// resolves.
function _levelSliderSamplesSync(language) {
    const raw = _levelSliderRawCache[language];
    return raw ? _samplesFromRaw(raw, language) : null;
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
    return _samplesFromRaw(raw, language);
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

// The level loader treats endRank as an exclusive boundary. Keep the setup
// readout on that same contract so every level reports its own real band
// (for example 201–400), rather than presenting every band as Ranks 1–X.
function _levelBandMetrics(level, samples = null) {
    const start = Math.max(1, Number(level?.startRank) || 1);
    const endExclusive = Math.max(start + 1, Number(level?.endRank) || start + 1);
    const end = endExclusive - 1;
    let count;
    if (samples) {
        const rankOf = _levelRankAccessor(level?.rankBasis);
        count = samples.filter(sample => {
            const rank = rankOf(sample);
            return rank >= start && rank < endExclusive;
        }).length;
    } else {
        count = Number(level?.bandCardCount);
        if (!Number.isFinite(count)) count = endExclusive - start;
    }
    return { start, end, count: Math.max(0, count) };
}

function _levelRankAccessor(rankBasis) {
    if (rankBasis === 'category') return item => item.categoryRank;
    if (rankBasis === 'stable') return item => item.stableRank;
    if (rankBasis === 'display') return item => item.displayRank;
    return item => item.rank;
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
            const metrics = _levelBandMetrics(lv, samples);
            rankEl.textContent = `${metrics.start.toLocaleString()}–${metrics.end.toLocaleString()}`;
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
    const levelEl = document.getElementById('lswLevelVal');
    if (levelEl) levelEl.textContent = `Level ${idx + 1}`;
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
        if (btn) {
            _setupLevelSelectionWasManual = true;
            btn.click(); // → renderRangeSelector (resets the set options)
        }
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
            if (!Number.isNaN(idx) && buttons[idx]) {
                _setupLevelSelectionWasManual = true;
                buttons[idx].click();
            }
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
    // Synchronous range and card count for this level's own band. Smart
    // ranges carry the exact band count; legacy ranges are counted against
    // the filtered samples when available.
    const _syncSamples = _levelSliderSamplesSync(selectedLanguage);
    if (rankEl) {
        const metrics = _levelBandMetrics(lv, _syncSamples);
        rankEl.textContent = `${metrics.start.toLocaleString()}–${metrics.end.toLocaleString()}`;
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
    let displayedWordCount = _levelBandMetrics(lv, _syncSamples).count;
    if (lv.freqMin != null) {
        freqValue = lv.freqMin;
        freqUnit = activeArtist
            ? `time${freqValue === 1 ? '' : 's'} in the lyrics`
            : `time${freqValue === 1 ? '' : 's'} per million words`;
    } else if (ppmData && ppmData.length > 0) {
        const _e = ppmData.find(p => p.rank === lv.endRank);
        if (_e) {
            freqValue = Math.round(_e.ppm);
            freqUnit = activeArtist
                ? `time${freqValue === 1 ? '' : 's'} in the lyrics`
                : `time${freqValue === 1 ? '' : 's'} per million words`;
        }
    }

    const _renderLine = (examplesText) => {
        // Frequency as a full sentence on its own line, then the example
        // words for this level on a new line underneath (stacked via the
        // .lsw-examples column layout in CSS).
        const wordLabel = `${displayedWordCount.toLocaleString()} word${displayedWordCount === 1 ? '' : 's'}`;
        const freqHTML = freqValue !== null
            ? `<div class="lsw-freq-sentence"><strong>${wordLabel}</strong> appear${displayedWordCount === 1 ? 's' : ''} <strong>${freqValue.toLocaleString()}</strong> ${freqUnit}</div>`
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
        displayedWordCount = _levelBandMetrics(lv, samples).count;
        // Pick 5 words from the upper portion of this level's range — the
        // ones that just qualified at this coverage threshold are the most
        // illustrative of "what you'll be learning here".
        const rankOf = _levelRankAccessor(lv.rankBasis);
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
    syncStudyPreferenceControls();
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
    // Cognate sensitivity (Loose / Default / Strict) lives in Study settings.
    // Higher threshold = only the most obvious
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
    // The sensitivity row's "?" is wired by setupSettingExplanations(), which
    // opens both its one-line description and the longer aria-controls block.
    updateCognateSensitivityVisibility();
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
    updateCognateSensitivityVisibility();
}

function setupLemmaToggle() {
    syncStudyPreferenceControls();
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
    // CEFR is deliberately hidden in both modes for now. Keep the handler
    // and data path intact so the mode can be restored later without a
    // migration or reimplementation.
    toggle.style.display = 'none';
    toggle.setAttribute('aria-hidden', 'true');
    toggle.tabIndex = -1;
    return;

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

        // On light accents, use a stable dark ink rather than the current page
        // background. The latter becomes near-white in light appearance and
        // would make yellow language/artist controls unreadable after a switch.
        const onLightAccent = '#17212b';
        root.style.setProperty('--accent-primary-text', luminance(langConfig.colorTheme.primary) < 0.4 ? '#ffffff' : onLightAccent);
        root.style.setProperty('--accent-secondary-text', luminance(langConfig.colorTheme.secondary) < 0.4 ? '#ffffff' : onLightAccent);

        root.style.setProperty('--accent-primary-rgb', hexToRgb(langConfig.colorTheme.primary));
        root.style.setProperty('--accent-secondary-rgb', hexToRgb(langConfig.colorTheme.secondary));
    }
}

// Shared vocabulary filter pipeline used by renderRangeSelector and loadVocabularyData.
// Applies all active exclusions in the correct order and assigns corpus-wide display ranks.
// Returns { vocab: filteredArray, counts: { english, cognates, singleOcc, lemma } }


const STABLE_SET_SLOT_COUNT = 20;

function getSetupLearningState(item, { seenLemmas = new Set(), estimatedIds = null, estimate = 0 } = {}) {
    if (!currentUser || currentUser.isGuest || !progressData) return false;

    const wordId = getWordId(item);
    const crossModeId = getCrossModeId(wordId);
    const relatedIds = crossModeId ? [wordId, crossModeId] : [wordId];
    const recordedStates = relatedIds.map(id => getWordProgressState(id));
    const recorded = recordedStates.find(state => state?.needsReview)
        || recordedStates.find(state => state?.seen)
        || recordedStates[0];
    const reviewInfo = relatedIds
        .map(id => getWordKnowledgeReviewInfo(id))
        .find(info => info?.needsReview);

    // A real answer is more specific than the estimated starting level;
    // in particular, a later wrong must remain reviewable. Setup and deck
    // construction must inspect the same current/cross-mode identities.
    if (reviewInfo) {
        return {
            ...recorded,
            seen: true,
            needsReview: true,
            learned: false,
            reviewReason: reviewInfo.reason,
            reviewAt: reviewInfo.reviewAt
        };
    }
    if (recorded?.seen) return recorded;
    if (relatedIds.some(id => wordHasKnowledgeProgress(id))) {
        return { ...recorded, seen: true };
    }

    // Merge Lemmas treats progress on any surface form as progress on the
    // shared lemma. This is the same set used by Learn New during deck build,
    // so the button count cannot advertise cards that will then be removed.
    if (seenLemmas.has(item.lemma)) {
        return { ...recorded, seen: true, needsReview: false, learned: true, inheritedLemma: true };
    }

    if (activeArtist) {
        if (item.id && estimatedIds?.has(item.id)) {
            return { seen: true, needsReview: false, learned: true, estimated: true };
        }
    } else if (item.rank <= estimate) {
        return { seen: true, needsReview: false, learned: true, estimated: true };
    }
    return recorded;
}

async function renderRangeSelector() {
    const langConfig = config.languages[selectedLanguage];
    const container = document.getElementById('rangeSelector');
    let minWord, maxWord;
    let rankBasis = 'source';

    const selectedLevelBtn = document.querySelector('.level-btn.selected');
    // Artist Extra category groups carry their own rank block on the selected
    // level button and are independent of percentage/CEFR mode.
    if (selectedLevelBtn?.dataset.rankBasis === 'category') {
        minWord = parseInt(selectedLevelBtn.dataset.startRank);
        maxWord = parseInt(selectedLevelBtn.dataset.endRank);
        rankBasis = 'category';
    } else if (percentageMode && ppmData && ppmData.length > 0) {
        const selectedBtn = selectedLevelBtn;
        if (!selectedBtn) return;
        minWord = parseInt(selectedBtn.dataset.startRank);
        maxWord = parseInt(selectedBtn.dataset.endRank);
        rankBasis = selectedBtn.dataset.rankBasis || 'source';
    } else {
        const level = getCefrLevels(selectedLanguage).find(item => item.level === selectedLevel);
        if (!level) return;
        [minWord, maxWord] = level.wordCount.split('-').map(Number);
    }
    if (!Number.isFinite(minWord) || !Number.isFinite(maxWord)) {
        console.warn('renderRangeSelector: bad level boundary', { minWord, maxWord, selectedLevel });
        container.innerHTML = '';
        return;
    }

    let vocabularyData = [];
    try {
        vocabularyData = await fetchActiveVocabularyData(langConfig);
    } catch (error) {
        console.error('Failed to load vocabulary data:', error);
    }
    const preparedVocabulary = getPreparedSetupVocabulary(selectedLanguage, vocabularyData);
    const filteredVocab = preparedVocabulary?.vocab || [];
    const filterCounts = preparedVocabulary?.counts || { lemma: 0, cognates: 0 };

    const lemmaInfo = document.getElementById('lemmaInfoLine');
    if (lemmaInfo) {
        lemmaInfo.textContent = `${filterCounts.lemma.toLocaleString()} flashcards merged`;
        lemmaInfo.style.display = filterCounts.lemma > 0 ? '' : 'none';
    }
    const cognateInfo = document.getElementById('cognateInfoLine');
    if (cognateInfo) {
        cognateInfo.textContent = `${filterCounts.cognates.toLocaleString()} flashcards excluded`;
        cognateInfo.style.display = filterCounts.cognates > 0 ? '' : 'none';
    }

    const rankOf = _levelRankAccessor(rankBasis);
    const wordsInLevel = filteredVocab.filter(item => {
        const rank = rankOf(item);
        return rank >= minWord && rank < maxWord;
    });
    if (wordsInLevel.length === 0) {
        container.innerHTML = '<div class="study-set-empty">No cards remain in this level with the current settings.</div>';
        document.getElementById('step4').style.display = 'block';
        return;
    }

    const estimate = levelEstimates[selectedLanguage] || 0;
    const estimatedIds = activeArtist && currentUser && !currentUser.isGuest
        ? await buildEstimatedKnownIds(estimate)
        : null;
    const seenLemmas = await window.buildSeenLemmaSet?.(vocabularyData) || new Set();

    // Sets use fixed baseline slots. Filters can make a set shorter, but
    // never refill it from its neighbour; this preserves membership, progress,
    // and the nearby-rank example neighbourhood across setting changes.
    const ranges = [];
    for (let start = minWord; start < maxWord; start += STABLE_SET_SLOT_COUNT) {
        const end = Math.min(start + STABLE_SET_SLOT_COUNT, maxWord);
        const words = wordsInLevel.filter(item => {
            const rank = rankOf(item);
            return rank >= start && rank < end;
        });
        const states = words.map(item => getSetupLearningState(item, {
            seenLemmas,
            estimatedIds,
            estimate
        }));
        const seenCount = states.filter(state => state?.seen).length;
        const reviewCount = states.filter(state => state?.needsReview).length;
        const dueCount = states.filter(state => state?.reviewReason === 'due').length;
        const knownCount = Math.max(0, seenCount - reviewCount);
        const unseenCount = words.length - seenCount;
        ranges.push({
            range: `${start}-${end}`,
            start,
            end,
            available: words.length > 0,
            cardCount: words.length,
            seenCount,
            knownCount,
            unseenCount,
            reviewCount,
            dueCount,
            pct: words.length > 0 ? Math.round(100 * seenCount / words.length) : 100,
            knownPct: words.length > 0 ? 100 * knownCount / words.length : 100,
            reviewEndPct: words.length > 0 ? 100 * (knownCount + reviewCount) / words.length : 100
        });
    }
    const firstIncomplete = ranges.findIndex(range => range.available && range.pct < 100);
    const lastAvailable = ranges.reduce((last, range, index) => range.available ? index : last, -1);
    const initialIndex = firstIncomplete >= 0 ? firstIncomplete : Math.max(0, lastAvailable);
    const completedCount = ranges.filter(range => range.available && range.pct === 100).length;
    const availableCount = ranges.filter(range => range.available).length;

    const dotsHTML = ranges.map((range, index) => {
        const classes = [
            'study-set-dot',
            range.pct === 100 && range.available ? 'is-complete' : '',
            range.pct > 0 && range.pct < 100 && range.available ? 'is-partial' : '',
            index === initialIndex ? 'is-current' : '',
            !range.available ? 'is-empty' : ''
        ].filter(Boolean).join(' ');
        return `<button type="button" class="${classes}"
                    data-index="${index}" data-range="${range.range}"
                    data-rank-basis="${rankBasis}" data-pct="${range.pct}"
                    style="--set-known-end: ${range.knownPct}%; --set-review-end: ${range.reviewEndPct}%"
                    role="radio" aria-checked="${index === initialIndex ? 'true' : 'false'}"
                    aria-label="Set ${index + 1}: ${range.knownCount} known, ${range.reviewCount} to review, ${range.unseenCount} unseen"
                    ${range.available ? '' : 'disabled'}><span>${index + 1}</span></button>`;
    }).join('');

    const levelReviewCount = ranges.reduce((sum, range) => sum + range.reviewCount, 0);
    const levelDueCount = ranges.reduce((sum, range) => sum + range.dueCount, 0);
    const levelUnfinishedCount = Math.max(0, levelReviewCount - levelDueCount);
    let reviewHTML = '';
    if (currentUser && !currentUser.isGuest && levelReviewCount > 0) {
        const reviewMeta = levelDueCount > 0 && levelUnfinishedCount > 0
            ? `${levelDueCount} due · ${levelUnfinishedCount} unfinished`
            : levelDueCount > 0
                ? `${levelDueCount} due in this level`
                : `${levelUnfinishedCount} unfinished in this level`;
        reviewHTML = `<button class="study-set-review" type="button">
                <span>Review cards</span>
                <small>${reviewMeta}</small>
            </button>`;
    }

    const canPersistLevelRouting = currentUser && !currentUser.isGuest;
    const levelSuggestionSkipped = canPersistLevelRouting
        && (window.isLevelMarkedDone?.(selectedLevel) || false);
    const levelDoneToggleHTML = canPersistLevelRouting ? `
        <button class="level-suggestion-toggle${levelSuggestionSkipped ? ' is-on' : ''}"
                id="levelSuggestionToggle" type="button"
                aria-pressed="${levelSuggestionSkipped ? 'true' : 'false'}">
            <span class="level-suggestion-toggle-copy">
                <strong>${levelSuggestionSkipped ? 'Skipped in suggestions' : 'Skip this level in suggestions'}</strong>
                <small>Your card history stays unchanged. You can still open this level yourself.</small>
            </span>
            <span class="level-suggestion-switch" aria-hidden="true"><i></i></span>
        </button>` : '';

    container.innerHTML = `
        <div class="study-set-panel">
            <div class="study-set-overview">
                <strong>${completedCount} of ${availableCount} sets seen</strong>
                <span>New cards stay separate from due and unfinished review</span>
            </div>
            <div class="study-set-legend" aria-label="Set progress colours">
                <span><i class="is-known"></i>Known</span>
                <span><i class="is-review"></i>Review</span>
                <span><i class="is-unseen"></i>Unseen</span>
            </div>
            <div class="study-set-dots" role="radiogroup" aria-label="Sets in this level">${dotsHTML}</div>
            <div class="study-set-current-copy">
                <strong id="studySetCurrentTitle"></strong>
                <span id="studySetCurrentMeta"></span>
            </div>
            <button class="range-btn-new study-set-start" id="studySetStartBtn" type="button"></button>
            ${reviewHTML}
            ${levelDoneToggleHTML}
        </div>`;
    document.getElementById('step4').style.display = 'block';
    setActiveSetupStep('step4');

    const selectSet = index => {
        const range = ranges[index];
        if (!range?.available) return;
        container.querySelectorAll('.study-set-dot').forEach(dot => {
            const selected = Number(dot.dataset.index) === index;
            dot.classList.toggle('is-current', selected);
            dot.setAttribute('aria-checked', selected ? 'true' : 'false');
        });
        document.getElementById('studySetCurrentTitle').textContent = `Set ${index + 1} of ${ranges.length}`;
        // Extra sets page within a category, so position labels read as "Words"
        // rather than frequency "Ranks".
        const positionLabel = rankBasis === 'category'
            ? `Words ${range.start.toLocaleString()}–${(range.end - 1).toLocaleString()} in this group`
            : `Ranks ${range.start.toLocaleString()}–${(range.end - 1).toLocaleString()}`;
        document.getElementById('studySetCurrentMeta').textContent =
            `${positionLabel} · ${range.knownCount} known · ${range.reviewCount} review · ${range.unseenCount} unseen`;
        const startBtn = document.getElementById('studySetStartBtn');
        startBtn.textContent = range.unseenCount > 0
            ? `Learn ${range.unseenCount} new card${range.unseenCount === 1 ? '' : 's'}`
            : `Study Set ${index + 1} Again`;
        startBtn.dataset.range = range.range;
        startBtn.dataset.rankBasis = rankBasis;
        startBtn.dataset.setNumber = String(index + 1);
        startBtn.dataset.levelSetCount = String(ranges.length);
        startBtn.dataset.studyMode = range.unseenCount > 0 ? 'new' : 'all';
    };
    container.querySelectorAll('.study-set-dot').forEach(dot => {
        dot.addEventListener('click', () => {
            // First tap selects and explains a set. Tapping that already
            // selected set again is the compact start action, useful when the
            // full-width button sits just below the mobile viewport.
            if (dot.classList.contains('is-current')) {
                document.getElementById('studySetStartBtn')?.click();
                return;
            }
            selectSet(Number(dot.dataset.index));
        });
    });
    selectSet(initialIndex);

    document.getElementById('studySetStartBtn').addEventListener('click', async function() {
        const selectedRange = this.dataset.range;
        const loadingMessage = document.getElementById('loadingMessage');
        loadingMessage.style.display = 'block';
        loadingMessage.textContent = `Loading Set ${this.dataset.setNumber}...`;
        window.showAppLoading?.(`Loading Set ${this.dataset.setNumber}`, 'Preparing your next cards…');
        try {
            await loadVocabularyData(selectedRange, {
                rankBasis: this.dataset.rankBasis,
                setNumber: Number(this.dataset.setNumber),
                levelSetCount: Number(this.dataset.levelSetCount),
                studyMode: this.dataset.studyMode
            });
        } finally {
            window.hideAppLoading?.();
        }
    });
    container.querySelector('.study-set-review')?.addEventListener('click', async () => {
        const loadingMessage = document.getElementById('loadingMessage');
        loadingMessage.style.display = 'block';
        loadingMessage.textContent = `Loading ${levelReviewCount} review card${levelReviewCount === 1 ? '' : 's'}...`;
        const levelButtons = Array.from(document.querySelectorAll(
            '.level-selector-buttons .level-btn, #levelSelector > .level-btn'
        ));
        const levelNumber = levelButtons.findIndex(button => button.dataset.level === selectedLevel) + 1;
        window.showAppLoading?.('Loading Review', 'Collecting the cards that need another look…');
        try {
            await loadLevelReviewSet(`${minWord}-${maxWord}`, {
                rankBasis,
                levelNumber
            });
        } finally {
            window.hideAppLoading?.();
        }
    });

    document.getElementById('levelSuggestionToggle')?.addEventListener('click', function() {
        const next = this.getAttribute('aria-pressed') !== 'true';
        this.setAttribute('aria-pressed', next ? 'true' : 'false');
        this.classList.toggle('is-on', next);
        const title = this.querySelector('strong');
        if (title) title.textContent = next
            ? 'Skipped in suggestions'
            : 'Skip this level in suggestions';

        const activeLevelButton = document.querySelector(`.level-btn[data-level="${CSS.escape(selectedLevel)}"]`);
        activeLevelButton?.classList.toggle('is-suggestion-skipped', next);
        const levelButtons = Array.from(document.querySelectorAll(
            '.level-selector-buttons .level-btn, #levelSelector > .level-btn'
        ));
        const levelIndex = levelButtons.indexOf(activeLevelButton);
        if (levelIndex >= 0) {
            document.querySelector(`#lswSlider .lsw-seg[data-i="${levelIndex}"]`)
                ?.classList.toggle('is-suggestion-skipped', next);
        }
        window.saveMarkedLevelDone?.(selectedLevel, next).catch(error => {
            console.error('Could not save level suggestion preference:', error);
        });
    });
}

function getNextStudySetMeta(rangeString) {
    if (window.isLevelMarkedDone?.(selectedLevel)) return null;
    const dots = Array.from(document.querySelectorAll('#rangeSelector .study-set-dot'));
    const currentIndex = dots.findIndex(dot => dot.dataset.range === rangeString);
    if (currentIndex < 0) return null;
    const next = dots.slice(currentIndex + 1).find(dot =>
        !dot.disabled && Number(dot.dataset.pct) < 100);
    if (!next) return null;
    return {
        range: next.dataset.range,
        rankBasis: next.dataset.rankBasis || 'stable',
        setNumber: Number(next.dataset.index) + 1,
        levelSetCount: dots.length
    };
}

function getNextStudyLevelMeta() {
    const buttons = Array.from(document.querySelectorAll(
        '.level-selector-buttons .level-btn, #levelSelector > .level-btn'
    ));
    const currentIndex = buttons.findIndex(button => button.dataset.level === selectedLevel);
    const remaining = currentIndex >= 0 ? buttons.slice(currentIndex + 1) : buttons;
    const next = remaining.find(button => {
        const skipped = window.isLevelMarkedDone?.(button.dataset.level) || false;
        const completion = Number(button.dataset.progressPct || 0);
        return !skipped && completion < 100;
    }) || null;
    if (!next) {
        if (activeArtist && artistVocabularyScope === 'main') {
            return {
                scope: 'extra',
                levelNumber: 1,
                label: `${activeArtist.name || 'Artist'} Extra`,
            };
        }
        return null;
    }
    const nextIndex = buttons.indexOf(next);
    return {
        level: next.dataset.level,
        levelNumber: nextIndex + 1,
        // In Extra scope the next "level" is another category — carry its label
        // so the finish button can name the group instead of a level number.
        label: activeArtist && artistVocabularyScope === 'extra'
            ? (next.dataset.full || null)
            : null
    };
}

async function startNextStudyLevelFirstSet() {
    // A progress percentage can be stale by the time the final card is
    // answered (or filters can leave a nominal level with no eligible unseen
    // set). Verify the rendered sets and keep walking forward until we find
    // real new cards. Never fall back to replaying a completed set: that made
    // continuation appear to "stick" and forced the learner back into setup.
    const visitedLevels = new Set();
    while (true) {
        const nextMeta = getNextStudyLevelMeta();
        if (!nextMeta) throw new Error('No next study level with new cards is available');
        if (nextMeta.scope === 'extra') {
            await window.goBackToSetup?.();
            await window.setArtistVocabularyScope?.('extra', { autoStart: true });
            return;
        }
        if (!nextMeta.level || visitedLevels.has(nextMeta.level)) {
            throw new Error('Could not resolve a distinct next study level');
        }
        visitedLevels.add(nextMeta.level);

        // Stay in the active study surface and render the candidate level's
        // stable sets. Clicking updates selectedLevel, so another loop pass
        // naturally searches only the levels after this candidate.
        const next = document.querySelector(
            `.level-btn[data-level="${CSS.escape(nextMeta.level)}"]`);
        if (!next) throw new Error(`Could not find next level ${nextMeta.level}`);

        next.click();
        if (!next._rangeRenderPromise) {
            throw new Error('Next level did not begin rendering its sets');
        }
        await next._rangeRenderPromise;
        const setDots = Array.from(document.querySelectorAll('#rangeSelector .study-set-dot'));
        const firstUnseenSet = setDots.find(dot =>
            !dot.disabled && Number(dot.dataset.pct || 0) < 100);
        if (!firstUnseenSet) continue;

        await loadVocabularyData(firstUnseenSet.dataset.range, {
            rankBasis: firstUnseenSet.dataset.rankBasis || 'stable',
            setNumber: Number(firstUnseenSet.dataset.index) + 1,
            levelSetCount: setDots.length,
            levelNumber: nextMeta.levelNumber
        });
        return;
    }
}


function showStatsModal() {
    document.getElementById('statsModal').classList.remove('hidden');
    updateStatsModal();
}

function hideStatsModal() {
    document.getElementById('statsModal').classList.add('hidden');
}

function showSettingsModal() {
    showSettingsModalWithTab('account');
}

function showSettingsModalWithTab(tabName, { singleTab = false } = {}) {
    // Show/hide refresh set option based on whether a study set is loaded and user is logged in
    const refreshSetToggle = document.getElementById('refreshSetToggle');
    if (currentUser && !currentUser.isGuest && flashcards.length > 0) {
        refreshSetToggle.style.display = 'flex';
    } else {
        refreshSetToggle.style.display = 'none';
    }

    // Sensitivity only applies while cognates are being excluded on a
    // language that has cognate-score data; reflects the live threshold too.
    updateCognateSensitivityVisibility();

    // Update account tab with current user
    const userBadge = currentUser ? (currentUser.isGuest ? 'GUEST' : currentUser.initials) : 'GUEST';
    document.getElementById('accountUserBadge').textContent = userBadge;
    const vocabularyImportButton = document.getElementById('openVocabularyImportBtn');
    if (vocabularyImportButton) {
        vocabularyImportButton.hidden = !(currentUser && !currentUser.isGuest);
    }
    const isJstAccount = Boolean(currentUser && currentUser.initials === 'JST');
    const appDataTabBtn = document.getElementById('appDataTabBtn');
    if (appDataTabBtn) appDataTabBtn.hidden = !isJstAccount;

    // Show/hide clear level estimate row
    const estimate = levelEstimates[selectedLanguage] || 0;
    const clearRow = document.getElementById('clearLevelEstimateRow');
    if (currentUser && !currentUser.isGuest && estimate > 0) {
        document.getElementById('levelEstimateDisplay').textContent = `~${estimate} words`;
        clearRow.style.display = 'flex';
    } else {
        clearRow.style.display = 'none';
    }

    // Switch to the requested settings surface. App data is a developer audit
    // and must never be exposed outside the JST account.
    const settingsModal = document.getElementById('settingsModal');
    const tabContentIds = {
        account: 'accountTabContent',
        study: 'studyTabContent',
        offline: 'offlineTabContent',
        appData: 'appDataTabContent'
    };
    const requestedTab = tabContentIds[tabName] && (tabName !== 'appData' || isJstAccount)
        ? tabName
        : 'account';
    const showOnlyStudy = singleTab && requestedTab === 'study';
    settingsModal.classList.toggle('settings-single-tab', showOnlyStudy);
    const singleTabTitle = document.getElementById('settingsSingleTabTitle');
    if (singleTabTitle) singleTabTitle.hidden = !showOnlyStudy;
    settingsModal.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
    settingsModal.querySelector(`.settings-tab[data-tab="${requestedTab}"]`)?.classList.add('active');
    settingsModal.querySelectorAll('.settings-tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(tabContentIds[requestedTab]).classList.add('active');

    // Data-freshness footer: newest Last-Modified across the vocab files
    // (set in vocab.js trackDataFreshness). An old date = the service
    // worker served cached data; "not loaded yet" = no deck fetched.
    // This entire audit surface is JST-only: newest data freshness, per-file
    // dates, app version, and recent development changelog entries.
    const freshnessEl = document.getElementById('dataFreshnessFooter');
    if (freshnessEl && isJstAccount) {
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
        renderDevFooter(freshnessEl);   // async, appends below basic line
    }

    settingsModal.classList.remove('hidden');
}

// Verbose data-provenance block for the JST (dev) account only: per-file
// Last-Modified dates, the running asset version, and the latest entries
// from config/dev_changelog.json (which Claude appends to when deck data
// changes). The containing App data tab is hidden from every other account.
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
            lines.push('<div class="dev-footer-label">Recent app/data changes</div>');
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
            if (r.ok) {
                const examples = await r.json();
                window.setActiveExamplesData?.(examples) || (window._cachedExamplesData = examples);
            }
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
    const vocab = cachedVocabularyData
        ? buildFilteredVocab(cachedVocabularyData).vocab
        : null;
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
        const coverageType = activeArtist
            ? (artistVocabularyScope === 'extra' ? `${activeArtist.name || 'Artist'} Extra` : 'lyrics')
            : 'speech';
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
    const activeScopeIds = activeArtist && vocab
        ? new Set(vocab.map(item => getWordId(item)))
        : null;
    if (progressData) {
        const counted = new Set();
        for (const [id, data] of Object.entries(progressData)) {
            if (data.language !== selectedLanguage) continue;
            if (activeScopeIds) {
                const crossId = getCrossModeId(id);
                if (!activeScopeIds.has(id) && !(crossId && activeScopeIds.has(crossId))) continue;
            }
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
        coverageLabelEl.textContent = activeArtist
            ? (artistVocabularyScope === 'extra' ? `${activeArtist.name || 'Artist'} Extra explored` : 'Lyrics comprehension')
            : 'Speech comprehension';
    }
    if (linesLabelEl) {
        linesLabelEl.textContent = activeArtist ? 'Complete lyric lines' : 'Complete sentences';
    }

    // Both modes share the same computation: walk every example sentence in
    // _cachedExamplesData and count the lines where every in-vocab token is
    // either in the user's known set or below their level estimate.
    // computeLinesUnderstood() handles the iteration; we lazy-loaded the
    // examples corpus and rank data above so it has what it needs.
    const activeExampleIds = activeArtist && vocab
        ? new Set(vocab.map(item => String(item.id || '')))
        : null;
    let linesResult = computeLinesUnderstood(activeExampleIds);
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
    const labelEl = document.getElementById('statsSetLabel');
    if (labelEl) labelEl.textContent = stats.setLabel ? `· ${stats.setLabel}` : '';
    renderActiveSetProgress();
}

function formatStudyProgressTimestamp(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '—';
    return new Intl.DateTimeFormat('en-GB', {
        day: '2-digit', month: '2-digit', year: '2-digit',
        hour: '2-digit', minute: '2-digit', hour12: false
    }).format(date).replace(',', '');
}

function getActiveSetCardResult(inDeckIdx, session) {
    const correct = Number(session?.correct || 0);
    const incorrect = Number(session?.incorrect || 0);
    const attempts = Array.isArray(session?.attempts) ? session.attempts : [];
    if (correct > 0 && incorrect > 0) {
        const latest = attempts.at(-1)?.result;
        return { key: 'mixed', label: latest === 'incorrect' ? 'Mixed · latest incorrect' : 'Mixed · latest correct' };
    }
    if (correct > 0) return { key: 'correct', label: 'Correct' };
    if (incorrect > 0) return { key: 'incorrect', label: 'Incorrect' };
    if (inDeckIdx === -1) return { key: 'known', label: 'Already seen' };
    if (inDeckIdx === currentIndex) return { key: 'current', label: 'Current' };
    if (stats.studied?.has?.(inDeckIdx)) return { key: 'skipped', label: 'Skipped' };
    return { key: 'unanswered', label: 'Not answered' };
}

function _studyProgressEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
}

function _appendStudyProgressDatum(host, label, value, valueClass = '') {
    const row = _studyProgressEl('div', 'active-set-history-row');
    row.append(
        _studyProgressEl('span', 'active-set-history-label', label),
        _studyProgressEl('span', `active-set-history-value ${valueClass}`.trim(), value)
    );
    host.appendChild(row);
}

function _appendSavedProgressRecord(host, label, record) {
    const card = _studyProgressEl('div', 'active-set-saved-record');
    card.appendChild(_studyProgressEl('strong', 'active-set-saved-record-title', label));
    _appendStudyProgressDatum(card, 'Answers', `${Number(record.correct || 0)} correct · ${Number(record.wrong || 0)} wrong`);
    _appendStudyProgressDatum(card, 'Latest correct', formatStudyProgressTimestamp(record.lastCorrect), 'active-set-history-time');
    _appendStudyProgressDatum(card, 'Latest incorrect', formatStudyProgressTimestamp(record.lastWrong), 'active-set-history-time');
    _appendStudyProgressDatum(card, 'Latest seen', formatStudyProgressTimestamp(record.lastSeen), 'active-set-history-time');
    _appendStudyProgressDatum(card, 'SRS stage', String(Number(record.srsStage || 0)));
    host.appendChild(card);
}

function renderActiveSetProgress() {
    const host = document.getElementById('activeSetProgressList');
    if (!host) return;
    host.innerHTML = '';

    const words = stats.allWords || [];
    if (words.length === 0) {
        host.appendChild(_studyProgressEl('p', 'active-set-progress-empty', 'No cards are loaded in this set.'));
        return;
    }

    // A picked Learn New set includes both its active cards and cards removed
    // because they are already complete. Keep both visible here so this panel
    // can answer “have I done this card before?” without hiding the evidence.
    const activeIdToIndex = new Map();
    flashcards.forEach((c, i) => {
        if (c && c.id) activeIdToIndex.set(c.id, i);
        if (c && c.fullId) activeIdToIndex.set(c.fullId, i);
    });

    words.forEach((w, position) => {
        const fullId = getWordId(w);
        const inDeckIdx = activeIdToIndex.has(w.id) ? activeIdToIndex.get(w.id) : -1;
        const session = inDeckIdx >= 0 ? (stats.cardStats || {})[inDeckIdx] : null;
        const result = getActiveSetCardResult(inDeckIdx, session);
        const details = _studyProgressEl('details', `active-set-card-progress is-${result.key}`);
        details.dataset.cardId = fullId;
        if (inDeckIdx === currentIndex) details.open = true;

        const summary = _studyProgressEl('summary', 'active-set-card-summary');
        summary.appendChild(_studyProgressEl('span', 'active-set-card-number', String(position + 1)));
        const identity = _studyProgressEl('span', 'active-set-card-identity');
        identity.appendChild(_studyProgressEl('strong', 'active-set-card-word', w.word || '(untitled card)'));
        if (w.translation) identity.appendChild(_studyProgressEl('small', 'active-set-card-translation', w.translation));
        summary.append(identity, _studyProgressEl('span', `active-set-card-result is-${result.key}`, result.label));
        details.appendChild(summary);

        const body = _studyProgressEl('div', 'active-set-card-history');
        const sessionSection = _studyProgressEl('section', 'active-set-history-section');
        sessionSection.appendChild(_studyProgressEl('h4', '', 'This open set'));
        const attempts = Array.isArray(session?.attempts) ? session.attempts : [];
        if (attempts.length) {
            attempts.forEach((attempt, index) => {
                const label = attempt.result === 'correct' ? 'Correct' : 'Incorrect';
                _appendStudyProgressDatum(sessionSection, `Attempt ${index + 1} · ${label}`, formatStudyProgressTimestamp(attempt.at), 'active-set-history-time');
            });
        } else {
            sessionSection.appendChild(_studyProgressEl('p', 'active-set-history-empty', 'No answer recorded in this open set.'));
        }
        body.appendChild(sessionSection);

        const modeIds = [{ id: fullId, label: activeArtist ? 'Lyrics card' : 'Speech card' }];
        const crossModeId = getCrossModeId(fullId);
        if (crossModeId) modeIds.push({ id: crossModeId, label: activeArtist ? 'Speech card' : 'Lyrics card' });
        const savedRecords = modeIds.filter(({ id }) => progressData?.[id]);
        const savedSection = _studyProgressEl('section', 'active-set-history-section');
        savedSection.appendChild(_studyProgressEl('h4', '', 'Saved card progress'));
        if (savedRecords.length) {
            savedRecords.forEach(({ id, label }) => _appendSavedProgressRecord(savedSection, label, progressData[id]));
        } else {
            savedSection.appendChild(_studyProgressEl('p', 'active-set-history-empty', 'No saved card history yet.'));
        }
        body.appendChild(savedSection);

        const parentIds = new Set(modeIds.map(({ id }) => id));
        const savedItems = Object.values(itemProgressData || {})
            .filter(item => parentIds.has(item?.parentWordId))
            .sort((a, b) => String(a.label || '').localeCompare(String(b.label || '')));
        if (savedItems.length) {
            const itemSection = _studyProgressEl('section', 'active-set-history-section');
            itemSection.appendChild(_studyProgressEl('h4', '', 'Saved sense and expression progress'));
            savedItems.forEach(item => {
                const type = item.itemType === 'mwe' || item.itemType === 'expression' ? 'Expression' : 'Sense';
                _appendSavedProgressRecord(itemSection, `${type} · ${item.label || 'Unnamed'}`, item);
            });
            body.appendChild(itemSection);
        }

        body.appendChild(_studyProgressEl(
            'p',
            'active-set-history-retention',
            'Progress keeps cumulative totals and the latest correct, incorrect, and seen times—not a timestamp for every older answer.'
        ));
        details.appendChild(body);
        host.appendChild(details);
    });
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
window.refreshSetupAfterProgress = async function() {
    if (_setupLevelSelectionWasManual) return renderRangeSelector();
    return renderLevelSelector(selectedLanguage, { preferActionable: true });
};
window.setupCognateToggle = setupCognateToggle;
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
        <p><strong>Lyrics</strong> teaches you Spanish vocabulary from ${name}'s lyrics, starting with the most frequent words.</p>
        <p><strong>Why frequency order?</strong></p>
        <p>Language follows a power law: a small number of words make up the vast majority of speech. By learning the most frequent words first, you understand more lyrics faster.</p>
        <p><strong>How are percentages calculated?</strong></p>
        <p>The coverage percentage tells you what fraction of all words in the lyrics you'd recognize. ${get70pctWordCount()} The remaining 30% are rarer words that appear less often.</p>
        <p><strong>How does it work?</strong></p>
        <p>Choose a numbered level and the app selects its first small set containing unseen cards. Incorrect and partly learned cards collect in a separate review for that level. When Spaced repetition is enabled in Study settings, due cards join that review and correct recalls graduate through 1, 3, 7, 14, 30, 60, and 120-day intervals; mistakes reset the schedule. Merge Lemmas and Cognate exclusions can shorten sets without moving cards between them. Each card shows real lyric examples from the songs where the word appears. If you leave an unfinished set, a Welcome back prompt offers to restore the exact card and settings next time you enter; finishing the set clears it.</p>
        <p>The progress bar tracks your coverage based on the frequency of words you've learned — learning a common word contributes more to your coverage than a rare one.</p>
    `;
}

function getNormalHelpContent() {
    return `
        <p><strong>What is this?</strong></p>
        <p><strong>Speech</strong> teaches vocabulary from subtitle dialogue, ordered by how frequently each word occurs.</p>
        <p><strong>Why frequency order?</strong></p>
        <p>Language follows a power law: a small number of words make up the vast majority of everyday speech. In Spanish, the top 1,000 words cover roughly 81% of spoken language, and the top 3,000 cover around 91%. By learning frequent words first, you build practical comprehension faster.</p>
        <p><strong>How does it work?</strong></p>
        <p>Choose a language, then Speech or Lyrics. Speech continues to numbered levels; Lyrics opens the artist clock. The app selects a level's first small set containing unseen cards, while incorrect and partly learned cards collect in that level's separate review. When Spaced repetition is enabled in Study settings, due cards join that review and correct recalls graduate through 1, 3, 7, 14, 30, 60, and 120-day intervals; mistakes reset the schedule. Merge Lemmas and Cognate exclusions can shorten sets without moving cards between them. Subtitle examples favour nearby-frequency vocabulary. If you leave an unfinished set, a Welcome back prompt offers to restore the exact card and settings next time you enter; finishing the set clears it.</p>
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
window.setupGlobalStudyDefaults = setupGlobalStudyDefaults;
window.setupPercentModeButton = setupPercentModeButton;
window.setupEstimationModal = setupEstimationModal;
window.updateLemmaToggleVisibility = updateLemmaToggleVisibility;
window.updateCognateToggleVisibility = updateCognateToggleVisibility;
window.applyLanguageColorTheme = applyLanguageColorTheme;
window.renderRangeSelector = renderRangeSelector;
window.getNextStudySetMeta = getNextStudySetMeta;
window.getNextStudyLevelMeta = getNextStudyLevelMeta;
window.startNextStudyLevelFirstSet = startNextStudyLevelFirstSet;
window.showStatsModal = showStatsModal;
window.hideStatsModal = hideStatsModal;
window.showSettingsModal = showSettingsModal;
window.showSettingsModalWithTab = showSettingsModalWithTab;
window.applyGlobalStudyDefaults = applyGlobalStudyDefaults;
window.saveGlobalStudyPreference = saveGlobalStudyPreference;
window.hideSettingsModal = hideSettingsModal;
window.showTotalStatsModal = showTotalStatsModal;
window.hideTotalStatsModal = hideTotalStatsModal;
window.updateTotalStatsButtonVisibility = updateTotalStatsButtonVisibility;
window.updateStatsModal = updateStatsModal;
