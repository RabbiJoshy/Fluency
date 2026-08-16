import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

import {
    parseSpanishDictUsageContext,
    spanishDictUsageCandidateForms,
} from '../js/spanishdict-usage.js';

const root = resolve(import.meta.dirname, '..');
const text = path => readFile(resolve(root, path), 'utf8');

test('SpanishDict usage notes preserve strength, alternatives, and semantic detail', () => {
    assert.deepEqual(
        parseSpanishDictUsageContext('to tolerate; used with "con"'),
        {
            raw: 'to tolerate; used with "con"',
            detail: 'to tolerate',
            qualifier: null,
            label: '+ con',
            terms: ['con'],
            structural: false,
        }
    );

    const often = parseSpanishDictUsageContext('to reach a place; often used with “a”');
    assert.equal(often.label, 'often + a');
    assert.equal(often.qualifier, 'often');

    const alternatives = parseSpanishDictUsageContext(
        'road or route; used with "a", "hacia," or "por"'
    );
    assert.equal(alternatives.label, '+ a / hacia / por');
    assert.deepEqual(alternatives.terms, ['a', 'hacia', 'por']);

    const preceded = parseSpanishDictUsageContext(
        'in relation to; used with "a" o "de" and sometimes preceded by "con"'
    );
    assert.equal(preceded.label, '+ a / de · sometimes preceded by con');
    assert.deepEqual(preceded.terms, ['a', 'de', 'con']);

    const singular = parseSpanishDictUsageContext(
        'stand at the end of; used with "a"; singular'
    );
    assert.equal(singular.label, '+ a · singular');
});

test('SpanishDict usage notes expose grammatical constructions without inventing terms', () => {
    const infinitive = parseSpanishDictUsageContext(
        'to start out; used with "por" plus infinitive'
    );
    assert.equal(infinitive.label, '+ por + infinitive');
    assert.deepEqual(infinitive.terms, ['por']);

    const gerund = parseSpanishDictUsageContext('used with a gerund');
    assert.equal(gerund.label, '+ gerund');
    assert.deepEqual(gerund.terms, []);
    assert.equal(gerund.structural, true);

    const mismo = parseSpanishDictUsageContext(
        'reflexive; often used with a form of "mismo"'
    );
    assert.equal(mismo.label, 'often + form of mismo');
    assert.deepEqual(mismo.terms, ['mismo']);

    const perception = parseSpanishDictUsageContext(
        'used with verbs of perception as an equivalent of "que"'
    );
    assert.equal(perception.label, '+ verbs of perception as an equivalent of que');
    assert.deepEqual(perception.terms, []);

    assert.equal(parseSpanishDictUsageContext('religious'), null);
});

test('possible UI matches include transparent Spanish realizations but remain non-evidential', () => {
    const usage = parseSpanishDictUsageContext('used with "a" or "con"');
    assert.deepEqual(
        spanishDictUsageCandidateForms(usage),
        ['conmigo', 'contigo', 'consigo', 'con', 'al', 'a']
    );

    const mismo = parseSpanishDictUsageContext('often used with a form of "mismo"');
    assert.deepEqual(
        spanishDictUsageCandidateForms(mismo),
        ['mismos', 'mismas', 'mismo', 'misma']
    );
});

test('card UI labels SpanishDict metadata and possible matches without claiming WSD proof', async () => {
    const [cards, css, sw, html] = await Promise.all([
        text('js/flashcards.js'),
        text('css/style.css'),
        text('service-worker.js'),
        text('index.html'),
    ]);
    assert.match(cards, /renderSenseContextHTML\(m\.context\)/);
    assert.match(cards, /data-source="spanishdict"/);
    assert.match(cards, /Possible match for this SpanishDict usage note; grammatical attachment is not verified/);
    assert.doesNotMatch(cards, /function _extractUsedWith/);
    assert.match(css, /\.meaning-usage-pill/);
    assert.match(css, /\.example-usage-highlight/);
    assert.match(sw, /js\/spanishdict-usage\.js/);
    assert.match(html, /modulepreload" href="js\/spanishdict-usage\.js\?v=/);

    const helpers = cards.slice(
        cards.indexOf('function escapeCardText'),
        cards.indexOf('// Choose a type scale')
    );
    const context = {
        selectedLanguage: 'spanish',
        parseSpanishDictUsageContext,
        spanishDictUsageCandidateForms,
        _cachedRegex: (source, flags) => new RegExp(source, flags),
    };
    runInNewContext(`${helpers}; result = {
        row: renderSenseContextHTML('to stop by; used with "por" or "a por"'),
        sentence: highlightPossibleSpanishDictUsage(
            'Paso a por ti y luego por casa.',
            parseSpanishDictUsageContext('used with "por" or "a por"'),
            'paso'
        ).html
    };`, context);
    assert.match(context.result.row, /· to stop by/);
    assert.match(context.result.row, /<span class="meaning-usage-source">SpanishDict<\/span>/);
    assert.match(context.result.row, /\+ por \/ a por/);
    assert.equal((context.result.sentence.match(/example-usage-highlight/g) || []).length, 2);
    assert.doesNotMatch(context.result.sentence, /example-usage-highlight[^>]*><span/);
});
