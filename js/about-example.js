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
// `cielo` is a genuine Bad Bunny deck entry — rank, line count, meanings,
// percentages, lyrics and timestamps all read out of the built deck rather
// than written for the walkthrough. `aunque` is the Speech-mode card the About
// copy already discusses.

const ABOUT_EXAMPLE_CARDS = {
    // Chosen for the quality of its sense assignment, not at random. `fuego`
    // was here first and read badly: its "light (for smoking)" row was
    // illustrated by "Fuego, desde que te vi me puse roja" and its "passion"
    // row by "me voy a fuego" — an idiom meaning "I go all out". Both are
    // real output of the current classifier, and a visitor who reads the
    // English can see they don't demonstrate the meaning claimed. A showcase
    // has to be a case the system gets right; `cielo` splits cleanly into two
    // concrete meanings a non-Spanish-speaker can check from the translation
    // alone. Revisit when sense assignment improves.
    cielo: {
        mode: 'lyrics',
        word: 'cielo',
        pos: 'NOUN',
        rank: 344,
        corpusCount: 33,
        meanings: [
            {
                pos: 'NOUN',
                translation: 'heaven',
                context: 'religious',
                pct: 70,
                examples: [
                    {
                        target: 'El cielo en el infierno, nadie va a entender',
                        english: 'Heaven in hell, no one will understand',
                        song: 'Volando (Remix)',
                        trackId: '0G2zPzWqVjR68iNPmx2TBe',
                        positionMs: 220310,
                        vocalists: 'Bad Bunny',
                    },
                    {
                        target: 'Lo subo al cielo, yo soy su Messiah',
                        english: 'I take him to heaven, I am his Messiah',
                        song: 'LA NOCHE DE ANOCHE',
                        trackId: '2XIc1pqjXV3Cr2BQUGNBck',
                        positionMs: 137190,
                        vocalists: 'ROSALÍA',
                    },
                    {
                        target: 'Ya estoy acostumbra’o a estar siempre en el cielo',
                        english: 'I’m already used to always being in heaven',
                        song: 'Estamos Bien',
                        trackId: '2OWVCFTolecLiGZPquvWvT',
                        positionMs: 68170,
                        vocalists: null,
                    },
                ],
            },
            {
                pos: 'NOUN',
                translation: 'sky',
                context: 'firmament',
                pct: 30,
                examples: [
                    {
                        target: 'Y ver pa’l cielo a ver si te veo caer',
                        english: 'And I look to the sky to see if I see you fall',
                        song: 'BAILE INoLVIDABLE',
                        trackId: '2lTm559tuIvatlT1u0JYG2',
                        positionMs: 118690,
                        vocalists: null,
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
// Decks and their annotations
// ---------------------------------------------------------------------------
//
// Two things are being selected independently, and conflating them was the
// first version's mistake:
//
//   * The DECK (Lyrics / Speech) — chosen by the tab. This is the only thing
//     the tab does.
//   * The FACE (back / front) — chosen by flipping the card, like anywhere
//     else in the app.
//
// Annotations belong to a FACE, not to a tab step. Flip the card and the whole
// numbered set is replaced by the one describing the side now showing;
// otherwise the labels stay behind pointing at elements that turned away.
//
// The back opens by default. It carries the senses, the shares and the
// evidence — everything the app is actually for. The front is a prompt.
//
// `anchor` is a CSS selector resolved inside the rendered card; `side` puts
// the note in the left or right column and pins its badge to the matching edge
// of the element, so a badge never has to cross the card to reach its note.

const ABOUT_EXAMPLE_DECKS = [
    {
        id: 'lyrics',
        card: 'cielo',
        tab: 'Lyrics',
        faces: {
            back: {
                title: 'What the app actually teaches you',
                blurb: 'This is the answer side of a flashcard. Instead of giving one '
                     + 'translation and hiding the rest, it shows every meaning the word has, '
                     + 'how often each one is really used, and a line from a song using it.',
                notes: [
                    {
                        side: 'left',
                        anchor: '.back-headword',
                        title: 'The word',
                        text: 'Repeated at the top so you keep your place reading down.',
                    },
                    {
                        side: 'right',
                        anchor: '.back-pos-legend',
                        title: 'Part of speech',
                        text: 'Noun, verb, adjective and so on — each with its own colour. The '
                            + 'same colour tints the rows below and the word in the lyric.',
                    },
                    {
                        side: 'left',
                        anchor: '.meanings-scroll .meaning-row:nth-child(1)',
                        title: 'Its most common meaning',
                        text: '“heaven” is how this word is used about 70% of the time across '
                            + 'his songs. The highlighted row is the one you’re looking at.',
                    },
                    {
                        side: 'left',
                        anchor: '.meanings-scroll .meaning-row:nth-child(2)',
                        title: 'Its other meanings',
                        text: 'Tap one to switch. The lyric underneath changes to a line where '
                            + 'that meaning is the one being used.',
                        interactive: true,
                    },
                    {
                        side: 'right',
                        anchor: '.about-example-pct',
                        title: 'How often each is used',
                        text: 'Every line in his songs containing this word was read and sorted '
                            + 'by meaning, so these are his real proportions — not a dictionary’s '
                            + 'ordering.',
                    },
                    {
                        side: 'right',
                        anchor: '.example-word-highlight',
                        title: 'The word in a real line',
                        text: 'Marked inside the lyric, in whatever form it takes there.',
                    },
                    {
                        side: 'left',
                        anchor: '.translation',
                        title: 'The line in English',
                        text: 'So the whole lyric makes sense without looking anything up.',
                    },
                    {
                        side: 'left',
                        anchor: '.example-song-credit',
                        title: 'Which song it’s from',
                        text: 'Plus any guest artist singing that line.',
                    },
                    {
                        side: 'right',
                        anchor: '.spotify-btn',
                        title: 'Play it — really',
                        text: 'A working button. It plays the song in your own Spotify, starting '
                            + 'at the second that line is sung. Spotify Premium required.',
                        interactive: true,
                    },
                    {
                        side: 'right',
                        anchor: '.example-counter-group',
                        title: 'More than one example',
                        text: 'Where a meaning turns up in several songs, tap the lyric to move '
                            + 'through them.',
                        interactive: true,
                    },
                ],
            },
            front: {
                title: 'The question side',
                blurb: 'You see the word on its own and try to recall it. The two figures '
                     + 'underneath say how common it is, which is how the app decides the order '
                     + 'you meet words in.',
                notes: [
                    {
                        side: 'left',
                        anchor: '.card-word',
                        title: 'The word',
                        text: 'Try to recall what it means before turning the card over. The '
                            + 'effort of remembering is what makes it stick.',
                    },
                    {
                        side: 'left',
                        anchor: '.card-rank-label',
                        title: 'How common it is',
                        text: 'The 344th most-used word across his songs. Words are taught in '
                            + 'that order — the ones you’ll hear most, first.',
                    },
                    {
                        side: 'right',
                        anchor: '.card-pos-list',
                        title: 'Part of speech',
                        text: 'Same label, same colour, same corner on both sides of the card.',
                    },
                    {
                        side: 'right',
                        anchor: '.card-freq-label',
                        title: 'How much evidence there is',
                        text: 'The number of lines in his songs that use this word.',
                    },
                ],
            },
        },
    },

    {
        id: 'speech',
        card: 'aunque',
        tab: 'Speech',
        faces: {
            back: {
                title: 'The same card, built from film and TV dialogue',
                blurb: 'Not everyone wants to learn from music. The other set of cards is built '
                     + 'from subtitles instead, and works identically — only the example '
                     + 'sentences come from somewhere else.',
                notes: [
                    {
                        side: 'left',
                        anchor: '.back-headword',
                        title: 'A small connecting word',
                        text: 'Courses built around topics — food, travel, the airport — leave '
                            + 'words like <em>aunque</em> until late. Teaching by how common a '
                            + 'word is puts it early, because it’s how sentences get joined '
                            + 'together.',
                    },
                    {
                        side: 'left',
                        anchor: '.meanings-scroll',
                        title: 'Three ways to translate it',
                        text: 'About 50% <em>even though</em>, 30% <em>although</em>, 20% '
                            + '<em>even if</em> — each with a sentence where that reading is the '
                            + 'right one.',
                        interactive: true,
                    },
                    {
                        side: 'left',
                        anchor: '.example-song-credit',
                        title: 'Where the sentence is from',
                        text: 'No song here. Lines come from film and TV subtitles, picked to sit '
                            + 'near your level so a hard word isn’t buried in a harder sentence.',
                    },
                    {
                        side: 'right',
                        anchor: '.about-example-pct',
                        title: 'The same proportions',
                        text: 'Measured the same way, over lines of dialogue instead of lyrics.',
                    },
                    {
                        side: 'right',
                        anchor: '.example-word-highlight',
                        title: 'The same marking',
                        text: 'The word you’re learning is highlighted inside the sentence, '
                            + 'exactly as on a song card.',
                    },
                    {
                        side: 'right',
                        anchor: '.sentence',
                        title: 'Everything else is the same',
                        text: 'Same rows, same flip, same tap for another example.',
                    },
                ],
            },
            front: {
                title: 'The question side, away from music',
                blurb: 'Identical to a song card, with one number swapped.',
                notes: [
                    {
                        side: 'left',
                        anchor: '.card-word',
                        title: 'The word',
                        text: 'The same prompt, whichever set of cards you’re in.',
                    },
                    {
                        side: 'left',
                        anchor: '.card-rank-label',
                        title: 'How common it is',
                        text: 'The 429th most-used word in Spanish film and TV dialogue — far '
                            + 'earlier than a topic-based course would reach it.',
                    },
                    {
                        side: 'right',
                        anchor: '.card-pos-list',
                        title: 'Part of speech',
                        text: 'Connecting words get their own colour, as every type does.',
                    },
                    {
                        side: 'right',
                        anchor: '.card-freq-label',
                        title: 'The figure that changes',
                        text: 'How often it appears per million words of dialogue. On a song card '
                            + 'this slot counts lyric lines instead.',
                    },
                ],
            },
        },
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
    deckIndex: 0,
    // The back opens first, deliberately: it holds the senses, the shares and
    // the evidence. The front is a prompt with a rank on it.
    flipped: true,
    meaningIndex: 0,
    exampleIndex: 0,
    activeNote: -1,
};

function currentDeck() {
    return ABOUT_EXAMPLE_DECKS[state.deckIndex];
}

function currentCard() {
    return ABOUT_EXAMPLE_CARDS[currentDeck().card];
}

// The annotation set is a property of the face on show, not of the tab. This
// is the whole reason flipping re-renders the notes.
function currentFace() {
    return currentDeck().faces[state.flipped ? 'back' : 'front'];
}

// Left column first, then right, so the numbers run in reading order and each
// badge sits on the same side as the note explaining it.
function orderedNotes() {
    const notes = currentFace().notes;
    return [
        ...notes.filter(n => n.side !== 'right'),
        ...notes.filter(n => n.side === 'right'),
    ];
}

// Full rebuild — used when the deck changes.
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
    renderFaceCopy();
    renderNotes();
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

// Flipping is a face change, so the annotations change with it: new copy, new
// numbered set, badges re-placed on the side now showing.
function flipCardFace() {
    const stage = document.getElementById('aboutExampleStage');
    const cardEl = stage?.querySelector('.card');
    if (!cardEl) return;

    state.flipped = !state.flipped;
    state.activeNote = -1;
    cardEl.classList.toggle('flipped', state.flipped);

    // Clear the outgoing badges immediately — leaving them on screen through
    // the 0.6s flip is exactly the "labels in the wrong place" problem.
    const layer = document.getElementById('aboutExampleMarkers');
    if (layer) layer.innerHTML = '';

    renderFaceCopy();
    renderNotes();
    syncFlipButton();
    // Re-place once the transform has settled, so boxes are measured flat.
    setTimeout(placeMarkers, 640);
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
        flipCardFace();
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

function syncFlipButton() {
    const btn = document.getElementById('aboutExampleFlip');
    if (!btn) return;
    btn.textContent = state.flipped ? '⟲  Show the front' : '⟲  Show the back';
}

// ---------------------------------------------------------------------------
// Annotations
// ---------------------------------------------------------------------------

// Badges are positioned from each target's measured box rather than hard-coded
// offsets, so they stay correct when a sense row wraps, the lyric runs to two
// lines, or the viewport narrows. A left-column note pins its badge to the
// element's left edge and a right-column note to its right edge, so no badge
// has to cross the card to reach the note it belongs to.
function placeMarkers() {
    const stage = document.getElementById('aboutExampleStage');
    const layer = document.getElementById('aboutExampleMarkers');
    if (!stage || !layer) return;
    layer.innerHTML = '';

    const stageRect = stage.getBoundingClientRect();

    orderedNotes().forEach((note, i) => {
        const target = stage.querySelector(note.anchor);
        if (!target) return;
        target.classList.add('about-example-anchored');
        target.dataset.aboutExampleNote = String(i);

        // Both faces are always in the DOM (backface-visibility does the
        // hiding) and both report real boxes. Only badge what is face-up.
        const onBack = !!target.closest('.card-back');
        if (onBack !== state.flipped) return;

        const rect = target.getBoundingClientRect();
        if (!rect.width && !rect.height) return;

        const onRight = note.side === 'right';
        const marker = document.createElement('button');
        marker.type = 'button';
        marker.className = `about-example-marker ${onRight ? 'is-right' : 'is-left'}`;
        marker.dataset.note = String(i);
        marker.textContent = String(i + 1);
        marker.setAttribute('aria-label', `Annotation ${i + 1}: ${note.title}`);
        marker.style.left = onRight
            ? `${rect.right - stageRect.left - 5}px`
            : `${rect.left - stageRect.left - 17}px`;
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

function renderFaceCopy() {
    const face = currentFace();
    const host = document.getElementById('aboutExampleIntro');
    if (!host) return;
    // The title is a lead-in to the summary, not a heading over it — one
    // line instead of two, because the card and its annotations have to share
    // the screen. No "Lyrics · Bad Bunny · back of card" line either: the tab
    // already says which deck, and the card in front of you already says
    // which side you are looking at.
    host.innerHTML = `
        <p class="about-example-blurb">
            <strong class="about-example-lede">${face.title}</strong>
            ${face.blurb}
        </p>`;
}

function noteHTML(note, index) {
    return `
        <li class="about-example-note" data-note="${index}">
            <span class="about-example-note-num">${index + 1}</span>
            <div>
                <strong>${note.title}${note.interactive ? '<span class="about-example-try">try it</span>' : ''}</strong>
                <span>${note.text}</span>
            </div>
        </li>`;
}

function renderNotes() {
    const left = document.getElementById('aboutExampleNotesLeft');
    const right = document.getElementById('aboutExampleNotesRight');
    if (!left || !right) return;

    const notes = orderedNotes();
    const leftHTML = [];
    const rightHTML = [];
    notes.forEach((note, i) => {
        (note.side === 'right' ? rightHTML : leftHTML).push(noteHTML(note, i));
    });

    left.innerHTML = `<ol class="about-example-note-list">${leftHTML.join('')}</ol>`;
    right.innerHTML = `<ol class="about-example-note-list">${rightHTML.join('')}</ol>`;

    document.getElementById('aboutExampleModal')
        ?.querySelectorAll('.about-example-note')
        .forEach((el) => {
            const i = Number(el.dataset.note);
            el.addEventListener('mouseenter', () => setActiveNote(i));
            el.addEventListener('mouseleave', () => setActiveNote(-1));
        });
}

// ---------------------------------------------------------------------------
// Deck tabs
// ---------------------------------------------------------------------------

function renderTabs() {
    const host = document.getElementById('aboutExampleTabs');
    if (!host) return;
    host.innerHTML = ABOUT_EXAMPLE_DECKS.map((d, i) => `
        <button type="button" class="about-example-tab${i === state.deckIndex ? ' is-current' : ''}"
                data-deck="${i}" role="tab" aria-selected="${i === state.deckIndex}">${esc(d.tab)}</button>`).join('');
    host.querySelectorAll('.about-example-tab').forEach((tab) => {
        tab.addEventListener('click', () => selectDeck(Number(tab.dataset.deck)));
    });
}

// Switching decks resets the card to its first sense and first example. The
// annotations are written against a known card state — leave "light" selected
// (one example, no counter) and the note about cycling points at nothing.
// Face is deliberately NOT reset: if you were reading the front, you stay on
// the front and get the other deck's front.
function selectDeck(index) {
    if (index < 0 || index >= ABOUT_EXAMPLE_DECKS.length || index === state.deckIndex) return;
    state.deckIndex = index;
    state.meaningIndex = 0;
    state.exampleIndex = 0;
    state.activeNote = -1;

    renderTabs();
    renderCard();
    syncFlipButton();

    const body = document.getElementById('aboutExampleBody');
    if (body) body.scrollTop = 0;
}

// ---------------------------------------------------------------------------
// Open / close
// ---------------------------------------------------------------------------

let _resizeHandler = null;

function openAboutExample(deckIndex = 0) {
    const modal = document.getElementById('aboutExampleModal');
    if (!modal) return;
    modal.classList.remove('hidden');
    state.deckIndex = deckIndex;
    state.flipped = true;
    state.meaningIndex = 0;
    state.exampleIndex = 0;
    state.activeNote = -1;

    renderTabs();
    renderCard();
    syncFlipButton();

    if (!_resizeHandler) {
        _resizeHandler = () => placeMarkers();
        window.addEventListener('resize', _resizeHandler);
    }
}

// The ✕ returns to About, which is where the walkthrough was opened from and
// where the rest of the project write-up still is. Closing straight through to
// the app would drop a reader out of the page they were part-way through.
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
    document.getElementById('aboutExampleFlip')?.addEventListener('click', flipCardFace);

    // Escape closes; left/right switch decks; space flips, as it does in study.
    document.addEventListener('keydown', (e) => {
        if (modal.classList.contains('hidden')) return;
        if (e.key === 'Escape') closeAboutExample();
        else if (e.key === 'ArrowRight') selectDeck(state.deckIndex + 1);
        else if (e.key === 'ArrowLeft') selectDeck(state.deckIndex - 1);
        else if (e.key === ' ' && !e.target.closest('button')) {
            e.preventDefault();
            flipCardFace();
        }
    });
}

document.addEventListener('DOMContentLoaded', setupAboutExample);
if (document.readyState !== 'loading') setupAboutExample();

window.openAboutExample = openAboutExample;
window.closeAboutExample = closeAboutExample;
