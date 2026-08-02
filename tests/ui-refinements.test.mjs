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
    assert.match(cards, /label\.tense === 'present' && distinctTenses\.size <= 1/);
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
    assert.equal(context.result[0].person, 'Él(la)');
    assert.equal(context.result[1].person, 'Tú');

    runInNewContext(`${helpers}; result = {
        people: ['1s', '2s', '3s', '1p', '2p', '3p'].map(formatMorphPerson),
        lonePresent: visibleMorphTense({ tense: 'present' }, [{ tense: 'present' }]),
        contrastedPresent: visibleMorphTense(
            { tense: 'present' },
            [{ tense: 'present' }, { tense: 'preterite' }]
        )
    };`, context);
    assert.deepEqual(
        [...context.result.people],
        ['Yo', 'Tú', 'Él(la)', 'Nosotros', 'Vosotros', 'Ellos']
    );
    assert.equal(context.result.lonePresent, '');
    assert.equal(context.result.contrastedPresent, 'present');
});

test('setup reuses filtering work and restores joined senses only after deck mutation', async () => {
    const [vocab, ui] = await Promise.all([
        text('js/vocab.js'), text('js/ui.js')
    ]);
    assert.match(vocab, /const vocabularySourcesNeedingRestore = new WeakSet\(\)/);
    assert.match(vocab, /if \(vocabularySourcesNeedingRestore\.has\(vocabData\)\)/);
    assert.match(vocab, /vocabularySourcesNeedingRestore\.add\(vocabularyData\)/);
    assert.match(vocab, /return \{ vocab: result, counts, stableBaseline \}/);
    assert.match(ui, /computeSmartLevelRanges\(prepared\?\.stableBaseline \|\| \[\]\)/);
    assert.doesNotMatch(ui, /const stableBaseline = assignStableVocabularyRanks\(_raw\)/);
});

test('nonessential study modules and unchanged card chrome avoid repeated startup/render work', async () => {
    const [main, html, cards, artistUi, conj] = await Promise.all([
        text('js/main.js'), text('index.html'), text('js/flashcards.js'),
        text('js/artist-ui.js'), text('js/flashcards-conj.js')
    ]);
    assert.doesNotMatch(main, /^import '\.\/spotify\.js/m);
    assert.doesNotMatch(main, /^import '\.\/flashcards-modals\.js/m);
    assert.match(main, /import\('\.\/spotify\.js\?v=/);
    assert.doesNotMatch(html, /modulepreload" href="js\/(?:spotify|flashcards-modals)\.js/);
    assert.doesNotMatch(main, /window\.loadConjugationData\) window\.loadConjugationData\(\)/);
    assert.match(conj, /await window\.loadConjugationData\(\)/);
    assert.match(cards, /const backDomChanged = renderedBack\?\._fluencyRenderedHTML !== backHTML/);
    assert.match(cards, /if \(backDomChanged\) \{/);
    assert.match(cards, /reverseBtn\.dataset\.renderKey === renderKey/);
    assert.match(artistUi, /face\.dataset\.albumImage === imageUrl/);
});

test('card rows use distinct POS themes and content-aware bilingual typography', async () => {
    const [cards, css] = await Promise.all([
        text('js/flashcards.js'), text('css/style.css')
    ]);
    const posHelper = cards.slice(
        cards.indexOf('function getPosColorClass'),
        cards.indexOf('function getPosAccentRgb')
    );
    const typeHelper = cards.slice(
        cards.indexOf('function adaptiveRowTextClass'),
        cards.indexOf('function toggleMorphAlternatives')
    );
    const context = {};
    runInNewContext(`${posHelper}; result = [
        getPosColorClass('NOUN'), getPosColorClass('PROPN'),
        getPosColorClass('CCONJ'), getPosColorClass('SCONJ'),
        getPosColorClass('PART'), getPosColorClass('CONTRACTION'),
        getPosColorClass('PHRASE'), getPosColorClass('CLITIC'),
        getPosColorClass('X')
    ];`, context);
    assert.deepEqual([...context.result], [
        'pos-noun', 'pos-propn', 'pos-cconj', 'pos-sconj', 'pos-part',
        'pos-contraction', 'pos-mwe', 'pos-clitic', 'pos-other'
    ]);

    runInNewContext(`${typeHelper}; result = [
        adaptiveRowTextClass('tiny'),
        adaptiveRowTextClass('a moderate translation that fits'),
        adaptiveRowTextClass('a very long translation '.repeat(8))
    ];`, context);
    assert.deepEqual([...context.result], ['row-text-xl', 'row-text-lg', 'row-text-sm']);
    assert.match(cards, /class="special-meaning-context">· /);
    assert.match(cards, /meaning-row-translation row-adaptive-text/);
    assert.match(css, /\.special-meaning-copy\s*\{[^}]*flex-direction: row;[^}]*flex-wrap: wrap;/s);
    assert.match(css, /\.special-meaning-copy strong\s*\{[^}]*font-style: italic;/s);
    assert.match(css, /\.card-details \.special-meaning-copy strong\s*\{[^}]*color: #fff;/s);
    assert.match(css, /\.mwe-expression\s*\{[^}]*font-style: normal;/s);
    assert.match(css, /\.row-text-xl\s*\{[^}]*--row-primary-size: 21px;/s);
});

test('setup routing advances past fully seen and suggestion-skipped levels', async () => {
    const [ui, auth, cards, main] = await Promise.all([
        text('js/ui.js'), text('js/auth.js'), text('js/flashcards.js'), text('js/main.js')
    ]);
    const helper = ui.slice(
        ui.indexOf('async function findFirstIncompleteLevelBtn'),
        ui.indexOf('async function renderLevelSelector')
    );
    const context = {};
    runInNewContext(`
        const items = Array.from({ length: 60 }, (_, index) => ({
            id: 'w' + (index + 1), rank: index + 1
        }));
        const seenIds = new Set(items.slice(0, 40).map(item => item.id));
        const skipped = new Set();
        const makeButton = (level, start, end) => ({
            dataset: { level, startRank: String(start), endRank: String(end), rankBasis: 'source' },
            classList: { toggle() {} },
            style: { setProperty() {} },
            setAttribute() {}
        });
        const buttons = [makeButton('L1', 1, 41), makeButton('L2', 41, 61)];
        const config = { languages: { spanish: {} } };
        const levelEstimates = { spanish: 0 };
        const activeArtist = null;
        const currentUser = { isGuest: false };
        const progressData = {};
        const percentageMode = true;
        const ppmData = [{}];
        const window = { isLevelMarkedDone: level => skipped.has(level) };
        const document = { querySelector: () => null };
        const fetchActiveVocabularyData = async () => items;
        const getPreparedSetupVocabulary = (_language, vocab) => ({ vocab });
        const _levelRankAccessor = () => item => item.rank;
        const getWordId = item => item.id;
        const getWordProgressState = id => ({ seen: seenIds.has(id), needsReview: id === 'w1' });
        const wordHasKnowledgeProgress = () => false;
        ${helper}
        result = (async () => {
            const afterSeen = await findFirstIncompleteLevelBtn('spanish', buttons);
            seenIds.delete('w40');
            skipped.add('L1');
            const afterSkip = await findFirstIncompleteLevelBtn('spanish', buttons);
            return {
                afterSeen: afterSeen.dataset.level,
                afterSkip: afterSkip.dataset.level,
                firstCompletion: buttons[0].dataset.progressPct
            };
        })();
    `, context);
    assert.deepEqual({ ...(await context.result) }, {
        afterSeen: 'L2',
        afterSkip: 'L2',
        firstCompletion: '98'
    });
    assert.match(cards, /renderLevelSelector\(selectedLanguage, \{ preferActionable: true \}\)/);
    assert.match(main, /refreshSetupAfterProgress/);
    assert.ok(
        auth.indexOf('applyCachedProgress(cached)') < auth.indexOf("await dbGet('localState'")
    );
});
