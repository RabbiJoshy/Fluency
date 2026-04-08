# Flashcard App - Google Sheets Backend Setup Instructions

## Overview

This guide will walk you through setting up the Google Sheets backend for your flashcard app. Once complete, users will be able to log in with their initials and have their progress automatically saved to and loaded from Google Sheets.

---

## Part 1: Create the Google Sheet

1. **Go to Google Sheets**
   - Visit [sheets.google.com](https://sheets.google.com)
   - Click **+ Blank** to create a new spreadsheet

2. **Name the Spreadsheet**
   - Click "Untitled spreadsheet" at the top
   - Rename it to something like "Flashcard Progress Tracker"

3. **The Script Will Auto-Create the Sheet**
   - You don't need to manually create columns
   - The Apps Script will automatically create a sheet named "UserProgress" with the correct headers when it runs for the first time

---

## Part 2: Add the Google Apps Script

1. **Open Apps Script Editor**
   - In your Google Sheet, click **Extensions** → **Apps Script**
   - This will open the Apps Script editor in a new tab

2. **Replace the Default Code**
   - You'll see a default `function myFunction() {}`
   - **Delete all the default code**
   - Copy the entire contents of `GoogleAppsScript.js` (included with this project)
   - Paste it into the Apps Script editor

3. **Save the Script**
   - Click the save icon (💾) or press `Ctrl+S` (Windows) / `Cmd+S` (Mac)
   - You can rename the project at the top (e.g., "Flashcard API")

---

## Part 3: Deploy as Web App

1. **Click Deploy → New Deployment**
   - In the Apps Script editor, click the **Deploy** button (top right)
   - Select **New deployment**

2. **Configure Deployment Settings**
   - Click the gear icon (⚙️) next to "Select type"
   - Choose **Web app**

3. **Set the Following Options**:
   - **Description**: "Flashcard Progress API" (or anything you like)
   - **Execute as**: **Me** (your email)
   - **Who has access**: **Anyone**
     - ⚠️ This is important! It allows your app to access the script without authentication

4. **Click Deploy**
   - You may see a warning: "This app isn't verified"
   - Click **Advanced** → **Go to [Project Name] (unsafe)**
   - Review the permissions and click **Allow**

5. **Copy the Web App URL**
   - After deployment, you'll see a **Web app URL**
   - It will look like: `https://script.google.com/macros/s/XXXXXXXX.../exec`
   - **Copy this URL** - you'll need it in the next step

---

## Part 4: Update Your index.html

1. **Open index.html**
   - Locate this line near the top of the `<script>` section (around line 2182):
   ```javascript
   const GOOGLE_SCRIPT_URL = 'YOUR_GOOGLE_APPS_SCRIPT_URL_HERE';
   ```

2. **Replace the Placeholder**
   - Replace `'YOUR_GOOGLE_APPS_SCRIPT_URL_HERE'` with your actual Web App URL:
   ```javascript
   const GOOGLE_SCRIPT_URL = 'https://script.google.com/macros/s/XXXXXXXX.../exec';
   ```

3. **Save index.html**

---

## Part 5: Test the Setup

### Test Guest Mode (LocalStorage)

1. **Open index.html in a Browser**
   - You should see the authentication modal

2. **Click "Guest Mode"**
   - The modal should close
   - You should see "GUEST" in the top-right corner
   - Practice a few words and mark them correct/incorrect
   - Close the browser and reopen - your session should be lost (guest mode doesn't save)

### Test Login Mode (Google Sheets)

1. **Logout** (if logged in as guest)
   - Click the "Logout" button in the top-right

2. **Click "Login"**
   - Enter your initials (2-4 letters, e.g., "JD")
   - Click "Continue"

3. **Practice Some Words**
   - Go through the flashcard setup
   - Practice at least 5-10 words
   - Mark some as correct ✓ and some as incorrect ✗

4. **Check Google Sheets**
   - Go back to your Google Sheet
   - You should see a new sheet tab called "UserProgress"
   - The sheet should have these columns:
     ```
     User | WordRank | Correct | Wrong | LastSeen
     ```
   - You should see rows with your initials and the words you practiced

5. **Test Progress Loading**
   - Close and reopen the browser
   - The app should remember your initials (stored in LocalStorage)
   - Your progress should automatically load from Google Sheets
   - Practice more words and verify they're being saved

---

## Part 6: Troubleshooting

### If the Script Doesn't Save Data

1. **Check the Browser Console**
   - Press `F12` (Windows) or `Cmd+Option+I` (Mac)
   - Look for error messages in the Console tab
   - Common errors:
     - "Failed to fetch" → Check your GOOGLE_SCRIPT_URL is correct
     - CORS errors → Make sure deployment is set to "Anyone"

2. **Re-deploy the Apps Script**
   - Go to Apps Script editor
   - Click **Deploy** → **Manage deployments**
   - Click the pencil icon (✏️) next to your deployment
   - Change the version to "New version"
   - Click **Deploy**
   - Update the URL in index.html if it changed

3. **Check Apps Script Execution Log**
   - In Apps Script editor, click **Executions** (left sidebar)
   - Look for failed executions and error messages

### If the Authentication Modal Doesn't Appear

1. **Check Browser Console for JavaScript Errors**
2. **Make sure you saved index.html after updating the GOOGLE_SCRIPT_URL**
3. **Clear your browser cache and reload**

### Guest Mode Not Saving Locally

- Guest mode intentionally doesn't persist data between sessions
- If you want progress saved, use Login mode

---

## Understanding the Data Flow

### Guest Mode
```
User marks word correct/incorrect
    ↓
saveWordProgress() checks currentUser.isGuest === true
    ↓
saveToLocalStorage() saves to browser's LocalStorage
    ↓
Data cleared when browser cache is cleared or user logs out
```

### Login Mode
```
User marks word correct/incorrect
    ↓
saveWordProgress() checks currentUser.isGuest === false
    ↓
POST request sent to Google Apps Script URL
    ↓
Apps Script saves data to Google Sheet
    ↓
Data persists across devices/browsers
```

### Loading Progress (Login Mode)
```
User enters initials and clicks Continue
    ↓
submitLogin() saves initials to LocalStorage
    ↓
loadUserProgressFromSheet() sends POST request to fetch user data
    ↓
Apps Script returns all rows matching user's initials
    ↓
Data loaded into progressData object for future reference
```

---

## Google Sheet Structure

After using the app, your Google Sheet will look like this:

| User | WordRank | Correct | Wrong | LastSeen              |
|------|----------|---------|-------|-----------------------|
| JD   | 42       | 3       | 1     | 2026-01-24T10:30:00Z |
| JD   | 89       | 2       | 0     | 2026-01-24T10:31:00Z |
| SM   | 42       | 1       | 2     | 2026-01-24T11:00:00Z |

- **User**: The initials entered during login
- **WordRank**: The frequency rank of the word (unique identifier)
- **Correct**: Number of times marked correct
- **Wrong**: Number of times marked incorrect
- **LastSeen**: ISO timestamp of last practice

---

## Security Notes

⚠️ **Important Security Considerations**:

1. **This setup is suitable for personal use or small groups**
   - The "Anyone" access setting means anyone with the URL can access the script
   - They cannot see or modify your Google Sheet directly
   - They can only add/read data through the API

2. **For Production Use**:
   - Consider implementing OAuth authentication
   - Add rate limiting to the Apps Script
   - Validate input data more strictly
   - Use a proper backend with user authentication

3. **Data Privacy**:
   - User initials are stored in plain text
   - No passwords or sensitive data is collected
   - Progress data is stored in your personal Google Sheet

---

## Advanced: API Endpoints

The Google Apps Script provides these endpoints:

### 1. Load Progress
```javascript
POST {
  "action": "load",
  "user": "JD"
}

// Response
{
  "success": true,
  "message": "Progress loaded successfully",
  "data": {
    "progress": [
      { "wordRank": 42, "correct": 3, "wrong": 1, "lastSeen": "2026-01-24..." }
    ]
  },
  "timestamp": "2026-01-24T10:30:00Z"
}
```

### 2. Save Progress
```javascript
POST {
  "action": "save",
  "user": "JD",
  "wordRank": 42,
  "correct": 3,
  "wrong": 1,
  "lastSeen": "2026-01-24T10:30:00Z"
}

// Response
{
  "success": true,
  "message": "Progress saved successfully",
  "timestamp": "2026-01-24T10:30:00Z"
}
```

### 3. Delete Progress (for testing)
```javascript
POST {
  "action": "delete",
  "user": "JD",
  "wordRank": 42  // optional - if omitted, deletes all user data
}

// Response
{
  "success": true,
  "message": "Progress deleted successfully",
  "timestamp": "2026-01-24T10:30:00Z"
}
```

### 4. Test Endpoint (GET request)
Visit your Web App URL in a browser to test:
```
https://script.google.com/macros/s/XXXXXXXX.../exec
```

You should see:
```json
{
  "status": "success",
  "message": "Flashcard API is running",
  "timestamp": "2026-01-24T10:30:00Z"
}
```

---

## Support

If you run into issues:

1. Check the browser console for errors (F12)
2. Check Apps Script execution logs (Executions tab in Apps Script editor)
3. Verify the GOOGLE_SCRIPT_URL is correct in index.html
4. Make sure the deployment is set to "Anyone" access
5. Try re-deploying with a new version

---

## Summary Checklist

- [ ] Created Google Sheet
- [ ] Added Apps Script code from GoogleAppsScript.js
- [ ] Deployed as Web App with "Anyone" access
- [ ] Copied Web App URL
- [ ] Updated GOOGLE_SCRIPT_URL in index.html
- [ ] Tested Guest Mode (works offline)
- [ ] Tested Login Mode (saves to Google Sheets)
- [ ] Verified data appears in Google Sheet
- [ ] Tested progress loading on page reload

---

**Congratulations!** Your flashcard app now has a working backend with user authentication and progress tracking! 🎉
