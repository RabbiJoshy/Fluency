import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';
import test from 'node:test';

const root = resolve(import.meta.dirname, '..');
const text = path => readFile(resolve(root, path), 'utf8');

test('Merge Lemmas elects one runtime representative when trepar ships two flags', async () => {
    const [vocabSource, indexSource, masterSource] = await Promise.all([
        text('js/vocab.js'),
        text('Artists/spanish/Bad Bunny/BadBunnyvocabulary.index.json'),
        text('Artists/spanish/vocabulary_master.json'),
    ]);
    const helperStart = vocabSource.indexOf('function lemmaGroupKey');
    const selectorStart = vocabSource.indexOf('function selectLemmaModeRepresentatives');
    const selectorEnd = vocabSource.indexOf('\nfunction getVocabularyExclusionReason', selectorStart);
    const helperEnd = vocabSource.indexOf('\nfunction computeLemmaExampleCounts', helperStart);
    const helpers = `${vocabSource.slice(helperStart, helperEnd)}\n${vocabSource.slice(selectorStart, selectorEnd)}`;

    const index = JSON.parse(indexSource);
    const master = JSON.parse(masterSource);
    const treparRows = index
        .filter(row => master[row.id]?.lemma === 'trepar')
        .map((row, rank) => ({ ...row, ...master[row.id], rank: rank + 1 }))
        .sort((a, b) => (b.corpus_count - a.corpus_count) || (a.rank - b.rank));
    treparRows.forEach((row, stableIndex) => { row.stableRank = stableIndex + 1; });
    assert.equal(treparRows.filter(row => row.most_frequent_lemma_instance).length, 2);

    const context = { rows: treparRows };
    runInNewContext(`${helpers}; result = selectLemmaModeRepresentatives(rows);`, context);
    assert.equal(context.result.length, 1);
    assert.equal(context.result[0].word, 'trepa');
    assert.equal(context.result[0]._lemmaModeRepresentative, true);
});

test('lemma–POS selection resets examples and pins the active meaning first', async () => {
    const cards = await text('js/flashcards.js');
    const helperStart = cards.indexOf('function lemmaPosGroupKeyForMeaning');
    const helperEnd = cards.indexOf('// Where a corpus example actually came from.', helperStart);
    const helpers = cards.slice(helperStart, helperEnd);
    const context = {
        window: {},
        stopExampleAutoplay() {},
        updateCard() { context.rendered = true; },
        meaningSelectionKey(_card, index) { return `card:${index}`; },
    };
    runInNewContext(`
        let flashcards = [{ meanings: [
            { pos: 'NOUN', headword: 'casa', allExamples: [{ target: 'noun example' }] },
            { pos: 'VERB', headword: 'casar', allExamples: [{ target: 'verb example' }] }
        ] }];
        let currentIndex = 0;
        let currentMeaningIndex = 0;
        let currentExampleIndex = 4;
        let currentMWEIndex = 3;
        let currentGroupSelection = { members: [0, 1] };
        let _explicitMeaningSelectionKey = null;
        ${helpers}
        selectLemmaPosGroup({ stopPropagation() {} }, 'VERB~~casar', 1);
        result = {
            currentMeaningIndex,
            currentExampleIndex,
            currentMWEIndex,
            currentGroupSelection,
            activePos: flashcards[0]._activePosTab,
            expanded: [...flashcards[0]._expandedPos],
            explicitKey: _explicitMeaningSelectionKey,
            order: orderMeaningEntriesForDisplay(flashcards[0].meanings, currentMeaningIndex)
                .map(entry => entry.meaning.headword),
        };
    `, context);
    assert.equal(context.result.currentMeaningIndex, 1);
    assert.equal(context.result.currentExampleIndex, 0);
    assert.equal(context.result.currentMWEIndex, 0);
    assert.equal(context.result.currentGroupSelection, null);
    assert.equal(context.result.activePos, 'VERB');
    assert.deepEqual([...context.result.expanded], ['VERB\u0000casar']);
    assert.equal(context.result.explicitKey, 'card:1');
    assert.deepEqual([...context.result.order], ['casar', 'casa']);
    assert.equal(context.rendered, true);
});

test('card rendering keeps lemma–POS groups scoped, labelled, and synchronized', async () => {
    const [cards, css] = await Promise.all([text('js/flashcards.js'), text('css/style.css')]);
    assert.match(cards, /if \(currentMeaning\?\.headword\) citationForm = currentMeaning\.headword/);
    assert.match(cards, /onclick="selectLemmaPosGroup\(event,/);
    assert.match(cards, /const hw = g\.headword[\s\S]*?pos-pill-lemma/);
    assert.match(cards, /orderMeaningEntriesForDisplay\(card\.meanings, currentMeaningIndex\)/);
    assert.match(cards, /\$\{m\.pos\}\\u0000\$\{m\.headword \|\| ''\}\\u0000\$\{ax\}/);
    assert.match(cards, /const orderedMembers = members\.includes\(currentMeaningIndex\)/);
    assert.match(cards, /activeExamples = dedupeExamples\(currentMeaning\.allExamples \|\| \[\]\)/);

    assert.doesNotMatch(cards, /class="spotify-btn link-btn/);
    assert.match(css, /@media \(hover: none\), \(max-width: 767px\)[\s\S]*?\.spotify-btn:focus-visible[\s\S]*?border-color: transparent/);
});
