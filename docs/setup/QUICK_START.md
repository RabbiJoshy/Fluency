# Quick Start Guide

## 🚀 Get Started in 5 Minutes

### Step 1: Create Google Sheet
1. Go to [sheets.google.com](https://sheets.google.com)
2. Create a new blank spreadsheet
3. Name it "Flashcard Progress"

### Step 2: Add the Script
1. In the sheet, click **Extensions** → **Apps Script**
2. Delete the default code
3. Copy all code from `GoogleAppsScript.js`
4. Paste it into the editor
5. Save (Ctrl+S / Cmd+S)

### Step 3: Deploy
1. Click **Deploy** → **New deployment**
2. Click gear icon → **Web app**
3. Set:
   - Execute as: **Me**
   - Who has access: **Anyone**
4. Click **Deploy**
5. **Copy the Web App URL** (looks like: `https://script.google.com/macros/s/...`)

### Step 4: Update Your App
1. Open `index.html`
2. Find line ~2182:
   ```javascript
   const GOOGLE_SCRIPT_URL = 'YOUR_GOOGLE_APPS_SCRIPT_URL_HERE';
   ```
3. Replace with your URL:
   ```javascript
   const GOOGLE_SCRIPT_URL = 'https://script.google.com/macros/s/XXXXX/exec';
   ```
4. Save the file

### Step 5: Test!
1. Open `index.html` in your browser
2. Try **Guest Mode** (works without Google Sheets)
3. Try **Login** with your initials (e.g., "JD")
4. Practice some words
5. Check your Google Sheet - you should see data!

---

## 📁 Files Included

- **GoogleAppsScript.js** - Copy this to Google Apps Script
- **index.html** - Your updated app (remember to add the URL!)
- **SETUP_INSTRUCTIONS.md** - Detailed setup guide
- **IMPLEMENTATION_SUMMARY.md** - What was added
- **QUICK_START.md** - This file

---

## ❓ Troubleshooting

**Authentication modal doesn't show?**
- Clear browser cache and reload

**Data not saving to Google Sheets?**
- Check the URL is correct in index.html (line ~2182)
- Make sure deployment is set to "Anyone"
- Check browser console (F12) for errors

**"Guest" mode vs "Login" mode?**
- Guest = Local only, data lost on logout
- Login = Saved to Google Sheets, persistent

---

## 💡 What You Get

✅ Startup modal (Guest or Login)
✅ User badge showing initials or "GUEST"
✅ Automatic progress tracking per word
✅ Google Sheets backend
✅ Logout functionality
✅ Progress persists across sessions (Login mode)

---

Need more details? See **SETUP_INSTRUCTIONS.md**
