// Vocabulary loading, filtering, and ID generation.
// Key functions: buildFilteredVocab() (central filter), loadVocabularyData(), getWordId(),
// mergeArtistVocabularies() (multi-artist merge by hex ID).
import './state.js';

// ISO 639-1 codes for each language key used in config.json
const LANG_CODES = {
    spanish: 'es', swedish: 'sv', italian: 'it',
    dutch: 'nl', polish: 'pl', french: 'fr', russian: 'ru'
};

/**
 * Compute a stable composite word ID: {2-char lang}{0=normal|1=lyrics}{hex}.
 * Hex is 6 chars for artist mode (master vocab), 4 chars for normal mode.
 * Examples: "es00001" (Spanish normal rank 1), "es1a1b2c3" (artist hex a1b2c3).
 * Always contains letters → Google Sheets never auto-converts to a number.
 */
function getWordId(item) {
    const lang = LANG_CODES[selectedLanguage] || selectedLanguage.slice(0, 2);
    const mode = activeArtist ? '1' : '0';
    const hex = item.id || Number(item.rank).toString(16).padStart(4, '0');
    return `${lang}${mode}${hex}`;
}

/**
 * Flip the mode bit in a fullId: es0... ↔ es1...
 * Returns null if the ID is too short or has no mode bit.
 */
function getCrossModeId(fullId) {
    if (!fullId || fullId.length < 4) return null;
    const modeChar = fullId[2];
    if (modeChar === '0') return fullId.slice(0, 2) + '1' + fullId.slice(3);
    if (modeChar === '1') return fullId.slice(0, 2) + '0' + fullId.slice(3);
    return null;
}

/**
 * Check if a word is known in either mode (correct > 0, matching language).
 */
function isWordKnown(fullId) {
    const check = (id) => {
        const p = progressData?.[id];
        return p && Number(p.correct) > 0 && p.language === selectedLanguage;
    };
    if (check(fullId)) return true;
    const crossId = getCrossModeId(fullId);
    return crossId ? check(crossId) : false;
}

/**
 * Build a Set of hex IDs for words covered by the level estimate.
 * Uses the normal-mode vocabulary index (general frequency ordering).
 * Cached per language + estimate so it's only computed once per session.
 */
async function buildEstimatedKnownIds(estimate) {
    if (!estimate || estimate <= 0) return new Set();

    const cacheKey = `${selectedLanguage}_${estimate}`;
    if (window._estimatedKnownIdsCache?.key === cacheKey) {
        return window._estimatedKnownIdsCache.ids;
    }

    const normalConfig = window._normalModeLangConfigs?.[selectedLanguage];
    if (!normalConfig) return new Set();

    const normalVocab = await fetchAndJoinIndex(normalConfig);
    const ids = new Set();
    for (let i = 0; i < Math.min(estimate, normalVocab.length); i++) {
        if (normalVocab[i].id) ids.add(normalVocab[i].id);
    }

    window._estimatedKnownIdsCache = { key: cacheKey, ids };
    return ids;
}

/**
 * Join per-artist index entries with the shared master vocabulary.
 * Reconstructs the full entry shape (word, lemma, meanings, flags, mwe_memberships)
 * expected by buildFilteredVocab() and the flashcard builder.
 *
 * @param {Array} indexData - Artist index entries [{id, corpus_count, most_frequent_lemma_instance, sense_frequencies}]
 * @param {Object} master - Master vocabulary {id: {word, lemma, senses, flags, mwe_memberships}}
 * @returns {Array} Denormalized entries matching the old monolith format
 */
function joinWithMaster(indexData, master) {
    const result = [];
    for (const idx of indexData) {
        const m = master[idx.id];
        if (!m) continue;

        // Build meanings array from master senses + artist sense_frequencies
        const meanings = (m.senses || []).map((sense, i) => ({
            pos: sense.pos,
            translation: sense.translation,
            frequency: String(idx.sense_frequencies?.[i] ?? 0),
            examples: []  // Attached later from examples file
        }));

        // Build mwe_memberships from index entry (per-artist, not master)
        const mwe_memberships = (idx.mwe_memberships || []).map(mwe => ({
            expression: mwe.expression,
            translation: mwe.translation || '',
            examples: []
        }));

        // Build clitic_memberships from index entry
        const clitic_memberships = (idx.clitic_memberships || []).map(cl => ({
            form: cl.form,
            translation: cl.translation || '',
            corpus_count: cl.corpus_count || 0,
            examples: []
        }));

        result.push({
            id: idx.id,
            word: m.word,
            lemma: m.lemma,
            meanings,
            most_frequent_lemma_instance: idx.most_frequent_lemma_instance,
            is_english: m.is_english || false,
            is_interjection: m.is_interjection || false,
            is_propernoun: m.is_propernoun || false,
            cognate_score: idx.cognate_score ?? m.cognate_score ?? (m.is_transparent_cognate ? 1 : 0),
            cognet_cognate: idx.cognet_cognate || m.cognet_cognate || false,
            corpus_count: idx.corpus_count || 0,
            display_form: m.display_form || null,
            variants: idx.variants || null,
            mwe_memberships: mwe_memberships.length > 0 ? mwe_memberships : undefined,
            clitic_memberships: clitic_memberships.length > 0 ? clitic_memberships : undefined,
            morphology: idx.morphology || null,
        });
    }
    return result;
}

/**
 * Fetch the artist/language index and join with master vocabulary if needed.
 * Caches the master and the joined result. Returns denormalized entries with all fields
 * (word, lemma, meanings, flags) that buildFilteredVocab() and other consumers expect.
 */
async function fetchAndJoinIndex(langConfig) {
    const indexPath = langConfig.indexPath || langConfig.dataPath;

    // Return cached result if available (cleared when language/artist changes)
    if (window._cachedJoinedIndex && window._cachedJoinedIndexPath === indexPath) {
        return window._cachedJoinedIndex;
    }

    const response = await fetch(indexPath);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    let data = await response.json();

    // Detect new master-based format and join if needed
    if (activeArtist && langConfig.masterPath && data.length > 0 && data[0].sense_frequencies) {
        if (!window._cachedMasterVocab) {
            try {
                const masterResp = await fetch(langConfig.masterPath);
                if (masterResp.ok) {
                    window._cachedMasterVocab = await masterResp.json();
                }
            } catch (e) {
                console.warn('Failed to load master vocabulary:', e);
            }
        }
        if (window._cachedMasterVocab) {
            data = joinWithMaster(data, window._cachedMasterVocab);
        }
    }

    window._cachedJoinedIndex = data;
    window._cachedJoinedIndexPath = indexPath;
    return data;
}

function buildFilteredVocab(vocabData) {
    // Assign stable rank from array position (pipeline sort order)
    vocabData.forEach((item, index) => {
        item.rank = index + 1;
        // Backward compat: old boolean cognate flag → score
        if (item.cognate_score === undefined && item.is_transparent_cognate) {
            item.cognate_score = 1;
        }
    });

    // Basic: non-blank, no duplicates, has meanings
    let result = vocabData.filter(item =>
        item.word && item.word.trim() !== '' && !item.duplicate && item.meanings && item.meanings.length > 0
    );

    // Strip placeholder meanings (POS=X with no translation) from --no-gemini runs
    for (const item of result) {
        item.meanings = item.meanings.filter(m => !(m.pos === 'X' && !m.translation));
    }
    result = result.filter(item => item.meanings.length > 0);


    const counts = { english: 0, cognates: 0, singleOcc: 0, lemma: 0 };

    // Artist/lyrics mode: skip English loanwords, interjections, proper nouns
    if (activeArtist) {
        const before = result.length;
        result = result.filter(item => !item.is_english && !item.is_interjection && !item.is_propernoun);
        counts.english = before - result.length;
    }

    // Cognate exclusion (score-based threshold)
    if (excludeCognates && cognateFieldAvailable) {
        const before = result.length;
        result = result.filter(item => item.cognate_score < cognateThreshold);
        counts.cognates = before - result.length;
    }

    // Single-occurrence word hiding
    if (hideSingleOccurrence && result.length > 0 && result[0].hasOwnProperty('corpus_count')) {
        const before = result.length;
        result = result.filter(item => item.corpus_count > 1);
        counts.singleOcc = before - result.length;
    }

    // Lemma mode: one card per lemma group
    if (useLemmaMode && lemmaFieldAvailable) {
        const before = result.length;
        result = result.filter(item => item.most_frequent_lemma_instance === true);
        counts.lemma = before - result.length;
    }

    // Assign corpus-wide display ranks so set numbering is continuous across levels
    result.forEach((item, idx) => { item.displayRank = idx + 1; });

    return { vocab: result, counts };
}

async function loadVocabularyData(rangeString) {
    // Completely clear all previous data and state
    flashcards = [];
    currentIndex = 0;
    currentSentenceIndex = 0;
    currentMeaningIndex = 0;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    isFlipped = false;
    cardNavStack = [];

    // Reset card flip state
    const flashcardEl = document.getElementById('flashcard');
    if (flashcardEl) {
        flashcardEl.classList.remove('flipped');
    }

    const langConfig = config.languages[selectedLanguage];
    const [rangeStart, rangeEnd] = rangeString.split('-').map(Number);

    // Use lightweight index for filtering when available
    const indexPath = langConfig.indexPath || langConfig.dataPath;

    try {
        // Multi-artist mode: merge vocabularies from all selected artists
        let vocabularyData;
        const selectedSlugs = window._selectedArtistSlugs || [];
        const allConfigs = window._allArtistsConfig;
        if (activeArtist && selectedSlugs.length > 1 && allConfigs) {
            const artistConfigs = selectedSlugs
                .map(slug => allConfigs[slug])
                .filter(Boolean);
            if (!window._cachedMergedIndex) {
                const { mergedIndex, mergedExamples } = await mergeArtistVocabularies(artistConfigs, window._cachedMasterVocab);
                window._cachedMergedIndex = mergedIndex;
                window._cachedMergedExamples = mergedExamples;
            }
            vocabularyData = window._cachedMergedIndex;
            // Point examples cache to merged examples
            window._cachedExamplesData = window._cachedMergedExamples;
        } else {
            // Single artist or normal mode: fetch and join with master if needed
            vocabularyData = await fetchAndJoinIndex(langConfig);
        }
        cachedVocabularyData = vocabularyData;

        // Store original index/rank from vocabulary file - this is the unique identifier
        vocabularyData.forEach((item, index) => {
            item.rank = index + 1; // Use original position as the rank (unique identifier)
        });

        const { vocab: _baseVocab, counts: exCounts } = buildFilteredVocab(vocabularyData);
        let filteredData = _baseVocab;
        const excludedEnglish = exCounts.english;
        const excludedCognates = exCounts.cognates;
        const excludedSingleOcc = exCounts.singleOcc;
        const excludedLemma = exCounts.lemma;
        let excludedMastered = 0;

        // Filter by the requested range using corpus-wide display ranks
        filteredData = filteredData.filter(item =>
            item.displayRank >= rangeStart && item.displayRank < rangeEnd
        );

        // Count total in range before mastered filtering
        const totalInRange = filteredData.length;
        const allInRange = filteredData.slice(); // preserve for "study anyway"

        // Filter out words the user has already got correct (for logged-in users),
        // including words covered by the level estimate high-water mark.
        // In artist mode, estimate maps to an ID set from normal-mode vocab (general frequency).
        if (currentUser && !currentUser.isGuest && progressData) {
            const beforeMastered = filteredData.length;
            const estimate = levelEstimates[selectedLanguage] || 0;

            // In artist mode, use ID set from normal-mode vocab for level estimate filtering
            const estimatedIds = activeArtist ? await buildEstimatedKnownIds(estimate) : null;

            filteredData = filteredData.filter(item => {
                // Level estimate filter: rank-based for normal mode, ID-based for artist mode
                if (activeArtist) {
                    if (item.id && estimatedIds.has(item.id)) return false;
                } else {
                    if (item.rank <= estimate) return false;
                }
                // Cross-mode progress check: known in either mode → skip
                return !isWordKnown(getWordId(item));
            });
            excludedMastered = beforeMastered - filteredData.length;
            if (excludedMastered > 0) {
                console.log(`Filtered out ${excludedMastered} previously mastered words`);
            }
        }

        // Convert to flashcards format
        const exampleTargetField = langConfig.exampleTargetField || 'example_spanish';
        const exampleEnglishField = langConfig.exampleEnglishField || 'example_english';

        // Load Spotify track mapping (fire-and-forget, non-blocking)
        if (!window._spotifyTracks) {
            fetch('Artists/spotify_tracks.json').then(r => r.ok ? r.json() : {}).then(d => {
                window._spotifyTracks = d;
            }).catch(() => { window._spotifyTracks = {}; });
        }

        // Lazy-load examples: fetch only when user commits to a set
        let allCorpusExamples = [];
        if (langConfig.examplesPath) {
            if (!window._cachedExamplesData) {
                const exResponse = await fetch(langConfig.examplesPath);
                if (exResponse.ok) {
                    window._cachedExamplesData = await exResponse.json();
                }
            }
            const examplesData = window._cachedExamplesData;
            if (examplesData) {
                // Merge examples back into filtered entries
                for (const item of filteredData) {
                    const ex = examplesData[item.id];
                    if (ex && ex.m) {
                        item.meanings.forEach((m, i) => {
                            m.examples = ex.m[i] || [];
                        });
                    }
                    if (ex && ex.w && item.mwe_memberships) {
                        item.mwe_memberships.forEach((mwe, i) => {
                            mwe.examples = ex.w[i] || [];
                        });
                    }
                }
                // MWE examples are pre-computed by the pipeline and stored in the "w"
                // field of the examples file. No need to build a corpus pool here.
            }
        } else {
            // Fallback: monolith path — examples are inline in vocabularyData
        }

        // Artist mode: filter sense pills for cleaner display.
        // Must happen AFTER examples are attached (above) so positional indices are correct,
        // but BEFORE card building (below) so cards only show relevant senses.
        if (activeArtist) {
            const MIN_SENSE_FREQ = 0.05;
            const MAX_SENSES = 6;
            for (const item of filteredData) {
                // Drop zero-frequency senses (unused by this artist/merge)
                item.meanings = item.meanings.filter(m => parseFloat(m.frequency) > 0);
                // Drop senses below minimum threshold
                item.meanings = item.meanings.filter(m => parseFloat(m.frequency) >= MIN_SENSE_FREQ);
                // Hard cap: keep top N by frequency
                if (item.meanings.length > MAX_SENSES) {
                    item.meanings.sort((a, b) => parseFloat(b.frequency) - parseFloat(a.frequency));
                    item.meanings = item.meanings.slice(0, MAX_SENSES);
                }
            }
            filteredData = filteredData.filter(item => item.meanings.length > 0);
        }

        for (const item of filteredData) {
            const meanings = item.meanings.map(m => {
                const { targetSentence, englishSentence, allExamples } = getExampleFromMeaning(m, exampleTargetField, exampleEnglishField);
                return {
                    pos: m.pos,
                    meaning: m.translation,
                    percentage: parseFloat(m.frequency),
                    targetSentence,
                    englishSentence,
                    allExamples
                };
            });

            // Normalize percentages if they're missing or sum to 0
            const totalPercentage = meanings.reduce((sum, m) => sum + (m.percentage || 0), 0);
            if (totalPercentage === 0 || isNaN(totalPercentage)) {
                // Default to equal distribution
                const equalPercentage = 1.0 / meanings.length;
                meanings.forEach(m => {
                    m.percentage = equalPercentage;
                });
            } else if (totalPercentage !== 1.0) {
                // Normalize to sum to 1.0
                meanings.forEach(m => {
                    m.percentage = (m.percentage || 0) / totalPercentage;
                });
            }

            // Synthesize a single MWE meaning that cycles through all expressions
            if (item.mwe_memberships && item.mwe_memberships.length > 0) {
                const allMWEs = [];
                // Sort artist-specific MWEs first, then wiktionary
                const sortedMWEs = [...item.mwe_memberships].sort((a, b) => {
                    const aArtist = (a.source || 'artist') === 'artist' ? 0 : 1;
                    const bArtist = (b.source || 'artist') === 'artist' ? 0 : 1;
                    return aArtist - bArtist;
                });
                // Strip elision markers for fuzzy MWE matching
                const stripElisions = (s) => s.replace(/['\u2019]/g, '').replace(/\s+/g, ' ');
                for (const mwe of sortedMWEs) {
                    // Use pre-attached examples if available (from examples.json "w" field),
                    // only fall back to corpus scan when needed (artist mode)
                    let matched = mwe.examples || [];
                    if (matched.length === 0 && allCorpusExamples.length > 0) {
                        const exprLower = mwe.expression.toLowerCase();
                        const exprNorm = stripElisions(exprLower);
                        // Word-boundary regex to avoid substring false positives
                        // (e.g. "solo que" matching "solo quedan")
                        const SP = 'a-zA-Z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00fc\u00c1\u00c9\u00cd\u00d3\u00da\u00d1\u00dc';
                        const escExpr = exprLower.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                        const escNorm = exprNorm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                        const exprRe = new RegExp('(?<![' + SP + '])' + escExpr + '(?![' + SP + '])', 'i');
                        const normRe = new RegExp('(?<![' + SP + '])' + escNorm + '(?![' + SP + '])', 'i');
                        matched = allCorpusExamples.filter(ex => {
                            const text = (ex.spanish || ex.target || '').toLowerCase();
                            return exprRe.test(text);
                        });
                        if (matched.length === 0) {
                            matched = allCorpusExamples.filter(ex => {
                                const text = stripElisions((ex.spanish || ex.target || '').toLowerCase());
                                return normRe.test(text);
                            });
                        }
                    }
                    allMWEs.push({
                        expression: mwe.expression,
                        translation: mwe.translation || '',
                        examples: matched.length > 0 ? matched : [{ spanish: '', english: '' }]
                    });
                }
                const firstEx = allMWEs[0].examples[0];
                meanings.push({
                    pos: 'MWE',
                    meaning: allMWEs[0].translation,
                    expression: allMWEs[0].expression,
                    allMWEs: allMWEs,
                    percentage: 0,
                    targetSentence: firstEx.spanish || firstEx.target || '',
                    englishSentence: firstEx.english || '',
                    allExamples: allMWEs[0].examples
                });
            }

            // Synthesize clitic meaning (parallel to MWE, cycles through forms)
            if (item.clitic_memberships && item.clitic_memberships.length > 0) {
                const allClitics = [];
                for (const cl of item.clitic_memberships) {
                    const matched = cl.examples || [];
                    allClitics.push({
                        form: cl.form,
                        translation: cl.translation || '',
                        corpus_count: cl.corpus_count || 0,
                        examples: matched.length > 0 ? matched : [{ spanish: '', english: '' }]
                    });
                }
                allClitics.sort((a, b) => b.corpus_count - a.corpus_count);
                const firstEx = allClitics[0].examples[0];
                meanings.push({
                    pos: 'CLITIC',
                    meaning: allClitics[0].form,
                    allClitics: allClitics,
                    percentage: 0,
                    targetSentence: firstEx.spanish || firstEx.target || '',
                    englishSentence: firstEx.english || '',
                    allExamples: allClitics[0].examples
                });
            }

            const firstExample = getExampleFromMeaning(item.meanings[0], exampleTargetField, exampleEnglishField);
            const card = {
                targetWord: item.word,
                lemma: item.lemma || '',
                id: item.id,
                fullId: getWordId(item),
                rank: item.rank,
                corpusCount: item.corpus_count || null,
                meanings: meanings,
                translation: item.meanings[0].translation,
                targetSentence: firstExample.targetSentence,
                englishSentence: firstExample.englishSentence,
                links: generateLinks(item.word, item.lemma || item.word, langConfig.referenceLinks),
                isMultiMeaning: true,
                variants: item.variants || null,
                homographIds: item.homograph_ids || null,
                morphology: item.morphology || null
            };
            flashcards.push(card);
        }

        if (filteredData.length === 0) {
            // Check if this is because all words are mastered
            if (currentUser && !currentUser.isGuest && progressData && allInRange.length > 0) {
                const studyAnyway = confirm('You\'ve already mastered all words in this set! Press OK to study them again, or Cancel to choose another set.');
                if (studyAnyway) {
                    filteredData = allInRange;
                    excludedMastered = 0;
                } else {
                    document.getElementById('loadingMessage').style.display = 'none';
                    return;
                }
            } else {
                alert('No flashcards found in this range. Please try another set.');
                document.getElementById('loadingMessage').style.display = 'none';
                return;
            }
        }

        // Build exclusion summary message (only report in-range exclusions)
        const totalExcluded = excludedLemma + excludedMastered;
        const loadingMsg = document.getElementById('loadingMessage');
        if (totalExcluded > 0) {
            const parts = [];
            if (excludedLemma > 0) parts.push(`${excludedLemma} lemma dup${excludedLemma > 1 ? 's' : ''}`);
            if (excludedMastered > 0) parts.push(`${excludedMastered} mastered`);
            loadingMsg.textContent = `✓ ${flashcards.length} cards from ${totalInRange} (${parts.join(', ')} excluded)`;
        } else {
            loadingMsg.textContent = `✓ ${flashcards.length} cards`;
        }
        loadingMsg.style.display = 'block';

        // Successfully loaded data - show message briefly, then transition to cards
        setTimeout(() => {
            document.getElementById('setupPanel').classList.add('hidden');
            document.getElementById('appContent').classList.remove('hidden');
            loadingMsg.style.display = 'none';

            // Show mobile floating buttons
            showFloatingBtns(true);

            // Initialize card display
            initializeApp();
            buildWordLookupMap();
        }, 800);
    } catch (error) {
        console.error(`Failed to load vocabulary data:`, error);
        document.getElementById('loadingMessage').style.display = 'none';
        alert(`Error loading ${rangeString}. Please try another set.`);
    }
}

// Build a lookup map from word/lemma → flashcard index for lyric breakdown
function buildWordLookupMap() {
    const map = new Map();
    for (let i = 0; i < flashcards.length; i++) {
        const card = flashcards[i];
        const word = card.targetWord.toLowerCase().trim();
        if (!map.has(word)) map.set(word, i);
        if (card.lemma) {
            const lemma = card.lemma.toLowerCase().trim();
            if (!map.has(lemma)) map.set(lemma, i);
        }
    }
    window._wordLookupMap = map;
}


// Load study set of all-time incorrect words for the selected language
async function loadIncorrectWordsSet() {
    if (!currentUser || currentUser.isGuest) {
        alert('Please log in to access your incorrect words history.');
        return;
    }

    // Get incorrect words for the currently selected language
    const incorrectWords = Object.entries(progressData)
        .filter(([wordId, data]) =>
            data.wrong > 0 &&
            data.language === selectedLanguage
        )
        .map(([wordId, data]) => ({
            wordId,
            ...data
        }))
        // Sort by least recently correct (null lastCorrect = never correct, comes first)
        // Then by least recently wrong as secondary sort
        .sort((a, b) => {
            // Never correct comes first
            if (!a.lastCorrect && b.lastCorrect) return -1;
            if (a.lastCorrect && !b.lastCorrect) return 1;
            if (!a.lastCorrect && !b.lastCorrect) {
                // Both never correct - sort by oldest wrong first
                const aWrong = a.lastWrong ? new Date(a.lastWrong).getTime() : 0;
                const bWrong = b.lastWrong ? new Date(b.lastWrong).getTime() : 0;
                return aWrong - bWrong;
            }
            // Both have been correct - sort by oldest correct first
            return new Date(a.lastCorrect).getTime() - new Date(b.lastCorrect).getTime();
        });

    if (incorrectWords.length === 0) {
        alert(`No incorrect words found for ${selectedLanguage}. Start practicing to build your incorrect words list!`);
        return;
    }

    document.getElementById('loadingMessage').style.display = 'block';
    document.getElementById('loadingMessage').textContent = `Loading ${incorrectWords.length} incorrect words...`;

    // Clear previous state
    flashcards = [];
    currentIndex = 0;
    currentSentenceIndex = 0;
    currentMeaningIndex = 0;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    isFlipped = false;

    const flashcardEl = document.getElementById('flashcard');
    if (flashcardEl) {
        flashcardEl.classList.remove('flipped');
    }

    const langConfig = config.languages[selectedLanguage];

    try {
        // Load the index (metadata) to get card details, joined with master if needed
        const vocabularyData = await fetchAndJoinIndex(langConfig);

        // Create a lookup map by stable hex ID
        const wordToVocab = {};
        vocabularyData.forEach((item, index) => {
            if (item.word && item.word.trim() !== '' && item.meanings && item.meanings.length > 0) {
                item.rank = index + 1; // assign dynamic rank from array position
                wordToVocab[item.id] = item;
            }
        });

        const exampleTargetField = langConfig.exampleTargetField || 'example_spanish';
        const exampleEnglishField = langConfig.exampleEnglishField || 'example_english';

        // Lazy-load examples for the incorrect words
        let allCorpusExamples = [];
        if (langConfig.examplesPath) {
            if (!window._cachedExamplesData) {
                const exResponse = await fetch(langConfig.examplesPath);
                if (exResponse.ok) {
                    window._cachedExamplesData = await exResponse.json();
                }
            }
            const examplesData = window._cachedExamplesData;
            if (examplesData) {
                // Merge examples into the incorrect word entries
                for (const incorrectWord of incorrectWords) {
                    const item = wordToVocab[incorrectWord.wordId];
                    if (!item) continue;
                    const ex = examplesData[item.id];
                    if (ex && ex.m) {
                        item.meanings.forEach((m, i) => {
                            m.examples = ex.m[i] || [];
                        });
                    }
                    if (ex && ex.w && item.mwe_memberships) {
                        item.mwe_memberships.forEach((mwe, i) => {
                            mwe.examples = ex.w[i] || [];
                        });
                    }
                }
                // MWE examples are pre-computed by the pipeline ("w" field)
            }
        }

        // Build flashcards from incorrect words
        for (const incorrectWord of incorrectWords) {
            // incorrectWord.wordId is a fullId (e.g., "es0ed68"); strip the 3-char prefix to get bare hex
            const bareId = incorrectWord.wordId.slice(3);
            const item = wordToVocab[bareId];
            if (!item) continue; // Skip if word not found in vocabulary

            const meanings = item.meanings.map(m => {
                const { targetSentence, englishSentence, allExamples } = getExampleFromMeaning(m, exampleTargetField, exampleEnglishField);
                return {
                    pos: m.pos,
                    meaning: m.translation,
                    percentage: parseFloat(m.frequency),
                    targetSentence,
                    englishSentence,
                    allExamples
                };
            });

            // Normalize percentages
            const totalPercentage = meanings.reduce((sum, m) => sum + (m.percentage || 0), 0);
            if (totalPercentage === 0 || isNaN(totalPercentage)) {
                const equalPercentage = 1.0 / meanings.length;
                meanings.forEach(m => { m.percentage = equalPercentage; });
            } else if (totalPercentage !== 1.0) {
                meanings.forEach(m => { m.percentage = (m.percentage || 0) / totalPercentage; });
            }

            // Synthesize a single MWE meaning that cycles through all expressions
            if (item.mwe_memberships && item.mwe_memberships.length > 0) {
                const allMWEs = [];
                // Sort artist-specific MWEs first, then wiktionary
                const sortedMWEs = [...item.mwe_memberships].sort((a, b) => {
                    const aArtist = (a.source || 'artist') === 'artist' ? 0 : 1;
                    const bArtist = (b.source || 'artist') === 'artist' ? 0 : 1;
                    return aArtist - bArtist;
                });
                // Strip elision markers for fuzzy MWE matching
                const stripElisions = (s) => s.replace(/['\u2019]/g, '').replace(/\s+/g, ' ');
                for (const mwe of sortedMWEs) {
                    // Use pre-attached examples if available (from examples.json "w" field),
                    // only fall back to corpus scan when needed (artist mode)
                    let matched = mwe.examples || [];
                    if (matched.length === 0 && allCorpusExamples.length > 0) {
                        const exprLower = mwe.expression.toLowerCase();
                        const exprNorm = stripElisions(exprLower);
                        // Word-boundary regex to avoid substring false positives
                        // (e.g. "solo que" matching "solo quedan")
                        const SP = 'a-zA-Z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00fc\u00c1\u00c9\u00cd\u00d3\u00da\u00d1\u00dc';
                        const escExpr = exprLower.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                        const escNorm = exprNorm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                        const exprRe = new RegExp('(?<![' + SP + '])' + escExpr + '(?![' + SP + '])', 'i');
                        const normRe = new RegExp('(?<![' + SP + '])' + escNorm + '(?![' + SP + '])', 'i');
                        matched = allCorpusExamples.filter(ex => {
                            const text = (ex.spanish || ex.target || '').toLowerCase();
                            return exprRe.test(text);
                        });
                        if (matched.length === 0) {
                            matched = allCorpusExamples.filter(ex => {
                                const text = stripElisions((ex.spanish || ex.target || '').toLowerCase());
                                return normRe.test(text);
                            });
                        }
                    }
                    allMWEs.push({
                        expression: mwe.expression,
                        translation: mwe.translation || '',
                        examples: matched.length > 0 ? matched : [{ spanish: '', english: '' }]
                    });
                }
                const firstEx = allMWEs[0].examples[0];
                meanings.push({
                    pos: 'MWE',
                    meaning: allMWEs[0].translation,
                    expression: allMWEs[0].expression,
                    allMWEs: allMWEs,
                    percentage: 0,
                    targetSentence: firstEx.spanish || firstEx.target || '',
                    englishSentence: firstEx.english || '',
                    allExamples: allMWEs[0].examples
                });
            }

            const firstExample = getExampleFromMeaning(item.meanings[0], exampleTargetField, exampleEnglishField);
            const card = {
                targetWord: item.word,
                lemma: item.lemma || '',
                rank: item.rank,
                id: item.id,
                fullId: getWordId(item),
                meanings: meanings,
                translation: item.meanings[0].translation,
                targetSentence: firstExample.targetSentence,
                englishSentence: firstExample.englishSentence,
                links: generateLinks(item.word, item.lemma || item.word, langConfig.referenceLinks),
                isMultiMeaning: true,
                variants: item.variants || null,
                homographIds: item.homograph_ids || null,
                morphology: item.morphology || null
            };
            flashcards.push(card);
        }

        if (flashcards.length === 0) {
            alert('Could not load incorrect words. Please try again.');
            document.getElementById('loadingMessage').style.display = 'none';
            return;
        }

        // Successfully loaded - show cards and hide setup
        document.getElementById('setupPanel').classList.add('hidden');
        document.getElementById('appContent').classList.remove('hidden');
        document.getElementById('loadingMessage').style.display = 'none';

        // Show mobile floating buttons
        showFloatingBtns(true);

        // Initialize card display
        initializeApp();
        buildWordLookupMap();
    } catch (error) {
        console.error('Failed to load incorrect words set:', error);
        document.getElementById('loadingMessage').style.display = 'none';
        alert('Error loading incorrect words. Please try again.');
    }
}

async function loadCSVFiles(ranges) {
    // Completely clear all previous data and state
    flashcards = [];
    currentIndex = 0;
    currentSentenceIndex = 0;
    currentMeaningIndex = 0;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    isFlipped = false;

    // Reset card flip state
    const flashcardEl = document.getElementById('flashcard');
    if (flashcardEl) {
        flashcardEl.classList.remove('flipped');
    }

    const langConfig = config.languages[selectedLanguage];

    for (const range of ranges) {
        try {
            const response = await fetch(range.path);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const fileText = await response.text();

            // Extract starting and ending rank from range (e.g., "0-50" -> 0, 50)
            const [rangeStart, rangeEnd] = range.range.split('-').map(Number);

            parseMultiMeaning(fileText, langConfig, rangeStart, rangeEnd);
        } catch (error) {
            console.error(`Failed to load ${range.path}:`, error);
            document.getElementById('loadingMessage').style.display = 'none';
            alert(`Error loading ${range.range}. Please try another set.`);
            return;
        }
    }

    if (flashcards.length === 0) {
        alert('No flashcards loaded. Please check your selection.');
        document.getElementById('loadingMessage').style.display = 'none';
        return;
    }

    // Successfully loaded data - show cards and hide setup
    document.getElementById('setupPanel').classList.add('hidden');
    document.getElementById('appContent').classList.remove('hidden');
    document.getElementById('loadingMessage').style.display = 'none';

    // Initialize card display
    updateCard();
}

function parseMultiMeaning(text, langConfig, rangeStart, rangeEnd) {
    const lines = text.split('\n');
    const wordGroups = {}; // Group meanings by rank

    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        const parts = trimmed.split('|');
        if (parts.length < 8) continue;

        const rank = parseInt(parts[0]);
        const word = parts[1];
        const lemma = parts[2];
        const pos = parts[3];
        const meaning = parts[4];
        const percentage = parseFloat(parts[5]);
        const targetSentence = parts[6];
        const englishSentence = parts[7];

        if (!wordGroups[rank]) {
            wordGroups[rank] = {
                rank: rank,
                word: word,
                lemma: lemma,
                meanings: []
            };
        }

        wordGroups[rank].meanings.push({
            pos: pos,
            meaning: meaning,
            percentage: percentage,
            targetSentence: targetSentence,
            englishSentence: englishSentence
        });
    }

    // Convert to flashcards array, filtering by range
    const ranks = Object.keys(wordGroups).map(Number).sort((a, b) => a - b);

    for (const rank of ranks) {
        if (rank >= rangeStart && rank < rangeEnd) {
            const group = wordGroups[rank];

            // Sort meanings by percentage (highest first)
            group.meanings.sort((a, b) => b.percentage - a.percentage);

            // Normalize percentages if they're missing or sum to 0
            const totalPercentage = group.meanings.reduce((sum, m) => sum + (m.percentage || 0), 0);
            if (totalPercentage === 0 || isNaN(totalPercentage)) {
                // Default to equal distribution
                const equalPercentage = 1.0 / group.meanings.length;
                group.meanings.forEach(m => {
                    m.percentage = equalPercentage;
                });
            } else if (totalPercentage !== 1.0) {
                // Normalize to sum to 1.0
                group.meanings.forEach(m => {
                    m.percentage = (m.percentage || 0) / totalPercentage;
                });
            }

            const card = {
                targetWord: group.word,
                lemma: group.lemma,
                rank: group.rank,
                meanings: group.meanings,
                // For compatibility, set primary translation to most common meaning
                translation: group.meanings[0].meaning,
                targetSentence: group.meanings[0].targetSentence,
                englishSentence: group.meanings[0].englishSentence,
                links: generateLinks(group.word, group.lemma || group.word, langConfig.referenceLinks),
                isMultiMeaning: true,
                variants: group.variants || null,
                morphology: group.morphology || null
            };

            flashcards.push(card);
        }
    }

    document.getElementById('loadingMessage').textContent = `✓ Loaded ${flashcards.length} cards!`;
    setTimeout(() => {
        document.getElementById('setupPanel').style.display = 'none';
        document.getElementById('appContent').classList.remove('hidden');
        initializeApp();
    }, 500);
}

// Truncate text to a maximum number of words, adding ellipsis if truncated
function truncateText(text, maxWords) {
    if (!text) return '';
    const words = text.split(/\s+/);
    if (words.length <= maxWords) return text;
    return words.slice(0, maxWords).join(' ') + '...';
}

function cleanValue(value) {
    return value ? value.replace(/^"|"$/g, '').trim() : '';
}

function generateLinks(word, lemma, linkTemplates) {
    const cleanWord = encodeURIComponent(lemma || word);
    const links = {};

    for (const [key, template] of Object.entries(linkTemplates)) {
        links[key] = template.replace('{word}', cleanWord);
    }

    return links;
}

// Helper to extract example sentences from a meaning object
// Supports new format (examples array) and legacy format (exampleTargetField/exampleEnglishField)
function getExampleFromMeaning(meaning, exampleTargetField, exampleEnglishField) {
    // Check for new examples array format
    if (meaning.examples && meaning.examples.length > 0) {
        const example = meaning.examples[0];
        // Support both 'target'/'english' and language-specific keys like 'spanish'/'english'
        const targetSentence = example.target || example.spanish || example.swedish ||
                               example.dutch || example.italian || example.polish || '';
        const englishSentence = example.english || '';
        return { targetSentence, englishSentence, allExamples: meaning.examples };
    }
    // Fall back to legacy format
    return {
        targetSentence: meaning[exampleTargetField] || '',
        englishSentence: meaning[exampleEnglishField] || '',
        allExamples: []
    };
}


// Merge vocabulary arrays from multiple artists by hex ID.
// With master vocab: IDs are guaranteed consistent, so merge is straightforward.
// Without master: falls back to legacy POS+translation union (backwards compat).
// Returns { mergedIndex: [...], mergedExamples: {...} }
async function mergeArtistVocabularies(artistConfigs, master) {
    const byId = new Map(); // id → merged entry
    const mergedExamples = {}; // id → { m: [...], w: [...] }

    for (const cfg of artistConfigs) {
        // Load lightweight index for word metadata
        const indexPath = cfg.indexPath || cfg.dataPath;
        let indexData;
        try {
            const resp = await fetch(indexPath);
            indexData = await resp.json();
        } catch (e) {
            console.warn(`Failed to load index for ${cfg.name}:`, e);
            continue;
        }

        // If master available and data is new format, join first
        const isNewFormat = indexData.length > 0 && indexData[0].sense_frequencies;
        if (master && isNewFormat) {
            indexData = joinWithMaster(indexData, master);
        }

        // Load separate examples file
        let examplesData = null;
        if (cfg.examplesPath) {
            try {
                const resp = await fetch(cfg.examplesPath);
                examplesData = await resp.json();
            } catch (e) {
                console.warn(`Failed to load examples for ${cfg.name}:`, e);
            }
        }

        for (const entry of indexData) {
            const id = entry.id;
            if (!id) continue;

            // Tag examples with artist slug
            const tagExamples = (examples) => {
                if (!examples) return [];
                return examples.map(ex => ({ ...ex, artist: cfg.slug }));
            };

            // Attach examples from split file onto meanings BEFORE merge,
            // so examples travel with their meaning
            if (examplesData && examplesData[id] && entry.meanings) {
                const ex = examplesData[id];
                if (ex.m) {
                    entry.meanings.forEach((m, i) => {
                        m.examples = ex.m[i] || [];
                    });
                }
                if (ex.w && entry.mwe_memberships) {
                    entry.mwe_memberships.forEach((mwe, i) => {
                        mwe.examples = ex.w[i] || [];
                    });
                }
                if (ex.c && entry.clitic_memberships) {
                    entry.clitic_memberships.forEach((cl, i) => {
                        cl.examples = ex.c[i] || [];
                    });
                }
            }

            if (byId.has(id)) {
                // Merge into existing entry — with master, senses are aligned by position
                const existing = byId.get(id);
                existing.corpus_count = (existing.corpus_count || 0) + (entry.corpus_count || 0);

                if (master && isNewFormat) {
                    // Master-based merge: senses are positionally aligned, just concat examples
                    if (entry.meanings) {
                        entry.meanings.forEach((newM, i) => {
                            if (i < existing.meanings.length) {
                                if (newM.examples) {
                                    existing.meanings[i].examples = (existing.meanings[i].examples || []).concat(tagExamples(newM.examples));
                                }
                            }
                        });
                    }
                } else {
                    // Legacy merge: union by POS+translation
                    const existingHasAnalysis = existing.meanings.some(m => m.pos !== 'X' && m.translation);
                    const newHasAnalysis = entry.meanings && entry.meanings.some(m => m.pos !== 'X' && m.translation);

                    if (entry.meanings) {
                        if (!existingHasAnalysis && newHasAnalysis) {
                            existing.meanings = entry.meanings.map(m => {
                                const tagged = { ...m };
                                if (tagged.examples) tagged.examples = tagExamples(tagged.examples);
                                return tagged;
                            });
                        } else if (existingHasAnalysis && !newHasAnalysis) {
                            // skip
                        } else {
                            for (const newM of entry.meanings) {
                                const existingM = existing.meanings.find(m => m.pos === newM.pos && m.translation === newM.translation);
                                if (existingM) {
                                    if (newM.examples) {
                                        existingM.examples = (existingM.examples || []).concat(tagExamples(newM.examples));
                                    }
                                } else {
                                    const tagged = { ...newM };
                                    if (tagged.examples) tagged.examples = tagExamples(tagged.examples);
                                    existing.meanings.push(tagged);
                                }
                            }
                        }
                    }
                }
            } else {
                // First time seeing this word — clone and tag
                const clone = JSON.parse(JSON.stringify(entry));
                if (clone.meanings) {
                    for (const m of clone.meanings) {
                        if (m.examples) m.examples = tagExamples(m.examples);
                    }
                }
                byId.set(id, clone);
            }

            // Build mergedExamples from the now-merged meanings
            if (byId.has(id)) {
                const merged = byId.get(id);
                mergedExamples[id] = { m: [] };
                merged.meanings.forEach((m, i) => {
                    mergedExamples[id].m[i] = m.examples || [];
                });
                if (merged.mwe_memberships) {
                    mergedExamples[id].w = [];
                    merged.mwe_memberships.forEach((mwe, i) => {
                        mergedExamples[id].w[i] = mwe.examples || [];
                    });
                }
            }
        }
    }

    // Recalculate frequency from example counts
    for (const entry of byId.values()) {
        if (entry.meanings && entry.meanings.length > 1) {
            const counts = entry.meanings.map(m => (m.examples || []).length);
            const total = counts.reduce((a, b) => a + b, 0);
            if (total > 0) {
                entry.meanings.forEach((m, i) => {
                    m.frequency = (counts[i] / total).toFixed(2);
                });
            }
        }
    }

    // Sort by combined corpus_count descending
    const mergedIndex = Array.from(byId.values()).sort((a, b) => (b.corpus_count || 0) - (a.corpus_count || 0));

    return { mergedIndex, mergedExamples };
}

window.mergeArtistVocabularies = mergeArtistVocabularies;
window.joinWithMaster = joinWithMaster;
window.fetchAndJoinIndex = fetchAndJoinIndex;
window.getWordId = getWordId;
window.getCrossModeId = getCrossModeId;
window.isWordKnown = isWordKnown;
window.buildEstimatedKnownIds = buildEstimatedKnownIds;
window.LANG_CODES = LANG_CODES;
window.buildFilteredVocab = buildFilteredVocab;
window.loadVocabularyData = loadVocabularyData;
window.loadIncorrectWordsSet = loadIncorrectWordsSet;
window.loadCSVFiles = loadCSVFiles;
window.parseMultiMeaning = parseMultiMeaning;
window.truncateText = truncateText;
window.cleanValue = cleanValue;
window.generateLinks = generateLinks;
window.getExampleFromMeaning = getExampleFromMeaning;
window.buildWordLookupMap = buildWordLookupMap;
