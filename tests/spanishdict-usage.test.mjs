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
    const [cards, vocab, css, sw, html] = await Promise.all([
        text('js/flashcards.js'),
        text('js/vocab.js'),
        text('css/style.css'),
        text('service-worker.js'),
        text('index.html'),
    ]);
    assert.match(cards, /renderSenseContextHTML\(m\.context\)/);
    assert.match(cards, /data-source="spanishdict"/);
    assert.match(cards, /Possible match for this SpanishDict usage note; grammatical attachment is not verified/);
    assert.match(cards, /buildSpanishDictPanelHTML/);
    assert.match(cards, />Dictionary<\/span>/);
    assert.match(cards, /Raw dictionary fields that reached this card/);
    assert.match(vocab, /meaning\.regions = \[\.\.\.sense\.regions\]/);
    assert.match(vocab, /meaning\.regions = \[\.\.\.m\.regions\]/);
    assert.doesNotMatch(cards, /function _extractUsedWith/);
    assert.match(css, /\.meaning-usage-pill/);
    assert.match(css, /\.example-usage-highlight/);
    assert.match(css, /\.spanish-dict-panel \.sd-meta-sense/);
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

test('dictionary panel exposes raw and parsed sense metadata without frequency claims', async () => {
    const cards = await text('js/flashcards.js');
    const helpers = cards.slice(
        cards.indexOf('function spanishDictMeaningsForCard'),
        cards.indexOf('// Sense-assignment provenance panel')
    );
    const context = {
        window: {},
        parseSpanishDictUsageContext,
        spanishDictUsageCandidateForms,
        escapeCardText: value => String(value || '').replace(/[&<>"']/g, character => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[character]),
    };
    runInNewContext(`${helpers}; result = buildSpanishDictPanelHTML({
        targetWord: 'llego',
        lemma: 'llegar',
        links: { spanishDict: 'https://www.spanishdict.com/translate/llegar' },
        meanings: [{
            source: 'spanishdict',
            senseId: 'abc',
            pos: 'VERB',
            headword: 'llegar',
            meaning: 'to reach',
            context: 'to reach a place; often used with "a"',
            regions: ['Mexico', 'Puerto Rico'],
            percentage: 0.73,
            allExamples: [{
                target: 'Llegamos a casa.',
                english: 'We reached home.',
                source: 'spanishdict',
                evidence: 'dictionary'
            }]
        }, {
            source: 'gemini',
            senseId: 'outside-menu',
            meaning: 'model-only gloss'
        }]
    });`, context);

    const panel = context.result;
    assert.match(panel, /SpanishDict data/);
    assert.match(panel, /to reach a place; often used with &quot;a&quot;/);
    assert.match(panel, /often \+ a/);
    assert.match(panel, /Mexico · Puerto Rico/);
    assert.match(panel, /Possible text matches/);
    assert.match(panel, /<code>al<\/code>/);
    assert.match(panel, /same-sentence presence does not verify grammatical attachment/);
    assert.match(panel, /Llegamos a casa\./);
    assert.match(panel, /Sense ID/);
    assert.match(panel, />abc</);
    assert.doesNotMatch(panel, /model-only gloss/);
    assert.doesNotMatch(panel, /0\.73|73%/);
});
