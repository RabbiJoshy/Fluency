import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const root = resolve(import.meta.dirname, '..');
const text = path => readFile(resolve(root, path), 'utf8');

test('active-deck Study preferences is a restricted settings surface', async () => {
    const [cards, ui, html] = await Promise.all([
        text('js/flashcards.js'), text('js/ui.js'), text('index.html')
    ]);
    assert.match(cards, /showSettingsModalWithTab\('study', \{ singleTab: true \}\)/);
    assert.match(ui, /function showSettingsModalWithTab\(tabName, \{ singleTab = false \} = \{\}\)/);
    assert.match(ui, /settingsModal\.classList\.toggle\('settings-single-tab', showOnlyStudy\)/);
    assert.match(ui, /showSettingsModalWithTab\('account'\)/);
    assert.match(html, /id="settingsSingleTabTitle"[^>]*>Study preferences</);
});

test('Study omits obsolete Extra filters and explains cognate sensitivity', async () => {
    const [html, cards, ui] = await Promise.all([
        text('index.html'), text('js/flashcards.js'), text('js/ui.js')
    ]);
    for (const obsoleteId of [
        'hideSingleOccToggle', 'excludePropernounsToggle', 'excludeNoiseToggle',
        'excludeEnglishLoanwordsToggle'
    ]) {
        assert.doesNotMatch(html, new RegExp(`id="${obsoleteId}"`));
        assert.doesNotMatch(cards, new RegExp(`getElementById\\('${obsoleteId}'\\)`));
        assert.doesNotMatch(ui, new RegExp(`getElementById\\('${obsoleteId}'\\)`));
    }
    assert.match(html, /id="cognateSensitivityInfoBtn"/);
    assert.match(html, /id="cognateSensitivityExplanation"/);
    assert.match(ui, /sensitivityExplanation\.hidden = !shouldOpen/);
});

test('morphology defaults to a preferred row and expands coupled alternatives', async () => {
    const [cards, css] = await Promise.all([
        text('js/flashcards.js'), text('css/style.css')
    ]);
    assert.ok(cards.indexOf('indicativo: 0') < cards.indexOf('imperativo: 6'));
    assert.match(cards, /const primary = morphLabels\[0\]/);
    assert.match(cards, /const alternatives = morphLabels\.slice\(1\)/);
    assert.match(cards, /class="morph-alternatives" hidden/);
    assert.match(cards, /toggleMorphAlternatives\(event\)/);
    assert.match(cards, /alternatives\.hidden = !shouldOpen/);
    assert.match(css, /\.morph-pill-plus/);
    assert.match(css, /\.morph-alternative-row/);

    const helpers = cards.slice(
        cards.indexOf('function formatMorphMood'),
        cards.indexOf('const CLITIC_ROLES')
    );
    const context = {};
    runInNewContext(`${helpers}; result = compactMorphLabels([
        { person: '2s', tense: 'afirmativo', mood: 'imperativo' },
        { person: '3s', tense: 'presente', mood: 'indicativo' }
    ]);`, context);
    assert.equal(context.result[0].moodCode, 'indicativo');
    assert.equal(context.result[1].moodCode, 'imperativo');
});
