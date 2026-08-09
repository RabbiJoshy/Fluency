import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';
import test from 'node:test';

const root = resolve(import.meta.dirname, '..');
const text = path => readFile(resolve(root, path), 'utf8');

test('setup new-card counts share exact and lemma progress with deck construction', async () => {
    const ui = await text('js/ui.js');
    const helper = ui.slice(
        ui.indexOf('function getSetupLearningState'),
        ui.indexOf('async function renderRangeSelector')
    );
    assert.ok(helper.startsWith('function getSetupLearningState'));

    const context = {};
    runInNewContext(`
        const currentUser = { isGuest: false };
        const progressData = {};
        const activeArtist = {};
        const itemProgress = new Map();
        const reviewInfo = new Map();
        const wordStates = new Map();
        const unseen = { seen: false, needsReview: false, learned: false };
        const getWordId = item => item.fullId;
        const getCrossModeId = id => id.slice(0, 2) + (id[2] === '1' ? '0' : '1') + id.slice(3);
        const getWordProgressState = id => wordStates.get(id) || unseen;
        const getWordKnowledgeReviewInfo = id => reviewInfo.get(id) || { needsReview: false };
        const wordHasKnowledgeProgress = id => itemProgress.has(id);
        ${helper}
        const card = { fullId: 'es1024935', id: '024935', lemma: 'poner', rank: 100 };

        wordStates.set('es1024935', { seen: true, needsReview: false, learned: true });
        const sameArtist = getSetupLearningState(card);

        wordStates.clear();
        wordStates.set('es0024935', { seen: true, needsReview: false, learned: true });
        const crossMode = getSetupLearningState(card);

        wordStates.clear();
        const inheritedLemma = getSetupLearningState(
            { ...card, fullId: 'es1e3e80f', id: 'e3e80f' },
            { seenLemmas: new Set(['poner']) }
        );

        reviewInfo.set('es0024935', { needsReview: true, reason: 'incorrect', reviewAt: 42 });
        const reviewWins = getSetupLearningState(card, { seenLemmas: new Set(['poner']) });

        result = { sameArtist, crossMode, inheritedLemma, reviewWins };
    `, context);

    const result = context.result;
    assert.equal(result.sameArtist.seen, true);
    assert.equal(result.crossMode.seen, true);
    assert.equal(result.inheritedLemma.inheritedLemma, true);
    assert.equal(result.reviewWins.needsReview, true);
    assert.equal(result.reviewWins.reviewReason, 'incorrect');
    assert.match(ui, /await window\.buildSeenLemmaSet\?\.\(vocabularyData\)/);
});

test('Learn New never falls back to the complete set', async () => {
    const vocab = await text('js/vocab.js');
    assert.doesNotMatch(vocab, /filteredData = allInRange\.slice\(\);[\s\S]{0,200}studyMode = 'all'/);
    assert.match(vocab, /No unseen flashcards remain in this set/);
    assert.match(vocab, /if \(studyMode === 'new'\) await window\.renderRangeSelector\?\.\(\)/);
});
