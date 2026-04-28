// Lazy-loaded extras for js/flashcards.js — see js/flashcards.js bottom for
// the stub layer that triggers this dynamic import.
//
// Functions exported on `window` here overwrite the lazy stubs installed by
// core flashcards.js, so subsequent calls hit the real implementation
// directly. State (flashcards, currentIndex, currentUser, etc.) and helpers
// like flagWord and getPosColorClass come through the globalThis proxy
// installed by state.js / auth.js / flashcards.js — no imports needed.

// ---------------------------------------------------------------------------
// Part-of-speech popup
// ---------------------------------------------------------------------------

// Part-of-speech lookup shown when a user taps the POS pill on a sense
// row. Full name + one-sentence plain-language description targeted at
// language learners, not grammarians. Keys match the UPOS / Kaikki POS
// values produced by the pipeline (see util_5c_sense_menu_format.py
// and util_5c_spanishdict.py).
const POS_INFO = {
    NOUN: { name: "Noun",
            description: "Names a person, place, thing, or idea (e.g. casa, amor, tiempo)." },
    VERB: { name: "Verb",
            description: "An action, state, or occurrence (e.g. correr, ser, tener)." },
    ADJ:  { name: "Adjective",
            description: "Describes or modifies a noun (e.g. grande, feliz, rápido)." },
    ADV:  { name: "Adverb",
            description: "Modifies a verb, adjective, or another adverb (e.g. rápidamente, muy, siempre)." },
    ADP:  { name: "Preposition",
            description: "Shows a relationship between words — usually place, time, or direction (e.g. a, de, en, con)." },
    DET:  { name: "Determiner",
            description: "Introduces or specifies a noun (e.g. el, una, este, mi)." },
    PRON: { name: "Pronoun",
            description: "Replaces a noun (e.g. él, ella, esto, nosotros)." },
    CCONJ: { name: "Conjunction",
             description: "Connects words, phrases, or clauses (e.g. y, pero, o, porque)." },
    SCONJ: { name: "Conjunction",
             description: "Introduces a subordinate clause (e.g. si, cuando, aunque)." },
    INTJ: { name: "Interjection",
            description: "An exclamation or sudden expression of emotion (e.g. ¡ay!, ¡oh!, ¡vale!)." },
    NUM:  { name: "Number",
            description: "Expresses a quantity or order (e.g. uno, dos, primero)." },
    PART: { name: "Particle",
            description: "A small grammatical marker with a specific role — doesn't always translate cleanly (e.g. no, sí, se)." },
    PROPN: { name: "Proper Noun",
             description: "The specific name of a person, place, or thing (e.g. María, Madrid, Spotify)." },
    PHRASE: { name: "Phrase",
              description: "A fixed group of words that function together (e.g. por favor, sin embargo)." },
    CONTRACTION: { name: "Contraction",
                   description: "Two words fused together into one written form (e.g. al = a + el, del = de + el, c'est = ce + est)." },
    X:    { name: "Unclassified",
            description: "Part of speech couldn't be determined for this sense." },
};

// Show an info popover describing a part of speech. The pill is tappable;
// a tap on the pill opens a full-screen semi-transparent overlay holding
// a small card with the POS name + description. If a percentage is
// passed and is a real sub-100 frequency, the popover also explains
// what that percentage means. Any subsequent click (or Escape) closes
// the overlay. The pill's own click stops propagation so the row's
// selectMeaning handler doesn't also fire.
function showPOSInfo(event, pos, pct) {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    const info = POS_INFO[pos] || {
        name: pos || "Unknown",
        description: "No description available for this part of speech.",
    };
    // Show the percentage-explainer only when a meaningful pct was
    // passed: integer between 1 and 99. 100% / missing / zero means
    // there's nothing to explain (either implicit or irrelevant).
    const pctNum = Number(pct);
    const showPct = Number.isFinite(pctNum) && pctNum > 0 && pctNum < 100;
    const pctSection = showPct ? `
            <div class="pos-info-divider"></div>
            <div class="pos-info-pct-label">Frequency on this card</div>
            <div class="pos-info-pct-value">${pctNum}%</div>
            <div class="pos-info-pct-description">
                Of the example sentences we have for this word, about
                ${pctNum}% use this meaning. The other ${100 - pctNum}%
                split between the other meanings shown on the card.
            </div>
    ` : '';
    const overlay = document.createElement('div');
    overlay.className = 'pos-info-overlay';
    // Inline the popover's colour accent so it matches the pill that
    // was tapped — the .pos-* classes on the pill carry the colour;
    // mirror them on the popover so the pairing is obvious.
    const posColorClass = getPosColorClass(pos) || '';
    overlay.innerHTML = `
        <div class="pos-info-popover ${posColorClass}" role="dialog" aria-label="${info.name}">
            <div class="pos-info-name">${info.name}</div>
            <div class="pos-info-description">${info.description}</div>
            ${pctSection}
            <div class="pos-info-hint">Tap anywhere to close</div>
        </div>
    `;
    document.body.appendChild(overlay);
    const close = () => {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        document.removeEventListener('keydown', onKey);
    };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    // Any click on the overlay (including the popover) closes. The user
    // asked for "press anywhere to close" — pairs cleanly with the
    // one-glance nature of the info.
    overlay.addEventListener('click', close);
    document.addEventListener('keydown', onKey);
}

// ---------------------------------------------------------------------------
// Lyric breakdown — modal that walks the current example sentence word by
// word, showing per-token translation/POS for in-deck and out-of-deck words.
// Triggered by tapping the example in artist-mode card view.
// ---------------------------------------------------------------------------

// Module-level cache for full vocab lookup (not in state — doesn't need proxy)
let fullVocabLookup = null;
let vocabByIdLookup = null;

function getVocabByIdLookup() {
    if (vocabByIdLookup) return vocabByIdLookup;
    if (!cachedVocabularyData) return new Map();
    vocabByIdLookup = new Map();
    for (const entry of cachedVocabularyData) {
        if (entry.id) vocabByIdLookup.set(entry.id, entry);
    }
    return vocabByIdLookup;
}

// Common Spanish elisions: elided form → possible full forms
const ELISION_MAP = {
    "pa": ["para"],
    "to": ["todo"],
    "na": ["nada"],
    "ta": ["esta", "estar"],
    "toy": ["estoy"],
    "tan": ["están"],
    "tamo": ["estamos"],
    "pal": ["para el"],
    "po": ["por"],
};

function getFullVocabLookup() {
    if (fullVocabLookup) return fullVocabLookup;
    if (!cachedVocabularyData) return new Map();
    fullVocabLookup = new Map();
    for (const entry of cachedVocabularyData) {
        const w = entry.word.toLowerCase().trim();
        if (!fullVocabLookup.has(w)) fullVocabLookup.set(w, entry);
        if (entry.lemma) {
            const l = entry.lemma.toLowerCase().trim();
            if (!fullVocabLookup.has(l)) fullVocabLookup.set(l, entry);
        }
    }
    return fullVocabLookup;
}

function tokenizeLyricLine(sentence) {
    if (!sentence) return [];
    // Strip any HTML tags (from word highlighting)
    const clean = sentence.replace(/<[^>]+>/g, '');
    const rawTokens = clean.split(/\s+/).filter(t => t.length > 0);
    return rawTokens.map(raw => {
        const match = raw.match(/^([^\p{L}\p{N}]*)([\p{L}\p{N}][\p{L}\p{N}'''-]*)([^\p{L}\p{N}]*)$/u);
        if (match) {
            return { original: raw, clean: match[2], punctBefore: match[1], punctAfter: match[3] };
        }
        // Pure punctuation or unmatched
        return { original: raw, clean: '', punctBefore: '', punctAfter: '' };
    });
}

function resolveToken(token) {
    if (!token.clean) return { token, source: 'unknown', entry: null, deckIndex: null };

    const lower = token.clean.toLowerCase();
    const lookupMap = window._wordLookupMap || new Map();

    // 1. Check current deck
    let deckIdx = lookupMap.get(lower);
    if (deckIdx !== undefined) {
        return { token, source: 'deck', entry: flashcards[deckIdx], deckIndex: deckIdx };
    }

    // 2. Try stripping trailing apostrophe (ere' → eres, etc.)
    if (lower.endsWith("'") || lower.endsWith("’")) {
        const stripped = lower.replace(/['’]+$/, '');
        deckIdx = lookupMap.get(stripped + 's');
        if (deckIdx !== undefined) return { token, source: 'deck', entry: flashcards[deckIdx], deckIndex: deckIdx };
        deckIdx = lookupMap.get(stripped);
        if (deckIdx !== undefined) return { token, source: 'deck', entry: flashcards[deckIdx], deckIndex: deckIdx };
    }

    // 3. Try elision map
    const elisions = ELISION_MAP[lower];
    if (elisions) {
        for (const full of elisions) {
            deckIdx = lookupMap.get(full);
            if (deckIdx !== undefined) return { token, source: 'deck', entry: flashcards[deckIdx], deckIndex: deckIdx };
        }
    }

    // 4. Check full vocabulary
    const fullLookup = getFullVocabLookup();
    let vocabEntry = fullLookup.get(lower);
    if (vocabEntry) return { token, source: 'vocab', entry: vocabEntry, deckIndex: null };

    // 5. Try elision recovery against full vocab
    if (lower.endsWith("'") || lower.endsWith("’")) {
        const stripped = lower.replace(/['’]+$/, '');
        vocabEntry = fullLookup.get(stripped + 's');
        if (vocabEntry) return { token, source: 'vocab', entry: vocabEntry, deckIndex: null };
        vocabEntry = fullLookup.get(stripped);
        if (vocabEntry) return { token, source: 'vocab', entry: vocabEntry, deckIndex: null };
    }
    if (elisions) {
        for (const full of elisions) {
            vocabEntry = fullLookup.get(full);
            if (vocabEntry) return { token, source: 'vocab', entry: vocabEntry, deckIndex: null };
        }
    }

    return { token, source: 'unknown', entry: null, deckIndex: null };
}

// Store current breakdown for popup access
let currentBreakdownResults = [];

function showLyricBreakdown(event) {
    event.stopPropagation();
    event.preventDefault();

    const card = flashcards[currentIndex];
    if (!card) return;

    const currentMeaning = card.meanings[currentMeaningIndex];
    if (!currentMeaning) return;

    // Get the raw (un-truncated) sentence — use MWE-specific examples if applicable
    let targetSentence = '';
    let englishSentence = '';
    let activeExamples;
    if (currentMeaning.allMWEs) {
        const mweIdx = currentMWEIndex % currentMeaning.allMWEs.length;
        activeExamples = dedupeExamples(currentMeaning.allMWEs[mweIdx].examples || []);
    } else {
        activeExamples = dedupeExamples(currentMeaning.allExamples || []);
    }
    if (activeExamples.length > 0) {
        const exIdx = currentExampleIndex % activeExamples.length;
        const example = activeExamples[exIdx];
        targetSentence = example.target || example.spanish || '';
        englishSentence = example.english || '';
    } else {
        targetSentence = currentMeaning.targetSentence || '';
        englishSentence = currentMeaning.englishSentence || '';
    }

    if (!targetSentence) return;

    // Tokenize and resolve each word
    const tokens = tokenizeLyricLine(targetSentence);
    currentBreakdownResults = tokens.map(t => resolveToken(t));

    // Build modal HTML
    let html = `
        <div class="breakdown-header">
            <div class="target-line">${targetSentence}</div>
            <div class="english-line">${englishSentence}</div>
        </div>
    `;

    currentBreakdownResults.forEach((result, idx) => {
        if (!result.token.clean) return; // skip pure punctuation

        const inDeck = result.source === 'deck';
        const rowClass = 'breakdown-word-row' + (inDeck ? ' in-deck' : '');

        let translation = '';
        let pos = '';
        if (result.entry) {
            if (result.source === 'deck') {
                // Flashcard object
                translation = result.entry.meanings?.[0]?.meaning || result.entry.translation || '';
                pos = result.entry.meanings?.[0]?.pos || '';
            } else {
                // Raw vocab entry
                translation = result.entry.meanings?.[0]?.translation || '';
                pos = result.entry.meanings?.[0]?.pos || '';
            }
        }

        const posClass = pos ? getPosColorClass(pos) : '';
        const posHTML = pos ? `<span class="word-pos card-pos ${posClass}">${pos}</span>` : '';

        html += `
            <div class="${rowClass}" onclick="showWordPopup(event, ${idx})">
                <span class="word-spanish">${result.token.clean}</span>
                <span class="word-translation">${translation || '<span style="opacity:0.4;">—</span>'}</span>
                ${posHTML}
            </div>
        `;
    });

    document.getElementById('lyricBreakdownBody').innerHTML = html;
    document.getElementById('lyricBreakdownModal').classList.remove('hidden');
}

function hideLyricBreakdown() {
    document.getElementById('lyricBreakdownModal').classList.add('hidden');
    hideWordPopup();
}

function hideWordPopup() {
    document.getElementById('wordPopup').classList.add('hidden');
}

function showWordPopup(event, tokenIndex) {
    event.stopPropagation();

    const result = currentBreakdownResults[tokenIndex];
    if (!result || !result.entry) return;

    const popup = document.getElementById('wordPopup');
    const inDeck = result.source === 'deck';

    let word, translation, pos, corpusCount;
    if (inDeck) {
        word = result.entry.targetWord;
        translation = result.entry.meanings?.[0]?.meaning || result.entry.translation || '';
        pos = result.entry.meanings?.[0]?.pos || '';
        corpusCount = result.entry.corpusCount;
    } else {
        word = result.entry.word;
        translation = result.entry.meanings?.[0]?.translation || '';
        pos = result.entry.meanings?.[0]?.pos || '';
        corpusCount = result.entry.corpus_count || null;
    }

    let html = `<div class="popup-word">${word}</div>`;
    html += `<div class="popup-translation">${translation || '—'}</div>`;
    if (pos) html += `<div class="popup-detail">POS: ${pos}</div>`;
    if (corpusCount) html += `<div class="popup-detail">Corpus count: ${corpusCount}</div>`;

    if (inDeck) {
        html += `<button class="popup-go-btn" onclick="navigateToCard(${result.deckIndex})">Go to card →</button>`;
    } else if (result.entry) {
        html += `<button class="popup-go-btn" onclick="navigateToVocabCard(${tokenIndex})">Go to card →</button>`;
    }

    popup.innerHTML = html;
    popup.classList.remove('hidden');

    // Position near the clicked row
    const rect = event.currentTarget.getBoundingClientRect();
    const popupWidth = 260;
    let left = rect.right + 8;
    let top = rect.top;

    // If would overflow right, put it to the left
    if (left + popupWidth > window.innerWidth) {
        left = rect.left - popupWidth - 8;
    }
    // If would overflow left, center below
    if (left < 8) {
        left = Math.max(8, (rect.left + rect.right) / 2 - popupWidth / 2);
        top = rect.bottom + 8;
    }
    // Clamp to viewport
    top = Math.max(8, Math.min(top, window.innerHeight - 250));

    popup.style.left = left + 'px';
    popup.style.top = top + 'px';

    // Dismiss on next click anywhere
    setTimeout(() => {
        document.addEventListener('click', function dismiss(e) {
            if (!popup.contains(e.target)) {
                hideWordPopup();
            }
            document.removeEventListener('click', dismiss);
        });
    }, 0);
}

// ---------------------------------------------------------------------------
// Card navigation stack — temp-card overlays for find-word, synonyms,
// homograph peek, and lyric-breakdown jumps. navigateBack pops the stack.
// ---------------------------------------------------------------------------

function navigateToCard(targetIndex) {
    // Cap at 1 level deep
    if (cardNavStack.length > 0) return;

    // Push current position onto stack
    cardNavStack.push({
        index: currentIndex,
        meaningIndex: currentMeaningIndex,
        exampleIndex: currentExampleIndex,
        mweIndex: currentMWEIndex,
        tempCard: false
    });

    // Close breakdown modal and popup
    hideLyricBreakdown();

    // Navigate to target card
    currentIndex = targetIndex;
    currentMeaningIndex = 0;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    document.getElementById('flashcard').classList.remove('flipped');
    updateCard();
}

function navigateToVocabCard(tokenIndex) {
    // Cap at 1 level deep
    if (cardNavStack.length > 0) return;

    const result = currentBreakdownResults[tokenIndex];
    if (!result || !result.entry) return;

    const vocabEntry = result.entry;

    // Build a temporary flashcard object from the vocab entry
    const langConfig = config.languages[selectedLanguage] || {};
    const exampleTargetField = langConfig.exampleTargetField || 'example_spanish';
    const exampleEnglishField = langConfig.exampleEnglishField || 'example_english';

    // Merge cached examples (sense, MWE, sense-cycle) before synthesis so
    // the MWE pill has lyric lines to render.
    const examplesData = window._cachedExamplesData;
    if (examplesData && examplesData[vocabEntry.id]) {
        const cached = examplesData[vocabEntry.id];
        if (cached.m && Array.isArray(vocabEntry.meanings)) {
            vocabEntry.meanings.forEach((m, i) => {
                if (!m.examples || m.examples.length === 0) {
                    m.examples = cached.m[i] || [];
                }
            });
        }
        if (cached.w && Array.isArray(vocabEntry.mwe_memberships)) {
            vocabEntry.mwe_memberships.forEach((mwe, i) => {
                if (!mwe.examples || mwe.examples.length === 0) {
                    mwe.examples = cached.w[i] || [];
                }
            });
        }
        if (cached.s && Array.isArray(vocabEntry.sense_cycles)) {
            vocabEntry.sense_cycles.forEach((sc, i) => {
                if (!sc.examples || sc.examples.length === 0) {
                    sc.examples = cached.s[i] || [];
                }
            });
        }
    }

    const meanings = (vocabEntry.meanings || []).map(m => {
        const ex = getExampleFromMeaning(m, exampleTargetField, exampleEnglishField);
        return {
            pos: m.pos,
            meaning: m.translation,
            percentage: parseFloat(m.frequency) || 0,
            targetSentence: ex.targetSentence,
            englishSentence: ex.englishSentence,
            allExamples: ex.allExamples
        };
    });

    // Synthesize MWE / CLITIC / SENSE_CYCLE meanings, mirroring
    // loadVocabularyData. The popup paths previously skipped this and so
    // never showed MWEs on cards reached via lyric-token click-through.
    if (typeof window.synthesizeSpecialMeanings === 'function') {
        window.synthesizeSpecialMeanings(vocabEntry, meanings);
    }

    const firstExample = meanings.length > 0 ? { targetSentence: meanings[0].targetSentence, englishSentence: meanings[0].englishSentence } : { targetSentence: '', englishSentence: '' };

    const tempCard = {
        targetWord: vocabEntry.word,
        lemma: vocabEntry.lemma || '',
        id: vocabEntry.id || '0000',
        fullId: getWordId(vocabEntry),
        rank: vocabEntry.rank || 0,
        corpusCount: vocabEntry.corpus_count || null,
        meanings: meanings,
        translation: meanings.length > 0 ? meanings[0].meaning : '',
        targetSentence: firstExample.targetSentence,
        englishSentence: firstExample.englishSentence,
        links: generateLinks(vocabEntry.word, vocabEntry.lemma || vocabEntry.word, langConfig.referenceLinks || {}),
        isMultiMeaning: true
    };

    // Append temp card to end of flashcards array
    const tempIndex = flashcards.length;
    flashcards.push(tempCard);

    // Push current position onto stack, mark as having a temp card
    cardNavStack.push({
        index: currentIndex,
        meaningIndex: currentMeaningIndex,
        exampleIndex: currentExampleIndex,
        mweIndex: currentMWEIndex,
        tempCard: true,
        tempIndex: tempIndex
    });

    // Close breakdown modal and popup
    hideLyricBreakdown();

    // Navigate to temp card
    currentIndex = tempIndex;
    currentMeaningIndex = 0;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    document.getElementById('flashcard').classList.remove('flipped');
    updateCard();
}

// Open a single vocab card as a popup (used by the find-word search and
// the synonyms panel's tap-to-jump). Pushes the current position onto
// cardNavStack so navigateBack returns to the previous state. Works
// whether or not a deck is currently loaded.
//
// opts.reopenSearchOnBack — when true (default for find-word callers),
// hitting back reopens the find-word search modal. The synonyms panel
// passes false so back returns straight to the originating card.
//
// In-flight guard: a fast double-click on a search result before the
// first invocation completes would push two entries onto cardNavStack
// and append two temp cards. The guard makes the second call a no-op.
async function popupFoundWord(entry, opts) {
    if (popupFoundWord._inFlight) return;
    popupFoundWord._inFlight = true;
    try {
        if (!entry || !entry.id) return;
        opts = opts || {};
        const reopenSearchOnBack = opts.reopenSearchOnBack !== false;
        const startFlipped = opts.startFlipped === true;

        // Look up the full vocab entry by ID from cached vocab data.
        const vocabSource = (activeArtist && window._cachedMergedIndex)
            ? window._cachedMergedIndex
            : window._cachedJoinedIndex;
        if (!vocabSource) {
            console.warn('popupFoundWord: no cached vocab index available');
            return;
        }
        const vocabEntry = vocabSource.find(it => it.id === entry.id);
        if (!vocabEntry) {
            console.warn('popupFoundWord: entry not found in cached index', entry.id);
            return;
        }

        const langConfig = (config && config.languages && config.languages[selectedLanguage]) || {};

        // Lazy-load examples file if needed and merge into the entry's meanings.
        if (langConfig.examplesPath && !window._cachedExamplesData) {
            try {
                const r = await fetch(langConfig.examplesPath);
                if (r.ok) window._cachedExamplesData = await r.json();
            } catch (e) {
                console.warn('popupFoundWord: failed to fetch examples', e);
            }
        }
        const examplesData = window._cachedExamplesData;
        if (examplesData && examplesData[vocabEntry.id]) {
            const ex = examplesData[vocabEntry.id];
            if (ex.m && Array.isArray(vocabEntry.meanings)) {
                vocabEntry.meanings.forEach((m, i) => {
                    if (!m.examples || m.examples.length === 0) {
                        m.examples = ex.m[i] || [];
                    }
                });
            }
            // Mirror loadVocabularyData's merge of "w" (MWE examples) and "s"
            // (sense-cycle examples) so the special-meaning synthesis below
            // has examples to render. Without this, MWE pills would render
            // empty even though mwe_memberships is populated.
            if (ex.w && Array.isArray(vocabEntry.mwe_memberships)) {
                vocabEntry.mwe_memberships.forEach((mwe, i) => {
                    if (!mwe.examples || mwe.examples.length === 0) {
                        mwe.examples = ex.w[i] || [];
                    }
                });
            }
            if (ex.s && Array.isArray(vocabEntry.sense_cycles)) {
                vocabEntry.sense_cycles.forEach((sc, i) => {
                    if (!sc.examples || sc.examples.length === 0) {
                        sc.examples = ex.s[i] || [];
                    }
                });
            }
        }

        // Build the temp card from the entry (mirrors navigateToVocabCard).
        const exampleTargetField = langConfig.exampleTargetField || 'example_spanish';
        const exampleEnglishField = langConfig.exampleEnglishField || 'example_english';

        const meanings = (vocabEntry.meanings || []).map(m => {
            const ex = getExampleFromMeaning(m, exampleTargetField, exampleEnglishField);
            const meaning = {
                pos: m.pos,
                meaning: m.translation,
                percentage: parseFloat(m.frequency) || 0,
                targetSentence: ex.targetSentence,
                englishSentence: ex.englishSentence,
                allExamples: ex.allExamples
            };
            if (m.unassigned) meaning.unassigned = true;
            if (m.assignment_method) meaning.assignment_method = m.assignment_method;
            if (m.source) meaning.source = m.source;
            if (m.context) meaning.context = m.context;
            if (m.allSenses) meaning.allSenses = m.allSenses;
            if (m.cycle_pos) meaning.cycle_pos = m.cycle_pos;
            return meaning;
        });

        // Synthesize MWE / CLITIC / SENSE_CYCLE meanings — without this the
        // popup would show only sense pills, hiding all MWEs (including
        // curated ones like "no te hagas") that the deck-flow path renders.
        if (typeof window.synthesizeSpecialMeanings === 'function') {
            window.synthesizeSpecialMeanings(vocabEntry, meanings);
        }

        const firstExample = meanings.length > 0
            ? { targetSentence: meanings[0].targetSentence, englishSentence: meanings[0].englishSentence }
            : { targetSentence: '', englishSentence: '' };

        const tempCard = {
            targetWord: vocabEntry.word,
            lemma: vocabEntry.lemma || '',
            id: vocabEntry.id || '0000',
            fullId: getWordId(vocabEntry),
            rank: vocabEntry.rank || 0,
            corpusCount: vocabEntry.corpus_count || null,
            meanings: meanings,
            translation: meanings.length > 0 ? meanings[0].meaning : '',
            targetSentence: firstExample.targetSentence,
            englishSentence: firstExample.englishSentence,
            links: generateLinks(vocabEntry.word, vocabEntry.lemma || vocabEntry.word, langConfig.referenceLinks || {}),
            isMultiMeaning: true,
            variants: vocabEntry.variants || null,
            homographIds: vocabEntry.homograph_ids || null,
            morphology: vocabEntry.morphology || null,
            relatedLemma: vocabEntry.related_lemma || null
        };

        // Hide the search modal while the card is being viewed.
        const findModal = document.getElementById('findWordModal');
        if (findModal) findModal.classList.add('hidden');

        const noDeckLoaded = !flashcards || flashcards.length === 0;
        const wasOnSetup = !document.getElementById('setupPanel').classList.contains('hidden');

        if (noDeckLoaded) {
            // No deck — build a one-card temp deck and show the app panel.
            cardNavStack.push({
                popupOnly: true,
                wasOnSetup: wasOnSetup,
                reopenSearchOnBack: reopenSearchOnBack
            });
            flashcards.length = 0;
            flashcards.push(tempCard);
            currentIndex = 0;
            currentMeaningIndex = 0;
            currentExampleIndex = 0;
            currentMWEIndex = 0;
            document.getElementById('setupPanel').classList.add('hidden');
            document.getElementById('appContent').classList.remove('hidden');
            showFloatingBtns(true);
            const fc = document.getElementById('flashcard');
            if (startFlipped) fc.classList.add('flipped'); else fc.classList.remove('flipped');
            initializeApp();
        } else {
            // Deck loaded — append temp card and push current position onto nav stack.
            const tempIndex = flashcards.length;
            flashcards.push(tempCard);
            cardNavStack.push({
                index: currentIndex,
                meaningIndex: currentMeaningIndex,
                exampleIndex: currentExampleIndex,
                mweIndex: currentMWEIndex,
                tempCard: true,
                tempIndex: tempIndex,
                reopenSearchOnBack: reopenSearchOnBack
            });
            currentIndex = tempIndex;
            currentMeaningIndex = 0;
            currentExampleIndex = 0;
            currentMWEIndex = 0;
            const fc = document.getElementById('flashcard');
            if (startFlipped) fc.classList.add('flipped'); else fc.classList.remove('flipped');
            updateCard();
        }
    } finally {
        popupFoundWord._inFlight = false;
    }
}

function navigateBack() {
    if (cardNavStack.length === 0) {
        goBackToSetup();
        return;
    }

    const prev = cardNavStack.pop();

    // Popup-only state: no deck was loaded when the temp card was opened.
    // Tear down the temp deck and restore the setup panel.
    if (prev.popupOnly) {
        flashcards.length = 0;
        currentIndex = 0;
        currentMeaningIndex = 0;
        currentExampleIndex = 0;
        currentMWEIndex = 0;
        if (prev.wasOnSetup) {
            document.getElementById('appContent').classList.add('hidden');
            document.getElementById('setupPanel').classList.remove('hidden');
            showFloatingBtns(false);
        }
        if (prev.reopenSearchOnBack) {
            const modal = document.getElementById('findWordModal');
            if (modal) modal.classList.remove('hidden');
            setTimeout(() => {
                const input = document.getElementById('findWordInput');
                if (input) input.focus();
            }, 50);
        }
        return;
    }

    // Remove temp card if one was created
    if (prev.tempCard && prev.tempIndex !== undefined) {
        flashcards.splice(prev.tempIndex, 1);
    }

    currentIndex = prev.index;
    currentMeaningIndex = prev.meaningIndex;
    currentExampleIndex = prev.exampleIndex;
    currentMWEIndex = prev.mweIndex || 0;
    document.getElementById('flashcard').classList.remove('flipped');
    updateCard();

    if (prev.reopenSearchOnBack) {
        const modal = document.getElementById('findWordModal');
        if (modal) modal.classList.remove('hidden');
        setTimeout(() => {
            const input = document.getElementById('findWordInput');
            if (input) input.focus();
        }, 50);
    }
}

// ---------------------------------------------------------------------------
// Homograph peek — opens a sibling-homograph as a temp card, pushed onto
// cardNavStack. Same temp-card pattern as navigateToVocabCard but without
// the lyric-breakdown context.
// ---------------------------------------------------------------------------

function peekHomograph(siblingId) {
    if (cardNavStack.length > 0) return;

    const lookup = getVocabByIdLookup();
    const vocabEntry = lookup.get(siblingId);
    if (!vocabEntry) return;

    // Attach examples from cached examples data (they aren't on cachedVocabularyData entries)
    const examplesData = window._cachedExamplesData;
    if (examplesData && examplesData[siblingId]) {
        const ex = examplesData[siblingId];
        (vocabEntry.meanings || []).forEach((m, i) => {
            if (!m.examples || m.examples.length === 0) {
                m.examples = ex.m[i] || [];
            }
        });
    }

    const langConfig = config.languages[selectedLanguage] || {};
    const exampleTargetField = langConfig.exampleTargetField || 'example_spanish';
    const exampleEnglishField = langConfig.exampleEnglishField || 'example_english';

    const meanings = (vocabEntry.meanings || []).map(m => {
        const ex = getExampleFromMeaning(m, exampleTargetField, exampleEnglishField);
        return {
            pos: m.pos,
            meaning: m.translation,
            percentage: parseFloat(m.frequency) || 0,
            targetSentence: ex.targetSentence,
            englishSentence: ex.englishSentence,
            allExamples: ex.allExamples
        };
    });

    const firstExample = meanings.length > 0
        ? { targetSentence: meanings[0].targetSentence, englishSentence: meanings[0].englishSentence }
        : { targetSentence: '', englishSentence: '' };

    const tempCard = {
        targetWord: vocabEntry.word,
        lemma: vocabEntry.lemma || '',
        id: vocabEntry.id || '0000',
        fullId: getWordId(vocabEntry),
        rank: vocabEntry.rank || 0,
        corpusCount: vocabEntry.corpus_count || null,
        meanings: meanings,
        translation: meanings.length > 0 ? meanings[0].meaning : '',
        targetSentence: firstExample.targetSentence,
        englishSentence: firstExample.englishSentence,
        links: generateLinks(vocabEntry.word, vocabEntry.lemma || vocabEntry.word, langConfig.referenceLinks || {}),
        isMultiMeaning: true,
        homographIds: vocabEntry.homograph_ids || null,
        isPeekCard: true
    };

    const tempIndex = flashcards.length;
    flashcards.push(tempCard);

    cardNavStack.push({
        index: currentIndex,
        meaningIndex: currentMeaningIndex,
        exampleIndex: currentExampleIndex,
        mweIndex: currentMWEIndex,
        tempCard: true,
        tempIndex: tempIndex
    });

    currentIndex = tempIndex;
    currentMeaningIndex = 0;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    document.getElementById('flashcard').classList.remove('flipped');
    updateCard();
}

// ---------------------------------------------------------------------------
// Card metadata popover (debug info — per-sense source + per-example method)
// ---------------------------------------------------------------------------

function _escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
}

function _renderCardMetaBody(card) {
    if (!card) return '<div class="card-meta-empty">No card selected.</div>';
    const showFlags = !!(currentUser && !currentUser.isGuest && currentUser.initials === 'JST');
    const flagBtn = (path, value) => showFlags
        ? `<button class="card-meta-flag-row" type="button" data-path="${_escapeHtml(path)}" data-value="${_escapeHtml(value == null ? '' : String(value))}" title="Flag this field">flag</button>`
        : '';

    const lines = [];
    const id = card.fullId || card.id || '';
    lines.push('<div class="card-meta-section">');
    lines.push('<dl class="card-meta-kv">');
    const wordVal = card.targetWord || card.word || '';
    lines.push(`<dt>word</dt><dd>${_escapeHtml(wordVal)}${flagBtn('word', wordVal)}</dd>`);
    if (card.lemma && card.lemma !== wordVal) {
        lines.push(`<dt>lemma</dt><dd>${_escapeHtml(card.lemma)}${flagBtn('lemma', card.lemma)}</dd>`);
    }
    if (id) lines.push(`<dt>id</dt><dd>${_escapeHtml(id)}</dd>`);
    if (card.rank) lines.push(`<dt>rank</dt><dd>${_escapeHtml(card.rank)}</dd>`);
    if (card.corpusCount != null) lines.push(`<dt>corpus</dt><dd>${_escapeHtml(card.corpusCount)}</dd>`);
    lines.push('</dl></div>');

    const meanings = card.meanings || [];
    lines.push('<div class="card-meta-section"><h4>Meanings</h4>');
    if (!meanings.length) {
        lines.push('<div class="card-meta-empty">No meanings.</div>');
    } else {
        lines.push('<ul class="card-meta-list">');
        meanings.forEach((m, i) => {
            const isCurrent = (typeof currentMeaningIndex === 'number' && i === currentMeaningIndex);
            const tags = [];
            if (m.source) tags.push(`<span class="card-meta-tag source">src: ${_escapeHtml(m.source)}</span>`);
            if (m.assignment_method) tags.push(`<span class="card-meta-tag method">m: ${_escapeHtml(m.assignment_method)}</span>`);
            if (m.unassigned) tags.push('<span class="card-meta-tag flag">unassigned</span>');
            if (m.pos === 'SENSE_CYCLE') tags.push('<span class="card-meta-tag flag">SENSE_CYCLE</span>');
            const pctText = (typeof m.percentage === 'number') ? (m.percentage * 100).toFixed(0) + '%' : '';
            const meaningText = m.meaning || m.translation || '';
            const label = `${_escapeHtml(m.pos || '?')} · ${_escapeHtml(meaningText)}${pctText ? ' · ' + pctText : ''}`;
            lines.push(`<li${isCurrent ? ' class="card-meta-current"' : ''}>${label}${flagBtn(`sense:${i}`, meaningText)}<div>${tags.join(' ') || '<span class="card-meta-empty">no tags</span>'}</div></li>`);
        });
        lines.push('</ul>');
    }
    lines.push('</div>');

    // Per-example methods for the currently displayed meaning.
    const curMeaning = meanings[currentMeaningIndex] || meanings[0];
    const exs = (curMeaning && curMeaning.allExamples) || [];
    const senseIdx = (typeof currentMeaningIndex === 'number') ? currentMeaningIndex : 0;
    lines.push('<div class="card-meta-section"><h4>Examples (current meaning)</h4>');
    if (!exs.length) {
        lines.push('<div class="card-meta-empty">No examples.</div>');
    } else {
        lines.push('<ul class="card-meta-list">');
        exs.forEach((ex, i) => {
            const isCurrent = (typeof currentExampleIndex === 'number' && i === (currentExampleIndex % exs.length));
            const method = ex.assignment_method ? `<span class="card-meta-tag method">m: ${_escapeHtml(ex.assignment_method)}</span>` : '<span class="card-meta-empty">no method</span>';
            const tsrc = ex.translation_source ? `<span class="card-meta-tag source">t: ${_escapeHtml(ex.translation_source)}</span>` : '';
            const spanish = ex.spanish || ex.targetSentence || ex.original || '';
            lines.push(`<li${isCurrent ? ' class="card-meta-current"' : ''}>${method} ${tsrc}${flagBtn(`example:${senseIdx}:${i}`, spanish)}<div class="card-meta-ex">${_escapeHtml(spanish)}</div></li>`);
        });
        lines.push('</ul>');
    }
    lines.push('</div>');

    return lines.join('');
}

function showCardMetaPopover() {
    const pop = document.getElementById('cardMetaPopover');
    const body = document.getElementById('cardMetaBody');
    const title = document.getElementById('cardMetaTitle');
    const footer = document.getElementById('cardMetaFooter');
    if (!pop || !body) return;
    const card = (typeof flashcards !== 'undefined' && flashcards) ? flashcards[currentIndex] : null;
    if (title) title.textContent = card ? `${card.targetWord || card.word || 'Card'} — info` : 'Card info';
    body.innerHTML = _renderCardMetaBody(card);
    body.querySelectorAll('.card-meta-flag-row').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const path = btn.dataset.path;
            const value = btn.dataset.value;
            if (card && typeof flagWord === 'function') flagWord(card, path, value);
            btn.classList.add('flagged');
        });
    });
    if (footer) {
        const showFlagBtn = !!(currentUser && !currentUser.isGuest && currentUser.initials === 'JST');
        footer.style.display = showFlagBtn ? '' : 'none';
    }
    pop.hidden = false;
    pop.setAttribute('aria-hidden', 'false');
}

function hideCardMetaPopover() {
    const pop = document.getElementById('cardMetaPopover');
    if (!pop) return;
    pop.hidden = true;
    pop.setAttribute('aria-hidden', 'true');
}

function toggleCardMetaPopover() {
    const pop = document.getElementById('cardMetaPopover');
    if (!pop) return;
    if (pop.hidden) showCardMetaPopover();
    else hideCardMetaPopover();
}

function refreshCardMetaPopoverIfOpen() {
    const pop = document.getElementById('cardMetaPopover');
    if (!pop || pop.hidden) return;
    showCardMetaPopover();
}

// Close button + outside-click dismiss + flag button. The toggle button
// (#cardMetaBtn) is wired by core flashcards.js's _initCardMetaButton IIFE,
// which calls window.toggleCardMetaPopover() — i.e. the lazy stub that
// triggered this module's load. Handlers here only matter when the popover
// is OPEN, which can only happen after this module has loaded, so attaching
// at module-load time is correct.
(function _initCardMetaPopoverInternals() {
    const pop = document.getElementById('cardMetaPopover');
    const closeBtn = document.getElementById('cardMetaClose');
    const flagBtn = document.getElementById('cardMetaFlagBtn');
    const content = document.getElementById('cardMetaContent');
    const btn = document.getElementById('cardMetaBtn');
    if (!pop) return;
    if (closeBtn) closeBtn.addEventListener('click', hideCardMetaPopover);
    if (flagBtn) {
        flagBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const card = (typeof flashcards !== 'undefined' && flashcards) ? flashcards[currentIndex] : null;
            if (card && typeof flagWord === 'function') flagWord(card);
            hideCardMetaPopover();
        });
    }
    document.addEventListener('click', (e) => {
        if (pop.hidden) return;
        if ((content && content.contains(e.target)) || (btn && btn.contains(e.target))) return;
        hideCardMetaPopover();
    });
})();

// Window exports — the lazy stubs in core flashcards.js look these up after
// the dynamic import resolves. The stub layer's post-resolve check verifies
// each name was reassigned to the real function (otherwise it would recurse
// into itself, since the stub is also on window).
window.showPOSInfo = showPOSInfo;
window.showLyricBreakdown = showLyricBreakdown;
window.hideLyricBreakdown = hideLyricBreakdown;
window.showWordPopup = showWordPopup;
window.hideWordPopup = hideWordPopup;
window.navigateToCard = navigateToCard;
window.navigateToVocabCard = navigateToVocabCard;
window.navigateBack = navigateBack;
window.popupFoundWord = popupFoundWord;
window.peekHomograph = peekHomograph;
window.showCardMetaPopover = showCardMetaPopover;
window.hideCardMetaPopover = hideCardMetaPopover;
window.toggleCardMetaPopover = toggleCardMetaPopover;
window.refreshCardMetaPopoverIfOpen = refreshCardMetaPopoverIfOpen;
