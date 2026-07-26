/**
 * Language Flashcard App - Google Apps Script Backend
 */

/**
 * Main entry point for HTTP requests
 */
function doPost(e) {
  try {
    const params = JSON.parse(e.postData.contents);
    const action = params.action;

    if (action === 'save') {
      return saveProgress(params);
    } else if (action === 'load') {
      return loadProgress(params);
    } else if (action === 'delete') {
      return deleteProgress(params);
    } else if (action === 'dump') {
      return dumpSheet(params);
    } else if (action === 'bulkSave') {
      return bulkSave(params);
    } else if (action === 'saveItem') {
      return saveItemProgress(params);
    } else if (action === 'loadItems') {
      return loadItemProgress(params);
    } else if (action === 'deleteItems') {
      return deleteItemProgress(params);
    } else {
      return createResponse(false, 'Invalid action');
    }
  } catch (error) {
    return createResponse(false, 'Error: ' + error.toString());
  }
}

/**
 * Handle GET requests (for testing)
 */
function doGet(e) {
  return ContentService.createTextOutput(JSON.stringify({
    status: 'success',
    message: 'Flashcard API is running',
    schemaVersion: 3,
    timestamp: new Date().toISOString()
  })).setMimeType(ContentService.MimeType.JSON);
}

/**
 * Save one explicit sense / expression / clitic result. Whole-card progress
 * remains in UserProgress/Lyrics; this sparse sheet stores only granular
 * overrides, with the newest parent-level or item-level timestamp winning in
 * the app.
 */
function saveItemProgress(params) {
  const {
    user, itemId, parentWordId, itemType, label, language,
    correct, wrong, lastCorrect, lastWrong, lastSeen, schemaVersion, srsStage
  } = params;
  if (!user || !itemId || !parentWordId) {
    return createResponse(false, 'Missing required fields: user, itemId, parentWordId');
  }

  const sheetObj = getOrCreateItemProgressSheet();
  const data = sheetObj.getDataRange().getValues();
  let rowIndex = -1;
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === user && data[i][1] === itemId) {
      rowIndex = i + 1;
      break;
    }
  }

  const timestamp = lastSeen || new Date().toISOString();
  const values = [
    user,
    itemId,
    parentWordId,
    itemType || '',
    label || '',
    language || '',
    correct || 0,
    wrong || 0,
    lastCorrect || '',
    lastWrong || '',
    timestamp,
    schemaVersion || 1,
    srsStage === undefined && rowIndex > 0
      ? data[rowIndex - 1][12]
      : normalizeSrsStage(srsStage)
  ];
  if (rowIndex > 0) {
    sheetObj.getRange(rowIndex, 1, 1, values.length).setValues([values]);
  } else {
    sheetObj.appendRow(values);
  }
  return createResponse(true, 'Item progress saved successfully');
}

/** Load every sparse knowledge override for one user. */
function loadItemProgress(params) {
  const { user } = params;
  if (!user) return createResponse(false, 'Missing required field: user');

  const sheetObj = getOrCreateItemProgressSheet();
  const data = sheetObj.getDataRange().getValues();
  const items = [];
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] !== user) continue;
    items.push({
      itemId: data[i][1],
      parentWordId: data[i][2],
      itemType: data[i][3],
      label: data[i][4],
      language: data[i][5],
      correct: data[i][6],
      wrong: data[i][7],
      lastCorrect: data[i][8],
      lastWrong: data[i][9],
      lastSeen: data[i][10],
      schemaVersion: data[i][11] || 1,
      srsStage: data[i][12]
    });
  }
  return createResponse(true, 'Item progress loaded successfully', { items: items });
}

/** Delete granular rows belonging to one or more parent cards. */
function deleteItemProgress(params) {
  const { user, parentWordId, parentWordIds } = params;
  if (!user) return createResponse(false, 'Missing required field: user');
  const parents = Array.isArray(parentWordIds)
    ? parentWordIds
    : (parentWordId ? [parentWordId] : []);
  if (parents.length === 0) {
    return createResponse(false, 'Missing parentWordId or parentWordIds');
  }
  const parentSet = {};
  parents.forEach(function(id) { parentSet[id] = true; });

  const sheetObj = getOrCreateItemProgressSheet();
  const data = sheetObj.getDataRange().getValues();
  let deleted = 0;
  for (let i = data.length - 1; i >= 1; i--) {
    if (data[i][0] === user && parentSet[data[i][2]]) {
      sheetObj.deleteRow(i + 1);
      deleted++;
    }
  }
  return createResponse(true, 'Deleted ' + deleted + ' item progress rows');
}

function getOrCreateItemProgressSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName('ItemProgress');
  if (!sheet) {
    sheet = ss.insertSheet('ItemProgress');
    sheet.appendRow([
      'User', 'ItemId', 'ParentWordId', 'ItemType', 'Label', 'Language',
      'Correct', 'Wrong', 'LastCorrect', 'LastWrong', 'LastSeen', 'SchemaVersion',
      'SrsStage'
    ]);
    sheet.getRange(1, 1, 1, 13).setFontWeight('bold');
    sheet.setFrozenRows(1);
    sheet.autoResizeColumns(1, 13);
  } else if (sheet.getRange(1, 13).getValue() !== 'SrsStage') {
    sheet.getRange(1, 13).setValue('SrsStage').setFontWeight('bold');
    sheet.autoResizeColumn(13);
  }
  return sheet;
}

/**
 * Save user progress to the sheet
 */
function saveProgress(params) {
  const {
    user, word, language, wordId, correct, wrong,
    lastCorrect, lastWrong, lastSeen, srsStage, sheet
  } = params;
  const sheetName = sheet || 'UserProgress';

  if (!user || wordId === undefined) {
    return createResponse(false, 'Missing required fields: user, wordId');
  }

  const sheetObj = getOrCreateSheet(sheetName);
  const data = sheetObj.getDataRange().getValues();

  const isSentinel = (word === '_LEVEL_ESTIMATE_');
  let rowIndex = -1;
  for (let i = 1; i < data.length; i++) {
    if (isSentinel) {
      if (data[i][0] === user && data[i][1] === '_LEVEL_ESTIMATE_' && data[i][3] === (language || '')) {
        rowIndex = i + 1;
        break;
      }
    } else {
      if (data[i][0] === user && data[i][2] == wordId) { // == handles Sheets auto-converting "0039"→39
        rowIndex = i + 1;
        break;
      }
    }
  }

  const timestamp = lastSeen || new Date().toISOString();
  const correctCount = correct || 0;
  const wrongCount = wrong || 0;

  if (rowIndex > 0) {
    sheetObj.getRange(rowIndex, 1, 1, 10).setValues([[
      user,
      word || data[rowIndex - 1][1],
      wordId,
      language || data[rowIndex - 1][3],
      correctCount,
      wrongCount,
      lastCorrect || data[rowIndex - 1][6],
      lastWrong || data[rowIndex - 1][7],
      srsStage === undefined ? data[rowIndex - 1][8] : normalizeSrsStage(srsStage),
      timestamp
    ]]);
  } else {
    sheetObj.appendRow([
      user,
      word || '',
      wordId,
      language || '',
      correctCount,
      wrongCount,
      lastCorrect || '',
      lastWrong || '',
      normalizeSrsStage(srsStage),
      timestamp
    ]);
  }

  return createResponse(true, 'Progress saved successfully');
}

/**
 * Load user progress from the sheet
 */
function loadProgress(params) {
  const { user, sheet } = params;
  const sheetName = sheet || 'UserProgress';

  if (!user) {
    return createResponse(false, 'Missing required field: user');
  }

  const sheetObj = getOrCreateSheet(sheetName);
  const data = sheetObj.getDataRange().getValues();
  const userProgress = [];
  const levelEstimates = {};

  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === user) {
      if (data[i][1] === '_LEVEL_ESTIMATE_') {
        levelEstimates[data[i][3]] = data[i][2]; // language -> rank
      } else {
        userProgress.push({
          word: data[i][1],
          wordId: data[i][2],
          language: data[i][3],
          correct: data[i][4],
          wrong: data[i][5],
          lastCorrect: data[i][6],
          lastWrong: data[i][7],
          srsStage: data[i][8],
          lastSeen: data[i][9]
        });
      }
    }
  }

  return createResponse(true, 'Progress loaded successfully', { progress: userProgress, levelEstimates });
}

/**
 * Delete user progress
 */
function deleteProgress(params) {
  const { user, wordId, sheet } = params;
  const sheetName = sheet || 'UserProgress';

  if (!user) {
    return createResponse(false, 'Missing required field: user');
  }

  const sheetObj = getOrCreateSheet(sheetName);
  const data = sheetObj.getDataRange().getValues();

  for (let i = data.length - 1; i >= 1; i--) {
    if (data[i][0] === user) {
      if (wordId === undefined || data[i][2] === wordId) {
        sheetObj.deleteRow(i + 1);
      }
    }
  }

  return createResponse(true, 'Progress deleted successfully');
}

/**
 * Dump all rows from a sheet (unfiltered, for local backup/debug)
 */
function dumpSheet(params) {
  const sheetName = params.sheet || 'UserProgress';
  const sheetObj = getOrCreateSheet(sheetName);
  const data = sheetObj.getDataRange().getValues();

  const headers = data[0] || [];
  const rows = [];
  for (let i = 1; i < data.length; i++) {
    rows.push(data[i]);
  }

  return createResponse(true, 'Sheet dumped successfully', { headers: headers, rows: rows });
}

/**
 * Get or create the sheet
 */
function getOrCreateSheet(sheetName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(sheetName);

  if (!sheet) {
    // Migration: rename old 'BadBunny' tab to 'Lyrics' if requested
    if (sheetName === 'Lyrics') {
      var oldSheet = ss.getSheetByName('BadBunny');
      if (oldSheet) {
        oldSheet.setName('Lyrics');
        sheet = oldSheet;
      }
    }
    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
      sheet.appendRow([
        'User', 'Word', 'WordId', 'Language', 'Correct', 'Wrong',
        'LastCorrect', 'LastWrong', 'SrsStage', 'LastSeen'
      ]);
      sheet.getRange(1, 1, 1, 10).setFontWeight('bold');
      sheet.setFrozenRows(1);
      sheet.autoResizeColumns(1, 10);
    }
  }

  if (sheet.getRange(1, 9).getValue() !== 'SrsStage') {
    sheet.getRange(1, 9).setValue('SrsStage').setFontWeight('bold');
    sheet.autoResizeColumn(9);
  }
  if (sheet.getRange(1, 10).getValue() !== 'LastSeen') {
    sheet.getRange(1, 10).setValue('LastSeen').setFontWeight('bold');
    sheet.autoResizeColumn(10);
  }

  return sheet;
}

/**
 * Bulk save rows to a sheet (for migrations/push from local)
 */
function bulkSave(params) {
  const { rows, sheet } = params;
  const sheetName = sheet || 'UserProgress';

  if (!rows || !Array.isArray(rows) || rows.length === 0) {
    return createResponse(false, 'Missing or empty rows array');
  }

  const sheetObj = getOrCreateSheet(sheetName);
  const data = sheetObj.getDataRange().getValues();

  // Build lookup: user+wordId → row index (1-based)
  const lookup = {};
  for (let i = 1; i < data.length; i++) {
    const key = data[i][0] + '|' + data[i][2];
    lookup[key] = i + 1;
  }

  let updated = 0;
  let inserted = 0;

  for (const row of rows) {
    const {
      user, word, wordId, language, correct, wrong,
      lastCorrect, lastWrong, lastSeen, srsStage
    } = row;
    if (!user || wordId === undefined) continue;

    const key = user + '|' + wordId;
    const existing = lookup[key] ? data[lookup[key] - 1] : [];
    const values = [
      user,
      word || '',
      wordId,
      language || '',
      correct || 0,
      wrong || 0,
      lastCorrect || '',
      lastWrong || '',
      srsStage === undefined && existing.length > 8
        ? existing[8]
        : normalizeSrsStage(srsStage),
      lastSeen === undefined && existing.length > 9 ? existing[9] : (lastSeen || '')
    ];

    if (lookup[key]) {
      sheetObj.getRange(lookup[key], 1, 1, 10).setValues([values]);
      updated++;
    } else {
      sheetObj.appendRow(values);
      inserted++;
    }
  }

  return createResponse(true, 'Bulk save complete: ' + updated + ' updated, ' + inserted + ' inserted');
}

/** Preserve a real zero while leaving legacy/migration rows blank. */
function normalizeSrsStage(value) {
  if (value === undefined || value === null || value === '') return '';
  const numeric = Number(value);
  if (!isFinite(numeric)) return '';
  return Math.max(0, Math.min(7, Math.floor(numeric)));
}

/**
 * Create a standardized JSON response
 */
function createResponse(success, message, data = null) {
  const response = {
    success: success,
    message: message,
    timestamp: new Date().toISOString()
  };

  if (data) {
    response.data = data;
  }

  return ContentService
    .createTextOutput(JSON.stringify(response))
    .setMimeType(ContentService.MimeType.JSON);
}
