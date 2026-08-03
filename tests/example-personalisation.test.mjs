import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';

import {
    collectRecentWrongWords,
    exampleReinforcesRecentMistake,
    filterPersonalisedExamples,
} from '../js/example-personalisation.js';

const root = resolve(import.meta.dirname, '..');
const json = async path => JSON.parse(await readFile(resolve(root, path), 'utf8'));
const text = path => readFile(resolve(root, path), 'utf8');

test('personalised templates appear only for recent incorrect words', () => {
    const now = Date.parse('2026-08-02T20:00:00Z');
    const progress = {
        recent: { wrong: 1, word: 'Coche', lastWrong: '2026-08-01T20:00:00Z' },
        old: { wrong: 3, word: 'mujer', lastWrong: '2026-07-01T20:00:00Z' },
        correctOnly: { wrong: 0, word: 'amigo', lastWrong: '2026-08-02T19:00:00Z' },
    };
    const wrongWords = collectRecentWrongWords(progress, now);
    assert.deepEqual([...wrongWords], ['coche']);

    const canonical = { target: 'Un ejemplo.', source: 'spanishdict' };
    const coche = { target: 'Este coche sirve.', personalised: true, reinforcement_word: 'coche' };
    const mujer = { target: 'La mujer sirve.', personalised: true, reinforcement_word: 'mujer' };
    assert.deepEqual(filterPersonalisedExamples([canonical, coche, mujer], wrongWords), [canonical, coche]);
    assert.equal(exampleReinforcesRecentMistake(coche, wrongWords), true);
    assert.equal(exampleReinforcesRecentMistake(mujer, wrongWords), false);
});

test('candidate frames are attached to their exact target sense and are consensus-only', async () => {
    const [index, examples, bank, manifest] = await Promise.all([
        json('Data/Spanish/vocabulary.index.json'),
        json('Data/Spanish/vocabulary.examples.json'),
        json('Data/Spanish/personalised_example_frames.json'),
        json('Data/Spanish/runs/normal_mode/2026-08-02_spanishdict_examples_v1/manifest.json'),
    ]);
    assert.equal(bank.status, 'beta_consensus_only');
    assert.equal(bank.frames.length, 15);
    assert.equal(manifest.metrics.personalised_frames, 15);
    const cards = new Map(index.map(card => [card.id, card]));
    for (const frame of bank.frames) {
        assert.match(frame.audit.a, /^(pass|accept)/);
        assert.match(frame.audit.b, /^(pass|accept)/);
        const card = cards.get(frame.target_card_id);
        assert.ok(card, frame.frame_id);
        const meaningIndex = card.meanings.findIndex(meaning =>
            (meaning.sense_id || meaning.id) === frame.target_sense_id);
        assert.notEqual(meaningIndex, -1, frame.frame_id);
        const candidates = examples[frame.target_card_id]?.m?.[meaningIndex] || [];
        const attached = candidates.find(example => example.frame_id === frame.frame_id);
        assert.ok(attached, frame.frame_id);
        assert.equal(attached.sense_id, frame.target_sense_id);
        assert.equal(attached.reinforcement_word, frame.reinforcement_word);
        assert.equal(attached.assignment_method, 'audited-template');
    }
});

test('candidate app labels canonical and personalised example provenance', async () => {
    const [cards, worker] = await Promise.all([
        text('js/flashcards.js'),
        text('service-worker.js'),
    ]);
    assert.match(cards, /Personalised practice/);
    assert.match(cards, /SpanishDict example/);
    assert.match(cards, /filterPersonalisedExamples/);
    assert.match(worker, /example-personalisation\.js/);
});
