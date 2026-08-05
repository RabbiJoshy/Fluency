// About → "See Example": an annotated walkthrough of real flashcards.
//
// The About copy already carries two small auto-playing demo cards
// (`demo://normal` / `demo://artist`, built in auth.js). Those show the card
// moving; they deliberately say nothing about what any part of it means.
// This module is the other half: a stepped tour where the card sits still,
// every element on it is numbered, and the numbers are explained beside it.
//
// Two constraints shape the implementation:
//
//   1. "Exact replica". The card is built from the same class names and the
//      same inline styles that updateCard() in flashcards.js emits, so it
//      inherits the real card's CSS rather than a lookalike stylesheet. Only
//      SIZE is overridden (see .about-example-card-inner in style.css), the
//      same trick the inline demo cards use.
//   2. "Spotify needs to work". The Spotify button is not a picture of a
//      button — it calls the real window.spotifyPlayTrack() with a real track
//      id and a real lyric timestamp, and the Spotify module handles the
//      login hand-off itself when the visitor isn't connected yet. Track ids
//      and timestamps below are lifted from Artists/spotify_tracks.json and
//      the Bad Bunny deck, so they play the actual line on the actual song.
//
// Everything else about the card is inert on purpose: no progress is written,
// no deck state is touched, nothing here needs the app to have loaded a
// vocabulary. The walkthrough works for a logged-out visitor landing on
// `?about=1`, which is the main audience for it.

// ---------------------------------------------------------------------------
// Demo cards — real entries, real lyrics, real track ids.
// ---------------------------------------------------------------------------
//
// `fuego` and `como` are genuine Bad Bunny deck entries (rank, line counts and
// sense splits match the built deck); `aunque` is the Speech-mode card the
// About copy already discusses. Percentages are the deck's own sense splits.

const ABOUT_EXAMPLE_CARDS = {
    fuego: {
        mode: 'lyrics',
        word: 'fuego',
        pos: 'NOUN',
        rank: 363,
        corpusCount: 32,
        meanings: [
            {
                pos: 'NOUN',
                translation: 'fire',
                context: 'element',
                pct: 70,
                examples: [
                    {
                        target: 'Donde hubo fuego, cenizas quedan',
                        english: 'Where there was fire, ashes remain',
                        song: 'X ÚLTIMA VEZ',
                        trackId: '48AJSd42lXpicsGqcgopof',
                        positionMs: 136010,
                        vocalists: 'Bad Bunny',
                    },
                    {
                        target: 'Y le prendiera fuego al que criticaba si repetía',
                        english: "And I'd set fire to anyone who criticised if I repeated myself",
                        song: 'YO VISTO ASÍ',
                        trackId: '5fROvzNghPid8mbKNDYvpJ',
                        positionMs: 135380,
                        vocalists: null,
                    },
                    {
                        target: 'A ti te gusta lo malo, irte a fuego conmigo',
                        english: 'You like the bad stuff, going wild with me',
                        song: 'Gato de Noche',
                        trackId: '54ELExv56KCAB4UP9cOCzC',
                        positionMs: 20040,
                        vocalists: 'Bad Bunny',
                    },
                ],
            },
            {
                pos: 'NOUN',
                translation: 'light',
                context: 'for smoking',
                pct: 20,
                examples: [
                    {
                        target: 'Fuego, desde que te vi me puse roja',
                        english: 'Fire — since I saw you I blushed',
                        song: 'PERFuMITO NUEVO',
                        trackId: '1Q9Efnm5csdCMFynISxL2x',
                        positionMs: 114800,
                        vocalists: 'RaiNao',
                    },
                ],
            },
            {
                pos: 'NOUN',
                translation: 'passion',
                context: 'emotion',
                pct: 10,
                examples: [
                    {
                        target: 'Y me voy a fuego, cuando se decide',
                        english: 'And I go all out, when it’s decided',
                        song: 'Satisfacción',
                        trackId: '21WvAGxPUNJARcZoSqswd7',
                        positionMs: 130310,
                        vocalists: 'Arcángel',
                    },
                ],
            },
        ],
    },

    como: {
        mode: 'lyrics',
        word: 'como',
        pos: 'CCONJ',
        rank: 26,
        corpusCount: 291,
        meanings: [
            {
                pos: 'CCONJ',
                translation: 'like',
                context: 'used to express comparison',
                pct: 90,
                examples: [
                    {
                        target: 'La luna nos quiere ver como nos tocamo’ los tres',
                        english: 'The moon wants to see the three of us touching each other',
                        song: 'Fantasía',
                        trackId: '72BQwM1wnBQCbjwjRu1rmF',
                        positionMs: 39000,
                        vocalists: 'Alex Sensation & Bad Bunny',
                    },
                    {
                        target: 'Hoy se vale to’-to’, como Calle 13',
                        english: 'Today anything goes, like Calle 13',
                        song: 'Dame Algo',
                        trackId: '4ByaTrfoYbXrmlbsTG8MTD',
                        positionMs: 40630,
                        vocalists: 'Bad Bunny',
                    },
                ],
            },
            {
                pos: 'CCONJ',
                translation: 'how',
                context: 'used with verbs of perception',
                pct: 10,
                examples: [
                    {
                        target: 'Como no sabía qué cartera comprarte, te las compré to’as',
                        english: "Since I didn't know which bag to buy you, I bought you all of them",
                        song: 'Give It Up',
                        trackId: '5dhOWHLE6k2uBeKRwDOniw',
                        positionMs: 112100,
                        vocalists: 'Bad Bunny',
                    },
                ],
            },
        ],
    },

    aunque: {
        mode: 'speech',
        word: 'aunque',
        pos: 'CCONJ',
        rank: 429,
        corpusCount: 229,
        meanings: [
            {
                pos: 'CCONJ',
                translation: 'even though',
                context: null,
                pct: 50,
                examples: [
                    {
                        target: 'Ella le escucha, aunque nadie más lo haga.',
                        english: 'She listens to him even though no one else does.',
                        sourceLabel: 'Speech example',
                    },
                ],
            },
            {
                pos: 'CCONJ',
                translation: 'although',
                context: null,
                pct: 30,
                examples: [
                    {
                        target: 'Estaré allí, aunque puede que llegue tarde.',
                        english: "I'll be there, although I may be late.",
                        sourceLabel: 'Speech example',
                    },
                ],
            },
            {
                pos: 'CCONJ',
                translation: 'even if',
                context: null,
                pct: 20,
                examples: [
                    {
                        target: 'Aunque no lo hagas, yo lo haré.',
                        english: "Even if you don't do it, I will.",
                        sourceLabel: 'Speech example',
                    },
                ],
            },
        ],
    },
};

// ---------------------------------------------------------------------------
// Steps — what the tour actually walks through.
// ---------------------------------------------------------------------------
//
// `anchor` on each note is a CSS selector resolved inside the rendered card;
// the first match gets a numbered badge and lights up when its note is
// hovered. Steps 1–3 are the same Lyrics card at three depths (front, sense
// list, lyric evidence) so the tour reads as one card being explored rather
// than three unrelated screenshots. Step 4 switches deck to show what changes
// when the examples come from subtitles instead of songs.

const ABOUT_EXAMPLE_STEPS = [
    {
        id: 'front',
        card: 'fuego',
        face: 'front',
        eyebrow: 'Lyrics · Bad Bunny',
        title: 'The front: one word, and why it’s here',
        blurb: 'Cards are ordered by how often the word actually appears in the '
             + 'catalogue, so the front carries the evidence for its position in the deck.',
        notes: [
            {
                anchor: '.card-word',
                title: 'The word',
                text: 'The Spanish word on its own. Try to recall the meaning before flipping — '
                    + 'that retrieval attempt is the part that makes it stick.',
            },
            {
                anchor: '.card-pos-list',
                title: 'Part of speech',
                text: 'Colour-coded and consistent across the app: nouns, verbs, adjectives and '
                    + 'function words each keep their own hue on every card.',
            },
            {
                anchor: '.card-rank-label',
                title: 'Vocabulary rank',
                text: '363rd most frequent word in the artist’s catalogue. Rank is the deck’s '
                    + 'ordering — you meet high-frequency words first because they pay off first.',
            },
            {
                anchor: '.card-freq-label',
                title: 'Lyric lines',
                text: 'How many lines across the catalogue contain this word. In Speech mode this '
                    + 'is replaced by frequency per million subtitle words.',
            },
            {
                anchor: '.about-example-flip-hint',
                title: 'Flip it',
                text: 'Tap the card to turn it over. Go ahead — this one is live.',
                interactive: true,
            },
        ],
    },
    {
        id: 'senses',
        card: 'fuego',
        face: 'back',
        eyebrow: 'Lyrics · Bad Bunny',
        title: 'The back: every meaning, with its share',
        blurb: 'Most words don’t have one translation. Rather than picking a winner and hiding '
             + 'the rest, the card shows the split the pipeline measured — and each meaning '
             + 'carries its own evidence.',
        notes: [
            {
                anchor: '.back-headword',
                title: 'The word again',
                text: 'Repeated at the top of the back so you keep your place while reading down.',
            },
            {
                anchor: '.meanings-scroll .meaning-row:nth-child(1)',
                title: 'The dominant sense',
                text: '“fire” accounts for roughly 70% of the times this word is used across '
                    + 'the catalogue. The highlighted row is the one currently selected.',
            },
            {
                anchor: '.meanings-scroll .meaning-row:nth-child(2)',
                title: 'The other senses',
                text: 'Tap any row to switch to it — the example below changes to a lyric where '
                    + 'that meaning is the one being used. Try “light”.',
                interactive: true,
            },
            {
                anchor: '.meaning-context',
                title: 'Disambiguating context',
                text: 'Where two senses share a translation, the dictionary context that separates '
                    + 'them is shown alongside it.',
            },
            {
                anchor: '.about-example-pct',
                title: 'The share',
                text: 'Worked out by classifying every line in the catalogue that contains the word, '
                    + 'so it reflects this artist’s usage rather than a general dictionary ordering.',
            },
        ],
    },
    {
        id: 'lyric',
        card: 'fuego',
        face: 'back',
        eyebrow: 'Lyrics · Bad Bunny',
        title: 'The evidence: a real line, on the real track',
        blurb: 'Every meaning is shown inside a lyric that actually uses it. The lyric is not '
             + 'decoration — it’s the thing that anchors the word to something you already know.',
        notes: [
            {
                anchor: '.example-word-highlight',
                title: 'The word in context',
                text: 'Highlighted inside the line so you can see the shape it takes in real use, '
                    + 'including any inflected or elided form.',
            },
            {
                anchor: '.translation',
                title: 'The line, translated',
                text: 'Underneath, so the meaning of the whole line is available without leaving '
                    + 'the card.',
            },
            {
                anchor: '.example-song-credit',
                title: 'The source',
                text: 'The track the line comes from, plus featured vocalists where the line isn’t '
                    + 'sung by the lead artist.',
            },
            {
                anchor: '.spotify-btn',
                title: 'Play it — for real',
                text: 'This button is live. It plays the track in your own Spotify, seeked to the '
                    + 'exact moment the line is sung. You’ll be asked to connect Spotify the first '
                    + 'time; Premium is required for in-app playback.',
                interactive: true,
            },
            {
                anchor: '.example-counter-group',
                title: 'More evidence',
                text: 'Where a sense has several lines, tap the lyric itself to cycle through them. '
                    + 'Seeing the same word in three different songs beats seeing it once.',
                interactive: true,
            },
        ],
    },
    {
        id: 'speech',
        card: 'aunque',
        face: 'back',
        eyebrow: 'Speech',
        title: 'Same card, different corpus',
        blurb: 'Speech decks are built the same way, from subtitle dialogue rather than lyrics. '
             + 'The anatomy is identical — only where the examples come from changes.',
        notes: [
            {
                anchor: '.back-headword',
                title: 'A function word, up front',
                text: 'Themed courses bury words like <em>aunque</em> behind vocabulary about food '
                    + 'and travel. Ordering by frequency brings it forward, because it’s how ideas '
                    + 'get joined together.',
            },
            {
                anchor: '.meanings-scroll',
                title: 'Three ways to translate it',
                text: 'Roughly 50% <em>even though</em>, 30% <em>although</em>, 20% <em>even if</em> — '
                    + 'each with a sentence where that reading is the one that fits.',
            },
            {
                anchor: '.example-song-credit',
                title: 'Subtitle sourcing',
                text: 'No track credit here: the line comes from OpenSubtitles or Tatoeba, chosen to '
                    + 'sit near your current level so a rare word isn’t hidden inside a rarer sentence.',
            },
            {
                anchor: '.sentence',
                title: 'Everything else is the same',
                text: 'Same sense rows, same highlighting, same tap-to-cycle. Learn the card once '
                    + 'and both decks read identically.',
            },
        ],
    },
];

// ---------------------------------------------------------------------------
// Card rendering — mirrors updateCard() in flashcards.js.
// ---------------------------------------------------------------------------

const POS_CLASS = {
    VERB: 'pos-verb', NOUN: 'pos-noun', ADJ: 'pos-adj', ADV: 'pos-adv',
    PREP: 'pos-prep', ADP: 'pos-prep', CONJ: 'pos-conj', CCONJ: 'pos-conj',
    SCONJ: 'pos-conj', PRON: 'pos-pron', DET: 'pos-det', INT: 'pos-int',
    INTJ: 'pos-int', NUM: 'pos-num', MWE: 'pos-mwe',
};

const POS_NAME = {
    VERB: 'verb', NOUN: 'noun', ADJ: 'adjective', ADV: 'adverb',
    PREP: 'preposition', ADP: 'preposition', CONJ: 'conjunction',
    CCONJ: 'conjunction', SCONJ: 'conjunction', PRON: 'pronoun',
    DET: 'determiner', INT: 'interjection', INTJ: 'interjection',
    NUM: 'number', MWE: 'expression',
};

const posClass = (pos) => POS_CLASS[String(pos || '').toUpperCase()] || '';
const posName = (pos) => POS_NAME[String(pos || '').toUpperCase()] || String(pos || '').toLowerCase();

function esc(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// Same word-boundary highlight the real card applies to its example sentence:
// unicode property escapes so Spanish letters are handled, case-insensitive so
// a sentence-initial "Fuego" still matches. The sentence is escaped first, so
// data can never inject markup.
function highlightWord(sentence, word) {
    const escaped = esc(sentence);
    if (!word) return escaped;
    const wordEsc = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    try {
        const re = new RegExp(`(?<![\\p{L}\\p{N}])(${wordEsc})(?![\\p{L}\\p{N}])`, 'giu');
        return escaped.replace(re, '<span class="example-word-highlight">$1</span>');
    } catch (_) {
        return escaped;  // engines without \p{...} support
    }
}

// Verbatim copy of the real card's Spotify mark so the button is visually and
// behaviourally identical — see the `spotifySvg` const in flashcards.js.
const SPOTIFY_SVG = '<svg width="44" height="44" viewBox="0 0 24 24" fill="#1DB954">'
    + '<path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34'
    + 'c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539'
    + '-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3'
    + 'c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6'
    + '-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36'
    + 'C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381'
    + ' 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/>'
    + '</svg>';

function renderFront(card) {
    const rankLabel = `<span class="card-rank-label">Vocabulary rank: `
        + `<strong class="card-stat-value">${card.rank.toLocaleString()}</strong></span>`;
    const count = `<strong class="card-stat-value">${card.corpusCount.toLocaleString()}</strong>`;
    const freqLabel = card.mode === 'lyrics'
        ? `<span class="card-freq-label">Lyric lines: ${count}</span>`
        : `<span class="card-freq-label">Frequency: ${count}/million</span>`;

    return `
        <div class="card-face card-front">
            <div class="card-word">${esc(card.word)}</div>
            <div class="card-pos-list" style="display: flex;">
                <span class="front-pos-unit"><span class="card-pos ${posClass(card.pos)}">${posName(card.pos)}</span></span>
            </div>
            <div class="card-ranking" style="display: flex;">${rankLabel}${freqLabel}</div>
            <div class="about-example-flip-hint" aria-hidden="true">Tap to flip</div>
            <div class="card-tint" aria-hidden="true"></div>
        </div>`;
}

// Sense rows. The real card emits several row layouts depending on how the
// meanings group; the singleton `.meaning-row-regular` branch below is the one
// these demo cards hit, reproduced with its inline styles intact so it picks
// up the live rules rather than a copy of them.
function renderMeaningRows(card, selectedIdx) {
    return card.meanings.map((m, idx) => {
        const isSelected = idx === selectedIdx;
        const bg = isSelected ? 'rgba(var(--sense-match-rgb), 0.2)' : 'rgba(255, 255, 255, 0.03)';
        const border = isSelected
            ? 'box-shadow: inset 3px 0 0 rgb(var(--sense-match-rgb)), inset -3px 0 0 rgb(var(--sense-match-rgb));'
            : '';
        const textColor = isSelected ? 'var(--text-primary)' : '#d7dee7';
        const ctx = m.context
            ? ` <span class="meaning-context">· ${esc(m.context)}</span>`
            : '';
        const pct = m.pct < 100
            ? `<span class="about-example-pct" style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%); font-family: var(--font-data); font-size: 14px; color: #c9d2dd; white-space: nowrap; pointer-events: none;">${m.pct}%</span>`
            : '';
        return `
            <div class="meaning-row meaning-row-regular${isSelected ? ' selected is-current-sense' : ''}" data-meaning-index="${idx}" style="position: relative; display: grid; grid-template-columns: 1fr; align-items: center; padding: 1px 2px; margin-bottom: 4px; background: ${bg}; ${border} border-radius: 8px; cursor: pointer; min-height: 39px;">
                <div class="meaning-row-body" style="display: flex; flex-direction: column; align-items: stretch; justify-content: center; min-width: 0; padding: 0 ${m.pct < 100 ? '42px' : '8px'} 0 8px;">
                    <span class="meaning-row-translation row-adaptive-text" style="font-weight: ${isSelected ? 700 : 500}; color: ${textColor}; text-align: center; width: 100%;">${esc(m.translation)}${ctx}</span>
                </div>
                ${pct}
            </div>`;
    }).join('');
}

// Credit strip beneath the lyric: song + vocalists on the left, autoplay /
// Spotify / example counter on the right. Speech cards have no track, so the
// strip degrades to a right-aligned source label, exactly as on a live card.
function renderCredit(card, meaning, example, exampleIdx) {
    const counter = meaning.examples.length > 1
        ? `<span class="example-counter-group"><span style="font-family: var(--font-data); font-size: 14px; min-width: 32px; text-align: center; display: inline-block;">${exampleIdx + 1}/${meaning.examples.length}</span></span>`
        : '';

    if (example.trackId) {
        // The live handler on the real card. It resolves the Spotify token,
        // starts the PKCE login when there isn't one, and picks the Web
        // Playback SDK or Connect depending on the device — all of which we
        // want here unchanged, which is why this defers to the global rather
        // than reimplementing any of it.
        const btn = `<button type="button" class="spotify-btn link-btn"
                data-track-id="${esc(example.trackId)}" data-position-ms="${example.positionMs}"
                title="Play in Spotify" style="cursor:pointer; margin:0; position:relative; z-index:999;"
                data-about-example-spotify="1">${SPOTIFY_SVG}</button>`;
        const vocalists = example.vocalists
            ? `<span class="example-vocalist-credit"> · ${esc(example.vocalists)}</span>`
            : '';
        return `
            <div style="display: flex; justify-content: space-between; align-items: center; color: #b9c2cd; font-size: 13px; margin-top: 8px; font-style: italic;">
                <span class="example-song-credit">— ${esc(example.song)}${vocalists}</span>
                <span style="display: flex; align-items: center; gap: 6px;">${btn}${counter}</span>
            </div>`;
    }

    const label = example.sourceLabel
        ? `<span class="example-song-credit" style="margin-right:auto;">${esc(example.sourceLabel)}</span>`
        : '';
    if (!label && !counter) return '';
    return `
        <div style="display: flex; justify-content: flex-end; align-items: center; color: #b9c2cd; font-size: 13px; margin-top: 8px;">
            ${label}<span style="display: flex; align-items: center; gap: 6px;">${counter}</span>
        </div>`;
}

function renderBack(card, selectedIdx, exampleIdx) {
    const meaning = card.meanings[selectedIdx];
    const example = meaning.examples[exampleIdx % meaning.examples.length];
    const cursor = meaning.examples.length > 1 ? 'cursor: pointer;' : '';

    return `
        <div class="card-face card-back">
            <div class="card-details">
                <div class="back-header">
                    <div class="flip-back-area">
                        <div class="back-headword-row">
                            <span class="back-headword" style="font-size: 42px; font-weight: bold; line-height: 1.1;">${esc(card.word)}</span>
                            <div class="back-pos-legend" aria-label="Parts of speech">
                                <span class="card-pos ${posClass(card.pos)}"><span class="back-pos-dot" aria-hidden="true"></span>${posName(card.pos)}</span>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="meanings-scroll">${renderMeaningRows(card, selectedIdx)}</div>
                <div class="sentence example-is-matched" style="text-align: center; ${cursor}" data-about-example-cycle="${meaning.examples.length > 1 ? '1' : '0'}">
                    <div class="breakdown-trigger" style="margin-bottom: 8px;">${highlightWord(example.target, card.word)}</div>
                    <div class="translation">${esc(example.english)}</div>
                    ${renderCredit(card, meaning, example, exampleIdx % meaning.examples.length)}
                </div>
            </div>
            <div class="card-tint" aria-hidden="true"></div>
        </div>`;
}

// ---------------------------------------------------------------------------
// Walkthrough controller
// ---------------------------------------------------------------------------

const state = {
    stepIndex: 0,
    flipped: false,
    meaningIndex: 0,
    exampleIndex: 0,
    activeNote: -1,
};

function currentStep() {
    return ABOUT_EXAMPLE_STEPS[state.stepIndex];
}

function currentCard() {
    return ABOUT_EXAMPLE_CARDS[currentStep().card];
}

// Full rebuild — used when the step (and possibly the card) changes.
function renderCard() {
    const stage = document.getElementById('aboutExampleStage');
    if (!stage) return;
    const card = currentCard();

    stage.innerHTML = `
        <div class="about-example-card-inner">
            <div class="card${state.flipped ? ' flipped' : ''}" data-rank="${card.rank}">
                ${renderFront(card)}
                ${renderBack(card, state.meaningIndex, state.exampleIndex)}
            </div>
        </div>`;

    wireCardShell(stage);
    wireBack(stage);
    syncFlipHint(stage);
    placeMarkers();
}

// Sense and example changes replace only the back face, leaving the .card
// element (and therefore its flip transform) untouched — the same division of
// labour as the live app, where updateCard() rewrites #backContent rather than
// the card around it.
function refreshBack() {
    const stage = document.getElementById('aboutExampleStage');
    const back = stage?.querySelector('.card-back');
    if (!stage || !back) return;
    back.outerHTML = renderBack(currentCard(), state.meaningIndex, state.exampleIndex);
    wireBack(stage);
    placeMarkers();
}

function wireCardShell(stage) {
    const cardEl = stage.querySelector('.card');
    if (!cardEl) return;

    // Flip on card tap, minus the controls that carry their own meaning.
    // Toggling the class (rather than re-rendering) is what lets the real
    // 0.6s flip transition actually play.
    cardEl.addEventListener('click', (e) => {
        if (e.target.closest('.spotify-btn')) return;
        if (e.target.closest('.meaning-row')) return;
        if (e.target.closest('.sentence[data-about-example-cycle="1"]')) return;
        state.flipped = !state.flipped;
        cardEl.classList.toggle('flipped', state.flipped);
        syncFlipHint(stage);
        // Badges belong to whichever face is now showing; re-place them once
        // the flip has finished so they land on settled boxes.
        setTimeout(placeMarkers, 620);
    });
}

// Handlers for everything inside the back face. Called again after every
// back-face rebuild, since those nodes are replaced wholesale.
function wireBack(stage) {
    // Sense selection — switching sense resets to that sense's first example,
    // the same as selectMeaning() does on a live card.
    stage.querySelectorAll('.meaning-row').forEach((row) => {
        row.addEventListener('click', (e) => {
            e.stopPropagation();
            const idx = Number(row.dataset.meaningIndex);
            if (Number.isNaN(idx)) return;
            state.meaningIndex = idx;
            state.exampleIndex = 0;
            refreshBack();
        });
    });

    // Tap the lyric to cycle this sense's other examples.
    const sentence = stage.querySelector('.sentence[data-about-example-cycle="1"]');
    if (sentence) {
        sentence.addEventListener('click', (e) => {
            if (e.target.closest('.spotify-btn')) return;
            e.stopPropagation();
            state.exampleIndex += 1;
            refreshBack();
        });
    }

    // The live Spotify hand-off. spotifyPlayTrack() is published on window by
    // spotify.js; it resolves the token, runs the PKCE login when there isn't
    // one, and picks the Web Playback SDK or Connect by device — all of which
    // we want unchanged, which is why this defers rather than reimplementing.
    // If the module somehow isn't loaded, fall back to the web player.
    const spotifyBtn = stage.querySelector('[data-about-example-spotify]');
    if (spotifyBtn) {
        spotifyBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            const trackId = spotifyBtn.dataset.trackId;
            const positionMs = Number(spotifyBtn.dataset.positionMs) || 0;
            if (typeof window.spotifyPlayTrack === 'function') {
                spotifyBtn.classList.add('autoplay-loading');
                Promise.resolve(window.spotifyPlayTrack(trackId, positionMs))
                    .catch(() => {})
                    .finally(() => spotifyBtn.classList.remove('autoplay-loading'));
            } else {
                window.open(`https://open.spotify.com/track/${trackId}`, '_blank', 'noopener');
            }
        });
    }
}

// The "tap to flip" nudge is only honest while the front is showing.
function syncFlipHint(stage) {
    const hint = stage.querySelector('.about-example-flip-hint');
    if (hint) hint.style.display = state.flipped ? 'none' : '';
}

// Numbered badges are positioned from the target's measured box rather than
// hard-coded offsets, so they stay correct when a sense row wraps, the lyric
// runs to two lines, or the viewport is narrow.
function placeMarkers() {
    const stage = document.getElementById('aboutExampleStage');
    const layer = document.getElementById('aboutExampleMarkers');
    if (!stage || !layer) return;
    layer.innerHTML = '';

    const step = currentStep();
    const stageRect = stage.getBoundingClientRect();

    step.notes.forEach((note, i) => {
        const target = stage.querySelector(note.anchor);
        if (!target) return;
        target.classList.add('about-example-anchored');
        target.dataset.aboutExampleNote = String(i);

        // Both faces are always in the DOM (backface-visibility does the
        // hiding), and both report real boxes. Badge only what's face-up,
        // or a visitor who flips mid-step gets front-face numbers floating
        // over the back of the card.
        const onBack = !!target.closest('.card-back');
        if (onBack !== state.flipped) return;

        const rect = target.getBoundingClientRect();
        if (!rect.width && !rect.height) return;

        const marker = document.createElement('button');
        marker.type = 'button';
        marker.className = 'about-example-marker';
        marker.dataset.note = String(i);
        marker.textContent = String(i + 1);
        marker.setAttribute('aria-label', `Annotation ${i + 1}: ${note.title}`);
        marker.style.left = `${rect.left - stageRect.left - 11}px`;
        marker.style.top = `${rect.top - stageRect.top + rect.height / 2 - 11}px`;
        marker.addEventListener('mouseenter', () => setActiveNote(i));
        marker.addEventListener('mouseleave', () => setActiveNote(-1));
        marker.addEventListener('focus', () => setActiveNote(i));
        marker.addEventListener('blur', () => setActiveNote(-1));
        layer.appendChild(marker);
    });

    if (state.activeNote >= 0) setActiveNote(state.activeNote);
}

// Hovering either a badge or its note lights up both, plus the element itself.
function setActiveNote(index) {
    state.activeNote = index;
    const root = document.getElementById('aboutExampleModal');
    if (!root) return;
    root.querySelectorAll('.about-example-marker').forEach((m) => {
        m.classList.toggle('is-active', Number(m.dataset.note) === index);
    });
    root.querySelectorAll('.about-example-note').forEach((n) => {
        n.classList.toggle('is-active', Number(n.dataset.note) === index);
    });
    root.querySelectorAll('.about-example-anchored').forEach((el) => {
        el.classList.toggle('is-annotation-active', Number(el.dataset.aboutExampleNote) === index);
    });
}

function renderNotes() {
    const step = currentStep();
    const host = document.getElementById('aboutExampleNotes');
    if (!host) return;

    host.innerHTML = `
        <div class="about-example-eyebrow">${esc(step.eyebrow)}</div>
        <h3 class="about-example-title">${step.title}</h3>
        <p class="about-example-blurb">${step.blurb}</p>
        <ol class="about-example-note-list">
            ${step.notes.map((n, i) => `
                <li class="about-example-note" data-note="${i}">
                    <span class="about-example-note-num">${i + 1}</span>
                    <div>
                        <strong>${n.title}${n.interactive ? '<span class="about-example-try">try it</span>' : ''}</strong>
                        <span>${n.text}</span>
                    </div>
                </li>`).join('')}
        </ol>`;

    host.querySelectorAll('.about-example-note').forEach((el) => {
        const i = Number(el.dataset.note);
        el.addEventListener('mouseenter', () => setActiveNote(i));
        el.addEventListener('mouseleave', () => setActiveNote(-1));
    });
}

function renderProgress() {
    const host = document.getElementById('aboutExampleProgress');
    if (!host) return;
    host.innerHTML = ABOUT_EXAMPLE_STEPS.map((s, i) => `
        <button type="button" class="about-example-pip${i === state.stepIndex ? ' is-current' : ''}"
                data-step="${i}" aria-label="Step ${i + 1}: ${esc(s.title)}"
                ${i === state.stepIndex ? 'aria-current="step"' : ''}></button>`).join('');
    host.querySelectorAll('.about-example-pip').forEach((pip) => {
        pip.addEventListener('click', () => goToStep(Number(pip.dataset.step)));
    });

    const back = document.getElementById('aboutExamplePrev');
    const next = document.getElementById('aboutExampleNext');
    if (back) back.disabled = state.stepIndex === 0;
    if (next) {
        const last = state.stepIndex === ABOUT_EXAMPLE_STEPS.length - 1;
        next.textContent = last ? 'Back to About' : 'Next →';
        next.classList.toggle('is-finish', last);
    }
}

function goToStep(index) {
    if (index < 0 || index >= ABOUT_EXAMPLE_STEPS.length) return;
    state.stepIndex = index;
    const step = currentStep();

    // Every step resets the card to its first sense and first example. It's
    // tempting to preserve whatever the visitor selected while exploring the
    // previous step, but a step's annotations are written against a known
    // card state — leave "light" selected (one example, no counter) and the
    // next step's note about cycling examples points at nothing.
    state.meaningIndex = 0;
    state.exampleIndex = 0;
    state.flipped = step.face === 'back';
    state.activeNote = -1;

    renderProgress();
    renderNotes();
    renderCard();

    const body = document.getElementById('aboutExampleBody');
    if (body) body.scrollTop = 0;
}

// ---------------------------------------------------------------------------
// Open / close
// ---------------------------------------------------------------------------

let _resizeHandler = null;

function openAboutExample(startStep = 0) {
    const modal = document.getElementById('aboutExampleModal');
    if (!modal) return;
    modal.classList.remove('hidden');
    state.stepIndex = startStep;
    state.flipped = ABOUT_EXAMPLE_STEPS[startStep].face === 'back';
    state.meaningIndex = 0;
    state.exampleIndex = 0;
    state.activeNote = -1;

    renderProgress();
    renderNotes();
    renderCard();

    if (!_resizeHandler) {
        _resizeHandler = () => placeMarkers();
        window.addEventListener('resize', _resizeHandler);
    }
}

function closeAboutExample() {
    const modal = document.getElementById('aboutExampleModal');
    if (!modal) return;
    modal.classList.add('hidden');
    // Leave any Spotify playback the visitor started running — they pressed
    // play deliberately, and closing a walkthrough shouldn't stop their music.
    if (_resizeHandler) {
        window.removeEventListener('resize', _resizeHandler);
        _resizeHandler = null;
    }
}

function setupAboutExample() {
    const modal = document.getElementById('aboutExampleModal');
    if (!modal || modal.dataset.ready === '1') return;
    modal.dataset.ready = '1';

    document.getElementById('closeAboutExampleModal')?.addEventListener('click', closeAboutExample);
    document.getElementById('aboutExamplePrev')?.addEventListener('click', () => goToStep(state.stepIndex - 1));
    document.getElementById('aboutExampleNext')?.addEventListener('click', () => {
        if (state.stepIndex === ABOUT_EXAMPLE_STEPS.length - 1) closeAboutExample();
        else goToStep(state.stepIndex + 1);
    });

    // Arrow keys page through steps; Escape closes. Only while open.
    document.addEventListener('keydown', (e) => {
        if (modal.classList.contains('hidden')) return;
        if (e.key === 'Escape') closeAboutExample();
        else if (e.key === 'ArrowRight') goToStep(state.stepIndex + 1);
        else if (e.key === 'ArrowLeft') goToStep(state.stepIndex - 1);
    });
}

document.addEventListener('DOMContentLoaded', setupAboutExample);
if (document.readyState !== 'loading') setupAboutExample();

window.openAboutExample = openAboutExample;
window.closeAboutExample = closeAboutExample;
