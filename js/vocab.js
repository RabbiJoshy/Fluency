// Vocabulary loading, filtering, and ID generation.
// Key functions: buildFilteredVocab() (central filter), loadVocabularyData(), getWordId(),
// mergeArtistVocabularies() (multi-artist merge by hex ID).
import './state.js?v=20260808c';

const LAST_STUDY_SESSION_KEY = 'fluency_last_study_session_v1';

function readStudySession(key) {
    try {
        const parsed = JSON.parse(localStorage.getItem(key) || 'null');
        return parsed && parsed.range && Array.isArray(parsed.order) ? parsed : null;
    } catch (error) {
        return null;
    }
}

// Scope key for a saved session. Same inputs as getProgressScopeKey so a
// snapshot and the progress rows it will resume against agree on what
// "this deck" means.
function studySessionScope({ mode, artistSlug, artistSlugs, language }) {
    return window.getProgressScopeKey?.({ mode, artistSlug, artistSlugs, language })
        || `${mode || 'speech'}:${artistSlug || language || ''}`;
}

// The deck the learner has explicitly opened, or null on a bare landing.
// Only an artist counts as explicit: arriving with no parameters is the
// landing, where offering whatever was studied last is the desired behaviour.
// A restored `selectedLanguage` is not an explicit choice and must not scope
// the prompt, or landing would stop offering a saved Lyrics set.
function activeStudySessionScope() {
    if (!activeArtist) return null;
    return studySessionScope({
        mode: 'lyrics',
        artistSlug: window._urlArtistSlug || null,
        artistSlugs: (window._selectedArtistSlugs || []).slice(),
        language: activeArtist.language || selectedLanguage
    });
}

// Resume resolution. Inside a deck, only that deck's own saved session is
// offered — previously the single global snapshot could send a learner who had
// just opened Bad Bunny into a Speech set, redirecting the URL to get there.
function getLastStudySession() {
    const scope = activeStudySessionScope();
    if (!scope) return readStudySession(LAST_STUDY_SESSION_KEY);
    const scoped = readStudySession(`${LAST_STUDY_SESSION_KEY}:${scope}`);
    if (scoped) return scoped;
    // Pre-migration sessions only exist under the global key; use one only
    // when it already belongs to the deck in front of the learner.
    const latest = readStudySession(LAST_STUDY_SESSION_KEY);
    return latest && studySessionScope(latest) === scope ? latest : null;
}

function renderResumeLastSetCard() {
    const snapshot = getLastStudySession();
    let card = document.getElementById('resumeLastSetCard');
    if (!snapshot) {
        if (card) card.remove();
        return;
    }
    // Resume is an entry decision, not a permanent setup-page advert. The
    // explicit ?resume=1 hop is already committed to resuming and skips this.
    const explicitResume = new URLSearchParams(window.location.search).get('resume') === '1';
    if (explicitResume) return;
    const snapshotScope = window.getProgressScopeKey?.({
        mode: snapshot.mode,
        artistSlug: snapshot.artistSlug,
        artistSlugs: snapshot.artistSlugs,
        language: snapshot.language
    });
    if (snapshot.selectedLevel
        && snapshotScope
        && window.isLevelMarkedDone?.(snapshot.selectedLevel, snapshotScope)) {
        if (card) card.remove();
        return;
    }
    try {
        if (sessionStorage.getItem('fluency_resume_prompt_seen_v1') === snapshot.savedAt) return;
    } catch (_) {}
    if (card) card.remove();
    card = document.createElement('section');
    card.id = 'resumeLastSetCard';
    card.className = 'modal resume-entry-modal';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-modal', 'true');
    card.setAttribute('aria-labelledby', 'resumeEntryTitle');
    const source = snapshot.mode === 'lyrics' ? 'Lyrics' : 'Speech';
    const level = snapshot.levelNumber ? `Level ${snapshot.levelNumber}` : 'Saved level';
    const set = snapshot.setNumber ? `Set ${snapshot.setNumber}` : 'Saved set';
    const track = snapshot.studyMode === 'review' ? 'Review' : 'Learn new';
    const forms = snapshot.useLemmaMode ? 'Merged lemmas' : 'Forms';
    const cognates = snapshot.excludeCognates ? 'Cognates excluded' : 'Cognates included';
    const title = snapshot.mode === 'lyrics'
        ? `${snapshot.artistName || 'Lyrics'}${snapshot.artistVocabularyScope === 'extra' ? ' Extra' : ''}`
        : `${snapshot.languageName || snapshot.language} speech`;
    card.innerHTML = `
        <div class="modal-content resume-entry-content">
            <span class="resume-set-eyebrow">Welcome back</span>
            <h3 id="resumeEntryTitle">Continue where you stopped?</h3>
            <strong>${title}</strong>
            <p>${source} · ${level} · ${set} · ${track}</p>
            <small>${forms} · ${cognates} · last card: ${snapshot.currentWord || 'saved card'}</small>
            <div class="resume-entry-actions">
                <button type="button" class="resume-entry-secondary" id="dismissResumeLastSetBtn">Choose a new set</button>
                <button type="button" class="resume-entry-primary" id="resumeLastSetBtn">Continue set</button>
            </div>
        </div>`;
    document.body.appendChild(card);
    const markSeenAndClose = () => {
        try { sessionStorage.setItem('fluency_resume_prompt_seen_v1', snapshot.savedAt); } catch (_) {}
        card.remove();
    };
    document.getElementById('resumeLastSetBtn')?.addEventListener('click', () => {
        markSeenAndClose();
        resumeLastStudySession();
    });
    document.getElementById('dismissResumeLastSetBtn')?.addEventListener('click', markSeenAndClose);
    card.addEventListener('click', event => {
        if (event.target === card) markSeenAndClose();
    });
}

function clearStudySessionSnapshot() {
    // Both copies have to go. Dropping only the global key would leave the
    // scoped one behind, and a finished set would keep being offered every
    // time the learner reopened that deck.
    try {
        const previous = readStudySession(LAST_STUDY_SESSION_KEY);
        localStorage.removeItem(LAST_STUDY_SESSION_KEY);
        if (previous) localStorage.removeItem(`${LAST_STUDY_SESSION_KEY}:${studySessionScope(previous)}`);
        const scope = activeStudySessionScope();
        if (scope) localStorage.removeItem(`${LAST_STUDY_SESSION_KEY}:${scope}`);
    } catch (_) {}
    document.getElementById('resumeLastSetCard')?.remove();
}

function saveStudySessionSnapshot() {
    if (!flashcards.length || cardNavStack.length > 0 || !stats.rangeString) return;
    const appContent = document.getElementById('appContent');
    if (!appContent || appContent.classList.contains('hidden')) return;
    const card = flashcards[currentIndex];
    if (!card) return;
    const levelButtons = Array.from(document.querySelectorAll('.level-selector-buttons .level-btn, #levelSelector > .level-btn'));
    const levelNumber = Math.max(0, levelButtons.findIndex(btn => btn.dataset.level === selectedLevel)) + 1;
    const languageName = config?.languages?.[selectedLanguage]?.name?.replace(/\s*\(.*\)$/, '') || selectedLanguage;
    const snapshot = {
        savedAt: new Date().toISOString(),
        mode: activeArtist ? 'lyrics' : 'speech',
        artistSlug: window._urlArtistSlug || null,
        artistSlugs: (window._selectedArtistSlugs || []).slice(),
        artistName: activeArtist?.name || null,
        artistVocabularyScope: activeArtist ? artistVocabularyScope : null,
        language: selectedLanguage,
        languageName,
        selectedLevel,
        levelNumber,
        range: stats.rangeString,
        rangeBasis: stats.rangeBasis || 'display',
        setNumber: stats.setNumber || null,
        levelSetCount: stats.levelSetCount || null,
        studyMode: stats.studyMode || 'new',
        groupSize,
        useLemmaMode,
        excludeCognates,
        hideSingleOccurrence,
        excludeProperNouns,
        excludeNoise,
        excludeEnglishLoanwords,
        directionFlipped: isFlipped,
        speechEnabled,
        cardFaceFlipped: document.getElementById('flashcard')?.classList.contains('flipped') || false,
        currentFullId: card.fullId,
        currentVocabularyRank: card.vocabularyRank || card.rank || null,
        currentWord: card.targetWord,
        currentMeaningIndex,
        currentExampleIndex,
        currentMWEIndex,
        setSize: stats.setSize,
        previouslyKnown: stats.previouslyKnown,
        order: flashcards.map(item => item.fullId)
    };
    try {
        const serialized = JSON.stringify(snapshot);
        // Global key = "most recent anywhere", which is what the landing
        // offers. The scoped copy is what a deck resumes from, so switching
        // between Bad Bunny and Speech no longer overwrites the other's
        // place in its set.
        localStorage.setItem(LAST_STUDY_SESSION_KEY, serialized);
        localStorage.setItem(`${LAST_STUDY_SESSION_KEY}:${studySessionScope(snapshot)}`, serialized);
    } catch (error) {
        // Storage can be unavailable in hardened/private contexts.
    }
}

async function resumeLastStudySession() {
    const snapshot = getLastStudySession();
    if (!snapshot) {
        window.hideAppLoading?.();
        return;
    }
    window.showAppLoading?.('Continuing Your Set', 'Returning to the card where you stopped…', true);
    try { sessionStorage.setItem('fluency_resume_prompt_seen_v1', snapshot.savedAt); } catch (_) {}
    document.getElementById('resumeLastSetCard')?.remove();
    const currentMode = activeArtist ? 'lyrics' : 'speech';
    const currentArtist = window._urlArtistSlug || null;
    if (snapshot.mode !== currentMode || (snapshot.mode === 'lyrics' && snapshot.artistSlug !== currentArtist)) {
        const url = new URL(window.location.href);
        url.search = '';
        if (snapshot.mode === 'lyrics' && snapshot.artistSlug) {
            url.searchParams.set('artist', snapshot.artistSlug);
            if (snapshot.artistVocabularyScope === 'extra') url.searchParams.set('scope', 'extra');
        }
        url.searchParams.set('resume', '1');
        window.location.href = url.toString();
        return;
    }

    const requestedExtra = snapshot.mode === 'lyrics' && snapshot.artistVocabularyScope === 'extra';
    if (requestedExtra && !window.isArtistExtraUnlocked?.(snapshot.artistSlug)) {
        clearStudySessionSnapshot();
        artistVocabularyScope = 'main';
        window.renderArtistSourceSummary?.();
        window.hideAppLoading?.();
        alert('Artist Extra unlocks after you understand 60% of this artist\'s main lyrics vocabulary.');
        return;
    }

    selectedLanguage = snapshot.language;
    window.applyLanguageColorTheme?.();
    selectedLevel = snapshot.selectedLevel;
    groupSize = snapshot.groupSize || 20;
    useLemmaMode = !!snapshot.useLemmaMode;
    excludeCognates = !!snapshot.excludeCognates;
    hideSingleOccurrence = snapshot.hideSingleOccurrence !== false;
    artistVocabularyScope = requestedExtra ? 'extra' : 'main';
    excludeProperNouns = snapshot.excludeProperNouns !== false;
    excludeNoise = snapshot.excludeNoise !== false;
    excludeEnglishLoanwords = snapshot.excludeEnglishLoanwords !== false;
    isFlipped = !!snapshot.directionFlipped;
    if (typeof snapshot.speechEnabled === 'boolean') speechEnabled = snapshot.speechEnabled;
    window.renderArtistSourceSummary?.();
    if (snapshot.mode === 'lyrics' && snapshot.artistSlugs?.length) {
        const oldKey = (window._selectedArtistSlugs || []).slice().sort().join(',');
        const newKey = snapshot.artistSlugs.slice().sort().join(',');
        if (oldKey !== newKey) {
            window._cachedMergedIndex = null;
            window._cachedMergedExamples = null;
            window._cachedExamplesData = null;
        }
        window._selectedArtistSlugs = snapshot.artistSlugs.slice();
        localStorage.setItem('selected_artists', JSON.stringify(snapshot.artistSlugs));
    }
    document.querySelectorAll('.lemma-toggle-btn').forEach(button =>
        button.classList.toggle('selected', (button.dataset.lemma === 'on') === useLemmaMode));
    document.querySelectorAll('.cognate-toggle-btn').forEach(button =>
        button.classList.toggle('selected', (button.dataset.cognate === 'exclude') === excludeCognates));
    const url = new URL(window.location.href);
    url.searchParams.delete('resume');
    if (snapshot.mode === 'lyrics' && artistVocabularyScope === 'extra') {
        url.searchParams.set('scope', 'extra');
    } else {
        url.searchParams.delete('scope');
    }
    history.replaceState(null, '', url);
    try {
        await loadVocabularyData(snapshot.range, {
            resumeSnapshot: snapshot,
            rankBasis: snapshot.rangeBasis || 'display',
            setNumber: snapshot.setNumber || null,
            levelSetCount: snapshot.levelSetCount || null
        });
    } finally {
        window.hideAppLoading?.();
    }
}

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
 * Check if a word is currently resolved in either mode. Historical wrong
 * counts remain available, but a newer wrong moves the card back to review.
 */
function isWordKnown(fullId) {
    const check = (id) => {
        const p = progressData?.[id];
        return p && p.language === selectedLanguage && getProgressState(p).learned;
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

async function buildSeenLemmaSet(vocabData) {
    if (!useLemmaMode || !lemmaFieldAvailable || !progressData) return new Set();

    const lemmaById = new Map();
    const addEntries = entries => {
        for (const entry of entries || []) {
            if (entry?.id && entry?.lemma) lemmaById.set(entry.id, entry.lemma);
        }
    };
    addEntries(vocabData);
    addEntries(Object.entries(window._cachedMasterVocab || {}).map(([id, entry]) => ({
        ...entry, id
    })));

    // The current artist master covers artist decks. Add the normal index so
    // normal-only surface forms also contribute to a merged lemma's history.
    if (activeArtist) {
        const normalConfig = window._normalModeLangConfigs?.[selectedLanguage];
        if (normalConfig) addEntries(await fetchAndJoinIndex(normalConfig));
    }

    const seenLemmas = new Set();
    const mark = (fullId, state) => {
        if (!state?.seen || !fullId) return;
        const lemma = lemmaById.get(fullId.slice(3));
        if (lemma) seenLemmas.add(lemma);
    };
    for (const [fullId, progress] of Object.entries(progressData)) {
        if (progress?.language === selectedLanguage) {
            mark(fullId, getProgressState(progress));
        }
    }
    for (const progress of Object.values(itemProgressData || {})) {
        if (progress?.language === selectedLanguage) {
            mark(progress.parentWordId, getProgressState(progress));
        }
    }
    return seenLemmas;
}

function relatedWordIds(fullId) {
    const crossId = getCrossModeId(fullId);
    return crossId ? [fullId, crossId] : [fullId];
}

function hasRelatedWordProgress(fullId) {
    return relatedWordIds(fullId).some(id =>
        getWordProgressState(id).seen || wordHasKnowledgeProgress(id));
}

function relatedWordNeedsReview(fullId) {
    return relatedWordIds(fullId).some(id => wordNeedsKnowledgeReview(id));
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

        // Keep the complete shared sense menu on the joined entry. Main cards
        // still prefer/drop to positive artist frequencies before rendering,
        // while one-off forms can reuse these dictionary senses and the
        // standard Speech evidence packaged in the examples split. This is
        // what makes Artist Extra useful without another Gemini pass.
        const methods = idx.sense_methods || [];
        const promptIds = idx.sense_prompt_ids || [];
        const runTimes = idx.sense_run_ts || [];
        const freqs = idx.sense_frequencies || [];
        const meanings = [];
        (m.senses || []).forEach((sense, i) => {
            const freq = Number(freqs[i]) || 0;
            const meaning = {
                pos: sense.pos,
                translation: sense.translation,
                frequency: String(freq),
                examples: []  // Attached later from examples file
            };
            // Provenance (which prompt/model produced this sense) for the
            // card's info panel — resolved against window._promptRegistry.
            if (freq > 0 && promptIds[i]) {
                meaning.prompt_id = promptIds[i];
                if (runTimes[i]) meaning.run_ts = runTimes[i];
            }
            if (sense.id || sense.sense_id) meaning.sense_id = sense.id || sense.sense_id;
            if (sense.sense_id_aliases?.length) meaning.sense_id_aliases = sense.sense_id_aliases;
            if (freq <= 0) {
                meaning.shared_fallback = true;
                meaning.unassigned = true;
            }
            if (sense.source) meaning.source = sense.source;
            if (sense.context) meaning.context = sense.context;
            // Register/dialect tag stamped by the classify-or-propose prompt
            // (slang | regional | figurative | vulgar | loanword | proper_noun).
            // Copy-through matters: meanings are rebuilt from scratch here and
            // again in buildFilteredVocab(), so anything not carried explicitly
            // is silently dropped before it reaches the card.
            if (sense.type) meaning.type = sense.type;
            const method = freq > 0 ? methods[i] : null;
            if (method) {
                meaning.assignment_method = method;
            } else if (freq > 0 && idx.unassigned) {
                meaning.unassigned = true;
            }
            meaning._masterSenseIndex = i;
            meanings.push(meaning);
        });

        // Build mwe_memberships from index entry (per-artist, not master)
        const mwe_memberships = (idx.mwe_memberships || []).map(mwe => ({
            id: mwe.id || null,
            expression: mwe.expression,
            translation: mwe.translation || '',
            family: mwe.family || '',
            variants: mwe.variants || null,
            variant_counts: mwe.variant_counts || null,
            count: Number(mwe.count) || 0,
            occurrence_count: Number(mwe.occurrence_count) || 0,
            num_songs: Number(mwe.num_songs) || 0,
            source: mwe.source || '',
            context: mwe.context || '',
            context_heuristic: mwe.context_heuristic || '',
            examples: []
        }));

        // Build clitic_memberships from index entry
        const clitic_memberships = (idx.clitic_memberships || []).map(cl => ({
            form: cl.form,
            translation: cl.translation || '',
            corpus_count: cl.corpus_count || 0,
            examples: []
        }));

        // Build sense_cycles from index entry (unassigned/cycling senses)
        const sense_cycles = (idx.sense_cycles || []).map(sc => ({
            pos: sc.pos,
            translation: sc.translation || '',
            cycle_pos: sc.cycle_pos || sc.pos,
            allSenses: sc.allSenses || [],
            unassigned: true,
            examples: []
        }));

        result.push({
            id: idx.id,
            word: m.word,
            lemma: m.lemma,
            meanings,
            _base_meanings: meanings.map(meaning => ({ ...meaning, examples: [] })),
            most_frequent_lemma_instance: idx.most_frequent_lemma_instance,
            is_english: m.is_english || false,
            // is_noise is the schema_v2 flag name; is_interjection is the
            // legacy alias kept for vocabularies built before the rename.
            // Carry both forward so downstream filters can read either.
            is_noise: m.is_noise || m.is_interjection || false,
            is_interjection: m.is_noise || m.is_interjection || false,
            is_propernoun: m.is_propernoun || false,
            // Corpus-derived proper-noun signal from cap-rate
            // (tool_8a_stamp_propernoun_corpus.py). Independent of the
            // pipeline-stamped `is_propernoun` flag — both can be true,
            // either alone is sufficient for filtering.
            is_propernoun_corpus: m.is_propernoun_corpus || false,
            propernoun_cap_rate: m.propernoun_cap_rate ?? null,
            // English loanword flag (tool_8a_stamp_loanword_flag.py --master),
            // from the Wiktionary-etymology layer. Toggleable filter.
            is_english_loanword: m.is_english_loanword || false,
            // Pipeline-assigned Extra grouping key (core / single_occurrence /
            // english / loanword / proper_noun / cognate / noise / …). Drives
            // the Artist Extra category selector; absent → "All Extra" fallback.
            extra_category: m.extra_category || null,
            cognate_score: idx.cognate_score ?? m.cognate_score ?? (m.is_transparent_cognate ? 1 : 0),
            cognet_cognate: idx.cognet_cognate || m.cognet_cognate || false,
            corpus_count: idx.corpus_count || 0,
            lemma_example_count: idx.lemma_example_count ?? idx.corpus_count ?? 0,
            display_form: m.display_form || null,
            variants: idx.variants || null,
            mwe_memberships: mwe_memberships.length > 0 ? mwe_memberships : undefined,
            clitic_memberships: clitic_memberships.length > 0 ? clitic_memberships : undefined,
            sense_cycles: sense_cycles.length > 0 ? sense_cycles : undefined,
            morphology: idx.morphology || null,
            synonyms: idx.synonyms || null,
            antonyms: idx.antonyms || null,
            related_lemma: idx.related_lemma || m.related_lemma || null,
            derivation_relation: idx.derivation_relation || m.derivation_relation || null,
        });
    }
    return result;
}

/**
 * Lemma mode: pool the dropped sibling forms' examples onto the surviving card.
 * One-card-per-lemma keeps only the most frequent form (quiero) and drops the
 * rest (quieres, quiere, …) — but their lyric/example lines still belong on the
 * surviving card. Appends each sibling's examples to the host meaning with the
 * same translation (falling back to the first meaning), deduped by sentence so
 * repeated deck loads can't double-append.
 *
 * Sibling examples come from the split examples file (`examplesData[id].m`,
 * bucketed in master sense order) when available, else from inline
 * `meanings[].examples` (multi-artist merged entries).
 */
function exampleSentenceKey(example) {
    return (example?.target || example?.spanish || example?.sentence || '').trim().toLowerCase();
}

function examplesForMeaning(item, meaning, meaningIndex, examplesData) {
    if (meaning.examples && meaning.examples.length > 0) return meaning.examples;
    const split = examplesData && item.id ? examplesData[item.id] : null;
    const bucket = meaning._masterSenseIndex ?? meaningIndex;
    return (split && split.m && split.m[bucket]) || [];
}

function mergeArtistExtraSupport(item, splitExamples) {
    if (!activeArtist || !splitExamples) return;
    const normalize = value => String(value || '').trim().toLowerCase();
    const dedupeInto = (target, additions) => {
        target.examples = target.examples || [];
        const seen = new Set(target.examples.map(exampleSentenceKey));
        for (const raw of additions || []) {
            const key = exampleSentenceKey(raw);
            if (!key || seen.has(key)) continue;
            seen.add(key);
            target.examples.push({ ...raw });
        }
    };

    // `p` is a compact, sense-labelled subset of the already-built Speech
    // examples. It is independent of artist master-sense array positions.
    for (const shared of splitExamples.p || []) {
        let target = (item.meanings || []).find(meaning =>
            normalize(meaning.pos) === normalize(shared.pos)
            && normalize(meaning.translation) === normalize(shared.translation)
            && normalize(meaning.context) === normalize(shared.context));
        if (!target) {
            target = {
                pos: shared.pos || 'X',
                translation: shared.translation || '',
                context: shared.context || '',
                frequency: '0',
                examples: [],
                shared_fallback: true,
                unassigned: true,
            };
            item.meanings = item.meanings || [];
            item.meanings.push(target);
        }
        dedupeInto(target, shared.examples || []);
        target.has_speech_fallback = true;
    }

    // The artist lyric is deliberately not stamped as assigned to a shared
    // sense. Put it on the first usable row so it is visible immediately; the
    // example-level match treatment remains absent, honestly signalling that
    // no classifier linked this lyric to that particular meaning.
    const lyricExamples = splitExamples.r || [];
    if (lyricExamples.length > 0) {
        const target = (item.meanings || []).find(meaning => meaning.examples?.length)
            || (item.meanings || [])[0];
        if (target) {
            const existing = target.examples || [];
            target.examples = [];
            dedupeInto(target, [...lyricExamples, ...existing]);
        } else {
            item.extra_raw_examples = lyricExamples.map(example => ({ ...example }));
        }
    }
}

function computeLemmaExampleCounts(vocabData, examplesData) {
    const linesByLemma = new Map();
    let hasExampleBasis = false;
    for (const item of vocabData) {
        if (!item.lemma || item.is_english || item.is_noise || item.is_interjection || item.duplicate) continue;
        if (!linesByLemma.has(item.lemma)) linesByLemma.set(item.lemma, new Set());
        const lines = linesByLemma.get(item.lemma);
        (item.meanings || []).forEach((meaning, i) => {
            for (const example of examplesForMeaning(item, meaning, i, examplesData)) {
                const key = exampleSentenceKey(example);
                if (!key) continue;
                hasExampleBasis = true;
                lines.add(key);
            }
        });
    }
    return {
        counts: new Map(Array.from(linesByLemma, ([lemma, lines]) => [lemma, lines.size])),
        hasExampleBasis
    };
}

function poolLemmaSiblingExamples(filteredData, allVocabData, examplesData) {
    const hosts = new Map();
    for (const item of filteredData) {
        if (item.lemma && !hosts.has(item.lemma)) hosts.set(item.lemma, item);
    }
    if (hosts.size === 0) return;

    const normalize = t => (t || '').trim().toLowerCase();
    for (const sib of allVocabData) {
        const host = sib.lemma && hosts.get(sib.lemma);
        if (!host || sib === host || (sib.id && sib.id === host.id)) continue;
        if (sib.is_english || sib.is_noise || sib.is_interjection || sib.duplicate) continue;
        if (!sib.meanings || sib.meanings.length === 0) continue;

        for (let i = 0; i < sib.meanings.length; i++) {
            const sm = sib.meanings[i];
            // Prefer inline examples (multi-artist merged entries carry the
            // cross-artist union); fall back to the split examples file.
            const sibExamples = examplesForMeaning(sib, sm, i, examplesData);
            if (sibExamples.length === 0) continue;

            const target = host.meanings.find(hm => normalize(hm.translation) === normalize(sm.translation))
                || host.meanings[0];
            if (!target) continue;
            if (!target.examples) target.examples = [];
            const seen = new Set(target.examples.map(exampleSentenceKey));
            for (const e of sibExamples) {
                const key = exampleSentenceKey(e);
                if (!key || seen.has(key)) continue;
                seen.add(key);
                target.examples.push({
                    ...e,
                    pooledFrom: sib.word,
                    // Keep the grammar of the exact sibling surface beside
                    // its pooled example. Merged cards can then present the
                    // evidenced form (dieron) while retaining the shared
                    // lemma (dar) as their stable identity.
                    pooledMorphology: e.pooledMorphology || sib.morphology || null
                });
            }
        }

        // One-off surface forms can carry their unclassified artist line in
        // the compact `r` bucket rather than a master-sense `m` bucket. They
        // still belong in the recurring lemma host's example pool.
        const rawSiblingExamples = examplesData?.[sib.id]?.r || [];
        const rawTarget = host.meanings.find(meaning => meaning.examples?.length)
            || host.meanings[0];
        if (rawTarget && rawSiblingExamples.length > 0) {
            rawTarget.examples = rawTarget.examples || [];
            const seen = new Set(rawTarget.examples.map(exampleSentenceKey));
            for (const example of rawSiblingExamples) {
                const key = exampleSentenceKey(example);
                if (!key || seen.has(key)) continue;
                seen.add(key);
                rawTarget.examples.push({
                    ...example,
                    pooledFrom: example.pooledFrom || sib.word,
                    pooledMorphology: example.pooledMorphology || sib.morphology || null
                });
            }
        }
    }

    // The card-front pooled frequency uses this exact attached-example
    // union. Count across meanings once so a line assigned to two senses
    // does not inflate the lemma total.
    for (const host of hosts.values()) {
        const seen = new Set();
        for (const meaning of (host.meanings || [])) {
            for (const example of (meaning.examples || [])) {
                const key = exampleSentenceKey(example);
                if (key) seen.add(key);
            }
        }
        host.lemma_example_count = seen.size;
        host.pooled_frequency = seen.size;
    }
}

/**
 * Keep the three jobs historically performed by `targetWord` separate:
 * - displaySurface: the corpus form used for a target-language prompt;
 * - citationForm: the dictionary/lemma form that explains the lexeme;
 * - productionAnswer: the preferred target-language answer used by the
 *   English→target direction.
 *
 * The snake_case aliases make this an adapter for future pipeline fields while
 * the lemma/word fallbacks preserve every currently shipped deck.
 */
function buildCardFormModel(item, meanings = [], options = {}) {
    const representativeSurface = String(
        item?.dominant_surface
        || item?.dominantSurface
        || item?.display_surface
        || item?.displaySurface
        || item?.word
        || item?.targetWord
        || ''
    ).trim();
    const citationForm = String(
        item?.citation_form
        || item?.citationForm
        || item?.lemma
        || representativeSurface
    ).trim();
    // Merge Lemmas still uses the most frequent surface entry as its stable
    // rank/progress host, but the learner is studying the lexeme, not that
    // accidental representative inflection. Present the citation form while
    // retaining targetWord/representativeSurface for IDs and exact examples.
    const mergedLemma = options.mergedLemma === true && Boolean(citationForm);
    const displaySurface = mergedLemma ? citationForm : representativeSurface;
    const hasVerbSense = meanings.some(meaning => {
        const pos = String(meaning?.pos || '').toLocaleLowerCase('en');
        return pos === 'v' || pos === 'vb' || pos.includes('verb');
    });
    const explicitPronominal = item?.is_pronominal ?? item?.isPronominal;
    const isPronominal = explicitPronominal !== undefined
        ? Boolean(explicitPronominal)
        : selectedLanguage === 'spanish'
            && hasVerbSense
            && /se$/iu.test(citationForm);
    const productionAnswer = String(
        item?.production_answer
        || item?.productionAnswer
        // A standalone surface-form card tests that surface. A merged card
        // tests the shared lemma. Pronominal verbs fall back to their complete
        // `-se` citation rather than presenting an incomplete bare form when
        // old data lacks enough morphology to choose me/te/se/nos/os safely.
        || (mergedLemma || isPronominal ? citationForm : representativeSurface)
        || citationForm
        || displaySurface
    ).trim();

    return {
        displaySurface,
        representativeSurface,
        citationForm,
        productionAnswer,
        isPronominal,
        mergedLemma
    };
}

/**
 * Fetch the artist/language index and join with master vocabulary if needed.
 * Caches the master and the joined result. Returns denormalized entries with all fields
 * (word, lemma, meanings, flags) that buildFilteredVocab() and other consumers expect.
 */
// Record the newest Last-Modified across the vocab data files, plus when we
// fetched. The service worker preserves the original response headers, so a
// stale cached file keeps its old date — the settings-modal footer surfaces
// this so "am I seeing cached data?" is answerable at a glance. Called at
// every vocab data fetch site (index, master, examples, merge, CSV ranges).
function trackDataFreshness(resp) {
    if (!resp || !resp.headers) return;
    const lm = resp.headers.get('last-modified');
    if (!lm) return;
    const t = new Date(lm).getTime();
    if (isNaN(t)) return;
    if (!window._vocabDataLastModified || t > window._vocabDataLastModified) {
        window._vocabDataLastModified = t;
    }
    window._vocabDataLoadedAt = Date.now();
    // Per-file breakdown for the JST dev footer.
    try {
        const name = decodeURIComponent(new URL(resp.url).pathname.split('/').pop());
        window._vocabDataFreshness = window._vocabDataFreshness || {};
        window._vocabDataFreshness[name] = t;
    } catch (e) { /* resp.url unset in some test contexts — breakdown only */ }
}
window.trackDataFreshness = trackDataFreshness;

// Keep parsed/joined indexes per path. A level-estimate lookup may need the
// Speech index while the learner is in Lyrics mode; the old single-slot cache
// evicted the artist index and forced another multi-megabyte parse immediately
// afterwards.
const joinedIndexCacheByPath = new Map();

async function fetchAndJoinIndex(langConfig) {
    const indexPath = langConfig.indexPath || langConfig.dataPath;

    // Preserve the legacy active-source pointers for search/modal consumers,
    // while retaining other sources in the path-keyed cache.
    if (window._cachedJoinedIndex && window._cachedJoinedIndexPath === indexPath) {
        return window._cachedJoinedIndex;
    }
    if (joinedIndexCacheByPath.has(indexPath)) {
        const cached = joinedIndexCacheByPath.get(indexPath);
        window._cachedJoinedIndex = cached;
        window._cachedJoinedIndexPath = indexPath;
        return cached;
    }

    const response = await fetch(indexPath);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    trackDataFreshness(response);
    let data = await response.json();

    // Detect new master-based format and join if needed
    if (activeArtist && langConfig.masterPath && data.length > 0 && data[0].sense_frequencies) {
        if (!window._cachedMasterVocab) {
            try {
                const masterResp = await fetch(langConfig.masterPath);
                if (masterResp.ok) {
                    trackDataFreshness(masterResp);
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
    joinedIndexCacheByPath.set(indexPath, data);
    return data;
}

async function fetchActiveVocabularyData(langConfig) {
    const selectedSlugs = window._selectedArtistSlugs || [];
    const allConfigs = window._allArtistsConfig;
    if (!(activeArtist && selectedSlugs.length > 1 && allConfigs)) {
        return fetchAndJoinIndex(langConfig);
    }

    if (!window._cachedMasterVocab) {
        // The primary artist fetch also loads the shared master.
        await fetchAndJoinIndex(langConfig);
    }
    if (!window._cachedMergedIndex) {
        const artistConfigs = selectedSlugs
            .map(slug => allConfigs[slug] ? { ...allConfigs[slug], slug } : null)
            .filter(Boolean);
        const { mergedIndex, mergedExamples } = await mergeArtistVocabularies(
            artistConfigs,
            window._cachedMasterVocab
        );
        window._cachedMergedIndex = mergedIndex;
        window._cachedMergedExamples = mergedExamples;
    }
    window._cachedExamplesData = window._cachedMergedExamples;
    return window._cachedMergedIndex;
}

async function ensureLemmaPoolingData(langConfig) {
    await fetchActiveVocabularyData(langConfig);
    if (window._cachedExamplesData || !langConfig?.examplesPath) {
        return window._cachedExamplesData || null;
    }
    try {
        const response = await fetch(langConfig.examplesPath);
        if (!response.ok) return null;
        trackDataFreshness(response);
        window._cachedExamplesData = await response.json();
        return window._cachedExamplesData;
    } catch (error) {
        console.warn('Failed to load examples for lemma pooling:', error);
        return null;
    }
}

// Assign a filter-independent frequency position to every teachable source
// entry. Optional settings may hide an entry or merge it into a lemma host,
// but they must never cause the remaining cards to migrate between levels or
// study sets. The source array position is the deterministic tie-breaker.
function artistLemmaEvidenceCount(item) {
    const stamped = Number(item?.lemma_example_count);
    if (Number.isFinite(stamped)) return Math.max(0, stamped);
    const fallback = Number(item?.corpus_count);
    return Number.isFinite(fallback) ? Math.max(0, fallback) : 0;
}

// Extra membership is by TAG, not frequency. Extra = anything the tagger
// classified as not-core-Spanish (loanword / English / proper noun / cognate /
// noise). Everything else — including one-off real Spanish words like `alguna`
// / `adelante` — is core → Main. `single_occurrence` and the old
// `lemma_example_count <= 1` frequency rule are retired (a rare word is still
// real vocab; frequent loanwords like `baby` belong in Extra regardless of count).
const ARTIST_EXTRA_CATEGORIES = new Set(
    ['loanword', 'english', 'proper_noun', 'cognate', 'noise']);
const ARTIST_MIN_SENSE_FREQ = 0.05;
function artistItemMatchesScope(item) {
    if (!activeArtist) return true;
    const cat = String(item?.extra_category || '').toLowerCase();
    // Fallback for entries not yet stamped: treat as core (Main), so nothing
    // real is hidden before the tag store is fully carried through.
    const isExtra = ARTIST_EXTRA_CATEGORIES.has(cat);
    return artistVocabularyScope === 'extra' ? isExtra : !isExtra;
}

// --- Artist Extra category grouping ---------------------------------------
// Extra vocabulary is supplementary and has no meaningful frequency ranking,
// so it is grouped by the pipeline-supplied `extra_category` string instead of
// frequency levels. The list of possible categories is intentionally NOT
// hardcoded: whatever distinct values the data carries are rendered, mapped to
// a readable label where known and title-cased otherwise. If no entry carries
// an `extra_category` yet, everything falls back to one "All Extra" group so
// the UI keeps working before the pipeline populates the field.
const EXTRA_CATEGORY_LABELS = {
    core: 'Core words',
    loanword: 'Loanwords',
    english: 'English words',
    cognate: 'Cognates',
    proper_noun: 'Names & places',
    propernoun: 'Names & places',
    proper_nouns: 'Names & places',
    slang: 'Slang & informal',
    single_occurrence: 'One-off words',
    interjection: 'Interjections',
    noise: 'Interjections & filler',
    onomatopoeia: 'Sound words',
    abbreviation: 'Abbreviations',
    name: 'Names',
};
const EXTRA_CATEGORY_ALL_KEY = '__all_extra__';

function extraCategoryKeyOf(item) {
    const raw = item && typeof item.extra_category === 'string'
        ? item.extra_category.trim().toLowerCase()
        : '';
    return raw;
}

function extraCategoryLabelFor(key) {
    if (!key || key === EXTRA_CATEGORY_ALL_KEY) return 'All Extra';
    if (EXTRA_CATEGORY_LABELS[key]) return EXTRA_CATEGORY_LABELS[key];
    // Default: title-case the raw key, turning separators into spaces.
    return key
        .replace(/[_-]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/\b\w/g, ch => ch.toUpperCase());
}

// Stamp a contiguous, category-blocked `categoryRank` on every Extra entry and
// return ordered group metadata the setup UI can turn into pickable groups.
// Each category occupies one continuous rank block; sets page through a block
// with the same STABLE_SET_SLOT machinery the frequency levels use. Order of
// items WITHIN a block is preserved from the incoming (frequency/pooled) sort
// so set membership is deterministic.
function assignExtraCategoryRanks(orderedVocab) {
    const groupsByKey = new Map();
    let anyCategory = false;
    for (const item of orderedVocab) {
        const key = extraCategoryKeyOf(item);
        if (key) anyCategory = true;
        const bucketKey = key || EXTRA_CATEGORY_ALL_KEY;
        if (!groupsByKey.has(bucketKey)) groupsByKey.set(bucketKey, []);
        groupsByKey.get(bucketKey).push(item);
    }

    // No entry carries a category yet → single "All Extra" group.
    let bucketEntries = Array.from(groupsByKey.entries());
    if (!anyCategory) {
        bucketEntries = [[EXTRA_CATEGORY_ALL_KEY, orderedVocab.slice()]];
    }

    // Deterministic group order: larger categories first, then by label. The
    // "All Extra" fallback always sits last if it somehow coexists with real
    // categories (e.g. some entries missing the field).
    bucketEntries.sort((a, b) => {
        const aAll = a[0] === EXTRA_CATEGORY_ALL_KEY;
        const bAll = b[0] === EXTRA_CATEGORY_ALL_KEY;
        if (aAll !== bAll) return aAll ? 1 : -1;
        const sizeDiff = b[1].length - a[1].length;
        if (sizeDiff !== 0) return sizeDiff;
        return extraCategoryLabelFor(a[0]).localeCompare(extraCategoryLabelFor(b[0]));
    });

    const groups = [];
    let cursor = 0;
    for (const [key, items] of bucketEntries) {
        if (items.length === 0) continue;
        const startRank = cursor + 1;
        for (const item of items) {
            cursor += 1;
            item.categoryRank = cursor;
            item.extraCategoryKey = key;
        }
        groups.push({
            key,
            label: extraCategoryLabelFor(key),
            startRank,
            endRank: cursor + 1, // exclusive, matches range-loader contract
            count: items.length,
        });
    }
    return groups;
}

// Ordered group metadata from the most recent Extra-scope buildFilteredVocab().
let _extraCategoryGroups = [];
const vocabularySourcesNeedingRestore = new WeakSet();
function getExtraCategoryGroups() {
    return _extraCategoryGroups.map(group => ({ ...group }));
}
window.getExtraCategoryGroups = getExtraCategoryGroups;

function _morphologyRows(item) {
    if (!item?.morphology) return [];
    return Array.isArray(item.morphology) ? item.morphology : [item.morphology];
}

function _foldSpanishForm(value) {
    return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/gu, '')
        .toLocaleLowerCase('es').trim();
}

function findSpuriousSelfInfinitives(vocabData) {
    const validConjugations = new Set();
    for (const item of vocabData) {
        const word = _foldSpanishForm(item?.word);
        const lemma = _foldSpanishForm(item?.lemma);
        if (!word || !lemma || word === lemma) continue;
        if (_morphologyRows(item).some(row => row?.mood && row.mood !== 'infinitivo')) {
            validConjugations.add(word);
        }
    }
    const rejected = new Set();
    for (const item of vocabData) {
        const word = _foldSpanishForm(item?.word);
        const lemma = _foldSpanishForm(item?.lemma);
        const hasVerb = (item?.meanings || []).some(meaning => meaning?.pos === 'VERB');
        const claimsInfinitive = _morphologyRows(item).some(row => row?.mood === 'infinitivo');
        const looksInfinitive = /(?:ar|er|ir)(?:se)?$/u.test(word);
        // Gap-fill senses can accidentally mint `quité|quité` beside the
        // authoritative `quité|quitar` analysis. Assembly then used to stamp
        // the self-lemma as an infinitive purely because word === lemma.
        // Suppress only when a valid same-surface conjugation is present.
        if (word && word === lemma && hasVerb && claimsInfinitive
            && !looksInfinitive && validConjugations.has(word)) {
            rejected.add(item);
        }
    }
    return rejected;
}

function assignStableVocabularyRanks(vocabData, spuriousSelfInfinitives = new Set()) {
    vocabData.forEach((item, index) => {
        item.rank = index + 1;
        if (item.cognate_score === undefined && item.is_transparent_cognate) {
            item.cognate_score = 1;
        }
    });
    const candidates = vocabData.filter(item => {
        if (!item.word || item.word.trim() === '' || item.duplicate || item.is_english
            || spuriousSelfInfinitives.has(item)) return false;
        if (!artistItemMatchesScope(item)) return false;
        const hasTranslation = Array.isArray(item.meanings)
            && item.meanings.some(meaning => meaning.translation && meaning.translation.trim());
        // Artist Extra deliberately includes raw lyric-only entries. A one-off
        // surface form inside a recurring lemma stays in Main and receives the
        // same fallback treatment, so it must also keep its stable slot.
        return hasTranslation || (activeArtist && (
            artistVocabularyScope === 'extra' || Number(item.corpus_count) <= 1
        ));
    });
    const hasCorpusFrequency = candidates.some(item => item.hasOwnProperty('corpus_count'));
    candidates.sort((a, b) => hasCorpusFrequency
        ? (((b.corpus_count || 0) - (a.corpus_count || 0)) || ((a.rank || 0) - (b.rank || 0)))
        : ((a.rank || 0) - (b.rank || 0)));
    candidates.forEach((item, index) => { item.stableRank = index + 1; });
    return candidates;
}

function getVocabularyExclusionReason(item) {
    if (!item || !item.word || item.duplicate) return 'unavailable entry';
    const meanings = Array.isArray(item.meanings)
        ? item.meanings.filter(meaning => String(meaning?.translation || '').trim())
        : [];
    if (activeArtist) {
        if (!artistItemMatchesScope(item)) {
            return artistVocabularyScope === 'extra' ? 'main artist vocabulary' : 'Artist Extra';
        }
        if (item.is_english) return 'English-language item';
        if (excludeNoise && (item.is_noise || item.is_interjection)) return 'noise or interjection';
        if (excludeEnglishLoanwords && item.is_english_loanword) return 'English loanword';
        if (excludeProperNouns) {
            const allProperNoun = meanings.length > 0
                && meanings.every(meaning => meaning.pos === 'PROPN');
            if (item.is_propernoun || item.is_propernoun_corpus || allProperNoun) {
                return 'proper noun';
            }
        }
    }
    if (excludeCognates && Number(item.cognate_score || 0) >= cognateThreshold) {
        return 'cognate';
    }
    if (useLemmaMode && lemmaFieldAvailable && item.most_frequent_lemma_instance !== true) {
        return 'merged lemma form';
    }
    return null;
}

function buildFilteredVocab(vocabData) {
    // Deck construction attaches examples and prunes senses in place. Restore
    // the joined master template only after a deck actually mutated it.
    // Setup calls this function several times; cloning every sense tree on
    // every pass was one of the largest avoidable mobile allocations.
    if (vocabularySourcesNeedingRestore.has(vocabData)) {
        for (const item of vocabData) {
            if (Array.isArray(item._base_meanings)) {
                item.meanings = item._base_meanings.map(meaning => ({
                    ...meaning,
                    examples: (meaning.examples || []).map(example => ({ ...example })),
                }));
                if (Array.isArray(item._base_extra_raw_examples)) {
                    item.extra_raw_examples = item._base_extra_raw_examples.map(example => ({ ...example }));
                } else {
                    delete item.extra_raw_examples;
                }
            }
        }
        vocabularySourcesNeedingRestore.delete(vocabData);
    }
    const spuriousSelfInfinitives = findSpuriousSelfInfinitives(vocabData);
    // Assign stable rank from array position (pipeline sort order)
    const stableBaseline = assignStableVocabularyRanks(vocabData, spuriousSelfInfinitives);

    // Single-pass filter combining: basic validity → POS=X placeholder
    // strip → artist scope → artist-mode flags → cognates → lemma mode.
    // Order is preserved so counts reflect what the chained .filter() calls
    // used to produce (e.g. an item failing both artist and cognate is
    // counted under "english" only, since the artist check ran first).
    const counts = { english: 0, cognates: 0, singleOcc: 0, lemma: 0 };
    const hasCorpusFrequency = vocabData.length > 0
        && vocabData[0].hasOwnProperty('corpus_count');
    const result = [];
    for (const item of vocabData) {
        if (!item.word || item.word.trim() === '' || item.duplicate
            || spuriousSelfInfinitives.has(item)) continue;
        if (!artistItemMatchesScope(item)) {
            counts.singleOcc++;
            continue;
        }
        const allowsRawArtistCard = activeArtist && (
            artistVocabularyScope === 'extra' || Number(item.corpus_count) <= 1
        );
        if ((!item.meanings || item.meanings.length === 0) && !allowsRawArtistCard) continue;
        // Strip any meaning with no translation (POS=X placeholders from
        // --no-gemini runs, plus SpanishDict rows that captured a usage label
        // but an empty gloss). Mutates the item, matching prior behavior.
        item.meanings = (item.meanings || []).filter(m => m.translation && m.translation.trim());
        if (item.meanings.length === 0 && !allowsRawArtistCard) continue;
        // Artist Extra deliberately KEEPS the over-tagged words (English,
        // loanwords, proper nouns, noise) instead of dropping them, so they
        // surface grouped by their `extra_category` rather than vanishing.
        // Main scope is unchanged — it still drops them so it stays clean.
        const isExtraScope = activeArtist && artistVocabularyScope === 'extra';
        if (activeArtist && !isExtraScope) {
            // English borrowings — always filtered (no toggle; they're not
            // Spanish words at all and have no Spanish meaning to teach).
            if (item.is_english) {
                counts.english++;
                continue;
            }
            // Noise / interjections (single-letter "y", filler "uh", "yeah").
            // Toggleable via excludeNoise in Advanced settings.
            if (excludeNoise && (item.is_noise || item.is_interjection)) {
                counts.english++;
                continue;
            }
            // English loanwords / code-switches (hey, baby, shot, panty),
            // flagged from Wiktionary etymology. Toggleable via
            // excludeEnglishLoanwords in Advanced settings.
            if (excludeEnglishLoanwords && item.is_english_loanword) {
                counts.english++;
                continue;
            }
            // Proper nouns — three signals, any one is sufficient:
            //   1. `is_propernoun` — pipeline-stamped from step_4a curation
            //      (Wiktionary-only-name + manual proper_nouns.json drops).
            //   2. `is_propernoun_corpus` — corpus capitalization rate ≥
            //      threshold, stamped by tool_8a_stamp_propernoun_corpus.py.
            //      Catches frequent proper nouns Wiktionary/curation miss
            //      (Bunny, Mercedes, Dios, LeBron, …).
            //   3. Runtime POS=PROPN bridge — every meaning POS-tagged as
            //      PROPN by Gemini. Kept for backwards-compat with vocab
            //      builds that haven't been corpus-stamped yet.
            if (excludeProperNouns) {
                const allPropn = item.meanings.length > 0 && item.meanings.every(m => m.pos === 'PROPN');
                if (item.is_propernoun || item.is_propernoun_corpus || allPropn) {
                    counts.english++;
                    continue;
                }
            }
            // Setup and deck construction must agree on whether an artist
            // card exists. Multi-occurrence rows with no assigned artist
            // sense are discarded later after examples attach; discard them
            // here too so they never appear as phantom new cards in a set.
            const hasAssignedArtistSense = item.meanings.some(meaning =>
                Number(meaning.frequency || 0) >= ARTIST_MIN_SENSE_FREQ);
            if (Number(item.corpus_count) > 1 && !hasAssignedArtistSense) {
                counts.singleOcc++;
                continue;
            }
        }
        // Cognates: dropped in Main/normal per the toggle, but KEPT in Extra so
        // they populate the Cognates category (the toggle is hidden there and
        // only decides which group cognates land in, not deck inclusion).
        if (!isExtraScope && excludeCognates && cognateFieldAvailable && item.cognate_score >= cognateThreshold) {
            counts.cognates++;
            continue;
        }
        if (useLemmaMode && lemmaFieldAvailable && item.most_frequent_lemma_instance !== true) {
            counts.lemma++;
            continue;
        }
        result.push(item);
    }

    // In lemma mode, pool each surviving representative's frequency across all
    // its collapsed sibling forms (same lemma) and order the deck by that total,
    // so the most common LEMMAS surface first — mirrors the example pooling in
    // poolLemmaSiblingExamples.
    if (useLemmaMode && lemmaFieldAvailable) {
        // A merged lemma lives wherever its highest-frequency surface form
        // lived in the baseline deck. This is the stable anchor that keeps
        // Merge Lemmas from moving the card to a different level or set.
        const lemmaStableRanks = new Map();
        for (const entry of vocabData) {
            if (!entry.lemma || !Number.isFinite(entry.stableRank)) continue;
            const previous = lemmaStableRanks.get(entry.lemma);
            if (previous === undefined || entry.stableRank < previous) {
                lemmaStableRanks.set(entry.lemma, entry.stableRank);
            }
        }
        const lemmaTotals = new Map();
        for (const e of vocabData) {
            if (!e.lemma || e.is_english || e.is_noise || e.is_interjection || e.duplicate) continue;
            lemmaTotals.set(e.lemma, (lemmaTotals.get(e.lemma) || 0) + (e.corpus_count || 0));
        }
        const exampleBasis = computeLemmaExampleCounts(vocabData, window._cachedExamplesData);
        for (const item of result) {
            item.stableRank = lemmaStableRanks.get(item.lemma) || item.stableRank;
            item.lemma_total_count = lemmaTotals.get(item.lemma) || item.corpus_count || 0;
            // The pipeline stamp includes raw one-off lyric evidence that may
            // intentionally have no assigned sense and therefore no `m`
            // bucket. Never erase it with the smaller assigned-example count.
            item.lemma_example_count = Math.max(
                artistLemmaEvidenceCount(item),
                exampleBasis.counts.get(item.lemma) || 0
            );
            item.pooled_frequency = exampleBasis.hasExampleBasis
                ? item.lemma_example_count
                : item.lemma_total_count;
        }
        result.sort((a, b) => (b.pooled_frequency || 0) - (a.pooled_frequency || 0));
    } else if (percentageMode && hasCorpusFrequency) {
        // Artist indexes are usually frequency-sorted, but that is not a safe
        // contract (the current Young Miko index has dozens of upward jumps).
        // Percentage mode's scrubber and deck must share a genuinely
        // frequency-descending order. Preserve item.rank as the source ID and
        // use it as the stable tie-breaker.
        result.sort((a, b) =>
            ((b.corpus_count || 0) - (a.corpus_count || 0))
            || ((a.rank || 0) - (b.rank || 0)));
    }

    // Assign corpus-wide display ranks so set numbering is continuous across levels
    result.forEach((item, idx) => { item.displayRank = idx + 1; });

    // Artist Extra is grouped by category rather than frequency levels. Stamp
    // the contiguous per-category rank now so setup and deck-build slice on the
    // same basis. Main scope (and normal mode) leave categoryRank untouched.
    if (activeArtist && artistVocabularyScope === 'extra') {
        _extraCategoryGroups = assignExtraCategoryRanks(result);
    } else {
        _extraCategoryGroups = [];
    }

    return { vocab: result, counts, stableBaseline };
}

async function loadVocabularyData(rangeString, opts = {}) {
    // Deck construction mutates the selected entries while attaching examples
    // and trimming artist senses. Force setup to rebuild its immutable view
    // when the learner returns to the menu.
    window.invalidatePreparedSetupVocabulary?.();
    const includeWordId = opts.includeWordId || null;
    let studyMode = opts.resumeSnapshot ? 'resume' : (opts.studyMode || 'new');
    // Completely clear all previous data and state
    flashcards = [];
    stats = {
        studied: new Set(),
        correct: 0,
        incorrect: 0,
        total: 0,
        cardStats: {},
        setSize: 0,
        previouslyKnown: 0,
        setLabel: '',
        rangeString: '',
        rangeBasis: opts.rankBasis || opts.resumeSnapshot?.rangeBasis || 'display',
        setNumber: opts.setNumber || opts.resumeSnapshot?.setNumber || null,
        levelSetCount: opts.levelSetCount || opts.resumeSnapshot?.levelSetCount || null,
        nextRange: null,
        nextSetNumber: null,
        nextRankBasis: 'display',
        studyMode,
        levelNumber: opts.levelNumber || opts.resumeSnapshot?.levelNumber || null,
        allWords: []
    };
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
    const rangeBasis = opts.rankBasis || opts.resumeSnapshot?.rangeBasis || 'display';

    // Use lightweight index for filtering when available
    const indexPath = langConfig.indexPath || langConfig.dataPath;

    try {
        // Single/multi-artist selection shares one source so setup ranges and
        // the committed deck see identical merged entries and examples.
        const vocabularyData = await fetchActiveVocabularyData(langConfig);
        // Derived from the data we already hold, so it costs nothing to keep
        // current on every deck build. It used to be recomputed only for
        // resume snapshots, which left it at its `false` default on any route
        // that skipped the setup panel (Continue set, direct deck start). A
        // false flag silently disables Merge Lemmas while the toggle still
        // reads "on": buildCardFormModel gets mergedLemma: false, so the card
        // keeps its surface form and the front falls through to the unmerged
        // variant list — every recorded spelling of the word.
        lemmaFieldAvailable = vocabularyData.some(item => item.hasOwnProperty('most_frequent_lemma_instance'));
        cognateFieldAvailable = vocabularyData.some(item =>
            (item.cognate_score > 0) || item.cognet_cognate || item.is_transparent_cognate
        );
        if (useLemmaMode) await ensureLemmaPoolingData(langConfig);
        cachedVocabularyData = vocabularyData;

        // Store original index/rank from vocabulary file - this is the unique identifier
        vocabularyData.forEach((item, index) => {
            item.rank = index + 1; // Use original position as the rank (unique identifier)
        });

        const { vocab: _baseVocab, counts: exCounts } = buildFilteredVocab(vocabularyData);
        // This is the complete vocabulary after the active source + filter
        // configuration, before level, set, and mastery slicing. Card rank
        // metadata must use this same basis so it remains stable when the
        // active set is shuffled or previously-known cards are omitted.
        const configurationVocabSize = _baseVocab.length;
        let filteredData = _baseVocab;
        const excludedEnglish = exCounts.english;
        const excludedCognates = exCounts.cognates;
        const excludedSingleOcc = exCounts.singleOcc;
        const excludedLemma = exCounts.lemma;
        let excludedMastered = 0;

        // Exact resume owns deck membership and order. This deliberately
        // bypasses the current mastery filter: a card answered just before
        // closing must still exist when the same session is continued. Match
        // IDs against the full configured vocabulary, not today's saved rank
        // range, because a refreshed corpus may move those cards across a
        // level boundary while their stable IDs remain valid.
        const resumeSnapshot = opts.resumeSnapshot || null;
        let totalInRange;
        let allInRange;
        if (resumeSnapshot?.order?.length) {
            const orderIndex = new Map(resumeSnapshot.order.map((id, index) => [id, index]));
            filteredData = filteredData
                .filter(item => orderIndex.has(getWordId(item)))
                .sort((a, b) => orderIndex.get(getWordId(a)) - orderIndex.get(getWordId(b)));
            totalInRange = resumeSnapshot.setSize || filteredData.length;
            allInRange = filteredData.slice();
        } else {
            // New stable sets slice on the pre-filter baseline rank. Legacy
            // sessions retain display-rank slicing so saved sessions remain
            // resumable across the UI migration.
            filteredData = filteredData.filter(item => {
                const rangeRank = rangeBasis === 'category' ? item.categoryRank
                    : rangeBasis === 'stable' ? item.stableRank
                    : item.displayRank;
                return rangeRank >= rangeStart && rangeRank < rangeEnd;
            });
            totalInRange = filteredData.length;
            allInRange = filteredData.slice(); // preserve for "study anyway"

            // Ordinary set study contains genuinely unseen cards only. A
            // wrong or partial answer therefore advances the new-card track
            // and enters the separate review queue instead of trapping this
            // set as unfinished. Review is current-source/current-settings and
            // current-level scoped because _baseVocab and the range slice
            // have already established those boundaries.
            if (currentUser && !currentUser.isGuest && progressData) {
                const beforeFiltered = filteredData.length;
                const estimate = levelEstimates[selectedLanguage] || 0;
                const estimatedIds = activeArtist && studyMode === 'new'
                    ? await buildEstimatedKnownIds(estimate)
                    : null;
                const seenLemmas = studyMode === 'new'
                    ? await buildSeenLemmaSet(vocabularyData)
                    : new Set();

                filteredData = filteredData.filter(item => {
                    // Never filter out a word the caller explicitly asked to
                    // include (for example a search jump target).
                    const itemId = getWordId(item);
                    if (includeWordId && (itemId === includeWordId || item.id === includeWordId)) {
                        return true;
                    }
                    const hasRelatedProgress = hasRelatedWordProgress(itemId);
                    if (studyMode === 'review') return relatedWordNeedsReview(itemId);
                    if (studyMode === 'all') return true;

                    const coveredByEstimate = !hasRelatedProgress && (activeArtist
                        ? (item.id && estimatedIds?.has(item.id))
                        : item.rank <= estimate);
                    return !coveredByEstimate
                        && !hasRelatedProgress
                        && !seenLemmas.has(item.lemma);
                });
                excludedMastered = beforeFiltered - filteredData.length;
                if (studyMode === 'review') {
                    filteredData.sort((a, b) => {
                        const aReview = getWordKnowledgeReviewInfo(getWordId(a));
                        const bReview = getWordKnowledgeReviewInfo(getWordId(b));
                        return (aReview.reviewAt - bReview.reviewAt)
                            || ((a.displayRank || a.rank || 0) - (b.displayRank || b.rank || 0));
                    });
                }
                if (excludedMastered > 0) {
                    console.log(`Filtered out ${excludedMastered} cards outside ${studyMode} mode`);
                }
            }
        }

        // Resolve an empty selection before attaching examples and building
        // cards. A newly-completed advertised set falls back to the same deck
        // as an explicit "Study Again" tap; genuinely empty ranges still stop.
        if (filteredData.length === 0 && studyMode === 'new' && allInRange.length > 0) {
            // A background progress refresh can finish after the set controls
            // render. If every advertised "new" card became seen meanwhile,
            // honour the learner's attempt to open the set by falling back to
            // the existing Study Again behavior instead of showing a dead-end
            // completion alert.
            filteredData = allInRange.slice();
            studyMode = 'all';
            stats.studyMode = 'all';
            excludedMastered = 0;
        }
        if (filteredData.length === 0) {
            const emptyMessage = studyMode === 'review'
                ? 'No cards need review in this level with the current settings.'
                : 'No unseen flashcards remain in this set with the current settings.';
            alert(emptyMessage);
            document.getElementById('loadingMessage').style.display = 'none';
            return;
        }

        // Everything below may attach examples, pool lemma siblings, or prune
        // the artist sense menu. The next setup/filter pass will restore the
        // canonical joined template once; repeated setup passes before then
        // remain allocation-free.
        if (vocabularyData.some(item => Array.isArray(item._base_meanings))) {
            vocabularySourcesNeedingRestore.add(vocabularyData);
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
                    trackDataFreshness(exResponse);
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
                            // ex.m is indexed against the master sense order;
                            // honor the explicit source index so future sense
                            // filtering cannot make the arrays drift apart.
                            const bucket = m._masterSenseIndex ?? i;
                            m.examples = ex.m[bucket] || [];
                        });
                    }
                    if (ex && ex.w && item.mwe_memberships) {
                        item.mwe_memberships.forEach((mwe, i) => {
                            mwe.examples = ex.w[i] || [];
                        });
                    }
                    if (ex && ex.c && item.clitic_memberships) {
                        item.clitic_memberships.forEach((clitic, i) => {
                            clitic.examples = ex.c[i] || [];
                        });
                    }
                    if (ex && ex.s && item.sense_cycles) {
                        item.sense_cycles.forEach((sc, i) => {
                            sc.examples = ex.s[i] || [];
                        });
                    }
                    if (ex) mergeArtistExtraSupport(item, ex);
                }
                // MWE examples are pre-computed by the pipeline and stored in the "w"
                // field of the examples file. No need to build a corpus pool here.
            }
        } else {
            // Fallback: monolith path — examples are inline in vocabularyData
        }

        // Lemma mode: dropped sibling forms contribute their example lines to
        // the surviving one-card-per-lemma card (deduped inside the helper).
        if (useLemmaMode && lemmaFieldAvailable) {
            poolLemmaSiblingExamples(filteredData, vocabularyData, window._cachedExamplesData);
        }

        // Artist mode: filter sense pills for cleaner display.
        // Must happen AFTER examples are attached (above) so positional indices are correct,
        // but BEFORE card building (below) so cards only show relevant senses.
        if (activeArtist) {
            const MAX_SENSES = 6;
            for (const item of filteredData) {
                const artistMeanings = item.meanings.filter(m =>
                    !m.shared_fallback && parseFloat(m.frequency) >= ARTIST_MIN_SENSE_FREQ);
                const supportedFallbacks = item.meanings.filter(m =>
                    m.shared_fallback && Array.isArray(m.examples) && m.examples.length > 0);
                if (artistVocabularyScope === 'extra') {
                    // Extra may have no artist-side assignment at all. Prefer
                    // shared senses that carry Speech evidence, then retain a
                    // small dictionary menu even when only the lyric exists.
                    item.meanings = artistMeanings.length > 0
                        ? artistMeanings
                        : (supportedFallbacks.length > 0
                            ? supportedFallbacks
                            : item.meanings.filter(m => m.translation).slice(0, MAX_SENSES));
                } else {
                    // Main normally retains the existing artist-assigned
                    // menu. A one-off surface form inside a recurring lemma
                    // is allowed to use its shared Speech support instead.
                    item.meanings = artistMeanings.length > 0
                        ? artistMeanings
                        : (Number(item.corpus_count) <= 1 ? supportedFallbacks : []);
                }
                // Hard cap: keep top N by frequency
                if (item.meanings.length > MAX_SENSES) {
                    item.meanings.sort((a, b) => parseFloat(b.frequency) - parseFloat(a.frequency));
                    item.meanings = item.meanings.slice(0, MAX_SENSES);
                }
            }
            filteredData = filteredData.filter(item =>
                item.meanings.length > 0
                || (item.extra_raw_examples?.length && (
                    artistVocabularyScope === 'extra' || Number(item.corpus_count) <= 1
                )));
        }

        for (const item of filteredData) {
            const meanings = item.meanings.map(m => {
                const { targetSentence, englishSentence, allExamples } = getExampleFromMeaning(m, exampleTargetField, exampleEnglishField);
                const meaning = {
                    pos: m.pos,
                    meaning: m.translation,
                    percentage: parseFloat(m.frequency),
                    targetSentence,
                    englishSentence,
                    allExamples
                };
                if (m.unassigned) meaning.unassigned = true;
                if (m.assignment_method) meaning.assignment_method = m.assignment_method;
                if (m.prompt_id) meaning.prompt_id = m.prompt_id;
                if (m.run_ts) meaning.run_ts = m.run_ts;
                if (m.source) meaning.source = m.source;
                if (m.sense_id || m.id) meaning.senseId = m.sense_id || m.id;
                if (m.sense_id_aliases?.length) meaning.senseIdAliases = m.sense_id_aliases;
                if (m.context) meaning.context = m.context;
                if (m.type) meaning.type = m.type;
                if (m.allSenses) meaning.allSenses = m.allSenses;
                if (m.cycle_pos) meaning.cycle_pos = m.cycle_pos;
                if (m.shared_fallback) meaning.sharedFallback = true;
                return meaning;
            });

            if (meanings.length === 0 && item.extra_raw_examples?.length) {
                const first = item.extra_raw_examples[0];
                meanings.push({
                    pos: 'EXAMPLE_ONLY',
                    meaning: '',
                    percentage: 1,
                    targetSentence: first.target || first.spanish || '',
                    englishSentence: first.english || '',
                    allExamples: item.extra_raw_examples,
                    exampleOnly: true,
                    unassigned: true,
                });
            }

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
                // Sort artist-sourced MWEs first (including artist-curated /
                // artist-pmi tags from step_2a lyric counting), then shared
                // sources (spanishdict / wiktionary / legacy).
                const sortedMWEs = [...item.mwe_memberships].sort((a, b) => {
                    const aSrc = a.source || 'artist';
                    const bSrc = b.source || 'artist';
                    const aArtist = aSrc === 'artist' || aSrc.startsWith('artist-') ? 0 : 1;
                    const bArtist = bSrc === 'artist' || bSrc.startsWith('artist-') ? 0 : 1;
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
                        id: mwe.id || null,
                        expression: mwe.expression,
                        translation: mwe.translation || '',
                        family: mwe.family || '',
                        variants: mwe.variants || null,
                        variantCounts: mwe.variant_counts || null,
                        corpusCount: Number(mwe.count) || 0,
                        occurrenceCount: Number(mwe.occurrence_count) || 0,
                        songCount: Number(mwe.num_songs) || 0,
                        // Two context tiers:
                        //   context           — real/scraped (authoritative)
                        //   context_heuristic — regex-split from quickdef
                        // Renderer prefers real over heuristic.
                        context: mwe.context || '',
                        context_heuristic: mwe.context_heuristic || '',
                        // Build-time provenance (wiktionary / spanishdict /
                        // artist-*). Empty for decks assembled before the
                        // stamp existed; the renderer shows no pill then.
                        source: mwe.source || '',
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
                        examples: matched
                    });
                }
                allClitics.sort((a, b) => b.corpus_count - a.corpus_count);
                const firstEx = allClitics[0].examples[0] || { spanish: '', english: '' };
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

            // Synthesize SENSE_CYCLE meanings (unassigned senses grouped by POS)
            if (item.sense_cycles && item.sense_cycles.length > 0) {
                for (const sc of item.sense_cycles) {
                    const scExamples = sc.examples || [];
                    const firstEx = scExamples[0] || { spanish: '', english: '' };
                    const meaning = {
                        pos: sc.pos === 'SENSE_CYCLE' ? 'SENSE_CYCLE' : sc.pos,
                        meaning: sc.translation || '',
                        percentage: 0,
                        unassigned: true,
                        targetSentence: firstEx.spanish || firstEx.target || '',
                        englishSentence: firstEx.english || '',
                        allExamples: scExamples
                    };
                    if (sc.allSenses && sc.allSenses.length > 0) {
                        meaning.allSenses = sc.allSenses;
                        meaning.cycle_pos = sc.cycle_pos || sc.pos;
                    }
                    meanings.push(meaning);
                }
            }

            // Sort meanings: frequency senses first, then SENSE_CYCLE, CLITIC, MWE
            const specialOrder = { 'SENSE_CYCLE': 1, 'CLITIC': 2, 'MWE': 3 };
            meanings.sort((a, b) => {
                const aOrder = specialOrder[a.pos] || 0;
                const bOrder = specialOrder[b.pos] || 0;
                if (aOrder !== bOrder) return aOrder - bOrder;
                return (b.percentage || 0) - (a.percentage || 0);
            });

            const firstExample = meanings.length > 0
                ? {
                    targetSentence: meanings[0].targetSentence || '',
                    englishSentence: meanings[0].englishSentence || '',
                }
                : { targetSentence: '', englishSentence: '' };
            const cardForm = buildCardFormModel(item, meanings, {
                mergedLemma: useLemmaMode && lemmaFieldAvailable
            });
            const card = {
                targetWord: item.word,
                lemma: item.lemma || '',
                ...cardForm,
                id: item.id,
                fullId: getWordId(item),
                rank: item.rank,
                vocabularyRank: item.displayRank,
                vocabularySize: configurationVocabSize,
                // Lemma mode uses the same unique pooled example-line basis
                // as the examples attached above. Raw token totals stay on
                // item.lemma_total_count for diagnostics only.
                corpusCount: artistVocabularyScope === 'extra'
                    ? (item.lemma_example_count || item.corpus_count || null)
                    : (useLemmaMode
                        ? (item.pooled_frequency ?? item.lemma_example_count ?? null)
                        : (item.corpus_count || null)),
                meanings: meanings,
                translation: meanings[0]?.meaning || '',
                targetSentence: firstExample.targetSentence,
                englishSentence: firstExample.englishSentence,
                links: generateLinks(
                    cardForm.displaySurface || item.word,
                    cardForm.citationForm || item.lemma || item.word,
                    langConfig.referenceLinks
                ),
                isMultiMeaning: true,
                variants: item.variants || null,
                homographIds: item.homograph_ids || null,
                morphology: item.morphology || null,
                synonyms: item.synonyms || null,
                antonyms: item.antonyms || null,
                // SpanishDict's morphological pointer (e.g. hay → haber).
                // Set when the word's semantic lemma is lexicalised but
                // SD also flags it as a conjugation of some verb. The
                // conjugation panel uses this as a fallback when the
                // card's own lemma has no inline paradigm.
                relatedLemma: item.related_lemma || null,
                derivationRelation: item.derivation_relation || null
            };
            // Retain routing diagnostics on the study card so a one-tap
            // classification report can state both the requested correction
            // and what the current pipeline actually stamped.
            card.is_english = item.is_english ?? null;
            card.is_english_loanword = item.is_english_loanword ?? null;
            card.cognate_score = item.cognate_score ?? null;
            card.translationUnavailable = meanings.every(meaning => !String(meaning.meaning || '').trim());
            card.artistVocabularyScope = activeArtist ? artistVocabularyScope : null;
            const deckCard = studyMode === 'review' ? buildFocusedReviewCard(card) : card;
            if (deckCard) flashcards.push(deckCard);
        }

        if (flashcards.length === 0) {
            alert(studyMode === 'review'
                ? 'No current meanings or expressions remain in this review.'
                : 'No flashcards could be built for this set.');
            document.getElementById('loadingMessage').style.display = 'none';
            return;
        }

        // New-card decks report how many cards in the stable set were already
        // seen. Review decks report the queue itself, not every card in the
        // containing level.
        stats.setSize = studyMode === 'review' ? flashcards.length : totalInRange;
        stats.previouslyKnown = studyMode === 'new' ? excludedMastered : 0;
        if (resumeSnapshot) {
            stats.setSize = resumeSnapshot.setSize || resumeSnapshot.order.length;
            stats.previouslyKnown = resumeSnapshot.previouslyKnown || 0;
        }
        stats.rangeString = rangeString;
        stats.rangeBasis = rangeBasis;
        stats.setNumber = opts.setNumber || resumeSnapshot?.setNumber || null;
        stats.levelSetCount = opts.levelSetCount || resumeSnapshot?.levelSetCount || null;
        stats.studyMode = resumeSnapshot?.studyMode || studyMode;
        stats.levelNumber = opts.levelNumber || resumeSnapshot?.levelNumber || stats.levelNumber || null;
        const nextSet = stats.studyMode === 'new' && window.getNextStudySetMeta
            ? window.getNextStudySetMeta(rangeString)
            : null;
        stats.nextRange = nextSet?.range || null;
        stats.nextSetNumber = nextSet?.setNumber || null;
        stats.nextRankBasis = nextSet?.rankBasis || rangeBasis;
        // Inclusive label for display, e.g. "475-499" for rangeString "475-500"
        // (rangeEnd is exclusive in the filter above).
        const rankLabel = `${rangeStart}-${rangeEnd - 1}`;
        stats.setLabel = stats.studyMode === 'review'
            ? `Level ${stats.levelNumber || ''} review · ranks ${rankLabel}`.replace('Level  review', 'Level review')
            : stats.setNumber
            ? `Set ${stats.setNumber}${stats.levelSetCount ? `/${stats.levelSetCount}` : ''} · ranks ${rankLabel}`
            : rankLabel;
        const statsWords = stats.studyMode === 'review' ? filteredData : allInRange;
        stats.allWords = statsWords.map(it => ({
            id: it.id,
            word: it.word,
            translation: (it.meanings && it.meanings[0] && it.meanings[0].translation) || '',
            displayRank: it.displayRank
        }));

        // Build exclusion summary message (only report in-range exclusions)
        const totalExcluded = excludedLemma + (studyMode === 'new' ? excludedMastered : 0);
        const loadingMsg = document.getElementById('loadingMessage');
        if (totalExcluded > 0) {
            const parts = [];
            if (excludedLemma > 0) parts.push(`${excludedLemma} lemma dup${excludedLemma > 1 ? 's' : ''}`);
            if (studyMode === 'new' && excludedMastered > 0) parts.push(`${excludedMastered} already seen`);
            loadingMsg.textContent = `✓ ${flashcards.length} cards from ${totalInRange} (${parts.join(', ')} excluded)`;
        } else {
            loadingMsg.textContent = `✓ ${flashcards.length} cards`;
        }
        loadingMsg.style.display = 'block';

        // Swap the completed deck into view immediately. Callers that need a
        // transition keep the app-level loading screen above this atomic DOM
        // update, so the previous card never flashes between sets.
        await new Promise(resolve => requestAnimationFrame(resolve));
        document.getElementById('setupPanel').classList.add('hidden');
        document.getElementById('appContent').classList.remove('hidden');
        loadingMsg.style.display = 'none';

        // Show mobile floating buttons
        showFloatingBtns(true);

        if (resumeSnapshot) {
            let resumeIndex = flashcards.findIndex(card => card.fullId === resumeSnapshot.currentFullId);
            if (resumeIndex < 0 && Number.isFinite(Number(resumeSnapshot.currentVocabularyRank))) {
                const targetRank = Number(resumeSnapshot.currentVocabularyRank);
                resumeIndex = flashcards.reduce((best, card, index) => {
                    const distance = Math.abs(Number(card.vocabularyRank || card.rank) - targetRank);
                    return distance < best.distance ? { index, distance } : best;
                }, { index: 0, distance: Infinity }).index;
            }
            currentIndex = Math.max(0, resumeIndex);
            const resumedCard = flashcards[currentIndex];
            const maxMeaningIndex = Math.max(0, (resumedCard?.meanings?.length || 1) - 1);
            currentMeaningIndex = Math.min(
                maxMeaningIndex,
                Math.max(0, resumeSnapshot.currentMeaningIndex || 0)
            );
            currentExampleIndex = Math.max(0, resumeSnapshot.currentExampleIndex || 0);
            currentMWEIndex = Math.max(0, resumeSnapshot.currentMWEIndex || 0);
            isFlipped = !!resumeSnapshot.directionFlipped;
            if (typeof resumeSnapshot.speechEnabled === 'boolean') {
                speechEnabled = resumeSnapshot.speechEnabled;
            }
        }

        // Initialize card display
        initializeApp();
        window.updateSpeakIcons?.();
        if (resumeSnapshot?.cardFaceFlipped) flashcardEl?.classList.add('flipped');
        else flashcardEl?.classList.remove('flipped');
        saveStudySessionSnapshot();
        buildWordLookupMap();
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


// Build the unresolved-mistake queue from the active vocabulary and the
// selected level. The ordinary loader owns source/settings filtering and card
// construction, keeping review behavior identical to Learn new.
async function loadLevelReviewSet(rangeString, opts = {}) {
    if (!currentUser || currentUser.isGuest) {
        alert('Please log in to review previous mistakes.');
        return;
    }
    return loadVocabularyData(rangeString, {
        ...opts,
        studyMode: 'review',
        setNumber: null,
        levelSetCount: null
    });
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
            trackDataFreshness(response);
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
                ...buildCardFormModel(group, group.meanings),
                rank: group.rank,
                meanings: group.meanings,
                // For compatibility, set primary translation to most common meaning
                translation: group.meanings[0].meaning,
                targetSentence: group.meanings[0].targetSentence,
                englishSentence: group.meanings[0].englishSentence,
                links: generateLinks(group.word, group.lemma || group.word, langConfig.referenceLinks),
                isMultiMeaning: true,
                variants: group.variants || null,
                morphology: group.morphology || null,
                synonyms: group.synonyms || null,
                antonyms: group.antonyms || null
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
    const combinedLemmaCounts = new Map();

    for (const cfg of artistConfigs) {
        // Load lightweight index for word metadata
        const indexPath = cfg.indexPath || cfg.dataPath;
        let indexData;
        try {
            const resp = await fetch(indexPath);
            trackDataFreshness(resp);
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

        // Every surface entry in an artist carries the same pooled count for
        // its lemma. Add that count once per artist, not once per form.
        const thisArtistLemmaCounts = new Map();
        for (const entry of indexData) {
            if (!entry.lemma) continue;
            thisArtistLemmaCounts.set(
                entry.lemma,
                Math.max(
                    thisArtistLemmaCounts.get(entry.lemma) || 0,
                    artistLemmaEvidenceCount(entry)
                )
            );
        }
        for (const [lemma, count] of thisArtistLemmaCounts) {
            combinedLemmaCounts.set(lemma, (combinedLemmaCounts.get(lemma) || 0) + count);
        }

        // Load separate examples file
        let examplesData = null;
        if (cfg.examplesPath) {
            try {
                const resp = await fetch(cfg.examplesPath);
                trackDataFreshness(resp);
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
                        const bucket = m._masterSenseIndex ?? i;
                        m.examples = ex.m[bucket] || [];
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
                if (ex.s && entry.sense_cycles) {
                    entry.sense_cycles.forEach((sc, i) => {
                        sc.examples = ex.s[i] || [];
                    });
                }
                mergeArtistExtraSupport(entry, ex);
            }

            if (byId.has(id)) {
                // Merge into an existing entry. Master-based senses retain
                // their stable source index across artists.
                const existing = byId.get(id);
                existing.corpus_count = (existing.corpus_count || 0) + (entry.corpus_count || 0);

                if (master && isNewFormat) {
                    // Merge on the preserved master-sense index rather than
                    // trusting whatever filtering a caller may later apply.
                    if (entry.meanings) {
                        const byMasterSense = new Map(existing.meanings.map((m, i) => [m._masterSenseIndex ?? i, m]));
                        entry.meanings.forEach((newM, i) => {
                            const masterSenseIndex = newM._masterSenseIndex ?? i;
                            const existingM = byMasterSense.get(masterSenseIndex);
                            if (existingM) {
                                existingM.examples = (existingM.examples || []).concat(tagExamples(newM.examples || []));
                                // Any assigned observation outweighs an
                                // unassigned bucket from another artist.
                                if (!newM.unassigned) delete existingM.unassigned;
                                if (!existingM.assignment_method && newM.assignment_method) {
                                    existingM.assignment_method = newM.assignment_method;
                                }
                                // Register tags come from the shared master, so
                                // whichever artist carries one is authoritative.
                                if (!existingM.type && newM.type) existingM.type = newM.type;
                                // Carry provenance from whichever artist first
                                // classified this shared master sense.
                                if (!existingM.prompt_id && newM.prompt_id) {
                                    existingM.prompt_id = newM.prompt_id;
                                    if (newM.run_ts) existingM.run_ts = newM.run_ts;
                                }
                            } else {
                                const added = structuredClone(newM);
                                added.examples = tagExamples(added.examples || []);
                                existing.meanings.push(added);
                                byMasterSense.set(masterSenseIndex, added);
                            }
                        });
                        existing.meanings.sort((a, b) =>
                            (a._masterSenseIndex ?? 0) - (b._masterSenseIndex ?? 0));
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
                if (entry.extra_raw_examples?.length) {
                    existing.extra_raw_examples = (existing.extra_raw_examples || [])
                        .concat(tagExamples(entry.extra_raw_examples));
                }
                if (entry.clitic_memberships?.length) {
                    const existingByForm = new Map((existing.clitic_memberships || [])
                        .map(clitic => [String(clitic.form || '').toLocaleLowerCase('es'), clitic]));
                    for (const incoming of entry.clitic_memberships) {
                        const key = String(incoming.form || '').toLocaleLowerCase('es');
                        const current = existingByForm.get(key);
                        if (current) {
                            current.corpus_count = Number(current.corpus_count || 0)
                                + Number(incoming.corpus_count || 0);
                            current.examples = (current.examples || [])
                                .concat(tagExamples(incoming.examples || []));
                        } else {
                            const added = structuredClone(incoming);
                            added.examples = tagExamples(added.examples || []);
                            if (!existing.clitic_memberships) existing.clitic_memberships = [];
                            existing.clitic_memberships.push(added);
                            existingByForm.set(key, added);
                        }
                    }
                }
            } else {
                // First time seeing this word — clone and tag.
                // structuredClone is the native deep-clone primitive; ~2-3×
                // faster than JSON round-trip on the entry shapes here and
                // doesn't lose `undefined` values or non-JSON types.
                const clone = structuredClone(entry);
                if (clone.meanings) {
                    for (const m of clone.meanings) {
                        if (m.examples) m.examples = tagExamples(m.examples);
                    }
                }
                if (clone.extra_raw_examples) {
                    clone.extra_raw_examples = tagExamples(clone.extra_raw_examples);
                }
                for (const clitic of (clone.clitic_memberships || [])) {
                    clitic.examples = tagExamples(clitic.examples || []);
                }
                byId.set(id, clone);
            }

        }
    }

    // Recalculate sense frequency from the same unique example lines the UI
    // cycles through. This also removes duplicate cross-artist/collab lines.
    for (const entry of byId.values()) {
        entry.lemma_example_count = combinedLemmaCounts.get(entry.lemma)
            || entry.lemma_example_count
            || entry.corpus_count
            || 0;
        for (const meaning of (entry.meanings || [])) {
            const seen = new Set();
            meaning.examples = (meaning.examples || []).filter(example => {
                const key = exampleSentenceKey(example);
                if (!key || seen.has(key)) return false;
                seen.add(key);
                return true;
            });
        }
        if (entry.extra_raw_examples?.length) {
            const seen = new Set();
            entry.extra_raw_examples = entry.extra_raw_examples.filter(example => {
                const key = exampleSentenceKey(example);
                if (!key || seen.has(key)) return false;
                seen.add(key);
                return true;
            });
        }
        for (const clitic of (entry.clitic_memberships || [])) {
            const seen = new Set();
            clitic.examples = (clitic.examples || []).filter(example => {
                const key = exampleSentenceKey(example);
                if (!key || seen.has(key)) return false;
                seen.add(key);
                return true;
            });
        }
        if (entry.meanings && entry.meanings.length > 1) {
            const counts = entry.meanings.map(m => (m.examples || []).length);
            const total = counts.reduce((a, b) => a + b, 0);
            if (total > 0) {
                entry.meanings.forEach((m, i) => {
                    m.frequency = (counts[i] / total).toFixed(2);
                });
            }
        }
        entry._base_meanings = (entry.meanings || []).map(meaning => ({
            ...meaning,
            examples: (meaning.examples || []).map(example => ({ ...example })),
        }));
        entry._base_extra_raw_examples = entry.extra_raw_examples?.map(example => ({ ...example }));
    }

    // Per-artist representative flags are incompatible after union: two
    // artists can choose different surface forms for the same lemma. Stamp
    // exactly one combined-corpus representative per lemma.
    const representativeByLemma = new Map();
    for (const entry of byId.values()) {
        if (!entry.lemma) continue;
        entry.most_frequent_lemma_instance = false;
        const previous = representativeByLemma.get(entry.lemma);
        if (!previous || (entry.corpus_count || 0) > (previous.corpus_count || 0)) {
            representativeByLemma.set(entry.lemma, entry);
        }
    }
    for (const representative of representativeByLemma.values()) {
        representative.most_frequent_lemma_instance = true;
    }

    // Rebuild split-example buckets only after every artist has merged.
    // Master-format buckets stay keyed by _masterSenseIndex, including holes.
    for (const [id, merged] of byId) {
        mergedExamples[id] = { m: [] };
        (merged.meanings || []).forEach((meaning, i) => {
            const bucket = meaning._masterSenseIndex ?? i;
            mergedExamples[id].m[bucket] = meaning.examples || [];
        });
        if (merged.mwe_memberships) {
            mergedExamples[id].w = [];
            merged.mwe_memberships.forEach((mwe, i) => {
                mergedExamples[id].w[i] = mwe.examples || [];
            });
        }
        if (merged.clitic_memberships) {
            mergedExamples[id].c = [];
            merged.clitic_memberships.forEach((clitic, i) => {
                mergedExamples[id].c[i] = clitic.examples || [];
            });
        }
    }

    // Sort by combined corpus_count descending
    const mergedIndex = Array.from(byId.values()).sort((a, b) => (b.corpus_count || 0) - (a.corpus_count || 0));

    return { mergedIndex, mergedExamples };
}

// Synthesize MWE / CLITIC / SENSE_CYCLE meanings on a card's meanings array.
// Mirrors the inline blocks in loadVocabularyData (line 484+) and
// Review and ordinary decks both consume the assembled membership examples.
// (and the sense_cycles equivalents) are already populated by the caller —
// no corpus-scan fallback. Used by the popup/temp-card paths in
// flashcards.js (popupFoundWord, navigateToVocabCard) which previously
// skipped this synthesis entirely, hiding all MWEs (including curated ones)
// on cards reached via search or click-through.
function synthesizeSpecialMeanings(item, meanings) {
    if (item.mwe_memberships && item.mwe_memberships.length > 0) {
        const sortedMWEs = [...item.mwe_memberships].sort((a, b) => {
            const aSrc = a.source || 'artist';
            const bSrc = b.source || 'artist';
            const aArtist = aSrc === 'artist' || aSrc.startsWith('artist-') ? 0 : 1;
            const bArtist = bSrc === 'artist' || bSrc.startsWith('artist-') ? 0 : 1;
            return aArtist - bArtist;
        });
        const allMWEs = sortedMWEs.map(mwe => {
            const matched = mwe.examples || [];
            return {
                id: mwe.id || null,
                expression: mwe.expression,
                translation: mwe.translation || '',
                family: mwe.family || '',
                variants: mwe.variants || null,
                variantCounts: mwe.variant_counts || null,
                corpusCount: Number(mwe.count) || 0,
                occurrenceCount: Number(mwe.occurrence_count) || 0,
                songCount: Number(mwe.num_songs) || 0,
                context: mwe.context || '',
                context_heuristic: mwe.context_heuristic || '',
                source: mwe.source || '',
                examples: matched.length > 0 ? matched : [{ spanish: '', english: '' }],
            };
        });
        const firstEx = allMWEs[0].examples[0];
        meanings.push({
            pos: 'MWE',
            meaning: allMWEs[0].translation,
            expression: allMWEs[0].expression,
            allMWEs,
            percentage: 0,
            targetSentence: firstEx.spanish || firstEx.target || '',
            englishSentence: firstEx.english || '',
            allExamples: allMWEs[0].examples,
        });
    }
    if (item.clitic_memberships && item.clitic_memberships.length > 0) {
        const allClitics = item.clitic_memberships.map(cl => {
            const matched = cl.examples || [];
            return {
                form: cl.form,
                translation: cl.translation || '',
                corpus_count: cl.corpus_count || 0,
                examples: matched,
            };
        });
        allClitics.sort((a, b) => b.corpus_count - a.corpus_count);
        const firstEx = allClitics[0].examples[0] || { spanish: '', english: '' };
        meanings.push({
            pos: 'CLITIC',
            meaning: allClitics[0].form,
            allClitics,
            percentage: 0,
            targetSentence: firstEx.spanish || firstEx.target || '',
            englishSentence: firstEx.english || '',
            allExamples: allClitics[0].examples,
        });
    }
    if (item.sense_cycles && item.sense_cycles.length > 0) {
        for (const sc of item.sense_cycles) {
            const scExamples = sc.examples || [];
            const firstEx = scExamples[0] || { spanish: '', english: '' };
            const meaning = {
                pos: sc.pos === 'SENSE_CYCLE' ? 'SENSE_CYCLE' : sc.pos,
                meaning: sc.translation || '',
                percentage: 0,
                unassigned: true,
                targetSentence: firstEx.spanish || firstEx.target || '',
                englishSentence: firstEx.english || '',
                allExamples: scExamples,
            };
            if (sc.allSenses && sc.allSenses.length > 0) {
                meaning.allSenses = sc.allSenses;
                meaning.cycle_pos = sc.cycle_pos || sc.pos;
            }
            meanings.push(meaning);
        }
    }
    const order = { 'SENSE_CYCLE': 1, 'CLITIC': 2, 'MWE': 3 };
    meanings.sort((a, b) => {
        const aOrd = order[a.pos] || 0;
        const bOrd = order[b.pos] || 0;
        if (aOrd !== bOrd) return aOrd - bOrd;
        return (b.percentage || 0) - (a.percentage || 0);
    });
}

window.synthesizeSpecialMeanings = synthesizeSpecialMeanings;
window.buildCardFormModel = buildCardFormModel;
window.mergeArtistVocabularies = mergeArtistVocabularies;
window.joinWithMaster = joinWithMaster;
window.fetchAndJoinIndex = fetchAndJoinIndex;
window.fetchActiveVocabularyData = fetchActiveVocabularyData;
window.ensureLemmaPoolingData = ensureLemmaPoolingData;
window.getWordId = getWordId;
window.getCrossModeId = getCrossModeId;
window.isWordKnown = isWordKnown;
window.buildEstimatedKnownIds = buildEstimatedKnownIds;
window.LANG_CODES = LANG_CODES;
window.buildFilteredVocab = buildFilteredVocab;
window.assignStableVocabularyRanks = assignStableVocabularyRanks;
window.findSpuriousSelfInfinitives = findSpuriousSelfInfinitives;
window.loadVocabularyData = loadVocabularyData;
window.renderResumeLastSetCard = renderResumeLastSetCard;
window.resumeLastStudySession = resumeLastStudySession;
window.saveStudySessionSnapshot = saveStudySessionSnapshot;
window.clearStudySessionSnapshot = clearStudySessionSnapshot;
window.loadLevelReviewSet = loadLevelReviewSet;
window.loadCSVFiles = loadCSVFiles;
window.parseMultiMeaning = parseMultiMeaning;
window.truncateText = truncateText;
window.cleanValue = cleanValue;
window.generateLinks = generateLinks;
window.getExampleFromMeaning = getExampleFromMeaning;
window.getVocabularyExclusionReason = getVocabularyExclusionReason;
window.buildWordLookupMap = buildWordLookupMap;
