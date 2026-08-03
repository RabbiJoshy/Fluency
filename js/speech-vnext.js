function titleCase(value) {
    const text = String(value || '').replaceAll('_', ' ').trim();
    return text ? text[0].toUpperCase() + text.slice(1) : '';
}

function buildMeaning(sense) {
    const example = sense.canonical_examples?.[0] || {};
    const allExamples = example.spanish ? [{
        spanish: example.spanish,
        target: example.spanish,
        english: example.english || '',
        source: 'spanishdict',
        sense_id: sense.sense_id,
        assignment_method: 'spanishdict-exact'
    }] : [];

    return {
        pos: 'NOUN',
        meaning: sense.translation,
        context: sense.context || '',
        percentage: Number(sense.share_of_sample) || 0,
        prominenceLabel: titleCase(sense.prominence),
        sense_id: sense.sense_id,
        targetSentence: example.spanish || '',
        englishSentence: example.english || '',
        allExamples
    };
}

export function buildSpeechVnextCards(data, linkBuilder = null) {
    if (data?.architecture !== 'spanish_speech_vnext' || !Array.isArray(data.words)) {
        throw new Error('Speech vNext preview data is missing or invalid.');
    }

    return data.words.map(word => {
        const meanings = word.dictionary_senses.filter(sense => sense.display).map(buildMeaning);
        const first = meanings[0] || {};
        return {
            targetWord: word.surface,
            lemma: word.lemma,
            id: word.legacy_word_id,
            meanings,
            translation: first.meaning || '',
            targetSentence: first.targetSentence || '',
            englishSentence: first.englishSentence || '',
            links: linkBuilder ? linkBuilder(word.surface, word.headword) : {},
            isMultiMeaning: true,
            speechVnext: true,
            previewOnly: true,
            previewVerdict: word.publication.status,
            previewHeadline: word.publication.headline,
            previewDetail: word.publication.detail,
            previewCoverage: word.sample.coverage,
            previewSourceRun: data.evidence.source_run
        };
    });
}

export async function startSpeechVnext() {
    const languageConfig = config.languages.spanish;
    // Keep a route-local fallback so an older controlling service worker's
    // cached config.json cannot make the first vNext visit fail. The same path
    // remains declared in config.json as the durable source contract.
    const deckPath = languageConfig.speechVnext?.deckPath
        || 'Data/Spanish/runs/speech_vnext/2026-08-03_pilot_v0_1/deck.json';
    const response = await fetch(deckPath);
    if (!response.ok) throw new Error(`Speech vNext deck fetch failed (${response.status}).`);
    const data = await response.json();

    selectedLanguage = 'spanish';
    activeArtist = null;
    speechVnextActive = true;
    useLemmaMode = false;
    isFlipped = false;
    currentIndex = 0;
    currentSentenceIndex = 0;
    currentMeaningIndex = 0;
    currentExampleIndex = 0;
    currentMWEIndex = 0;
    currentGroupSelection = null;
    cardNavStack = [];
    stats = {
        studied: new Set(),
        correct: 0,
        incorrect: 0,
        total: 0,
        cardStats: {},
        setSize: data.words.length,
        previouslyKnown: 0,
        setLabel: 'Speech vNext preview',
        rangeString: '',
        rangeBasis: 'preview',
        setNumber: null,
        levelSetCount: null,
        nextRange: null,
        nextSetNumber: null,
        nextRankBasis: 'preview',
        studyMode: 'preview',
        levelNumber: null,
        allWords: []
    };

    flashcards = buildSpeechVnextCards(data, (word, lemma) =>
        window.generateLinks(word, lemma, languageConfig.referenceLinks || {}));
    stats.allWords = flashcards.map(card => ({
        id: card.id,
        word: card.targetWord,
        translation: card.translation,
        displayRank: null
    }));

    document.body.classList.add('speech-vnext-mode');
    document.title = 'Speech vNext · Fluency';
    document.getElementById('setupPanel').classList.add('hidden');
    document.getElementById('setupPanel').style.display = 'none';
    document.getElementById('appContent').classList.remove('hidden');
    document.getElementById('loadingMessage').style.display = 'none';
    window.showFloatingBtns(true);
    window.initializeApp();
    window.buildWordLookupMap();
}
