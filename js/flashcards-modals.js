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

// Part-of-speech lookup shown when a user taps a pill in the card-back
// legend. Full name + one-sentence plain-language description targeted at
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
    MWE: { name: "Expressions",
           description: "A multi-word expression whose meaning or use belongs to the words together." },
    CLITIC: { name: "Clitics",
              description: "A short grammatical form that attaches closely to another word (e.g. me, te, se)." },
    CONTRACTION: { name: "Contraction",
                   description: "Two words fused together into one written form (e.g. al = a + el, del = de + el, c'est = ce + est)." },
    X:    { name: "Unclassified",
            description: "Part of speech couldn't be determined for this sense." },
};

// Show an info popover describing a part of speech. The pill is tappable;
// a tap on the pill opens a full-screen semi-transparent overlay holding
// a small card with the POS name + description. If a percentage is
// passed and is a real sub-100 frequency, the popover also explains
// what that percentage means. The backdrop, close button, or Escape closes
// the overlay; interaction inside the popover stays inside it so the content
// can be scrolled safely on touch screens. The pill's own click stops propagation so the row's
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
        <div class="pos-info-popover ${posColorClass}" role="dialog" aria-modal="true" aria-label="${info.name}" tabindex="-1">
            <button type="button" class="pos-info-close" aria-label="Close information popup">×</button>
            <div class="pos-info-name">${info.name}</div>
            <div class="pos-info-description">${info.description}</div>
            ${pctSection}
            <div class="pos-info-hint">Scroll for details · tap outside to close</div>
        </div>
    `;
    document.body.appendChild(overlay);
    const close = () => {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        document.removeEventListener('keydown', onKey);
    };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    const popover = overlay.querySelector('.pos-info-popover');
    const closeButton = overlay.querySelector('.pos-info-close');
    // Mobile browsers can emit a click after a touch-scroll. Only a genuine
    // backdrop click dismisses, so scrolling or selecting text in the dialog
    // never tears the overlay down underneath the gesture.
    overlay.addEventListener('click', e => {
        if (e.target === overlay) close();
    });
    popover.addEventListener('click', e => e.stopPropagation());
    closeButton.addEventListener('click', e => {
        e.stopPropagation();
        close();
    });
    document.addEventListener('keydown', onKey);
    popover.focus({ preventScroll: true });
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
        ...(window.buildCardFormModel?.(vocabEntry, meanings) || {}),
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

        // Find-word results carry the exact full joined entry they were built
        // from. Prefer it over global cache pointers, which other setup work
        // can legitimately repoint between rendering and selecting a result.
        const vocabSource = (activeArtist && window._cachedMergedIndex)
            ? window._cachedMergedIndex
            : window._cachedJoinedIndex;
        const vocabEntry = entry.sourceEntry
            || (vocabSource && vocabSource.find(it => it.id === entry.id));
        if (!vocabEntry) {
            throw new Error(`Search entry ${entry.id} is no longer available in the active vocabulary`);
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
                        const bucket = m._masterSenseIndex ?? i;
                        m.examples = ex.m[bucket] || [];
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

        const sourceMeanings = (vocabEntry.meanings || []).filter(m =>
            String(m?.translation || '').trim()
            && (!activeArtist || Number(m.frequency || 0) > 0));
        const meanings = sourceMeanings.map(m => {
            const ex = window.getExampleFromMeaning(m, exampleTargetField, exampleEnglishField);
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

        // A searchable source entry can legitimately have corpus examples but
        // no usable translation or artist-matched sense. Keep it inspectable:
        // collapse every examples payload (sense/MWE/remainder) into one
        // deduplicated examples-only meaning instead of handing updateCard an
        // empty meanings array.
        if (meanings.length === 0) {
            const gathered = [];
            const gatherExamples = value => {
                if (Array.isArray(value)) {
                    value.forEach(gatherExamples);
                    return;
                }
                if (!value || typeof value !== 'object') return;
                if (value.target || value.spanish || value.swedish || value.dutch
                    || value.italian || value.polish) {
                    gathered.push(value);
                    return;
                }
                Object.values(value).forEach(gatherExamples);
            };
            gatherExamples(examplesData && examplesData[vocabEntry.id]);
            const seen = new Set();
            const examples = gathered.filter(example => {
                const target = example.target || example.spanish || example.swedish
                    || example.dutch || example.italian || example.polish || '';
                const key = example.id || `${example.song || ''}\u0000${target}`;
                if (!target || seen.has(key)) return false;
                seen.add(key);
                return true;
            });
            const first = examples[0] || {};
            meanings.push({
                pos: 'EXAMPLE_ONLY',
                meaning: '',
                percentage: 1,
                targetSentence: first.target || first.spanish || first.swedish
                    || first.dutch || first.italian || first.polish || '',
                englishSentence: first.english || '',
                allExamples: examples,
                exampleOnly: true,
                unassigned: true
            });
        }

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
            ...(window.buildCardFormModel?.(vocabEntry, meanings) || {}),
            id: vocabEntry.id || '0000',
            fullId: window.getWordId(vocabEntry),
            rank: vocabEntry.rank || 0,
            corpusCount: vocabEntry.corpus_count || null,
            meanings: meanings,
            translation: meanings.length > 0 ? meanings[0].meaning : '',
            targetSentence: firstExample.targetSentence,
            englishSentence: firstExample.englishSentence,
            links: window.generateLinks(vocabEntry.word, vocabEntry.lemma || vocabEntry.word, langConfig.referenceLinks || {}),
            isMultiMeaning: true,
            variants: vocabEntry.variants || null,
            homographIds: vocabEntry.homograph_ids || null,
            morphology: vocabEntry.morphology || null,
            relatedLemma: vocabEntry.related_lemma || null,
            derivationRelation: vocabEntry.derivation_relation || null,
            searchExclusionReason: entry.exclusionReason || null,
            searchExamplesOnly: entry.examplesOnly || meanings[0]?.exampleOnly || false
        };

        // Keep search visible until the temporary card has rendered. Hiding it
        // early made any render exception look like an inert/dead result click.
        const findModal = document.getElementById('findWordModal');

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
            window.showFloatingBtns(true);
            const fc = document.getElementById('flashcard');
            if (startFlipped) fc.classList.add('flipped'); else fc.classList.remove('flipped');
            window.initializeApp();
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
            window.updateCard();
        }
        if (findModal) findModal.classList.add('hidden');
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
        ...(window.buildCardFormModel?.(vocabEntry, meanings) || {}),
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
// End-of-deck modal — shown when handleSwipeAction or nextCard exhausts the
// current deck. Buttons (restart all / review incorrect) are wired in core's
// initializeApp via lazy stubs.
// ---------------------------------------------------------------------------

function showEndOfDeckOptions() {
    // A completed deck is no longer resumable. Starting a follow-up set or
    // mistake review will create a fresh snapshot on its first rendered card.
    window.clearStudySessionSnapshot?.();
    const incorrectCards = Object.keys(stats.cardStats)
        .filter(idx => stats.cardStats[idx].incorrect > stats.cardStats[idx].correct)
        .map(Number);

    const totalAttempts = stats.correct + stats.incorrect;
    const accuracy = totalAttempts > 0 ? Math.round((stats.correct / totalAttempts) * 100) : 0;

    // Update modal content. Ordinary decks are intentionally small stable
    // sets, so completion is a frequent reward inside the larger level.
    const titleEl = document.getElementById('deckCompleteTitle');
    if (titleEl) {
        titleEl.textContent = stats.studyMode === 'review'
            ? 'Review Complete!'
            : stats.setNumber
            ? `Set ${stats.setNumber} Complete!`
            : 'Set Complete!';
    }
    document.getElementById('completeCorrect').textContent = stats.correct;
    document.getElementById('completeIncorrect').textContent = stats.incorrect;
    document.getElementById('completeAccuracy').textContent = `${accuracy}% accuracy`;

    const continueBtn = document.getElementById('continueIncorrectBtn');
    const messageEl = document.getElementById('completeMessage');
    const finishBtn = document.getElementById('markCompleteBtn');
    const finishLabel = document.getElementById('markCompleteLabel');
    const finishIcon = document.getElementById('markCompleteIcon');

    if (finishBtn && finishLabel && finishIcon) {
        // A level can be exhausted before its final physical dot when every
        // later set was completed previously. In that case advance directly
        // to the next actionable level instead of hiding the continuation.
        const nextLevel = !stats.nextRange ? window.getNextStudyLevelMeta?.() : null;
        finishBtn.dataset.action = '';
        if (stats.nextRange) {
            finishLabel.textContent = `Start Set ${stats.nextSetNumber}`;
            finishIcon.textContent = '→';
            finishBtn.dataset.action = 'next-set';
            finishBtn.classList.add('has-next-set');
            finishBtn.style.display = '';
        } else if (nextLevel) {
            finishLabel.textContent = (nextLevel.scope === 'extra' || nextLevel.label)
                ? `Start ${nextLevel.label}`
                : `Start Level ${nextLevel.levelNumber}, Set 1`;
            finishIcon.textContent = '→';
            finishBtn.dataset.action = 'next-level';
            finishBtn.classList.add('has-next-set');
            finishBtn.style.display = '';
        } else {
            finishBtn.classList.remove('has-next-set');
            finishBtn.style.display = 'none';
        }
    }

    if (incorrectCards.length > 0) {
        messageEl.textContent = `${incorrectCards.length} card${incorrectCards.length > 1 ? 's' : ''} to review`;
        continueBtn.disabled = false;
        continueBtn.querySelector('span:last-child').textContent = `Review ${incorrectCards.length} Mistake${incorrectCards.length > 1 ? 's' : ''}`;
    } else {
        messageEl.innerHTML = '<span class="deck-complete-perfect">No mistakes this time.</span>';
        continueBtn.disabled = true;
        continueBtn.querySelector('span:last-child').textContent = 'No mistakes';
    }

    // Store incorrect cards for later use
    window.currentIncorrectCards = incorrectCards;

    // Show the modal
    document.getElementById('deckCompleteModal').classList.remove('hidden');
}

function hideDeckCompleteModal() {
    document.getElementById('deckCompleteModal').classList.add('hidden');
}

function restartWithIncorrectCards(incorrectIndices) {
    // Create new deck with only incorrect cards
    const incorrectFlashcards = incorrectIndices.map(idx => flashcards[idx]);

    // Reset stats
    stats.correct = 0;
    stats.incorrect = 0;
    stats.total = 0;
    stats.studied = new Set();
    stats.cardStats = {};

    // Set new flashcards array
    flashcards = incorrectFlashcards;
    currentIndex = 0;
    currentSentenceIndex = 0;

    updateCard();
    document.getElementById('flashcard').classList.remove('flipped');
}

function restartAllCards() {
    // Reset stats
    stats.correct = 0;
    stats.incorrect = 0;
    stats.total = 0;
    stats.studied = new Set();
    stats.cardStats = {};

    currentIndex = 0;
    currentSentenceIndex = 0;

    updateCard();
    document.getElementById('flashcard').classList.remove('flipped');
}

function _escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
}

// ---------------------------------------------------------------------------
// Audit flag menu — target and problem category are independent. The visible
// sense/example pairing remains the useful default, but lemma, form, whole-card,
// and note-only reports are first-class choices rather than hidden fallbacks.
//
// Reuses flagWord(card, fieldPath, fieldValue) from auth.js: the payload is
// backward-compatible with the existing eight-column FlaggedWords sheet: a
// structured text report is stored in its existing `word` value column.
// ---------------------------------------------------------------------------
let _flagSelIdx = 0;      // which sense row is highlighted
let _flagTarget = 'pairing';
let _flagCategory = 'matching';
const FLAG_TARGETS = [
    { key: 'pairing', label: 'Sense + example', detail: 'The line is linked to the wrong meaning' },
    { key: 'sense', label: 'Meaning', detail: 'Gloss, context, or part of speech' },
    { key: 'example', label: 'Example line', detail: 'Lyric, subtitle, translation, or timing' },
    { key: 'lemma', label: 'Lemma', detail: 'Wrong base word or merged family' },
    { key: 'surface', label: 'Word form', detail: 'Conjugation or displayed morphology' },
    { key: 'card', label: 'Whole card', detail: 'Rank, frequency, layout, or mixed issue' },
    { key: 'note', label: 'Note', detail: 'Describe something without choosing a field', quickOnly: true },
    { key: 'routing', label: 'Classification tag', detail: 'English, loanword, or cognate', quickOnly: true }
];
const FLAG_CATEGORIES = [
    { key: 'matching', label: 'Wrong match' },
    { key: 'translation', label: 'Translation' },
    { key: 'lemma', label: 'Lemma / grouping' },
    { key: 'morphology', label: 'Morphology' },
    { key: 'example', label: 'Example / lyric' },
    { key: 'expression', label: 'Expression / clitic' },
    { key: 'frequency', label: 'Frequency / rank' },
    { key: 'other', label: 'Other' }
];
const FLAG_ROUTING_TAGS = [
    { key: 'english', label: 'English word', shortLabel: 'English', detail: 'English or code-switch vocabulary' },
    { key: 'loanword', label: 'Loanword', shortLabel: 'Loanword', detail: 'A borrowed English word used in Spanish' },
    { key: 'cognate', label: 'Cognate', shortLabel: 'Cognate', detail: 'Transparent enough to be filtered as a cognate' }
];
const FLAG_SENSE_TARGETS = new Set(['pairing', 'sense', 'example']);
const FLAG_DEFAULT_CATEGORY = {
    pairing: 'matching', sense: 'translation', example: 'example',
    lemma: 'lemma', surface: 'morphology', card: 'other'
};

// ---------------------------------------------------------------------------
// Canonical flag taxonomy (schema v2).
//
// The audit sheet stores these STABLE KEYS, never the display labels, so
// renaming a label in the UI can no longer orphan flag history. Two entry
// paths write flags — the full menu (FLAG_TARGETS keys) and the quick actions
// (_sendSimpleFlag's own shorthand) — and they historically emitted different
// Target vocabularies into the same column. FLAG_QUICK_CANONICAL folds the
// quick shorthand onto the menu's vocabulary so both paths agree.
//
// fieldPath strings are deliberately NOT changed here: they are the sheet's
// dedup key, so re-flagging the same field must keep updating its existing row.
// ---------------------------------------------------------------------------
const FLAG_CATEGORY_LABELS = {
    ...Object.fromEntries(FLAG_CATEGORIES.map(item => [item.key, item.label])),
    ...Object.fromEntries(FLAG_ROUTING_TAGS.map(item => [item.key, item.label])),
    pos: 'Part of speech',
    proper_noun: 'Proper noun'
};
const FLAG_QUICK_CANONICAL = {
    note: { target: 'note', category: 'other' },
    propernoun: { target: 'routing', category: 'proper_noun', requestedTag: 'proper_noun' },
    english: { target: 'routing', category: 'english', requestedTag: 'english' },
    cognate: { target: 'routing', category: 'cognate', requestedTag: 'cognate' },
    lemma: { target: 'lemma', category: 'lemma' },
    elision: { target: 'surface', category: 'morphology' },
    'card-pos': { target: 'card', category: 'pos' },
    'sense-pos': { target: 'sense', category: 'pos' },
    pairing: { target: 'pairing', category: 'matching' },
    card: { target: 'card', category: 'other' }
};

function _flagCanonicalQuick(target) {
    return FLAG_QUICK_CANONICAL[target] || { target: target, category: 'other' };
}

function _flagMenuCard() {
    return (typeof flashcards !== 'undefined' && flashcards) ? flashcards[currentIndex] : null;
}

function _flagMenuExample(meaning) {
    if (window._currentDisplayedExample) return window._currentDisplayedExample;
    const examples = (meaning && meaning.allExamples) || [];
    if (!examples.length) return null;
    const index = (typeof currentExampleIndex === 'number')
        ? currentExampleIndex % examples.length : 0;
    return examples[index] || examples[0];
}

function _flagTextHash(value) {
    let hash = 5381;
    for (const char of String(value || '')) {
        hash = ((hash << 5) + hash) ^ char.codePointAt(0);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

function _flagActiveDetail(meaning) {
    const cycleIndex = typeof currentMWEIndex === 'number' ? currentMWEIndex : 0;
    if (meaning?.allMWEs?.length) {
        const item = meaning.allMWEs[cycleIndex % meaning.allMWEs.length];
        return {
            kind: 'Expression', id: item.id || '', label: item.expression || '',
            translation: item.translation || '', family: item.family || ''
        };
    }
    if (meaning?.allClitics?.length) {
        const item = meaning.allClitics[cycleIndex % meaning.allClitics.length];
        return {
            kind: 'Clitic', id: item.id || '', label: item.form || '',
            translation: item.translation || '', family: ''
        };
    }
    if (meaning?.allSenses?.length) {
        const item = meaning.allSenses[cycleIndex % meaning.allSenses.length];
        return {
            kind: 'Remainder sense', id: item.sense_id || item.id || '',
            label: item.translation || item.meaning || '', translation: '',
            family: '', context: item.context || ''
        };
    }
    return null;
}

function _flagTargetLabel() {
    return FLAG_TARGETS.find(item => item.key === _flagTarget)?.label || _flagTarget;
}

function _flagCategoryLabel() {
    return [...FLAG_CATEGORIES, ...FLAG_ROUTING_TAGS]
        .find(item => item.key === _flagCategory)?.label || 'Unspecified';
}

function _focusFlagNote() {
    requestAnimationFrame(() => {
        const note = document.getElementById('flagMenuNote');
        if (!note) return;
        note.focus();
        note.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
}

function _updateFlagConfirmState() {
    const confirmEl = document.getElementById('flagMenuConfirm');
    const noteSendEl = document.getElementById('flagMenuNoteSend');
    if (!confirmEl && !noteSendEl) return;
    const note = (document.getElementById('flagMenuNote')?.value || '').trim();
    const noteRequired = _flagTarget === 'note';
    const routingRequired = _flagTarget === 'routing';
    if (confirmEl) {
        confirmEl.disabled = (noteRequired && !note) || (routingRequired && !_flagCategory);
        confirmEl.textContent = noteRequired
            ? 'Send note'
            : routingRequired
                ? `Tag as ${_flagCategoryLabel()}`
                : 'Send audit flag';
        confirmEl.title = noteRequired && !note
            ? 'Type the note before sending it'
            : routingRequired
                ? `Send the ${_flagCategoryLabel()} classification to the data audit`
                : 'Send this report to the data audit';
    }
    if (noteSendEl) noteSendEl.disabled = !note;
}

function _renderFlagMenu() {
    const card = _flagMenuCard();
    const bodyEl = document.querySelector('#flagMenu .card-meta-body');
    const footerEl = document.querySelector('#flagMenu .card-meta-footer');
    const hintEl = document.getElementById('flagMenuHint');
    const quickSectionEl = document.getElementById('flagMenuQuickSection');
    const targetSectionEl = document.getElementById('flagMenuTargetSection');
    const sensesEl = document.getElementById('flagMenuSenses');
    const targetsEl = document.getElementById('flagMenuTargets');
    const quickActionsEl = document.getElementById('flagMenuQuickActions');
    const categoriesEl = document.getElementById('flagMenuCategories');
    const senseSectionEl = document.getElementById('flagMenuSenseSection');
    const categorySectionEl = document.getElementById('flagMenuCategorySection');
    const previewSectionEl = document.getElementById('flagMenuPreviewSection');
    const noteSectionEl = document.getElementById('flagMenuNoteSection');
    const noteSummaryEl = document.getElementById('flagMenuNoteSummary');
    const titleEl = document.getElementById('flagMenuTitle');
    const previewEl = document.getElementById('flagMenuPairingPreview');
    if (!card || !sensesEl || !targetsEl || !quickActionsEl || !categoriesEl) return;

    const word = card.targetWord || card.word || 'card';
    const noteMode = _flagTarget === 'note';
    const routingMode = _flagTarget === 'routing';
    const needsSense = FLAG_SENSE_TARGETS.has(_flagTarget);
    if (titleEl) titleEl.textContent = noteMode ? `Send a note: ${word}` : `Flag: ${word}`;

    const meanings = card.meanings || [];
    // Clamp selection into range.
    if (_flagSelIdx < 0) _flagSelIdx = 0;
    if (_flagSelIdx > meanings.length - 1) _flagSelIdx = Math.max(0, meanings.length - 1);

    bodyEl?.classList.toggle('is-note-mode', noteMode);
    if (hintEl) hintEl.textContent = noteMode
        ? 'Write what you noticed below. Nothing is sent until you tap Send note.'
        : 'Tell the data audit exactly where to look. The visible sense and example start selected.';
    if (quickSectionEl) quickSectionEl.hidden = false;
    if (targetSectionEl) targetSectionEl.hidden = noteMode;
    if (senseSectionEl) senseSectionEl.hidden = noteMode || !needsSense;
    if (categorySectionEl) categorySectionEl.hidden = noteMode || routingMode;
    if (previewSectionEl) previewSectionEl.hidden = noteMode;
    if (noteSectionEl) {
        noteSectionEl.hidden = false;
        if (noteMode) noteSectionEl.open = true;
    }
    if (footerEl) footerEl.hidden = noteMode;
    if (noteSummaryEl) noteSummaryEl.textContent = noteMode ? 'Send a note' : 'Add details';
    if (!meanings.length) {
        sensesEl.innerHTML = '<li class="card-meta-empty">No senses on this card.</li>';
    } else {
        sensesEl.innerHTML = meanings.map((m, i) => {
            const gloss = m.meaning || m.translation || '';
            const pct = (typeof m.percentage === 'number') ? (m.percentage * 100).toFixed(0) + '%' : '';
            const sel = (needsSense && i === _flagSelIdx) ? ' selected' : '';
            return `<li class="flag-menu-sense${sel}" data-idx="${i}" role="option" aria-selected="${needsSense && i === _flagSelIdx}">
                <span class="fm-pos">${_escapeHtml(m.pos || '?')}</span>
                <span class="fm-gloss">${_escapeHtml(gloss)}</span>
                ${pct ? `<span class="fm-pct">${pct}</span>` : ''}
            </li>`;
        }).join('');
    }

    quickActionsEl.innerHTML = `
        <button type="button" class="flag-menu-quick-action flag-menu-quick-note${noteMode ? ' selected' : ''}" data-quick-target="note">
            <strong>Add a note</strong><span>Write it here before sending</span>
        </button>
        ${FLAG_ROUTING_TAGS.map(item => `
            <button type="button" class="flag-menu-quick-action${routingMode && _flagCategory === item.key ? ' selected' : ''}" data-quick-target="routing" data-quick-category="${item.key}">
                <strong>${item.shortLabel}</strong><span>${item.detail}</span>
            </button>
        `).join('')}
    `;

    targetsEl.innerHTML = FLAG_TARGETS.filter(item => !item.quickOnly).map(item => {
        const sel = item.key === _flagTarget ? ' selected' : '';
        return `<button type="button" class="flag-menu-target${sel}" data-target="${item.key}">
            <strong>${item.label}</strong><span>${item.detail}</span>
        </button>`;
    }).join('');

    categoriesEl.innerHTML = FLAG_CATEGORIES.map(item => {
        const sel = item.key === _flagCategory ? ' selected' : '';
        const disabled = _flagTarget === 'note' ? ' disabled' : '';
        return `<button type="button" class="flag-menu-category${sel}" data-category="${item.key}"${disabled}>${item.label}</button>`;
    }).join('');
    categoriesEl.classList.toggle('is-disabled', _flagTarget === 'note');

    const selectedMeaning = meanings[_flagSelIdx] || null;
    const selectedExample = _flagMenuExample(selectedMeaning);
    const activeDetail = _flagActiveDetail(selectedMeaning);
    if (previewEl) {
        const gloss = selectedMeaning
            ? (selectedMeaning.meaning || selectedMeaning.translation || '') : '';
        const spanish = selectedExample
            ? (selectedExample.spanish || selectedExample.target || selectedExample.targetSentence || selectedExample.original || '') : '';
        const english = selectedExample?.english || selectedExample?.englishSentence || '';
        const senseHTML = `<div class="flag-pairing-sense"><span>${_escapeHtml(activeDetail?.kind || selectedMeaning?.pos || '?')}</span>${_escapeHtml(activeDetail?.label || gloss || 'No sense text')}</div>`;
        const exampleHTML = `<div class="flag-pairing-example">${_escapeHtml(spanish || 'No visible example')}${english ? `<small>${_escapeHtml(english)}</small>` : ''}</div>`;
        const word = card.targetWord || card.word || '';
        const lemma = card.lemma || word;
        const previews = {
            pairing: `${senseHTML}<div class="flag-pairing-arrow" aria-hidden="true">linked to</div>${exampleHTML}`,
            sense: `${senseHTML}${selectedMeaning?.context ? `<div class="flag-preview-context">${_escapeHtml(selectedMeaning.context)}</div>` : ''}`,
            example: exampleHTML,
            lemma: `<div class="flag-preview-object"><span>Lemma</span><strong>${_escapeHtml(lemma || 'Missing')}</strong><small>Current form: ${_escapeHtml(word || 'unknown')}</small></div>`,
            surface: `<div class="flag-preview-object"><span>Word form</span><strong>${_escapeHtml(word || 'Missing')}</strong><small>Lemma: ${_escapeHtml(lemma || 'unknown')}</small></div>`,
            card: `<div class="flag-preview-object"><span>Whole card</span><strong>${_escapeHtml(word || 'Unknown card')}</strong><small>${_escapeHtml(card.fullId || card.id || 'No card ID')}</small></div>`,
            note: '<div class="flag-preview-object"><span>Note only</span><strong>No field selected</strong><small>Your note will still include the current card ID for audit context.</small></div>',
            routing: `<div class="flag-preview-object"><span>Classification tag</span><strong>${_escapeHtml(_flagCategoryLabel())}</strong><small>${_escapeHtml(word || 'Unknown card')} · ${_escapeHtml(card.fullId || card.id || 'No card ID')}</small></div>`
        };
        previewEl.innerHTML = previews[_flagTarget] || previews.card;
    }

    // Wire row + issue clicks (innerHTML wiped the previous listeners).
    sensesEl.querySelectorAll('.flag-menu-sense').forEach(li => {
        li.addEventListener('click', () => {
            const idx = parseInt(li.dataset.idx, 10);
            if (!isNaN(idx)) {
                flagMenuSelect(idx);
            }
        });
    });
    quickActionsEl.querySelectorAll('.flag-menu-quick-action').forEach(btn => {
        btn.addEventListener('click', () => {
            const requestedTarget = btn.dataset.quickTarget;
            if (requestedTarget === 'note' && _flagTarget === 'note') {
                _flagTarget = 'pairing';
                _flagCategory = 'matching';
                if (noteSectionEl) noteSectionEl.open = false;
            } else {
                _flagTarget = requestedTarget;
                _flagCategory = btn.dataset.quickCategory || '';
                if (_flagTarget !== 'note' && noteSectionEl) noteSectionEl.open = false;
            }
            _renderFlagMenu();
            if (_flagTarget === 'note') _focusFlagNote();
        });
    });
    targetsEl.querySelectorAll('.flag-menu-target').forEach(btn => {
        btn.addEventListener('click', () => {
            _flagTarget = btn.dataset.target;
            _flagCategory = _flagTarget === 'note'
                ? ''
                : (FLAG_DEFAULT_CATEGORY[_flagTarget] || 'other');
            _renderFlagMenu();
        });
    });
    categoriesEl.querySelectorAll('.flag-menu-category').forEach(btn => {
        btn.addEventListener('click', () => {
            if (_flagTarget === 'note') return;
            _flagCategory = btn.dataset.category === _flagCategory ? '' : btn.dataset.category;
            _renderFlagMenu();
        });
    });
    _updateFlagConfirmState();
}

// Highlight a sense AND sync the underlying card to it (reuses selectMeaning),
// so the sense pill the user is flagging is the one shown on the card behind
// the menu.
function flagMenuSelect(idx) {
    _flagSelIdx = idx;
    if (typeof window.selectMeaning === 'function'
        && typeof currentMeaningIndex === 'number'
        && idx !== currentMeaningIndex) {
        window.selectMeaning(idx);
    }
    _renderFlagMenu();
}

// Up/down through the sense rows (clamped, no wrap).
function flagMenuNav(delta) {
    const card = _flagMenuCard();
    const n = (card && card.meanings) ? card.meanings.length : 0;
    if (n <= 1) return;
    if (!FLAG_SENSE_TARGETS.has(_flagTarget)) return;
    let next = _flagSelIdx + delta;
    if (next < 0) next = 0;
    if (next > n - 1) next = n - 1;
    if (next !== _flagSelIdx) flagMenuSelect(next);
    else _renderFlagMenu();
}

function showFlagMenu() {
    const pop = document.getElementById('flagMenu');
    const card = _flagMenuCard();
    if (!pop || !card) return;
    _flagSelIdx = (typeof currentMeaningIndex === 'number') ? currentMeaningIndex : 0;
    _flagTarget = 'pairing';
    _flagCategory = 'matching';
    const note = document.getElementById('flagMenuNote');
    if (note) note.value = '';
    const noteSection = document.getElementById('flagMenuNoteSection');
    if (noteSection) noteSection.open = false;
    _renderFlagMenu();
    pop.hidden = false;
    pop.setAttribute('aria-hidden', 'false');
}

function hideFlagMenu() {
    const pop = document.getElementById('flagMenu');
    if (!pop) return;
    pop.hidden = true;
    pop.setAttribute('aria-hidden', 'true');
}

function flagMenuConfirm() {
    const card = _flagMenuCard();
    if (!card) { hideFlagMenu(); return; }
    const meanings = card.meanings || [];
    const m = meanings[_flagSelIdx] || null;
    const gloss = m ? (m.meaning || m.translation || '') : '';
    const example = _flagMenuExample(m);
    const spanish = example
        ? (example.spanish || example.target || example.targetSentence || example.original || '') : '';
    const english = example?.english || example?.englishSentence || '';
    const song = example?.song_name || example?.song || '';
    const note = (document.getElementById('flagMenuNote')?.value || '').trim().slice(0, 600);
    if (_flagTarget === 'note' && !note) {
        document.getElementById('flagMenuNote')?.focus();
        _updateFlagConfirmState();
        return;
    }
    const word = card.targetWord || card.word || '';
    const lemma = card.lemma || word;
    const cardId = card.fullId || card.id || '';
    const senseId = m?.sense_id || m?.senseId || m?.id || '';
    const activeDetail = _flagActiveDetail(m);
    const stableSenseRef = activeDetail?.id || senseId || String(_flagSelIdx);

    let path;
    switch (_flagTarget) {
        case 'lemma':
            path = `lemma:${_flagTextHash(lemma)}`;
            break;
        case 'sense':
            path = `sense:${stableSenseRef}`;
            break;
        case 'example':
            path = `example:${stableSenseRef}:${_flagTextHash(spanish)}`;
            break;
        case 'surface':
            path = `surface:${_flagTextHash(word)}`;
            break;
        case 'card':
            path = 'card';
            break;
        case 'routing':
            path = `routing:${_flagCategory || 'unspecified'}`;
            break;
        case 'note':
            path = `note:${Date.now()}`;
            break;
        case 'pairing':
        default:
            path = `pairing:${stableSenseRef}:${_flagTextHash(spanish)}`;
            break;
    }

    const reportLines = [
        '[Audit flag]',
        `Target: ${_flagTargetLabel()}`,
        `Category: ${_flagCategoryLabel()}`,
        `Word: ${word}`,
        `Lemma: ${lemma}`,
        `Card ID: ${cardId || '(missing)'}`,
    ];
    const displayedSurface = card._activeExampleSurface || card.displaySurface || word;
    if (displayedSurface && displayedSurface !== word) {
        reportLines.push(`Displayed form: ${displayedSurface}`);
    }
    if (FLAG_SENSE_TARGETS.has(_flagTarget)) {
        reportLines.push(`Sense ${_flagSelIdx + 1}: ${m?.pos || '?'} · ${gloss || '(empty)'}`);
        if (senseId) reportLines.push(`Sense ID: ${senseId}`);
        if (m?.context) reportLines.push(`Context: ${m.context}`);
        if (m?.assignment_method) reportLines.push(`Sense assignment: ${m.assignment_method}`);
        if (m?.unassigned) reportLines.push('Sense status: unassigned');
        if (activeDetail) {
            reportLines.push(`${activeDetail.kind}: ${activeDetail.label || '(empty)'} · ${activeDetail.translation || '(untranslated)'}`);
            if (activeDetail.id) reportLines.push(`${activeDetail.kind} ID: ${activeDetail.id}`);
            if (activeDetail.family) reportLines.push(`Expression family: ${activeDetail.family}`);
            if (activeDetail.context) reportLines.push(`${activeDetail.kind} context: ${activeDetail.context}`);
        }
    }
    if (_flagTarget === 'pairing' || _flagTarget === 'example') {
        reportLines.push(`Example: ${spanish || '(none visible)'}`);
        if (english) reportLines.push(`Translation: ${english}`);
        if (song) reportLines.push(`Source: ${song}`);
        if (example?.artist || example?.artist_name) reportLines.push(`Artist: ${example.artist || example.artist_name}`);
        if (example?.assignment_method) reportLines.push(`Example assignment: ${example.assignment_method}`);
        if (example?.translation_source) reportLines.push(`Translation source: ${example.translation_source}`);
        const spotifyRef = example?.spotify_url || example?.spotifyUrl || example?.spotify_track_id || example?.track_id;
        if (spotifyRef) reportLines.push(`Spotify: ${spotifyRef}`);
        const start = example?.start_ms ?? example?.timestamp_ms ?? example?.position_ms;
        const end = example?.end_ms;
        if (start != null || end != null) reportLines.push(`Timing: ${start ?? '?'}–${end ?? '?'} ms`);
    }
    if (_flagTarget === 'surface' || _flagCategory === 'morphology') {
        const morphology = card.morphology ? JSON.stringify(card.morphology).slice(0, 500) : '';
        reportLines.push(`Morphology: ${morphology || '(none)'}`);
    }
    if (_flagCategory === 'frequency') {
        reportLines.push(`Rank: ${card.vocabularyRank || card.rank || '(none)'}`);
        reportLines.push(`Corpus count: ${card.corpusCount ?? card.corpus_count ?? '(none)'}`);
    }
    if (_flagTarget === 'routing') {
        reportLines.push(`Requested classification: ${_flagCategoryLabel()}`);
        reportLines.push(`Current is_english: ${card.is_english ?? '(missing)'}`);
        reportLines.push(`Current is_english_loanword: ${card.is_english_loanword ?? '(missing)'}`);
        reportLines.push(`Current cognate score: ${card.cognate_score ?? '(missing)'}`);
    }
    if (note) reportLines.push(`Note: ${note}`);
    const report = reportLines.join('\n');

    const isSenseTarget = FLAG_SENSE_TARGETS.has(_flagTarget);
    const isExampleTarget = _flagTarget === 'pairing' || _flagTarget === 'example';
    const fields = {
        schemaVersion: 2,
        target: _flagTarget,
        category: _flagTarget === 'routing' ? _flagCategory : (_flagCategory || ''),
        requestedTag: _flagTarget === 'routing' ? _flagCategory : '',
        wordText: word,
        lemma: lemma,
        cardId: cardId,
        sensePos: isSenseTarget ? (m?.pos || '') : '',
        senseId: isSenseTarget ? senseId : '',
        senseGloss: isSenseTarget ? gloss : '',
        context: isSenseTarget ? (m?.context || '') : '',
        senseAssignment: isSenseTarget ? (m?.assignment_method || '') : '',
        example: isExampleTarget ? spanish : '',
        translation: isExampleTarget ? english : '',
        song: isExampleTarget ? song : '',
        exampleAssignment: isExampleTarget ? (example?.assignment_method || '') : '',
        translationSource: isExampleTarget ? (example?.translation_source || '') : '',
        note: note
    };

    if (typeof flagWord === 'function') {
        flagWord(card, path, report, fields);
    }
    hideFlagMenu();
    // Hand back to core flashcards.js for the flag animation + advance.
    if (typeof window.advanceAfterFlag === 'function') window.advanceAfterFlag();
}

// Close button, backdrop dismiss, and keyboard control while open. The menu
// owns arrows/Enter/Esc when visible; core flashcards.js's global keydown
// bails out while #flagMenu is not hidden, so there's no double-handling.
(function _initFlagMenuInternals() {
    const pop = document.getElementById('flagMenu');
    if (!pop) return;
    const closeBtn = document.getElementById('flagMenuClose');
    const confirmBtn = document.getElementById('flagMenuConfirm');
    const content = document.getElementById('flagMenuContent');
    const note = document.getElementById('flagMenuNote');
    const noteBack = document.getElementById('flagMenuNoteBack');
    const noteSend = document.getElementById('flagMenuNoteSend');
    if (closeBtn) closeBtn.addEventListener('click', hideFlagMenu);
    if (confirmBtn) confirmBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        flagMenuConfirm();
    });
    if (noteBack) noteBack.addEventListener('click', () => {
        _flagTarget = 'pairing';
        _flagCategory = 'matching';
        const noteSection = document.getElementById('flagMenuNoteSection');
        if (noteSection) noteSection.open = false;
        _renderFlagMenu();
        document.getElementById('flagMenuQuickSection')?.scrollIntoView({ block: 'start' });
    });
    if (noteSend) noteSend.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!note?.value.trim()) return;
        flagMenuConfirm();
    });
    if (note) {
        note.addEventListener('input', _updateFlagConfirmState);
    }
    document.addEventListener('click', (e) => {
        if (pop.hidden) return;
        if (content && content.contains(e.target)) return;
        hideFlagMenu();
    });
    document.addEventListener('keydown', (e) => {
        if (pop.hidden) return;
        if (e.key === 'Escape') { e.preventDefault(); hideFlagMenu(); }
    });
})();

// ---------------------------------------------------------------------------
// Simplified audit flow. The previous target/category matrix remains above for
// payload compatibility, but this is the only UI exposed to the learner.
// Every action has one explicit send gesture; successful non-card flags keep
// the sheet open, while the whole-card action confirms and then closes.
// ---------------------------------------------------------------------------
let _simpleFlagBusy = false;
let _simpleFlagCloseTimer = null;

function _simpleFlagStatus(message, isError = false) {
    const status = document.getElementById('flagMenuStatus');
    if (!status) return;
    status.hidden = false;
    status.textContent = message;
    status.classList.toggle('is-error', isError);
}

function _simpleFlagExample(meaning, index) {
    if (index === currentMeaningIndex && window._currentDisplayedExample) {
        return window._currentDisplayedExample;
    }
    return meaning?.allExamples?.[0] || null;
}

function _simpleFlagReport(target, { meaningIndex = 0, note = '' } = {}) {
    const card = _flagMenuCard();
    const meaning = card?.meanings?.[meaningIndex] || null;
    const example = _simpleFlagExample(meaning, meaningIndex);
    const word = card?.targetWord || card?.word || '';
    const lemma = card?.lemma || word;
    const gloss = meaning?.meaning || meaning?.translation || '';
    const spanish = example?.spanish || example?.target || example?.targetSentence || example?.original || '';
    const english = example?.english || example?.englishSentence || '';
    const labels = {
        note: 'Note', propernoun: 'Proper noun', english: 'English', cognate: 'Cognate',
        lemma: 'Wrong lemma', elision: 'Wrong elision correction',
        'card-pos': 'Wrong card POS', 'sense-pos': 'Wrong sense POS',
        pairing: 'Sense–meaning pairing', card: 'Whole card'
    };
    const lines = [
        '[Audit flag]',
        `Target: ${labels[target] || target}`,
        `Word: ${word}`,
        `Lemma: ${lemma}`,
        `Card ID: ${card?.fullId || card?.id || '(missing)'}`
    ];
    if (target === 'pairing' || target === 'sense-pos') {
        lines.push(`Sense ${meaningIndex + 1}: ${meaning?.pos || '?'} · ${gloss || '(empty)'}`);
        const senseId = meaning?.sense_id || meaning?.senseId || meaning?.id;
        if (senseId) lines.push(`Sense ID: ${senseId}`);
        if (meaning?.context) lines.push(`Context: ${meaning.context}`);
        if (meaning?.assignment_method) lines.push(`Sense assignment: ${meaning.assignment_method}`);
        if (target === 'pairing') {
            lines.push(`Example: ${spanish || '(none visible)'}`);
            if (english) lines.push(`Translation: ${english}`);
            if (example?.song_name || example?.song) lines.push(`Source: ${example.song_name || example.song}`);
            if (example?.assignment_method) lines.push(`Example assignment: ${example.assignment_method}`);
        }
    }
    if (target === 'propernoun') lines.push('Requested classification: Proper noun', `Current is_propernoun: ${card?.is_propernoun ?? '(missing)'}`);
    if (target === 'english') lines.push('Requested classification: English', `Current is_english: ${card?.is_english ?? '(missing)'}`);
    if (target === 'cognate') lines.push('Requested classification: Cognate', `Current cognate score: ${card?.cognate_score ?? '(missing)'}`);
    if (target === 'elision') {
        lines.push(`Displayed form: ${card?._activeExampleSurface || card?.displaySurface || word}`);
        lines.push(`Morphology: ${card?.morphology ? JSON.stringify(card.morphology).slice(0, 500) : '(none)'}`);
    }
    if (target === 'card-pos') {
        const cardPos = card?.pos || card?.partOfSpeech || [...new Set((card?.meanings || []).map(item => item?.pos).filter(Boolean))].join(', ');
        lines.push(`Current card POS: ${cardPos || '(missing)'}`);
    }
    if (note) lines.push(`Note: ${note}`);
    return lines.join('\n');
}

function _simpleFlagPath(target, meaningIndex = 0) {
    const card = _flagMenuCard();
    const meaning = card?.meanings?.[meaningIndex] || null;
    const example = _simpleFlagExample(meaning, meaningIndex);
    const senseRef = meaning?.sense_id || meaning?.senseId || meaning?.id || meaningIndex;
    const spanish = example?.spanish || example?.target || example?.targetSentence || '';
    const paths = {
        propernoun: 'routing:propernoun', english: 'routing:english', cognate: 'routing:cognate',
        lemma: `lemma:${_flagTextHash(card?.lemma || '')}`,
        elision: `surface:elision:${_flagTextHash(card?._activeExampleSurface || card?.displaySurface || card?.targetWord || '')}`,
        'card-pos': 'card:pos',
        card: 'card'
    };
    if (target === 'note') return `note:${Date.now()}`;
    if (target === 'pairing') return `pairing:${senseRef}:${_flagTextHash(spanish)}`;
    if (target === 'sense-pos') return `sense:${senseRef}:pos`;
    return paths[target] || target;
}

// Structured payload for the quick-action path, folded onto the same canonical
// vocabulary the full menu emits so the audit sheet has one Target/Category
// namespace regardless of which control raised the flag.
function _simpleFlagFields(target, { meaningIndex = 0, note = '' } = {}) {
    const card = _flagMenuCard();
    const meaning = card?.meanings?.[meaningIndex] || null;
    const example = _simpleFlagExample(meaning, meaningIndex);
    const canonical = _flagCanonicalQuick(target);
    const isSense = target === 'pairing' || target === 'sense-pos';
    const isExample = target === 'pairing';
    const word = card?.targetWord || card?.word || '';
    return {
        schemaVersion: 2,
        target: canonical.target,
        category: canonical.category || '',
        requestedTag: canonical.requestedTag || '',
        wordText: word,
        lemma: card?.lemma || word,
        cardId: card?.fullId || card?.id || '',
        sensePos: isSense ? (meaning?.pos || '') : '',
        senseId: isSense ? (meaning?.sense_id || meaning?.senseId || meaning?.id || '') : '',
        senseGloss: isSense ? (meaning?.meaning || meaning?.translation || '') : '',
        context: isSense ? (meaning?.context || '') : '',
        senseAssignment: isSense ? (meaning?.assignment_method || '') : '',
        example: isExample
            ? (example?.spanish || example?.target || example?.targetSentence || example?.original || '') : '',
        translation: isExample ? (example?.english || example?.englishSentence || '') : '',
        song: isExample ? (example?.song_name || example?.song || '') : '',
        exampleAssignment: isExample ? (example?.assignment_method || '') : '',
        translationSource: isExample ? (example?.translation_source || '') : '',
        note: note || ''
    };
}

async function _sendSimpleFlag(target, options = {}) {
    if (_simpleFlagBusy) return false;
    const card = _flagMenuCard();
    if (!card || typeof flagWord !== 'function') return false;
    _simpleFlagBusy = true;
    document.getElementById('flagMenuContent')?.classList.add('is-sending');
    try {
        const ok = await flagWord(
            card,
            _simpleFlagPath(target, options.meaningIndex || 0),
            _simpleFlagReport(target, options),
            _simpleFlagFields(target, options)
        );
        if (!ok) {
            _simpleFlagStatus('This flag could not be saved. Please sign in and try again.', true);
            return false;
        }
        const labels = {
            note: 'Note sent.', propernoun: 'Proper noun flag sent.', english: 'English flag sent.',
            cognate: 'Cognate flag sent.', lemma: 'Wrong lemma flag sent.',
            elision: 'Wrong elision correction flag sent.',
            'card-pos': 'Wrong card POS flag sent.', 'sense-pos': 'Wrong sense POS flag sent.',
            pairing: 'Sense–meaning pairing flag sent.', card: 'Whole-card flag sent.'
        };
        _simpleFlagStatus(labels[target] || 'Flag sent.');
        return true;
    } catch (error) {
        console.error('Could not save audit flag', error);
        _simpleFlagStatus('This flag could not be saved. Please try again.', true);
        return false;
    } finally {
        _simpleFlagBusy = false;
        document.getElementById('flagMenuContent')?.classList.remove('is-sending');
    }
}

function _renderSimpleSenses() {
    const card = _flagMenuCard();
    const host = document.getElementById('flagSimpleSenses');
    if (!host) return;
    const meanings = card?.meanings || [];
    host.innerHTML = meanings.length ? meanings.map((meaning, index) => {
        const example = _simpleFlagExample(meaning, index);
        const spanish = example?.spanish || example?.target || example?.targetSentence || '';
        const english = example?.english || example?.englishSentence || '';
        return `<article class="flag-simple-sense">
            <div class="flag-simple-sense-meaning"><span>${_escapeHtml(meaning.pos || '?')}</span><strong>${_escapeHtml(meaning.meaning || meaning.translation || '(empty meaning)')}</strong></div>
            <div class="flag-simple-sense-example">${_escapeHtml(spanish || 'No paired example')}${english ? `<small>${_escapeHtml(english)}</small>` : ''}</div>
            <div class="flag-simple-sense-actions">
                <button type="button" data-flag-sense="${index}">Flag this pairing</button>
                <button type="button" data-flag-sense-pos="${index}">Wrong POS</button>
            </div>
        </article>`;
    }).join('') : '<div class="card-meta-empty">No senses are available on this card.</div>';
}

function showSimpleFlagMenu() {
    const pop = document.getElementById('flagMenu');
    const card = _flagMenuCard();
    if (!pop || !card) return;
    if (_simpleFlagCloseTimer) clearTimeout(_simpleFlagCloseTimer);
    document.getElementById('flagMenuTitle').textContent = `Flag: ${card.targetWord || card.word || 'card'}`;
    document.getElementById('flagMenuMainView').hidden = false;
    document.getElementById('flagMenuSensesView').hidden = true;
    const status = document.getElementById('flagMenuStatus');
    if (status) { status.hidden = true; status.textContent = ''; status.classList.remove('is-error'); }
    const note = document.getElementById('flagMenuNote');
    if (note) note.value = '';
    const sendNote = document.getElementById('flagSimpleSendNote');
    if (sendNote) sendNote.disabled = true;
    _renderSimpleSenses();
    pop.hidden = false;
    pop.setAttribute('aria-hidden', 'false');
}

(function _initSimpleFlagMenu() {
    const note = document.getElementById('flagMenuNote');
    const sendNote = document.getElementById('flagSimpleSendNote');
    note?.addEventListener('input', () => { if (sendNote) sendNote.disabled = !note.value.trim(); });
    sendNote?.addEventListener('click', async () => {
        const text = note?.value.trim().slice(0, 600) || '';
        if (!text) return note?.focus();
        if (await _sendSimpleFlag('note', { note: text })) {
            note.value = '';
            sendNote.disabled = true;
        }
    });
    document.querySelectorAll('[data-simple-flag]').forEach(button => {
        button.addEventListener('click', () => _sendSimpleFlag(button.dataset.simpleFlag));
    });
    document.getElementById('flagOpenSenses')?.addEventListener('click', () => {
        document.getElementById('flagMenuMainView').hidden = true;
        document.getElementById('flagMenuSensesView').hidden = false;
        _renderSimpleSenses();
    });
    document.getElementById('flagSensesBack')?.addEventListener('click', () => {
        document.getElementById('flagMenuSensesView').hidden = true;
        document.getElementById('flagMenuMainView').hidden = false;
    });
    document.getElementById('flagSimpleSenses')?.addEventListener('click', event => {
        const button = event.target.closest('[data-flag-sense]');
        const posButton = event.target.closest('[data-flag-sense-pos]');
        if (button) _sendSimpleFlag('pairing', { meaningIndex: Number(button.dataset.flagSense) });
        else if (posButton) _sendSimpleFlag('sense-pos', { meaningIndex: Number(posButton.dataset.flagSensePos) });
    });
    document.getElementById('flagWholeCard')?.addEventListener('click', async () => {
        if (await _sendSimpleFlag('card')) {
            _simpleFlagCloseTimer = setTimeout(hideFlagMenu, 1100);
        }
    });
})();

window.showFlagMenu = showSimpleFlagMenu;
window.hideFlagMenu = hideFlagMenu;
window.flagMenuNav = flagMenuNav;
window.flagMenuSelect = flagMenuSelect;
window.flagMenuConfirm = flagMenuConfirm;

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
window.showEndOfDeckOptions = showEndOfDeckOptions;
window.hideDeckCompleteModal = hideDeckCompleteModal;
window.restartWithIncorrectCards = restartWithIncorrectCards;
window.restartAllCards = restartAllCards;
