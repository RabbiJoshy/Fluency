import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';
import test from 'node:test';

const root = resolve(import.meta.dirname, '..');
const text = path => readFile(resolve(root, path), 'utf8');

test('Study progress is a per-card audit with retained and in-session history', async () => {
    const [html, ui, cards, css] = await Promise.all([
        text('index.html'), text('js/ui.js'), text('js/flashcards.js'), text('css/style.css')
    ]);
    assert.match(html, /id="activeSetProgressList"/);
    for (const obsolete of [
        'correctCount', 'incorrectCount', 'skippedCount', 'accuracyPercent', 'wordListBody'
    ]) assert.doesNotMatch(html, new RegExp(`id="${obsolete}"`));
    assert.match(ui, /Saved card progress/);
    assert.match(ui, /Saved sense and expression progress/);
    assert.match(ui, /Progress keeps cumulative totals and the latest correct, incorrect, and seen times/);
    assert.match(cards, /attempts\.push\(\{[\s\S]*?new Date\(\)\.toISOString\(\)/);
    assert.match(css, /\.active-set-card-progress/);

    const helper = ui.slice(
        ui.indexOf('function formatStudyProgressTimestamp'),
        ui.indexOf('function getActiveSetCardResult')
    );
    const context = {};
    runInNewContext(`${helper}; result = formatStudyProgressTimestamp('2026-08-08T14:05:00Z');`, context);
    assert.match(context.result, /^\d{2}\/\d{2}\/\d{2} \d{2}:\d{2}$/);
});

test('owner shortcuts open progress, preferences, model provenance, and both flag routes', async () => {
    const [html, cards] = await Promise.all([text('index.html'), text('js/flashcards.js')]);
    assert.match(cards, /commandKey === 's'[\s\S]*?showStatsModal\(\)/);
    assert.match(cards, /commandKey === 'p'[\s\S]*?showSettingsModalWithTab\('study', \{ singleTab: true \}\)/);
    assert.match(cards, /commandKey === 'i'[\s\S]*?isJstOwner\(\)[\s\S]*?toggleProvenancePanel\(\)/);
    assert.match(cards, /Data & model info/);
    assert.match(cards, /ensureProvenancePanelForCurrentCard/);
    assert.match(cards, /commandKey === 'f' && canFlag/);
    assert.match(cards, /if \(e\.shiftKey\) window\.showFlagMenu\?\.\(\)/);
    assert.match(cards, /else window\.sendWholeCardFlag\?\.\(\)/);
    assert.match(cards, /'showFlagMenu', 'hideFlagMenu', 'sendWholeCardFlag'/);
    for (const label of ['Ctrl S', 'Ctrl P', 'Ctrl I', 'Ctrl F', 'Ctrl Shift F']) assert.match(html, new RegExp(label));
});

test('Gemini off-menu definitions carry an owner-only card marker', async () => {
    const [cards, vocab, css, pipeline] = await Promise.all([
        text('js/flashcards.js'), text('js/vocab.js'), text('css/style.css'),
        text('pipeline/artist/step_8b_assemble_artist_vocabulary.py')
    ]);
    assert.match(pipeline, /sense_model_proposed/);
    assert.match(pipeline, /method\.startswith\("lexical-gap-fill-"\)/);
    assert.match(vocab, /idx\.sense_model_proposed/);
    assert.match(vocab, /meaning\.modelProposed = true/);
    assert.match(cards, /function modelProposalMarkerHTML\(meaning\)[\s\S]*?isJstOwner\(\)[\s\S]*?meaning\?\.modelProposed/);
    assert.match(cards, /Gemini proposed this definition because it was not in the SpanishDict sense menu/);
    assert.match(css, /\.model-proposed-marker/);
});

test('SpanishDict auto evidence cannot masquerade as a Gemini run', async () => {
    const [cards, vocab] = await Promise.all([text('js/flashcards.js'), text('js/vocab.js')]);
    const helpers = vocab.slice(
        vocab.indexOf('function isAutomaticSenseMethod'),
        vocab.indexOf('/**\n * Lemma mode: pool')
    );
    const context = {};
    runInNewContext(`${helpers}; meaning = {
        prompt_id: 'sd-cop-v3', run_ts: '2026-08-08T00:14Z', model_proposed: true
    }; reconcileMeaningProvenanceFromExamples(meaning, [
        { assignment_method: 'spanishdict-auto', prompt_id: 'sd-cop-v3' }
    ]);`, context);
    assert.equal(context.meaning.assignment_method, 'spanishdict-auto');
    assert.equal(context.meaning.prompt_id, undefined);
    assert.equal(context.meaning.run_ts, undefined);
    assert.equal(context.meaning.model_proposed, undefined);
    assert.match(cards, /SpanishDict auto · no model call/);
    assert.match(cards, /single available dictionary sense/);
    assert.match(cards, /Shared sense register auto · no model call/);
    assert.match(cards, /exact line reused from another registered artist/);
    assert.match(cards, /POS-filtered auto · no model call/);
});

test('every quick flag closes at the send gesture and confirms outside the menu', async () => {
    const [html, modals, css] = await Promise.all([
        text('index.html'), text('js/flashcards-modals.js'), text('css/style.css')
    ]);
    assert.match(html, /id="flagSentToast"[\s\S]*?id="flagSentToastType"/);
    assert.match(css, /\.flag-sent-toast\.is-visible/);
    const send = modals.slice(
        modals.indexOf('async function _sendSimpleFlag'),
        modals.indexOf('function _renderSimpleSenses')
    );
    assert.ok(send.indexOf('hideFlagMenu();') < send.indexOf('await flagWord'));
    assert.match(send, /showFlagSentToast\(typeLabel\)/);
    assert.match(send, /showFlagSentToast\(typeLabel, true\)/);
    assert.match(modals, /function sendWholeCardFlag\(\)/);
});

test('example highlighting prefers the exact occurrence surface and hides clitic form piles', async () => {
    const cards = await text('js/flashcards.js');
    const helpers = cards.slice(
        cards.indexOf('function foldSurfaceForm'),
        cards.indexOf('// 18px-wide slot')
    );
    const context = {
        _cachedRegex: (source, flags) => new RegExp(source, flags)
    };
    runInNewContext(`${helpers}; result = {
        elision: getExampleOccurrenceSurface(
            { targetWord: 'cometamos' },
            { surface: "cometamo'" },
            'Que cometamo’ el mismo error otra vez'
        ),
        pooled: getExampleOccurrenceSurface(
            { targetWord: 'querer' },
            { pooledFrom: 'quieres' },
            'Tú quieres bailar'
        ),
        missing: getExampleOccurrenceSurface(
            { targetWord: 'cometamos' }, {}, 'Otro ejemplo'
        )
    };`, context);
    assert.equal(context.result.elision, "cometamo'");
    assert.equal(context.result.pooled, 'quieres');
    assert.equal(context.result.missing, '');

    const variants = cards.slice(
        cards.indexOf('const MIN_VARIANT_COUNT'),
        cards.indexOf('function foldSurfaceForm')
    );
    runInNewContext(`${variants}; result = {
        clitics: getVariantForms({ variants: ['dime', 'dile', 'decirme'] }),
        elisions: getVariantForms({ variants: { "pa'": 9, para: 4 } })
    };`, context);
    assert.equal(context.result.clitics, null);
    assert.deepEqual([...context.result.elisions], ["pa'", 'para']);
    assert.match(cards, /currentExample, displayTargetSentence/);
    assert.match(cards, /title="Recorded form in this example"/);
});
