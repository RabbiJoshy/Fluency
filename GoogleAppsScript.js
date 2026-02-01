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
    timestamp: new Date().toISOString()
  })).setMimeType(ContentService.MimeType.JSON);
}

/**
 * Save user progress to the sheet
 */
function saveProgress(params) {
  const { user, word, language, wordRank, correct, wrong, lastCorrect, lastWrong, lastSeen, sheet } = params;
  const sheetName = sheet || 'UserProgress';

  if (!user || wordRank === undefined) {
    return createResponse(false, 'Missing required fields: user, wordRank');
  }

  const sheetObj = getOrCreateSheet(sheetName);
  const data = sheetObj.getDataRange().getValues();

  let rowIndex = -1;
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === user && data[i][2] === wordRank) {
      rowIndex = i + 1;
      break;
    }
  }

  const timestamp = lastSeen || new Date().toISOString();
  const correctCount = correct || 0;
  const wrongCount = wrong || 0;

  if (rowIndex > 0) {
    sheetObj.getRange(rowIndex, 1, 1, 8).setValues([[
      user,
      word || data[rowIndex - 1][1],
      wordRank,
      language || data[rowIndex - 1][3],
      correctCount,
      wrongCount,
      lastCorrect || data[rowIndex - 1][6],
      lastWrong || data[rowIndex - 1][7]
    ]]);
  } else {
    sheetObj.appendRow([
      user,
      word || '',
      wordRank,
      language || '',
      correctCount,
      wrongCount,
      lastCorrect || '',
      lastWrong || ''
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

  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === user) {
      userProgress.push({
        word: data[i][1],
        wordRank: data[i][2],
        language: data[i][3],
        correct: data[i][4],
        wrong: data[i][5],
        lastCorrect: data[i][6],
        lastWrong: data[i][7]
      });
    }
  }

  return createResponse(true, 'Progress loaded successfully', { progress: userProgress });
}

/**
 * Delete user progress
 */
function deleteProgress(params) {
  const { user, wordRank, sheet } = params;
  const sheetName = sheet || 'UserProgress';

  if (!user) {
    return createResponse(false, 'Missing required field: user');
  }

  const sheetObj = getOrCreateSheet(sheetName);
  const data = sheetObj.getDataRange().getValues();

  for (let i = data.length - 1; i >= 1; i--) {
    if (data[i][0] === user) {
      if (wordRank === undefined || data[i][2] === wordRank) {
        sheetObj.deleteRow(i + 1);
      }
    }
  }

  return createResponse(true, 'Progress deleted successfully');
}

/**
 * Get or create the sheet
 */
function getOrCreateSheet(sheetName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(sheetName);

  if (!sheet) {
    sheet = ss.insertSheet(sheetName);
    sheet.appendRow(['User', 'Word', 'WordRank', 'Language', 'Correct', 'Wrong', 'LastCorrect', 'LastWrong']);
    sheet.getRange(1, 1, 1, 8).setFontWeight('bold');
    sheet.setFrozenRows(1);
    sheet.autoResizeColumns(1, 8);
  }

  return sheet;
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
