import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import {
    englishProductionCue,
    selectReverseCueMeanings,
    splitProductionCloze,
} from '../js/reverse-cues.js';

const conjugatedEnglish = {
    ir: {
        'to go': {
            'pretérito-perfecto-simple': ['I went', 'you went', 'he went', 'we went', 'you (pl) went', 'they went'],
        },
    },
    ser: {
        'to be': {
            'pretérito-perfecto-simple': ['I was', 'you were', 'he was', 'we were', 'you (pl) were', 'they were'],
        },
    },
    casar: {
        'to marry': {
            presente: ['I marry', 'you marry', 'he marries', 'we marry', 'you (pl) marry', 'they marry'],
        },
    },
    llegar: {
        'to arrive': {
            presente: ['I arrive', 'you arrive', 'he arrives', 'we arrive', 'you (pl) arrive', 'they arrive'],
        },
        'to manage to': {
            presente: ['I manage to', 'you manage to', 'he manages to', 'we manage to', 'you (pl) manage to', 'they manage to'],
        },
    },
    dar: {
        'to give': {
            'indicativo/presente': ['I give', 'you give', 'he gives', 'we give', 'you (pl) give', 'they give'],
        },
    },
    hablar: {
        'to speak': {
            'gerundio/gerundio': ['speaking'],
            'participo/participo': ['spoken'],
        },
    },
};

test('reverse fingerprint covers distinct lemmas before adding extra senses', () => {
    const meanings = [
        { pos: 'VERB', headword: 'ir', meaning: 'to go', percentage: 0.6 },
        { pos: 'VERB', headword: 'ir', meaning: 'to go', percentage: 0.4, context: 'to attend' },
        { pos: 'VERB', headword: 'ser', meaning: 'to be', percentage: 0 },
    ];

    assert.deepEqual(
        selectReverseCueMeanings(meanings).map(meaning => [meaning.headword, meaning.meaning]),
        [['ir', 'to go'], ['ser', 'to be']],
    );
});

test('reverse fingerprint keeps useful polysemy but caps the dictionary list', () => {
    const meanings = [
        { pos: 'VERB', headword: 'llegar', meaning: 'to manage to', percentage: 0.4 },
        { pos: 'VERB', headword: 'llegar', meaning: 'to arrive', percentage: 0.3 },
        { pos: 'VERB', headword: 'llegar', meaning: 'to reach', percentage: 0.2 },
        { pos: 'VERB', headword: 'llegar', meaning: 'to come', percentage: 0.1 },
        { pos: 'VERB', headword: 'llegar', meaning: 'to show up', percentage: 0 },
        { pos: 'MWE', meaning: 'as soon as' },
    ];

    assert.deepEqual(
        selectReverseCueMeanings(meanings).map(meaning => meaning.meaning),
        ['to manage to', 'to arrive', 'to reach', 'to come'],
    );
});

test('reverse fingerprint excludes lemma senses that cannot realize the exact surface', () => {
    const card = {
        targetWord: 'puedes',
        lemma: 'poder',
        morphology: { mood: 'indicativo', tense: 'presente', person: '2s' },
    };
    const meanings = [
        { pos: 'NOUN', headword: 'poder', meaning: 'power', percentage: 0.33 },
        { pos: 'VERB', headword: 'poder', meaning: 'can', percentage: 0.33 },
        { pos: 'VERB', headword: 'poder', meaning: 'to put up with', percentage: 0.33 },
    ];

    assert.deepEqual(
        selectReverseCueMeanings(meanings, { card }).map(meaning => meaning.meaning),
        ['can', 'to put up with'],
    );
});

test('reverse fingerprint never blanks an older card when no compatible gloss survives', () => {
    const card = {
        targetWord: 'des',
        lemma: 'dar',
        morphology: { mood: 'subjuntivo', tense: 'presente', person: '2s' },
    };
    const legacyMeanings = [
        { pos: 'NOUN', headword: 'de', meaning: 'name of the letter d', percentage: 1 },
    ];

    assert.deepEqual(
        selectReverseCueMeanings(legacyMeanings, { card }).map(meaning => meaning.meaning),
        ['name of the letter d'],
    );
});

test('English verb morphology follows each sense lemma, not the card lemma', () => {
    const card = {
        targetWord: 'fue',
        lemma: 'ir',
        morphology: { mood: 'indicativo', tense: 'pretérito-perfecto-simple', person: '3s' },
    };

    assert.equal(
        englishProductionCue(card, { pos: 'VERB', headword: 'ir', meaning: 'to go' }, conjugatedEnglish),
        'he/she/it went',
    );
    assert.equal(
        englishProductionCue(card, { pos: 'VERB', headword: 'ser', meaning: 'to be' }, conjugatedEnglish),
        'he/she/it was',
    );
});

test('English production handles noun and verb readings of the same surface separately', () => {
    const card = {
        targetWord: 'casas',
        productionAnswer: 'casas',
        lemma: 'casa',
        morphology: { mood: 'indicativo', tense: 'presente', person: '2s' },
    };

    assert.equal(
        englishProductionCue(card, { pos: 'NOUN', headword: 'casa', meaning: 'house' }, conjugatedEnglish),
        'houses',
    );
    assert.equal(
        englishProductionCue(card, { pos: 'NOUN', headword: 'casa', meaning: 'company' }, conjugatedEnglish),
        'companies',
    );
    assert.equal(
        englishProductionCue(card, { pos: 'VERB', headword: 'casar', meaning: 'to marry' }, conjugatedEnglish),
        'you marry',
    );
});

test('English production shows supported ambiguous analyses without guessing at unsupported ones', () => {
    const card = {
        targetWord: 'da',
        lemma: 'dar',
        morphology: [
            { mood: 'indicativo', tense: 'presente', person: '3s' },
            { mood: 'imperativo', tense: 'afirmativo', person: '2s' },
        ],
    };

    assert.equal(
        englishProductionCue(card, { pos: 'VERB', headword: 'dar', meaning: 'to give' }, conjugatedEnglish),
        'he/she/it gives / give!',
    );

    const partlySupported = {
        ...card,
        targetWord: 'dé',
        morphology: [
            { mood: 'subjuntivo', tense: 'presente', person: '3s' },
            { mood: 'imperativo', tense: 'afirmativo', person: '3s' },
        ],
    };
    assert.equal(
        englishProductionCue(partlySupported, { pos: 'VERB', headword: 'dar', meaning: 'to give' }, conjugatedEnglish),
        'give!',
    );
});

test('English production covers conditional, gerund, and participle analyses', () => {
    const meaning = { pos: 'VERB', headword: 'hablar', meaning: 'to speak' };

    assert.equal(englishProductionCue({
        targetWord: 'hablaría',
        morphology: { mood: 'condicional', tense: 'presente', person: '3s' },
    }, meaning, conjugatedEnglish), 'he/she/it would speak');
    assert.equal(englishProductionCue({
        targetWord: 'hablando',
        morphology: { mood: 'gerundio', tense: 'gerundio', person: '' },
    }, meaning, conjugatedEnglish), 'speaking');
    assert.equal(englishProductionCue({
        targetWord: 'hablado',
        morphology: { mood: 'participio', tense: 'participio', person: '' },
    }, meaning, conjugatedEnglish), 'spoken');
});

test('English production abstains from context-dependent imperfect and subjunctive', () => {
    const meaning = { pos: 'VERB', headword: 'hablar', meaning: 'to speak' };

    for (const morphology of [
        { mood: 'indicativo', tense: 'pretérito-imperfecto', person: '1s' },
        { mood: 'subjuntivo', tense: 'presente', person: '1s' },
        { mood: 'subjuntivo', tense: 'pretérito-imperfecto', person: '1s' },
    ]) {
        assert.equal(englishProductionCue({ targetWord: 'hablara', morphology }, meaning, conjugatedEnglish), null);
    }
});

test('English-first card renderer consumes the bounded, sense-aware cues', () => {
    const source = fs.readFileSync(new URL('../js/flashcards.js', import.meta.url), 'utf8');
    assert.match(source, /selectReverseCueMeanings\(normalMeanings, \{ card \}\)/u);
    assert.match(source, /getProductionEnglishCue\(card, m\) \|\| m\.meaning/u);
    assert.doesNotMatch(source, /getConjugatedEnglish\(card, m\.meaning\)/u);
});

test('optional production cloze finds the exact answer across apostrophe styles', () => {
    assert.deepEqual(splitProductionCloze('Esto es pa’ ti.', "pa'"), {
        before: 'Esto es ',
        matched: 'pa’',
        after: ' ti.',
    });
    assert.deepEqual(splitProductionCloze('Lo voy   a hacer.', 'voy a'), {
        before: 'Lo ',
        matched: 'voy   a',
        after: ' hacer.',
    });
    assert.equal(splitProductionCloze('La parada está cerca.', 'para'), null,
        'a production blank must not consume a substring of another word');
});

test('English-first presentation keeps grammar visible and context optional', () => {
    const source = fs.readFileSync(new URL('../js/flashcards.js', import.meta.url), 'utf8');
    const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
    const css = fs.readFileSync(new URL('../css/style.css', import.meta.url), 'utf8');

    assert.match(source, /const showFrontMorph = Boolean\(isFlipped && frontHasVerb && morphLabels\.length\)/u);
    assert.match(source, /class="front-morph-analysis"/u);
    assert.match(source, /foldSurfaceForm\(answerInSentence\) !== foldSurfaceForm\(activeAnswer\)/u);
    assert.match(source, /toggleFrontProductionHint\(event\)/u);
    assert.match(html, /<\/button>\s*<div class="front-production-hint" id="frontProductionHint" hidden><\/div>\s*<!-- POS pill/u);
    assert.match(css, /\.front-production-cloze\[hidden\]\s*\{\s*display: none;/u);
});

test('recognition back makes sense density calmer without weakening filters', () => {
    const source = fs.readFileSync(new URL('../js/flashcards.js', import.meta.url), 'utf8');
    const css = fs.readFileSync(new URL('../css/style.css', import.meta.url), 'utf8');

    assert.doesNotMatch(source, /back-pos-tab-label[^\n]*Choose/u);
    assert.match(source, /aria-label="Filter senses by part of speech"/u);
    assert.match(source, /pos-section-summary[^\n]*summarySense[^\n]*\$\{extra\}/u,
        'the extra-sense count belongs beside the gloss');
    assert.match(source, /key === activeLemmaPosKey && activeGroupSense/u,
        'the active low-frequency sense must also lead its lemma–POS summary');
    assert.match(source, /card\._backSectionsManuallySet = true/u);
    assert.match(source, /scroll\.scrollHeight <= availableForScroll \+ 1/u);
    assert.match(css, /\.meaning-row-group \.row-adaptive-text\s*\{\s*font-size: calc\(var\(--row-primary-size, 17px\) \+ 1px\)/u);
});
