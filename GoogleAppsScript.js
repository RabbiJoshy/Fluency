/**
 * Language Flashcard App - Google Apps Script Backend
 *
 * This script provides a REST API for the flashcard app to save and load user progress.
 * Deploy as a web app with "Execute as: Me" and "Who has access: Anyone"
 */

// Configuration
const SHEET_NAME = 'UserProgress';

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
 * Params: { action: 'save', user, wordRank, correct, wrong, lastSeen }
 */
function saveProgress(params) {
  const { user, wordRank, correct, wrong, lastSeen } = params;

  if (!user || wordRank === undefined) {
    return createResponse(false, 'Missing required fields: user, wordRank');
  }

  const sheet = getOrCreateSheet();
  const data = sheet.getDataRange().getValues();

  // Find existing row for this user + wordRank
  let rowIndex = -1;
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === user && data[i][1] === wordRank) {
      rowIndex = i + 1; // +1 because sheet rows are 1-indexed
      break;
    }
  }

  const timestamp = lastSeen || new Date().toISOString();
  const correctCount = correct || 0;
  const wrongCount = wrong || 0;

  if (rowIndex > 0) {
    // Update existing row
    sheet.getRange(rowIndex, 3).setValue(correctCount);
    sheet.getRange(rowIndex, 4).setValue(wrongCount);
    sheet.getRange(rowIndex, 5).setValue(timestamp);
  } else {
    // Add new row
    sheet.appendRow([user, wordRank, correctCount, wrongCount, timestamp]);
  }

  return createResponse(true, 'Progress saved successfully');
}

/**
 * Load user progress from the sheet
 * Params: { action: 'load', user }
 */
function loadProgress(params) {
  const { user } = params;

  if (!user) {
    return createResponse(false, 'Missing required field: user');
  }

  const sheet = getOrCreateSheet();
  const data = sheet.getDataRange().getValues();
  const userProgress = [];

  // Find all rows for this user (skip header row)
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === user) {
      userProgress.push({
        wordRank: data[i][1],
        correct: data[i][2],
        wrong: data[i][3],
        lastSeen: data[i][4]
      });
    }
  }

  return createResponse(true, 'Progress loaded successfully', { progress: userProgress });
}

/**
 * Delete user progress (for testing/cleanup)
 * Params: { action: 'delete', user, wordRank? }
 */
function deleteProgress(params) {
  const { user, wordRank } = params;

  if (!user) {
    return createResponse(false, 'Missing required field: user');
  }

  const sheet = getOrCreateSheet();
  const data = sheet.getDataRange().getValues();

  // Delete rows in reverse order to avoid index shifts
  for (let i = data.length - 1; i >= 1; i--) {
    if (data[i][0] === user) {
      if (wordRank === undefined || data[i][1] === wordRank) {
        sheet.deleteRow(i + 1);
      }
    }
  }

  return createResponse(true, 'Progress deleted successfully');
}

/**
 * Get or create the sheet
 */
function getOrCreateSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);

  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    // Add headers
    sheet.appendRow(['User', 'WordRank', 'Correct', 'Wrong', 'LastSeen']);
    sheet.getRange(1, 1, 1, 5).setFontWeight('bold');
    sheet.setFrozenRows(1);
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
