// Shared mutable application state — imported by all modules via side-effect.
// Also exposes all state as globalThis properties so bare variable names work
// in ES module strict-mode code (reads AND writes) without any changes to function bodies.

export const state = {
    // Core flashcard state
    flashcards: [],
    currentIndex: 0,
    currentSentenceIndex: 0,
    currentMeaningIndex: 0,
    currentExampleIndex: 0,
    currentMWEIndex: 0,
    // When a group card's shared field is clicked, this holds
    // {axis, groupKey, members:[idx,...]} so the example pane shows the
    // union of all member examples and the shared field gets the selected
    // outline. Cleared by selectMeaning() (sub-row click) and on card change.
    currentGroupSelection: null,
    isFlipped: false,
    isAppInitialized: false,
    stats: {
        studied: new Set(),
        correct: 0,
        incorrect: 0,
        total: 0,
        cardStats: {},
        // Set sizing: how many words the user picked vs. how many are in the
        // active deck after filtering out previously-seen words. The active-set
        // history uses this to retain previously completed cards in its audit.
        setSize: 0,
        previouslyKnown: 0,
        // Display label of the picked range, e.g. "475-499". Shown as the
        // stats modal title.
        setLabel: '',
        rangeString: '',
        rangeBasis: 'display',
        setNumber: null,
        levelSetCount: null,
        nextRange: null,
        nextSetNumber: null,
        nextRankBasis: 'display',
        studyMode: 'new',
        levelNumber: null,
        // Snapshot of every word in the picked range (active + previously
        // mastered), so the active-set history can show the full list. Each entry:
        // { id, word, translation, displayRank }.
        allWords: []
    },

    // Selection / app mode state
    selectedLanguage: 'spanish',
    selectedLevel: null,
    selectedRanges: [],
    // Legacy resume metadata. New study sets use fixed 20-position baseline
    // chunks so membership does not change with a size preference.
    groupSize: 20,

    // Feature flags
    useLemmaMode: false,
    lemmaFieldAvailable: false,
    excludeCognates: false,
    cognateFieldAvailable: false,
    cognateThreshold: 0.85,
    percentageMode: true,
    // Lyrics has two mutually-exclusive vocabularies. `main` contains lemma
    // families evidenced in multiple distinct lyric lines; `extra` contains
    // genuinely one-off lemma families, including cards with no translation.
    artistVocabularyScope: 'main',
    // Legacy switch retained for saved-session compatibility. Artist decks
    // now use artistVocabularyScope instead of hiding individual 1x forms.
    hideSingleOccurrence: true,
    // Artist-mode filters that mirror the pipeline flags. Defaults match
    // the prior unconditional filter so behaviour is unchanged until the
    // user opts a category back in via Advanced settings.
    excludeProperNouns: true,
    excludeNoise: true,
    // English loanwords / code-switches (hey, baby, shot, panty). Flagged
    // by tool_8a_stamp_loanword_flag.py from the Wiktionary-etymology layer.
    // Hidden by default; toggle to study them.
    excludeEnglishLoanwords: true,
    speechEnabled: true,
    // Query-only app route used to evaluate the new Spanish Speech sense
    // architecture without changing normal decks or saving preview answers.
    speechVnextActive: false,
    // Optional while the app/content are still being developed. When off,
    // time-based due cards remain Known; explicit mistakes and partial cards
    // still enter Review. Existing stages/timestamps are preserved.
    spacedRepetitionEnabled: false,

    // Config / data
    config: null,
    cefrLevelsConfig: null,
    ppmData: null,
    totalPpm: 0,

    // Auth / progress
    GOOGLE_SCRIPT_URL: '',
    currentUser: null,
    progressData: {},
    itemProgressData: {},
    levelEstimates: {},
    // Suggestion-only per-level overrides, keyed by a stable
    // mode|language|source scope. Values are { levelId: true } maps so they
    // serialize directly into the per-user progress cache.
    markedDoneLevels: {},
    // Starts unknown so writes use the legacy sheet names until a harmless
    // capabilities request confirms the consolidated v4 backend is deployed.
    progressBackendSchemaVersion: 0,

    // Artist / lyrics mode
    activeArtist: null,         // null = normal mode, object = artist config from artists.json
    artistAlbumsDictionary: null,
    songToAlbumMap: {},

    // Lyric breakdown
    cardNavStack: [],
    cachedVocabularyData: null,
    // Derived indexes over cachedVocabularyData. They live here, not as
    // module-level `let`s, because both sides of the lazy split touch them:
    // the lyric-breakdown modal builds them, updateCard()'s homograph chips
    // read them, and goBackToSetup() clears them. A module-local declaration
    // in either file is invisible to the other and throws a ReferenceError
    // under module strict mode.
    fullVocabLookup: null,
    vocabByIdLookup: null,

    // Phrase/clitic chaining — MWE/CLITIC entries a parent card hands off to
    // a single scrollable summary card shown after the parent is marked
    // correct. Gated by the "Phrases mode" study preference (js/ui.js); off
    // restores the pinned meanings-tray behavior.
    cardChainQueue: [],
    cardChainReturnIndex: -1,
    // A parent card can hand off to more than one child in sequence (phrases,
    // then sense-free corpus sentences). `cardChainChildren` is the ordered
    // plan, `cardChainIndex` the position in it, and the two payload arrays
    // hold whatever the currently rendered child needs.
    cardChainChildren: [],
    cardChainIndex: 0,
    cardChainExamples: [],
    phrasesModeEnabled: true,
    extraExamplesEnabled: true,

    // Level estimation
    estimationState: {
        active: false,
        vocabularyData: null,
        validWords: [],
        bands: [],
        coverageOrder: [],
        maxLevel: 0,
        wordsTestedCount: 0,
        shownWordIds: new Set(),
        shownLemmaKeys: new Set(),
        currentWord: null,
        currentBandIndex: null,
        translationRevealed: false,
        estimatedLevel: null,
        estimateInterval: null,
        autoAdvanceTimer: null
    },
};

// No hardcoded album constants — album image maps now live in artists.json

export const percentageLevels = [
    { level: '50%',   threshold: 0.50,  description: '50% coverage' },
    { level: '60%',   threshold: 0.60,  description: '60% coverage' },
    { level: '70%',   threshold: 0.70,  description: '70% coverage' },
    { level: '80%',   threshold: 0.80,  description: '80% coverage' },
    { level: '90%',   threshold: 0.90,  description: '90% coverage' },
    { level: '95%',   threshold: 0.95,  description: '95% coverage' },
    { level: '98%',   threshold: 0.98,  description: '98% coverage (freq \u2265 3)' },
    { level: '99%',   threshold: 0.99,  description: '99% coverage (freq \u2265 2)' },
    { level: '99.5%', threshold: 0.995, description: '99.5% coverage (freq \u2265 2)' },
    { level: '100%',  threshold: 1.00,  description: 'All words (freq \u2265 2)' }
];

export const speechLangCodes = {
    spanish: 'es-ES',
    swedish: 'sv-SE',
    italian: 'it-IT',
    dutch:   'nl-NL',
    polish:  'pl-PL',
    french:  'fr-FR',
    russian: 'ru-RU'
};

// Expose all mutable state as globalThis properties with getters/setters.
// This allows bare variable names (e.g., `flashcards`, `currentIndex`) to work
// in any ES module without import changes, for both reads and writes.
for (const key of Object.keys(state)) {
    Object.defineProperty(globalThis, key, {
        get() { return state[key]; },
        set(v) { state[key] = v; },
        configurable: true,
        enumerable: true,
    });
}

// Expose constants on globalThis as read-only
globalThis.percentageLevels = percentageLevels;
globalThis.speechLangCodes  = speechLangCodes;
