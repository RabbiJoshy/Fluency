import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';

const root = resolve(import.meta.dirname, '..');
const coreSource = await readFile(resolve(root, 'js/vocabulary-import-core.js'), 'utf8');
const {
    buildImportBulkChunks,
    buildVocabularyImportPlan,
    importPlanFingerprint,
    normalizeImportedSurface,
    parseVocabularyImport
} = await import(`data:text/javascript;base64,${Buffer.from(coreSource).toString('base64')}`);

const fixtureIndex = [
    { id: '11111111', word: 'hablo', lemma: 'hablar' },
    { id: '22222222', word: 'comieron', lemma: 'comer' },
    { id: '33333333', word: 'sí', lemma: 'sí' },
    { id: '44444444', word: 'si', lemma: 'si' }
];
const now = Date.parse('2026-08-16T12:00:00.000Z');

test('plain text, BOM, CRLF, CSV aliases, quoted CSV and TSV parse deterministically', () => {
    const plain = parseVocabularyImport('\ufeff Hablo \r\ncomieron\r\n');
    assert.equal(plain.format, 'text');
    assert.deepEqual(plain.rows.map(row => row.surface), ['Hablo', 'comieron']);
    assert.deepEqual(parseVocabularyImport('hola,\n').rows.map(row => row.surface), ['hola,']);

    const csv = parseVocabularyImport(
        'word,headword,last_correct,last_wrong\n"sí","sí",2026-08-01,"2026-07-01T10:30:00Z"\n'
    );
    assert.equal(csv.format, 'csv');
    assert.deepEqual(csv.rows[0], {
        line: 2,
        surface: 'sí',
        lemma: 'sí',
        lastCorrect: '2026-08-01',
        lastWrong: '2026-07-01T10:30:00Z'
    });

    const tsv = parseVocabularyImport('surface\tlemma\tlast_incorrect\ncomieron\tcomer\t2026-08-02\n');
    assert.equal(tsv.format, 'tsv');
    assert.equal(tsv.rows[0].lastWrong, '2026-08-02');
});

test('matching uses only trimmed NFC Spanish surface and keeps accents distinct', () => {
    assert.equal(normalizeImportedSurface(' SI\u0301 '), 'sí');
    const parsed = parseVocabularyImport('surface,lemma\nSI\u0301,si\nsi,sí\nunknown,hablo\n');
    const plan = buildVocabularyImportPlan(parsed, fixtureIndex, {}, { now });
    assert.deepEqual(plan.entries.map(entry => entry.itemId).sort(), ['es033333333', 'es044444444']);
    assert.deepEqual(plan.unmatched.map(row => row.surface), ['unknown']);
    assert.ok(plan.entries.every(entry => /^es0[0-9a-f]{8}$/.test(entry.itemId)));
});

test('duplicates collapse, dates combine, and invalid or future rows are skipped', () => {
    const parsed = parseVocabularyImport([
        'surface,last_correct,last_incorrect',
        'hablo,2026-07-01,',
        'HABLO,2026-08-01,2026-07-10',
        'comieron,not-a-date,',
        'sí,2026-09-01,',
        'si,2026-02-30,'
    ].join('\n'));
    const plan = buildVocabularyImportPlan(parsed, fixtureIndex, {}, { now });
    assert.equal(plan.duplicateCount, 1);
    assert.equal(plan.matchedCount, 1);
    assert.equal(plan.invalid.length, 3);
    assert.equal(plan.entries[0].progress.lastCorrect, '2026-08-01T00:00:00.000Z');
    assert.equal(plan.entries[0].progress.lastWrong, '2026-07-10T00:00:00.000Z');
});

test('undated rows become known now while a later incorrect date remains review', () => {
    const undated = buildVocabularyImportPlan(parseVocabularyImport('hablo'), fixtureIndex, {}, { now });
    assert.equal(undated.entries[0].progress.lastCorrect, '2026-08-16T12:00:00.000Z');
    assert.equal(undated.entries[0].progress.correct, 1);
    assert.equal(undated.entries[0].progress.srsStage, 1);

    const wrong = buildVocabularyImportPlan(
        parseVocabularyImport('surface,last_correct,last_incorrect\ncomieron,2026-06-01,2026-07-01'),
        fixtureIndex,
        {},
        { now }
    );
    assert.ok(Date.parse(wrong.entries[0].progress.lastWrong) > Date.parse(wrong.entries[0].progress.lastCorrect));
    assert.equal(wrong.entries[0].progress.wrong, 1);
    assert.equal(wrong.entries[0].progress.srsStage, 0);
});

test('newer existing answers win and re-import remains idempotent', () => {
    const parsed = parseVocabularyImport('surface,last_correct\nhablo,2026-06-01');
    const existing = {
        es011111111: {
            word: 'hablo', language: 'spanish', correct: 5, wrong: 2,
            lastCorrect: '2026-08-10T00:00:00.000Z',
            lastWrong: '2026-08-01T00:00:00.000Z',
            lastSeen: '2026-08-10T00:00:00.000Z', srsStage: 4
        }
    };
    const first = buildVocabularyImportPlan(parsed, fixtureIndex, existing, { now });
    assert.equal(first.entries[0].progress.correct, 5);
    assert.equal(first.entries[0].progress.lastCorrect, '2026-08-10T00:00:00.000Z');
    assert.equal(first.entries[0].progress.srsStage, 4);
    const afterFirst = { es011111111: first.entries[0].progress };
    const second = buildVocabularyImportPlan(parsed, fixtureIndex, afterFirst, { now });
    assert.equal(second.changedEntries.length, 0);
    assert.equal(importPlanFingerprint(second), '811c9dc5');
});

test('bulk rows are normal-mode word upserts, carry user per row, and chunk at 50', () => {
    const index = Array.from({ length: 101 }, (_, index) => ({
        id: index.toString(16).padStart(8, '0'),
        word: `word-${index}`
    }));
    const parsed = parseVocabularyImport(index.map(entry => entry.word).join('\n'));
    const plan = buildVocabularyImportPlan(parsed, index, {}, { now });
    const chunks = buildImportBulkChunks(plan, 'JST');
    assert.deepEqual(chunks.map(chunk => chunk.length), [50, 50, 1]);
    for (const row of chunks.flat()) {
        assert.equal(row.user, 'JST');
        assert.equal(row.itemType, 'word');
        assert.equal(row.mode, 'normal');
        assert.equal(row.language, 'spanish');
        assert.match(row.itemId, /^es0[0-9a-f]{8}$/);
    }
});

test('UI gates guests, requires preview confirmation, refreshes setup, and queued bulk rows overlay reloads', async () => {
    const [ui, importer, queue, html] = await Promise.all([
        readFile(resolve(root, 'js/ui.js'), 'utf8'),
        readFile(resolve(root, 'js/vocabulary-import.js'), 'utf8'),
        readFile(resolve(root, 'js/sync-queue.js'), 'utf8'),
        readFile(resolve(root, 'index.html'), 'utf8')
    ]);
    assert.match(ui, /vocabularyImportButton\.hidden = !\(currentUser && !currentUser\.isGuest\)/);
    assert.match(importer, /if \(!currentPlan \|\| !currentPlan\.changedEntries\.length\) return/);
    assert.match(importer, /window\.refreshSetupAfterProgress/);
    assert.match(importer, /action: 'bulkSave'/);
    assert.match(queue, /p\.action === 'bulkSave' && Array\.isArray\(p\.rows\)/);
    assert.match(html, /id="confirmVocabularyImportBtn" disabled/);
});
