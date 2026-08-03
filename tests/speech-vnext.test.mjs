import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';

const root = resolve(import.meta.dirname, '..');
const text = path => readFile(resolve(root, path), 'utf8');

test('Speech vNext is an isolated query route with a versioned deck', async () => {
    const [main, config, deck, manifest, deckBody] = await Promise.all([
        text('js/main.js'),
        JSON.parse(await text('config/config.json')),
        JSON.parse(await text('Data/Spanish/runs/speech_vnext/2026-08-03_pilot_v0_1/deck.json')),
        JSON.parse(await text('Data/Spanish/runs/speech_vnext/2026-08-03_pilot_v0_1/manifest.json')),
        text('Data/Spanish/runs/speech_vnext/2026-08-03_pilot_v0_1/deck.json')
    ]);

    assert.match(main, /_initialParams\.get\('speech'\) === 'vnext'/);
    assert.match(main, /import\('\.\/speech-vnext\.js\?v=/);
    assert.equal(
        config.languages.spanish.speechVnext.deckPath,
        'Data/Spanish/runs/speech_vnext/2026-08-03_pilot_v0_1/deck.json'
    );
    assert.equal(deck.architecture, 'spanish_speech_vnext');
    assert.equal(deck.legacy_compatibility.default_app_unchanged, true);
    assert.equal(deck.legacy_compatibility.legacy_app_index, 'Data/Spanish/vocabulary.index.json');
    assert.equal(manifest.deck.bytes, Buffer.byteLength(deckBody));
    assert.equal(manifest.deck.sha256, createHash('sha256').update(deckBody).digest('hex'));
});

test('Speech vNext cards keep stable IDs, broad labels and exact examples', async () => {
    const source = await text('js/speech-vnext.js');
    const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
    const { buildSpeechVnextCards } = await import(moduleUrl);
    const deck = JSON.parse(await text(
        'Data/Spanish/runs/speech_vnext/2026-08-03_pilot_v0_1/deck.json'
    ));
    const cards = buildSpeechVnextCards(deck, word => ({ spanishDict: word }));

    assert.deepEqual(cards.map(card => card.targetWord), ['banco', 'cola', 'cura', 'sierra']);
    assert.equal(cards[0].id, '2232e7');
    assert.equal(cards[0].meanings[0].sense_id, '18e');
    assert.equal(cards[0].meanings[0].prominenceLabel, 'Dominant');
    assert.equal(cards[0].meanings[0].allExamples[0].source, 'spanishdict');
    assert.equal(cards[0].meanings[0].allExamples[0].assignment_method, 'spanishdict-exact');
    assert.ok(cards.every(card => card.previewOnly && card.rank === undefined));
    assert.ok(cards.every(card => card.meanings.every(meaning => meaning.allExamples.length > 0)));
});

test('Speech vNext learner deck excludes unaudited corpus candidates', async () => {
    const deckText = await text(
        'Data/Spanish/runs/speech_vnext/2026-08-03_pilot_v0_1/deck.json'
    );
    const deck = JSON.parse(deckText);
    assert.equal(deck.evidence.corpus_candidates_in_learner_deck, false);
    assert.doesNotMatch(deckText, /Quizás prefieras que te patee la cola/);
    for (const word of deck.words) {
        const displayed = word.dictionary_senses.filter(sense => sense.display);
        assert.ok(displayed.length > 0);
        assert.ok(displayed.every(sense => sense.canonical_examples.length > 0));
    }
});

test('preview answers are explicitly blocked from progress persistence', async () => {
    const cards = await text('js/flashcards.js');
    assert.match(cards, /if \(currentCard\?\.previewOnly\) return;/);
    assert.match(cards, /if \(speechVnextActive\)/);
});
