/**
 * Language Flashcard App - Google Apps Script Backend
 *
 * Schema v4 consolidates UserProgress, Lyrics, and ItemProgress into one
 * discriminated Progress tab. The old action names remain accepted so a
 * cached v3 client can keep saving safely during rollout.
 */

const PROGRESS_SCHEMA_VERSION = 4;
const PROGRESS_SHEET_NAME = 'Progress';
const PROGRESS_HEADERS = [
  'User', 'ItemId', 'ItemType', 'Mode', 'Source', 'ParentWordId', 'Label',
  'Language', 'Correct', 'Wrong', 'LastCorrect', 'LastWrong', 'LastSeen',
  'SchemaVersion', 'SrsStage', 'Value'
];
// Flag schema v2. v1 was the progress-shaped eight-column tab
// (User, Word, WordId, Language, Correct, Wrong, LastCorrect, LastWrong) where
// the whole audit report was crammed into Word, fieldPath was smuggled through
// LastCorrect, the flag timestamp through LastWrong, and Correct/Wrong were
// always zero. The app's flag UI can emit ~29 distinct attributes, so v2 gives
// each one a real column and keeps the rendered blob in Report for reading.
const FLAG_SCHEMA_VERSION = 2;
const FLAGGED_WORDS_SHEET_NAME = 'FlaggedWords';
const FLAGGED_WORDS_HEADERS = [
  'User', 'FlaggedAt', 'Word', 'Lemma', 'Language', 'WordId', 'CardId',
  'FieldPath', 'Target', 'Category', 'SensePos', 'SenseId', 'SenseGloss',
  'Context', 'Example', 'Translation', 'Song', 'ExampleAssignment',
  'TranslationSource', 'SenseAssignment', 'RequestedTag', 'Note', 'Report',
  'SchemaVersion'
];
const FLAGGED_WORDS_V1_HEADERS = [
  'User', 'Word', 'WordId', 'Language', 'Correct', 'Wrong',
  'LastCorrect', 'LastWrong'
];
const F = {
  USER: 0,
  FLAGGED_AT: 1,
  WORD: 2,
  LEMMA: 3,
  LANGUAGE: 4,
  WORD_ID: 5,
  CARD_ID: 6,
  FIELD_PATH: 7,
  TARGET: 8,
  CATEGORY: 9,
  SENSE_POS: 10,
  SENSE_ID: 11,
  SENSE_GLOSS: 12,
  CONTEXT: 13,
  EXAMPLE: 14,
  TRANSLATION: 15,
  SONG: 16,
  EXAMPLE_ASSIGNMENT: 17,
  TRANSLATION_SOURCE: 18,
  SENSE_ASSIGNMENT: 19,
  REQUESTED_TAG: 20,
  NOTE: 21,
  REPORT: 22,
  SCHEMA: 23
};
const PROGRESS_MIGRATION_PROPERTY = 'FLUENCY_PROGRESS_V4_MIGRATED';
const FLAG_MIGRATION_PROPERTY = 'FLUENCY_FLAGS_V2_MIGRATED';

const P = {
  USER: 0,
  ITEM_ID: 1,
  ITEM_TYPE: 2,
  MODE: 3,
  SOURCE: 4,
  PARENT_ID: 5,
  LABEL: 6,
  LANGUAGE: 7,
  CORRECT: 8,
  WRONG: 9,
  LAST_CORRECT: 10,
  LAST_WRONG: 11,
  LAST_SEEN: 12,
  SCHEMA: 13,
  SRS_STAGE: 14,
  VALUE: 15
};

function doPost(e) {
  try {
    const params = JSON.parse(e.postData.contents);
    const action = params.action;

    if (action === 'save') return saveProgress(params);
    if (action === 'load') return loadProgress(params);
    if (action === 'delete') return deleteProgress(params);
    if (action === 'deleteRow') return deleteExactProgressRow(params);
    if (action === 'dump') return dumpSheet(params);
    if (action === 'bulkSave') return bulkSave(params);
    if (action === 'saveItem') return saveItemProgress(params);
    if (action === 'loadItems') return loadItemProgress(params);
    if (action === 'deleteItems') return deleteItemProgress(params);
    if (action === 'saveMeta') return saveMetaProgress(params);
    if (action === 'capabilities') {
      return createResponse(true, 'Backend capabilities', {
        schemaVersion: PROGRESS_SCHEMA_VERSION,
        flagSchemaVersion: FLAG_SCHEMA_VERSION,
        sheets: [PROGRESS_SHEET_NAME, FLAGGED_WORDS_SHEET_NAME]
      });
    }
    if (action === 'migrateProgress') {
      const result = ensureProgressSchema(true);
      return createResponse(true, 'Progress schema migration complete', result.summary);
    }
    if (action === 'migrateFlags') {
      const result = ensureFlaggedWordsSchema(true);
      return createResponse(true, 'Flag schema migration complete', result.summary);
    }
    return createResponse(false, 'Invalid action');
  } catch (error) {
    return createResponse(false, 'Error: ' + error.toString());
  }
}

/** Lightweight deployment check. Migration itself happens on the first POST. */
function doGet() {
  const props = PropertiesService.getScriptProperties();
  return ContentService.createTextOutput(JSON.stringify({
    status: 'success',
    message: 'Flashcard API is running',
    schemaVersion: PROGRESS_SCHEMA_VERSION,
    flagSchemaVersion: FLAG_SCHEMA_VERSION,
    progressMigrationComplete: props.getProperty(PROGRESS_MIGRATION_PROPERTY) === '1',
    flagMigrationComplete: props.getProperty(FLAG_MIGRATION_PROPERTY) === '1',
    timestamp: new Date().toISOString()
  })).setMimeType(ContentService.MimeType.JSON);
}

function normalizeMode(mode, id) {
  if (mode === 'normal' || mode === 'artist' || mode === 'all') return mode;
  const text = String(id || '');
  if (text.length > 2 && text.charAt(2) === '1') return 'artist';
  if (text.length > 2 && text.charAt(2) === '0') return 'normal';
  return 'normal';
}

function legacySheetMode(sheetName) {
  const name = String(sheetName || '');
  if (name.indexOf('Lyrics') === 0 || name.indexOf('BadBunny') === 0) return 'artist';
  if (name.indexOf('UserProgress') === 0) return 'normal';
  return '';
}

function normalizeItemType(itemType) {
  const value = String(itemType || '').toLowerCase();
  if (value === 'expression' || value === 'mwe') return 'mwe';
  if (value === 'sense' || value === 'clitic' || value === 'word' || value === 'meta') {
    return value;
  }
  return value || 'sense';
}

function valueOr(existingValue, incomingValue, fallback) {
  if (incomingValue !== undefined && incomingValue !== null) return incomingValue;
  if (existingValue !== undefined && existingValue !== null) return existingValue;
  return fallback;
}

function progressRowKey(row) {
  const user = String(row[P.USER] || '');
  const itemId = String(row[P.ITEM_ID] || '');
  const type = normalizeItemType(row[P.ITEM_TYPE]);
  const mode = normalizeMode(row[P.MODE], row[P.PARENT_ID] || itemId);
  if (type === 'meta') {
    return [user, type, mode, row[P.SOURCE] || '', row[P.LANGUAGE] || '',
      row[P.LABEL] || '', itemId].join('|');
  }
  return [user, type, mode, itemId].join('|');
}

function rowTimestamp(row) {
  const candidates = [row[P.LAST_SEEN], row[P.LAST_CORRECT], row[P.LAST_WRONG]];
  let latest = 0;
  candidates.forEach(function(value) {
    const parsed = value ? new Date(value).getTime() : 0;
    if (isFinite(parsed)) latest = Math.max(latest, parsed);
  });
  return latest;
}

function findProgressRow(data, key) {
  for (let i = 1; i < data.length; i++) {
    if (progressRowKey(data[i]) === key) return i + 1;
  }
  return -1;
}

function upsertProgressRow(row) {
  const sheet = getProgressSheet();
  const data = sheet.getDataRange().getValues();
  const rowIndex = findProgressRow(data, progressRowKey(row));
  if (rowIndex > 0) sheet.getRange(rowIndex, 1, 1, PROGRESS_HEADERS.length).setValues([row]);
  else sheet.appendRow(row);
  return rowIndex > 0 ? 'updated' : 'inserted';
}

function buildProgressRow(params, existing) {
  const mode = normalizeMode(params.mode || legacySheetMode(params.sheet), params.parentWordId || params.itemId);
  const itemType = normalizeItemType(params.itemType);
  return [
    params.user,
    params.itemId,
    itemType,
    mode,
    params.source || '',
    params.parentWordId || '',
    valueOr(existing[P.LABEL], params.label, ''),
    valueOr(existing[P.LANGUAGE], params.language, ''),
    Number(valueOr(existing[P.CORRECT], params.correct, 0)) || 0,
    Number(valueOr(existing[P.WRONG], params.wrong, 0)) || 0,
    valueOr(existing[P.LAST_CORRECT], params.lastCorrect, ''),
    valueOr(existing[P.LAST_WRONG], params.lastWrong, ''),
    valueOr(existing[P.LAST_SEEN], params.lastSeen, new Date().toISOString()),
    PROGRESS_SCHEMA_VERSION,
    params.srsStage === undefined
      ? valueOr(existing[P.SRS_STAGE], undefined, '')
      : normalizeSrsStage(params.srsStage),
    valueOr(existing[P.VALUE], params.value, '')
  ];
}

function existingProgressRow(params) {
  const sheet = getProgressSheet();
  const data = sheet.getDataRange().getValues();
  const probe = buildProgressRow(params, []);
  const rowIndex = findProgressRow(data, progressRowKey(probe));
  return rowIndex > 0 ? data[rowIndex - 1] : [];
}

/** Save one whole-card row. Legacy level-estimate sentinels become meta rows. */
function saveProgress(params) {
  if (params.sheet === 'FlaggedWords') return saveFlaggedWord(params);
  if (params.word === '_LEVEL_ESTIMATE_') {
    return saveMetaProgress({
      user: params.user,
      metaKey: 'level-estimate',
      metaId: params.language || 'unknown',
      mode: 'normal',
      source: 'speech',
      language: params.language || '',
      value: params.wordId,
      lastSeen: params.lastSeen
    });
  }
  const itemId = params.wordId;
  if (!params.user || itemId === undefined) {
    return createResponse(false, 'Missing required fields: user, wordId');
  }
  const normalized = {
    user: params.user,
    itemId: itemId,
    itemType: 'word',
    mode: params.mode || legacySheetMode(params.sheet),
    source: '',
    parentWordId: '',
    label: params.word || '',
    language: params.language || '',
    correct: params.correct,
    wrong: params.wrong,
    lastCorrect: params.lastCorrect,
    lastWrong: params.lastWrong,
    lastSeen: params.lastSeen,
    srsStage: params.srsStage,
    value: ''
  };
  const existing = existingProgressRow(normalized);
  upsertProgressRow(buildProgressRow(normalized, existing));
  return createResponse(true, 'Progress saved successfully');
}

/** Save one sparse sense / MWE / clitic row in Progress. */
function saveItemProgress(params) {
  const itemType = normalizeItemType(params.itemType);
  if (!params.user || !params.itemId || !params.parentWordId) {
    return createResponse(false, 'Missing required fields: user, itemId, parentWordId');
  }
  if (['sense', 'mwe', 'clitic', 'lemma'].indexOf(itemType) < 0) {
    return createResponse(false, 'Invalid itemType: ' + itemType);
  }
  const normalized = {
    user: params.user,
    itemId: params.itemId,
    itemType: itemType,
    mode: params.mode || normalizeMode('', params.parentWordId),
    source: '',
    parentWordId: params.parentWordId,
    label: params.label || '',
    language: params.language || '',
    correct: params.correct,
    wrong: params.wrong,
    lastCorrect: params.lastCorrect,
    lastWrong: params.lastWrong,
    lastSeen: params.lastSeen,
    srsStage: params.srsStage,
    value: ''
  };
  const existing = existingProgressRow(normalized);
  upsertProgressRow(buildProgressRow(normalized, existing));
  return createResponse(true, 'Item progress saved successfully');
}

/** Save a scalar metadata row such as a level estimate or level-done flag. */
function saveMetaProgress(params) {
  if (!params.user || !params.metaKey || params.metaId === undefined) {
    return createResponse(false, 'Missing required fields: user, metaKey, metaId');
  }
  const normalized = {
    user: params.user,
    itemId: String(params.metaId),
    itemType: 'meta',
    mode: params.mode || 'normal',
    source: params.source || '',
    parentWordId: '',
    label: params.metaKey,
    language: params.language || '',
    correct: 0,
    wrong: 0,
    lastCorrect: '',
    lastWrong: '',
    lastSeen: params.lastSeen || new Date().toISOString(),
    srsStage: '',
    value: params.value
  };
  const existing = existingProgressRow(normalized);
  upsertProgressRow(buildProgressRow(normalized, existing));
  return createResponse(true, 'Progress metadata saved successfully');
}

/** Load word rows plus metadata. mode='all' preserves cross-mode knowledge. */
function loadProgress(params) {
  const user = params.user;
  if (!user) return createResponse(false, 'Missing required field: user');

  const requestedMode = params.mode || legacySheetMode(params.sheet) || 'all';
  const modeFilter = normalizeMode(requestedMode);
  const data = getProgressSheet().getDataRange().getValues();
  const userProgress = [];
  const levelEstimates = {};
  const meta = [];

  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    if (row[P.USER] !== user) continue;
    const itemType = normalizeItemType(row[P.ITEM_TYPE]);
    const rowMode = normalizeMode(row[P.MODE], row[P.PARENT_ID] || row[P.ITEM_ID]);
    if (itemType === 'word') {
      if (modeFilter !== 'all' && rowMode !== modeFilter) continue;
      userProgress.push({
        word: row[P.LABEL],
        wordId: row[P.ITEM_ID],
        itemType: 'word',
        mode: rowMode,
        language: row[P.LANGUAGE],
        correct: row[P.CORRECT],
        wrong: row[P.WRONG],
        lastCorrect: row[P.LAST_CORRECT],
        lastWrong: row[P.LAST_WRONG],
        lastSeen: row[P.LAST_SEEN],
        schemaVersion: row[P.SCHEMA] || PROGRESS_SCHEMA_VERSION,
        srsStage: row[P.SRS_STAGE]
      });
    } else if (itemType === 'meta') {
      const metaRow = {
        metaId: row[P.ITEM_ID],
        metaKey: row[P.LABEL],
        mode: rowMode,
        source: row[P.SOURCE] || '',
        language: row[P.LANGUAGE] || '',
        value: row[P.VALUE],
        lastSeen: row[P.LAST_SEEN]
      };
      meta.push(metaRow);
      if (metaRow.metaKey === 'level-estimate') {
        levelEstimates[metaRow.language] = metaRow.value;
      }
    }
  }

  return createResponse(true, 'Progress loaded successfully', {
    schemaVersion: PROGRESS_SCHEMA_VERSION,
    progress: userProgress,
    levelEstimates: levelEstimates,
    meta: meta
  });
}

function loadItemProgress(params) {
  const user = params.user;
  if (!user) return createResponse(false, 'Missing required field: user');
  const requestedMode = params.mode || 'all';
  const modeFilter = normalizeMode(requestedMode);
  const data = getProgressSheet().getDataRange().getValues();
  const items = [];
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    if (row[P.USER] !== user) continue;
    const itemType = normalizeItemType(row[P.ITEM_TYPE]);
    if (['sense', 'mwe', 'clitic', 'lemma'].indexOf(itemType) < 0) continue;
    const rowMode = normalizeMode(row[P.MODE], row[P.PARENT_ID]);
    if (modeFilter !== 'all' && rowMode !== modeFilter) continue;
    items.push({
      itemId: row[P.ITEM_ID],
      parentWordId: row[P.PARENT_ID],
      itemType: itemType,
      mode: rowMode,
      label: row[P.LABEL],
      language: row[P.LANGUAGE],
      correct: row[P.CORRECT],
      wrong: row[P.WRONG],
      lastCorrect: row[P.LAST_CORRECT],
      lastWrong: row[P.LAST_WRONG],
      lastSeen: row[P.LAST_SEEN],
      schemaVersion: row[P.SCHEMA] || PROGRESS_SCHEMA_VERSION,
      srsStage: row[P.SRS_STAGE]
    });
  }
  return createResponse(true, 'Item progress loaded successfully', { items: items });
}

function deleteProgress(params) {
  if (params.sheet === 'FlaggedWords') return deleteFlaggedWord(params);
  const user = params.user;
  if (!user) return createResponse(false, 'Missing required field: user');
  const modeFilter = normalizeMode(params.mode || legacySheetMode(params.sheet) || 'all');
  const sheet = getProgressSheet();
  const data = sheet.getDataRange().getValues();
  let deleted = 0;
  for (let i = data.length - 1; i >= 1; i--) {
    const row = data[i];
    if (row[P.USER] !== user || normalizeItemType(row[P.ITEM_TYPE]) !== 'word') continue;
    if (modeFilter !== 'all' && normalizeMode(row[P.MODE], row[P.ITEM_ID]) !== modeFilter) continue;
    if (params.wordId === undefined || String(row[P.ITEM_ID]) === String(params.wordId)) {
      sheet.deleteRow(i + 1);
      deleted++;
    }
  }
  return createResponse(true, 'Deleted ' + deleted + ' progress rows');
}

function deleteItemProgress(params) {
  const user = params.user;
  if (!user) return createResponse(false, 'Missing required field: user');
  const parents = Array.isArray(params.parentWordIds)
    ? params.parentWordIds
    : (params.parentWordId ? [params.parentWordId] : []);
  if (parents.length === 0) return createResponse(false, 'Missing parentWordId or parentWordIds');
  const parentSet = {};
  parents.forEach(function(id) { parentSet[id] = true; });
  const sheet = getProgressSheet();
  const data = sheet.getDataRange().getValues();
  let deleted = 0;
  for (let i = data.length - 1; i >= 1; i--) {
    const row = data[i];
    const itemType = normalizeItemType(row[P.ITEM_TYPE]);
    if (row[P.USER] === user && ['sense', 'mwe', 'clitic', 'lemma'].indexOf(itemType) >= 0
        && parentSet[row[P.PARENT_ID]]) {
      sheet.deleteRow(i + 1);
      deleted++;
    }
  }
  return createResponse(true, 'Deleted ' + deleted + ' item progress rows');
}

/** Delete one exact unified row; used by the guarded local replace tool. */
function deleteExactProgressRow(params) {
  const itemType = normalizeItemType(params.itemType);
  if (!params.user || params.itemId === undefined || !itemType) {
    return createResponse(false, 'Missing required fields: user, itemId, itemType');
  }
  const probe = [
    params.user, params.itemId, itemType,
    normalizeMode(params.mode, params.parentWordId || params.itemId),
    params.source || '', params.parentWordId || '', params.label || '',
    params.language || '', 0, 0, '', '', '', PROGRESS_SCHEMA_VERSION, '', ''
  ];
  const key = progressRowKey(probe);
  const sheet = getProgressSheet();
  const data = sheet.getDataRange().getValues();
  let deleted = 0;
  for (let i = data.length - 1; i >= 1; i--) {
    if (progressRowKey(data[i]) === key) {
      sheet.deleteRow(i + 1);
      deleted++;
    }
  }
  return createResponse(true, 'Deleted ' + deleted + ' exact progress rows');
}

function bulkSave(params) {
  const rows = params.rows;
  if (!rows || !Array.isArray(rows) || rows.length === 0) {
    return createResponse(false, 'Missing or empty rows array');
  }
  if (params.sheet === 'FlaggedWords') return bulkSaveFlaggedWords(rows);

  const legacyMode = legacySheetMode(params.sheet);
  let updated = 0;
  let inserted = 0;
  rows.forEach(function(row) {
    const itemType = normalizeItemType(row.itemType || 'word');
    if (!row.user) return;
    let responseKind;
    if (itemType === 'meta') {
      const normalized = {
        user: row.user,
        itemId: row.itemId || row.metaId,
        itemType: 'meta',
        mode: row.mode || legacyMode || 'normal',
        source: row.source || '',
        parentWordId: '',
        label: row.label || row.metaKey || '',
        language: row.language || '',
        correct: 0,
        wrong: 0,
        lastCorrect: '',
        lastWrong: '',
        lastSeen: row.lastSeen,
        srsStage: '',
        value: row.value
      };
      const existing = existingProgressRow(normalized);
      responseKind = upsertProgressRow(buildProgressRow(normalized, existing));
    } else if (itemType === 'word') {
      const normalized = {
        user: row.user,
        itemId: row.itemId !== undefined ? row.itemId : row.wordId,
        itemType: 'word',
        mode: row.mode || legacyMode || normalizeMode('', row.itemId || row.wordId),
        source: '',
        parentWordId: '',
        label: row.label || row.word || '',
        language: row.language || '',
        correct: row.correct,
        wrong: row.wrong,
        lastCorrect: row.lastCorrect,
        lastWrong: row.lastWrong,
        lastSeen: row.lastSeen,
        srsStage: row.srsStage,
        value: ''
      };
      if (normalized.itemId === undefined) return;
      const existing = existingProgressRow(normalized);
      responseKind = upsertProgressRow(buildProgressRow(normalized, existing));
    } else {
      const normalized = {
        user: row.user,
        itemId: row.itemId,
        itemType: itemType,
        mode: row.mode || normalizeMode('', row.parentWordId),
        source: '',
        parentWordId: row.parentWordId || '',
        label: row.label || '',
        language: row.language || '',
        correct: row.correct,
        wrong: row.wrong,
        lastCorrect: row.lastCorrect,
        lastWrong: row.lastWrong,
        lastSeen: row.lastSeen,
        srsStage: row.srsStage,
        value: ''
      };
      if (!normalized.itemId || !normalized.parentWordId) return;
      const existing = existingProgressRow(normalized);
      responseKind = upsertProgressRow(buildProgressRow(normalized, existing));
    }
    if (responseKind === 'updated') updated++;
    else if (responseKind === 'inserted') inserted++;
  });
  return createResponse(true, 'Bulk save complete: ' + updated + ' updated, ' + inserted + ' inserted');
}

function dumpSheet(params) {
  const requested = params.sheet || PROGRESS_SHEET_NAME;
  if (requested === PROGRESS_SHEET_NAME) {
    const data = getProgressSheet().getDataRange().getValues();
    return createResponse(true, 'Sheet dumped successfully', {
      headers: data[0] || PROGRESS_HEADERS,
      rows: data.slice(1)
    });
  }
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  // Flags migrate on read as well as on write: sync_sheets.py dumps the tab
  // before anything has been flagged, and must not receive the v1 shape.
  if (requested === FLAGGED_WORDS_SHEET_NAME) {
    const flagData = getOrCreateFlaggedWordsSheet().getDataRange().getValues();
    return createResponse(true, 'Sheet dumped successfully', {
      headers: flagData[0] || FLAGGED_WORDS_HEADERS,
      rows: flagData.slice(1)
    });
  }
  let sheet = ss.getSheetByName(requested);
  if (!sheet) sheet = ss.getSheetByName(requested + '_legacy');
  if (!sheet) return createResponse(false, 'Sheet not found: ' + requested);
  const data = sheet.getDataRange().getValues();
  return createResponse(true, 'Sheet dumped successfully', {
    headers: data[0] || [],
    rows: data.slice(1)
  });
}

function getProgressSheet() {
  return ensureProgressSchema(false).sheet;
}

function ensureProgressSchema(force) {
  const props = PropertiesService.getScriptProperties();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(PROGRESS_SHEET_NAME);
  const alreadyMigrated = props.getProperty(PROGRESS_MIGRATION_PROPERTY) === '1';
  if (sheet && alreadyMigrated && progressHeadersMatch(sheet) && !force) {
    return { sheet: sheet, summary: { migrated: false, rows: Math.max(0, sheet.getLastRow() - 1) } };
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    sheet = ss.getSheetByName(PROGRESS_SHEET_NAME);
    if (sheet && !progressHeadersMatch(sheet)) {
      // A half-deployed v3 frontend could have asked the old backend to create
      // a tab literally named Progress with the legacy word schema. Preserve
      // it as another migration source rather than overwriting it in place.
      renameLegacySheet(ss, sheet, 'Progress_pre_v4_legacy');
      sheet = null;
      props.deleteProperty(PROGRESS_MIGRATION_PROPERTY);
    }
    if (!sheet) {
      // If the unified tab was removed after migration, rebuild it from the
      // retained legacy backups instead of trusting the stale property flag.
      props.deleteProperty(PROGRESS_MIGRATION_PROPERTY);
      sheet = createProgressSheet(ss);
    }

    if (props.getProperty(PROGRESS_MIGRATION_PROPERTY) === '1'
        && progressHeadersMatch(sheet) && !force) {
      return { sheet: sheet, summary: { migrated: false, rows: Math.max(0, sheet.getLastRow() - 1) } };
    }

    const current = sheet.getDataRange().getValues();
    const rowsByKey = {};
    for (let i = 1; i < current.length; i++) {
      const row = current[i].slice(0, PROGRESS_HEADERS.length);
      while (row.length < PROGRESS_HEADERS.length) row.push('');
      rowsByKey[progressRowKey(row)] = row;
    }

    const migratedCounts = {};
    const sourceNames = [
      'UserProgress', 'Lyrics', 'ItemProgress', 'BadBunny',
      'UserProgress_legacy', 'Lyrics_legacy', 'ItemProgress_legacy', 'BadBunny_legacy'
    ];
    ss.getSheets().forEach(function(candidate) {
      const candidateName = candidate.getName();
      if (candidateName.indexOf('Progress_pre_v4_legacy') === 0) sourceNames.push(candidateName);
    });
    sourceNames.forEach(function(name) {
      const legacy = ss.getSheetByName(name);
      if (!legacy) return;
      const converted = convertLegacySheet(name, legacy);
      converted.forEach(function(row) {
        const key = progressRowKey(row);
        const previous = rowsByKey[key];
        if (!previous || rowTimestamp(row) >= rowTimestamp(previous)) rowsByKey[key] = row;
      });
      migratedCounts[name] = converted.length;
      if (name.indexOf('_legacy') < 0) renameLegacySheet(ss, legacy, name + '_legacy');
    });

    const rows = Object.keys(rowsByKey).map(function(key) { return rowsByKey[key]; });
    sheet.clearContents();
    sheet.getRange(1, 1, 1, PROGRESS_HEADERS.length).setValues([PROGRESS_HEADERS]);
    if (rows.length > 0) sheet.getRange(2, 1, rows.length, PROGRESS_HEADERS.length).setValues(rows);
    formatProgressSheet(sheet);
    props.setProperty(PROGRESS_MIGRATION_PROPERTY, '1');
    return {
      sheet: sheet,
      summary: { migrated: true, rows: rows.length, legacyRows: migratedCounts }
    };
  } finally {
    lock.releaseLock();
  }
}

function createProgressSheet(ss) {
  const sheet = ss.insertSheet(PROGRESS_SHEET_NAME);
  sheet.getRange(1, 1, 1, PROGRESS_HEADERS.length).setValues([PROGRESS_HEADERS]);
  formatProgressSheet(sheet);
  return sheet;
}

function progressHeadersMatch(sheet) {
  const current = sheet.getRange(1, 1, 1, PROGRESS_HEADERS.length).getValues()[0];
  for (let i = 0; i < PROGRESS_HEADERS.length; i++) {
    if (current[i] !== PROGRESS_HEADERS[i]) return false;
  }
  return true;
}

function formatProgressSheet(sheet) {
  sheet.getRange(1, 1, 1, PROGRESS_HEADERS.length).setFontWeight('bold');
  sheet.setFrozenRows(1);
  sheet.autoResizeColumns(1, PROGRESS_HEADERS.length);
}

function headerMap(headers) {
  const map = {};
  headers.forEach(function(header, index) { map[String(header || '').toLowerCase()] = index; });
  return map;
}

function legacyValue(row, map, name, fallbackIndex) {
  const index = map[String(name).toLowerCase()];
  if (index !== undefined) return row[index];
  return fallbackIndex !== undefined ? row[fallbackIndex] : '';
}

function convertLegacySheet(name, sheet) {
  const data = sheet.getDataRange().getValues();
  if (data.length <= 1) return [];
  const map = headerMap(data[0]);
  const rows = [];
  for (let i = 1; i < data.length; i++) {
    const old = data[i];
    if (name.indexOf('ItemProgress') === 0) {
      const itemId = legacyValue(old, map, 'ItemId', 1);
      const parentWordId = legacyValue(old, map, 'ParentWordId', 2);
      if (!legacyValue(old, map, 'User', 0) || !itemId || !parentWordId) continue;
      rows.push([
        legacyValue(old, map, 'User', 0),
        itemId,
        normalizeItemType(legacyValue(old, map, 'ItemType', 3)),
        normalizeMode('', parentWordId),
        '',
        parentWordId,
        legacyValue(old, map, 'Label', 4),
        legacyValue(old, map, 'Language', 5),
        Number(legacyValue(old, map, 'Correct', 6)) || 0,
        Number(legacyValue(old, map, 'Wrong', 7)) || 0,
        legacyValue(old, map, 'LastCorrect', 8),
        legacyValue(old, map, 'LastWrong', 9),
        legacyValue(old, map, 'LastSeen', 10),
        PROGRESS_SCHEMA_VERSION,
        normalizeSrsStage(legacyValue(old, map, 'SrsStage', 12)),
        ''
      ]);
      continue;
    }

    const user = legacyValue(old, map, 'User', 0);
    const word = legacyValue(old, map, 'Word', 1);
    const wordId = legacyValue(old, map, 'WordId', 2);
    const language = legacyValue(old, map, 'Language', 3);
    if (!user || wordId === '') continue;
    if (word === '_LEVEL_ESTIMATE_') {
      rows.push([
        user, language || 'unknown', 'meta', 'normal', 'speech', '',
        'level-estimate', language || '', 0, 0, '', '',
        legacyValue(old, map, 'LastSeen', 9), PROGRESS_SCHEMA_VERSION, '', wordId
      ]);
    } else {
      rows.push([
        user, wordId, 'word', legacySheetMode(name) || normalizeMode('', wordId), '', '', word || '', language || '',
        Number(legacyValue(old, map, 'Correct', 4)) || 0,
        Number(legacyValue(old, map, 'Wrong', 5)) || 0,
        legacyValue(old, map, 'LastCorrect', 6),
        legacyValue(old, map, 'LastWrong', 7),
        legacyValue(old, map, 'LastSeen', 9),
        PROGRESS_SCHEMA_VERSION,
        normalizeSrsStage(legacyValue(old, map, 'SrsStage', 8)),
        ''
      ]);
    }
  }
  return rows;
}

function renameLegacySheet(ss, sheet, preferredName) {
  let target = preferredName;
  let suffix = 2;
  while (ss.getSheetByName(target) && ss.getSheetByName(target) !== sheet) {
    target = preferredName + '_' + suffix;
    suffix++;
  }
  sheet.setName(target);
}

// --- Flag schema v2 -------------------------------------------------------
//
// Both app entry paths (full audit menu + quick actions) historically wrote
// display LABELS into a single free-text column, and used two different Target
// vocabularies. These maps fold every label either path ever emitted onto the
// canonical stable keys the app now sends directly, so migrated history and new
// rows are queryable in the same namespace.
const FLAG_LEGACY_TARGETS = {
  // Full audit menu vocabulary.
  'Sense + example': { target: 'pairing' },
  'Meaning': { target: 'sense' },
  'Example line': { target: 'example' },
  'Lemma': { target: 'lemma' },
  'Word form': { target: 'surface' },
  'Whole card': { target: 'card' },
  'Note': { target: 'note' },
  'Classification tag': { target: 'routing' },
  // Quick-action vocabulary.
  'Proper noun': { target: 'routing', category: 'proper_noun', requestedTag: 'proper_noun' },
  'English': { target: 'routing', category: 'english', requestedTag: 'english' },
  'Cognate': { target: 'routing', category: 'cognate', requestedTag: 'cognate' },
  'Wrong lemma': { target: 'lemma', category: 'lemma' },
  'Wrong elision correction': { target: 'surface', category: 'morphology' },
  'Wrong card POS': { target: 'card', category: 'pos' },
  'Wrong sense POS': { target: 'sense', category: 'pos' },
  'Sense–meaning pairing': { target: 'pairing', category: 'matching' }
};
const FLAG_LEGACY_CATEGORIES = {
  'Wrong match': 'matching',
  'Translation': 'translation',
  'Lemma / grouping': 'lemma',
  'Morphology': 'morphology',
  'Example / lyric': 'example',
  'Expression / clitic': 'expression',
  'Frequency / rank': 'frequency',
  'Other': 'other',
  'English word': 'english',
  'Loanword': 'loanword',
  'Cognate': 'cognate',
  'Proper noun': 'proper_noun',
  'Part of speech': 'pos',
  'Unspecified': ''
};

/** Pull "Label: value" out of a rendered flag report blob. */
function flagReportField(report, label) {
  if (!report) return '';
  const lines = String(report).split('\n');
  for (let i = 0; i < lines.length; i++) {
    const idx = lines[i].indexOf(': ');
    if (idx > 0 && lines[i].slice(0, idx).trim() === label) {
      return lines[i].slice(idx + 2).trim();
    }
  }
  return '';
}

/** "Sense 1: VERB · to dance" -> { pos: 'VERB', gloss: 'to dance' } */
function flagReportSense(report) {
  if (!report) return { pos: '', gloss: '' };
  const lines = String(report).split('\n');
  for (let i = 0; i < lines.length; i++) {
    const match = /^Sense \d+: (.*)$/.exec(lines[i]);
    if (!match) continue;
    const parts = match[1].split(' · ');
    return {
      pos: (parts[0] || '').trim() === '?' ? '' : (parts[0] || '').trim(),
      gloss: (parts.slice(1).join(' · ') || '').trim()
    };
  }
  return { pos: '', gloss: '' };
}

/**
 * Convert one v1 row into a v2 row by back-parsing its report blob.
 * v1 layout: [User, Word(=report), WordId, Language, Correct, Wrong,
 *             LastCorrect(=fieldPath), LastWrong(=timestamp)]
 */
function convertLegacyFlagRow(v1Row) {
  const report = String(v1Row[1] || '');
  const wordId = String(v1Row[2] || '');
  const fieldPath = String(v1Row[6] || '');
  const targetLabel = flagReportField(report, 'Target');
  const mapped = FLAG_LEGACY_TARGETS[targetLabel] || {};
  const categoryLabel = flagReportField(report, 'Category');
  const requestedLabel = flagReportField(report, 'Requested classification');
  const sense = flagReportSense(report);

  // Pre-Target reports ([Sense ↔ example]) only ever described a pairing.
  let target = mapped.target || '';
  if (!target) target = report.indexOf('[Sense') === 0 ? 'pairing' : '';
  if (!target && fieldPath) target = fieldPath.split(':')[0];

  let category = FLAG_LEGACY_CATEGORIES[categoryLabel];
  if (category === undefined) category = mapped.category || '';
  let requestedTag = mapped.requestedTag || '';
  if (!requestedTag && requestedLabel) {
    requestedTag = FLAG_LEGACY_CATEGORIES[requestedLabel] || '';
  }

  const cardId = flagReportField(report, 'Card ID') || wordId.split('#')[0];
  const row = new Array(FLAGGED_WORDS_HEADERS.length).fill('');
  row[F.USER] = v1Row[0] || '';
  row[F.FLAGGED_AT] = v1Row[7] || '';
  row[F.WORD] = flagReportField(report, 'Word');
  row[F.LEMMA] = flagReportField(report, 'Lemma');
  row[F.LANGUAGE] = v1Row[3] || '';
  row[F.WORD_ID] = wordId;
  row[F.CARD_ID] = cardId === '(missing)' ? '' : cardId;
  row[F.FIELD_PATH] = fieldPath;
  row[F.TARGET] = target;
  row[F.CATEGORY] = category;
  row[F.SENSE_POS] = sense.pos;
  row[F.SENSE_ID] = flagReportField(report, 'Sense ID');
  row[F.SENSE_GLOSS] = sense.gloss === '(empty)' ? '' : sense.gloss;
  row[F.CONTEXT] = flagReportField(report, 'Context');
  row[F.EXAMPLE] = flagReportField(report, 'Example');
  row[F.TRANSLATION] = flagReportField(report, 'Translation');
  row[F.SONG] = flagReportField(report, 'Source');
  row[F.EXAMPLE_ASSIGNMENT] = flagReportField(report, 'Example assignment');
  row[F.TRANSLATION_SOURCE] = flagReportField(report, 'Translation source');
  row[F.SENSE_ASSIGNMENT] = flagReportField(report, 'Sense assignment');
  row[F.REQUESTED_TAG] = requestedTag;
  row[F.NOTE] = flagReportField(report, 'Note');
  row[F.REPORT] = report;
  row[F.SCHEMA] = 1;  // provenance: migrated from v1, not natively captured
  return row;
}

function flagHeadersMatch(sheet) {
  if (!sheet || sheet.getLastColumn() < FLAGGED_WORDS_HEADERS.length) return false;
  const header = sheet.getRange(1, 1, 1, FLAGGED_WORDS_HEADERS.length).getValues()[0];
  for (let i = 0; i < FLAGGED_WORDS_HEADERS.length; i++) {
    if (String(header[i]).trim() !== FLAGGED_WORDS_HEADERS[i]) return false;
  }
  return true;
}

function writeFlaggedWordsHeader(sheet) {
  const range = sheet.getRange(1, 1, 1, FLAGGED_WORDS_HEADERS.length);
  range.setValues([FLAGGED_WORDS_HEADERS]);
  range.setFontWeight('bold');
  sheet.setFrozenRows(1);
}

/**
 * Create the tab, or migrate a v1 tab in place. The pre-migration tab is copied
 * to FlaggedWords_v1_backup first, so a bad parse is always recoverable.
 * Entirely blank rows (three exist at the top of the live sheet, left over from
 * an early schema) are dropped rather than carried forward.
 */
function ensureFlaggedWordsSchema(force) {
  const props = PropertiesService.getScriptProperties();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(FLAGGED_WORDS_SHEET_NAME);
  const alreadyMigrated = props.getProperty(FLAG_MIGRATION_PROPERTY) === '1';
  if (sheet && alreadyMigrated && flagHeadersMatch(sheet) && !force) {
    return { sheet: sheet, summary: { migrated: false, rows: Math.max(0, sheet.getLastRow() - 1) } };
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    sheet = ss.getSheetByName(FLAGGED_WORDS_SHEET_NAME);
    if (!sheet) {
      sheet = ss.insertSheet(FLAGGED_WORDS_SHEET_NAME);
      writeFlaggedWordsHeader(sheet);
      sheet.autoResizeColumns(1, FLAGGED_WORDS_HEADERS.length);
      props.setProperty(FLAG_MIGRATION_PROPERTY, '1');
      return { sheet: sheet, summary: { migrated: false, created: true, rows: 0 } };
    }
    if (flagHeadersMatch(sheet) && !force) {
      props.setProperty(FLAG_MIGRATION_PROPERTY, '1');
      return { sheet: sheet, summary: { migrated: false, rows: Math.max(0, sheet.getLastRow() - 1) } };
    }

    const existing = sheet.getDataRange().getValues();
    if (!ss.getSheetByName(FLAGGED_WORDS_SHEET_NAME + '_v1_backup')) {
      sheet.copyTo(ss).setName(FLAGGED_WORDS_SHEET_NAME + '_v1_backup');
    }

    const converted = [];
    let dropped = 0;
    for (let i = 1; i < existing.length; i++) {
      const raw = existing[i];
      const isBlank = raw.every(function(cell) { return String(cell || '').trim() === ''; });
      if (isBlank) { dropped++; continue; }
      converted.push(convertLegacyFlagRow(raw));
    }

    sheet.clear();
    writeFlaggedWordsHeader(sheet);
    if (converted.length) {
      sheet.getRange(2, 1, converted.length, FLAGGED_WORDS_HEADERS.length).setValues(converted);
    }
    sheet.autoResizeColumns(1, FLAGGED_WORDS_HEADERS.length);
    props.setProperty(FLAG_MIGRATION_PROPERTY, '1');
    return {
      sheet: sheet,
      summary: { migrated: true, rows: converted.length, droppedBlankRows: dropped }
    };
  } finally {
    lock.releaseLock();
  }
}

function getOrCreateFlaggedWordsSheet() {
  return ensureFlaggedWordsSchema(false).sheet;
}

/**
 * Build a v2 row from a save payload. `wordText`/`report` are the v2 fields;
 * the `word` fallback is the v1 client contract, where `word` carried the
 * rendered report and there was no separate headword field.
 */
function buildFlagRow(params, existing) {
  const row = existing
    ? existing.slice(0, FLAGGED_WORDS_HEADERS.length)
    : new Array(FLAGGED_WORDS_HEADERS.length).fill('');
  while (row.length < FLAGGED_WORDS_HEADERS.length) row.push('');

  const report = params.report !== undefined && params.report !== null && params.report !== ''
    ? String(params.report)
    : String(params.word || '');
  const set = function(index, value) {
    if (value !== undefined && value !== null && value !== '') row[index] = value;
  };

  row[F.USER] = params.user;
  row[F.WORD_ID] = params.wordId;
  row[F.FLAGGED_AT] = params.flaggedAt || params.lastWrong || new Date().toISOString();
  // Preserve on re-flag: a partial payload (e.g. a bulkSave that omits these)
  // must not blank a column the row already has.
  row[F.FIELD_PATH] = params.fieldPath || params.lastCorrect || row[F.FIELD_PATH] || '';
  if (report) row[F.REPORT] = report;
  row[F.SCHEMA] = FLAG_SCHEMA_VERSION;
  set(F.WORD, params.wordText || flagReportField(report, 'Word'));
  set(F.LEMMA, params.lemma || flagReportField(report, 'Lemma'));
  set(F.LANGUAGE, params.language);
  set(F.CARD_ID, params.cardId || String(params.wordId || '').split('#')[0]);
  set(F.TARGET, params.target);
  set(F.CATEGORY, params.category);
  set(F.SENSE_POS, params.sensePos);
  set(F.SENSE_ID, params.senseId);
  set(F.SENSE_GLOSS, params.senseGloss);
  set(F.CONTEXT, params.context);
  set(F.EXAMPLE, params.example);
  set(F.TRANSLATION, params.translation);
  set(F.SONG, params.song);
  set(F.EXAMPLE_ASSIGNMENT, params.exampleAssignment);
  set(F.TRANSLATION_SOURCE, params.translationSource);
  set(F.SENSE_ASSIGNMENT, params.senseAssignment);
  set(F.REQUESTED_TAG, params.requestedTag);
  set(F.NOTE, params.note);
  return row;
}

/** Row index (1-based) of an existing flag for this user + wordId, else -1. */
function findFlagRowIndex(data, user, wordId) {
  for (let i = 1; i < data.length; i++) {
    if (data[i][F.USER] === user && String(data[i][F.WORD_ID]) === String(wordId)) {
      return i + 1;
    }
  }
  return -1;
}

function saveFlaggedWord(params) {
  if (!params.user || params.wordId === undefined || String(params.wordId) === '') {
    return createResponse(false, 'Missing required fields: user, wordId');
  }
  const sheet = getOrCreateFlaggedWordsSheet();
  const data = sheet.getDataRange().getValues();
  const rowIndex = findFlagRowIndex(data, params.user, params.wordId);
  const existing = rowIndex > 0 ? data[rowIndex - 1] : null;
  const values = buildFlagRow(params, existing);
  if (rowIndex > 0) sheet.getRange(rowIndex, 1, 1, values.length).setValues([values]);
  else sheet.appendRow(values);
  return createResponse(true, 'Flag saved successfully');
}

function deleteFlaggedWord(params) {
  if (!params.user) return createResponse(false, 'Missing required field: user');
  const sheet = getOrCreateFlaggedWordsSheet();
  const data = sheet.getDataRange().getValues();
  let deleted = 0;
  for (let i = data.length - 1; i >= 1; i--) {
    if (data[i][F.USER] === params.user
        && (params.wordId === undefined || String(data[i][F.WORD_ID]) === String(params.wordId))) {
      sheet.deleteRow(i + 1);
      deleted++;
    }
  }
  return createResponse(true, 'Deleted ' + deleted + ' flagged rows');
}

function bulkSaveFlaggedWords(rows) {
  let updated = 0;
  let inserted = 0;
  const sheet = getOrCreateFlaggedWordsSheet();
  rows.forEach(function(row) {
    if (!row.user || row.wordId === undefined || String(row.wordId) === '') return;
    const data = sheet.getDataRange().getValues();
    const rowIndex = findFlagRowIndex(data, row.user, row.wordId);
    const values = buildFlagRow(row, rowIndex > 0 ? data[rowIndex - 1] : null);
    if (rowIndex > 0) {
      sheet.getRange(rowIndex, 1, 1, values.length).setValues([values]);
      updated++;
    } else {
      sheet.appendRow(values);
      inserted++;
    }
  });
  return createResponse(true, 'Bulk save complete: ' + updated + ' updated, ' + inserted + ' inserted');
}

/** Preserve a real zero while leaving legacy/migration rows blank. */
function normalizeSrsStage(value) {
  if (value === undefined || value === null || value === '') return '';
  const numeric = Number(value);
  if (!isFinite(numeric)) return '';
  return Math.max(0, Math.min(7, Math.floor(numeric)));
}

function createResponse(success, message, data) {
  const response = {
    success: success,
    message: message,
    timestamp: new Date().toISOString()
  };
  if (data !== undefined && data !== null) response.data = data;
  return ContentService
    .createTextOutput(JSON.stringify(response))
    .setMimeType(ContentService.MimeType.JSON);
}
