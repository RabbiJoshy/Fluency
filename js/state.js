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
    isFlipped: false,
    isAppInitialized: false,
    stats: {
        studied: new Set(),
        correct: 0,
        incorrect: 0,
        total: 0,
        cardStats: {}
    },

    // Selection / app mode state
    currentMode: 'flashcards',
    selectedLanguage: 'spanish',
    selectedLevel: null,
    selectedRanges: [],
    groupSize: 25,

    // Feature flags
    useLemmaMode: true,
    lemmaFieldAvailable: false,
    excludeCognates: false,
    cognateFieldAvailable: false,
    percentageMode: false,
    hideSingleOccurrence: true,
    speechEnabled: true,

    // Config / data
    config: null,
    cefrLevelsConfig: null,
    ppmData: null,
    totalPpm: 0,

    // Auth / progress
    GOOGLE_SCRIPT_URL: '',
    currentUser: null,
    progressData: {},
    levelEstimates: {},

    // Bad Bunny
    isBadBunnyMode: new URLSearchParams(window.location.search).get('mode') === 'badbunny',
    badBunnyAlbumsDictionary: null,
    songToAlbumMap: {},

    // Level estimation
    estimationCheckpoints: null,
    estimationState: {
        active: false,
        mode: 'quick',
        currentLevel: 500,
        stride: 500,
        minStride: 100,
        wordIndex: 0,
        correct: 0,
        wrong: 0,
        checkpointCorrect: 0,
        checkpointWrong: 0,
        currentWords: [],
        estimatedLevel: null,
        vocabularyData: null,
        history: [],
        maxLevel: 8500
    },
};

// Constants (not mutable state — never reassigned)
export const albumToImagePath = {
    'X 100PRE (2018)': 'Bad Bunny/Images/X100PRE.jpg',
    'OASIS (2019) [with J Balvin]': 'Bad Bunny/Images/OASIS.png',
    'YHLQMDLG (2020)': 'Bad Bunny/Images/YHLQMDLG.png',
    'LAS QUE NO IBAN A SALIR (2020)': 'Bad Bunny/Images/LAS_QUE_NO_IBAN_A_SALIR.jpg',
    'EL ÚLTIMO TOUR DEL MUNDO (2020)': 'Bad Bunny/Images/EL_ULTIMO_TOUR_DEL_MUNDO.png',
    'UN VERANO SIN TI (2022)': 'Bad Bunny/Images/UN_VERANO_SIN_TI.png',
    'NADIE SABE LO QUE VA A PASAR MAÑANA (2023)': 'Bad Bunny/Images/NADIE_SABE_LO_QUE_VA_A_PASAR_MANANA.png',
    'DEBÍ TIRAR MÁS FOTOS (2025)': 'Bad Bunny/Images/DEBI_TIRAR_MAS_FOTOS.png',
    'Singles & Other Tracks': 'Bad Bunny/Images/SINGLES.jpg'
};
export const defaultAlbumArt = 'Bad Bunny/Images/SINGLES.jpg';

export const percentageLevels = [
    { level: '50%',   threshold: 0.50,  description: '50% language coverage' },
    { level: '60%',   threshold: 0.60,  description: '60% language coverage' },
    { level: '70%',   threshold: 0.70,  description: '70% language coverage' },
    { level: '80%',   threshold: 0.80,  description: '80% language coverage' },
    { level: '85%',   threshold: 0.85,  description: '85% language coverage' },
    { level: '90%',   threshold: 0.90,  description: '90% language coverage' },
    { level: '95%',   threshold: 0.95,  description: '95% language coverage' },
    { level: '96%',   threshold: 0.96,  description: '96% language coverage' },
    { level: '97%',   threshold: 0.97,  description: '97% language coverage' },
    { level: '98%',   threshold: 0.98,  description: '98% language coverage' },
    { level: '99%',   threshold: 0.99,  description: '99% language coverage' },
    { level: '99.5%', threshold: 0.995, description: '99.5% language coverage' }
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
globalThis.albumToImagePath = albumToImagePath;
globalThis.defaultAlbumArt  = defaultAlbumArt;
globalThis.percentageLevels = percentageLevels;
globalThis.speechLangCodes  = speechLangCodes;
