#!/usr/bin/env node
'use strict';

// In-memory regression test for the manually deployed Apps Script backend.
// It deliberately uses no package dependency so it can run with plain Node.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Range {
    constructor(sheet, row, column, rowCount = 1, columnCount = 1) {
        this.sheet = sheet;
        this.row = row;
        this.column = column;
        this.rowCount = rowCount;
        this.columnCount = columnCount;
    }
    getValues() {
        return Array.from({ length: this.rowCount }, (_, rowOffset) =>
            Array.from({ length: this.columnCount }, (_, columnOffset) =>
                this.sheet.rows[this.row - 1 + rowOffset]?.[this.column - 1 + columnOffset] ?? ''));
    }
    setValues(values) {
        for (let r = 0; r < this.rowCount; r++) {
            const targetRow = this.row - 1 + r;
            while (this.sheet.rows.length <= targetRow) this.sheet.rows.push([]);
            for (let c = 0; c < this.columnCount; c++) {
                this.sheet.rows[targetRow][this.column - 1 + c] = values[r][c];
            }
        }
        return this;
    }
    getValue() { return this.getValues()[0][0]; }
    setValue(value) { return this.setValues([[value]]); }
    setFontWeight() { return this; }
}

class Sheet {
    constructor(spreadsheet, name, rows = []) {
        this.spreadsheet = spreadsheet;
        this.name = name;
        this.rows = rows.map(row => row.slice());
    }
    getName() { return this.name; }
    setName(nextName) {
        delete this.spreadsheet.sheets[this.name];
        this.name = nextName;
        this.spreadsheet.sheets[nextName] = this;
        return this;
    }
    getLastRow() { return this.rows.length; }
    getDataRange() {
        const columns = Math.max(1, ...this.rows.map(row => row.length));
        return new Range(this, 1, 1, Math.max(1, this.rows.length), columns);
    }
    getRange(row, column, rowCount = 1, columnCount = 1) {
        return new Range(this, row, column, rowCount, columnCount);
    }
    appendRow(row) { this.rows.push(row.slice()); return this; }
    deleteRow(row) { this.rows.splice(row - 1, 1); }
    clearContents() { this.rows = []; return this; }
    setFrozenRows() { return this; }
    autoResizeColumns() { return this; }
}

class Spreadsheet {
    constructor(seed) {
        this.sheets = {};
        for (const [name, rows] of Object.entries(seed)) {
            this.sheets[name] = new Sheet(this, name, rows);
        }
    }
    getSheetByName(name) { return this.sheets[name] || null; }
    getSheets() { return Object.values(this.sheets); }
    insertSheet(name) {
        assert.equal(this.getSheetByName(name), null, `duplicate sheet ${name}`);
        const sheet = new Sheet(this, name);
        this.sheets[name] = sheet;
        return sheet;
    }
}

const wordHeaders = [
    'User', 'Word', 'WordId', 'Language', 'Correct', 'Wrong',
    'LastCorrect', 'LastWrong', 'SrsStage', 'LastSeen'
];
const itemHeaders = [
    'User', 'ItemId', 'ParentWordId', 'ItemType', 'Label', 'Language',
    'Correct', 'Wrong', 'LastCorrect', 'LastWrong', 'LastSeen', 'SchemaVersion', 'SrsStage'
];
const spreadsheet = new Spreadsheet({
    UserProgress: [
        wordHeaders,
        ['JT', 'hablar', 'es000001', 'spanish', 2, 1, '2026-07-20', '2026-07-19', 2, '2026-07-20'],
        ['JT', '_LEVEL_ESTIMATE_', 1400, 'spanish', 0, 0, '', '', '', '2026-07-18']
    ],
    Lyrics: [
        wordHeaders,
        ['JT', 'fuego', 'es100001', 'spanish', 4, 0, '2026-07-21', '', 3, '2026-07-21']
    ],
    ItemProgress: [
        itemHeaders,
        ['JT', 'sense-1', 'es100001', 'sense', 'fire', 'spanish', 1, 0,
            '2026-07-21', '', '2026-07-21', 3, 1],
        ['JT', 'mwe-1', 'es000001', 'expression', 'hablar de', 'spanish', 0, 1,
            '', '2026-07-22', '2026-07-22', 3, 0]
    ],
    FlaggedWords: [['User', 'Word', 'WordId', 'Language', 'Correct', 'Wrong', 'LastCorrect', 'LastWrong']]
});
const properties = new Map();
const context = {
    console,
    Date,
    JSON,
    isFinite,
    SpreadsheetApp: { getActiveSpreadsheet: () => spreadsheet },
    PropertiesService: {
        getScriptProperties: () => ({
            getProperty: key => properties.get(key) ?? null,
            setProperty: (key, value) => properties.set(key, String(value)),
            deleteProperty: key => properties.delete(key)
        })
    },
    LockService: {
        getScriptLock: () => ({ waitLock() {}, releaseLock() {} })
    },
    ContentService: {
        MimeType: { JSON: 'application/json' },
        createTextOutput: text => ({
            text,
            setMimeType() { return this; }
        })
    }
};
vm.createContext(context);
const source = fs.readFileSync(path.join(__dirname, 'GoogleAppsScript.js'), 'utf8');
vm.runInContext(source, context, { filename: 'GoogleAppsScript.js' });

function post(payload) {
    const response = context.doPost({ postData: { contents: JSON.stringify(payload) } });
    return JSON.parse(response.text);
}

assert.equal(post({ action: 'capabilities' }).data.schemaVersion, 4);

const migrated = post({ action: 'load', sheet: 'Progress', mode: 'all', user: 'JT' });
assert.equal(migrated.success, true);
assert.equal(migrated.data.progress.length, 2);
assert.equal(migrated.data.levelEstimates.spanish, 1400);
assert.equal(spreadsheet.getSheetByName('UserProgress'), null);
assert.ok(spreadsheet.getSheetByName('UserProgress_legacy'));
assert.ok(spreadsheet.getSheetByName('Lyrics_legacy'));
assert.ok(spreadsheet.getSheetByName('ItemProgress_legacy'));
assert.ok(spreadsheet.getSheetByName('FlaggedWords'));

const normalOnly = post({ action: 'load', sheet: 'UserProgress', user: 'JT' });
const artistOnly = post({ action: 'load', sheet: 'Lyrics', user: 'JT' });
assert.deepEqual(normalOnly.data.progress.map(row => row.wordId), ['es000001']);
assert.deepEqual(artistOnly.data.progress.map(row => row.wordId), ['es100001']);

const items = post({ action: 'loadItems', mode: 'all', user: 'JT' }).data.items;
assert.equal(items.length, 2);
assert.equal(items.find(item => item.itemId === 'mwe-1').itemType, 'mwe');

assert.equal(post({
    action: 'save', sheet: 'Lyrics', user: 'JT', word: 'fuego', wordId: 'es100001',
    language: 'spanish', correct: 5, wrong: 0, lastSeen: '2026-07-23', srsStage: 4
}).success, true);
assert.equal(post({ action: 'load', sheet: 'Lyrics', user: 'JT' }).data.progress[0].correct, 5);

const importRow = {
    user: 'JT', itemId: 'es0deadbeef', itemType: 'word', mode: 'normal',
    label: 'hubiera', language: 'spanish', correct: 1, wrong: 1,
    lastCorrect: '2026-07-01T00:00:00.000Z',
    lastWrong: '2026-07-02T00:00:00.000Z',
    lastSeen: '2026-07-02T00:00:00.000Z', srsStage: 0
};
assert.equal(post({
    action: 'bulkSave', sheet: 'Progress', rows: [
        importRow,
        { ...importRow, itemId: 'es0bad00000', user: '' }
    ]
}).success, true);
let imported = post({ action: 'load', sheet: 'UserProgress', user: 'JT' }).data.progress
    .find(row => row.wordId === 'es0deadbeef');
assert.equal(imported.word, 'hubiera');
assert.equal(imported.mode, 'normal');
assert.equal(imported.lastCorrect, '2026-07-01T00:00:00.000Z');
assert.equal(imported.lastWrong, '2026-07-02T00:00:00.000Z');
assert.equal(imported.srsStage, 0);
assert.equal(post({ action: 'load', sheet: 'UserProgress', user: 'JT' }).data.progress
    .some(row => row.wordId === 'es0bad00000'), false);
const beforeImportRetry = spreadsheet.getSheetByName('Progress').getLastRow();
assert.equal(post({ action: 'bulkSave', sheet: 'Progress', rows: [importRow] }).success, true);
assert.equal(spreadsheet.getSheetByName('Progress').getLastRow(), beforeImportRetry);
imported = post({ action: 'load', sheet: 'UserProgress', user: 'JT' }).data.progress
    .find(row => row.wordId === 'es0deadbeef');
assert.equal(imported.correct, 1);

for (const sourceName of ['bad-bunny', 'rosalia']) {
    assert.equal(post({
        action: 'saveMeta', user: 'JT', metaKey: 'level-done', metaId: 'c1800',
        mode: 'artist', source: sourceName, language: 'spanish', value: 1
    }).success, true);
}
const meta = post({ action: 'load', mode: 'all', user: 'JT' }).data.meta
    .filter(row => row.metaKey === 'level-done');
assert.equal(meta.length, 2);
assert.deepEqual(new Set(meta.map(row => row.source)), new Set(['bad-bunny', 'rosalia']));

assert.equal(post({
    action: 'deleteRow', user: 'JT', itemId: 'c1800', itemType: 'meta',
    mode: 'artist', source: 'bad-bunny', language: 'spanish', label: 'level-done'
}).success, true);
const remainingMeta = post({ action: 'load', mode: 'all', user: 'JT' }).data.meta
    .filter(row => row.metaKey === 'level-done');
assert.deepEqual(remainingMeta.map(row => row.source), ['rosalia']);

const beforeForce = spreadsheet.getSheetByName('Progress').getLastRow();
assert.equal(post({ action: 'migrateProgress' }).success, true);
assert.equal(spreadsheet.getSheetByName('Progress').getLastRow(), beforeForce);

console.log('GoogleAppsScript v4 migration and round-trip tests passed');
