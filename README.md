# Language Flashcard App

A web-based flashcard application for learning Dutch and Spanish vocabulary with integrated reference links.

## Features

- **Multi-language support**: Dutch and Spanish (extensible to more languages)
- **Flexible word selection**: Choose specific ranges (0-100, 100-200, etc.) or custom ranges (e.g., 0-500)
- **Three study modes**:
  - **Flashcards**: Flip cards to see translations, POS tags, example sentences, and reference links
  - **Quiz**: Multiple-choice questions to test comprehension
  - **Type**: Practice spelling by typing translations
- **Clickable reference links**: Quick access to WordReference, SpanishDict, Reverso, and conjugation sites
- **Progress tracking**: Monitor cards studied, correct answers, and accuracy
- **Mobile-friendly**: Responsive design optimized for phone use
- **PWA support**: Install as a standalone app on your phone

## How It Works

### File Structure

The app automatically loads CSV files from your repository based on the configuration in `config.json`:

```
Fluency/
├── index.html          # Main app
├── config.json         # Language and CSV mappings
├── Dutch/
│   └── Vocabulary/
│       └── ChatGPT_Sets/
│           ├── 0-100.csv
│           ├── 100-200.csv
│           └── ...
└── Spanish/
    └── Vocabulary/
        └── ChatGPT_Sets/
            ├── 0-100.csv
            ├── 100-200.csv
            └── ...
```

### CSV Format

**Dutch CSVs:**
- Columns: `Dutch`, `POS`, `ChatGPT_Sentence`
- Example sentence format: Two lines (Dutch sentence, then English translation)

**Spanish CSVs:**
- Columns: `Spanish`, `show`, `lemma`, `ChatGPT_Sentence`
- `show`: English translation
- `lemma`: Base form of the word
- Example sentence format: Two lines (Spanish sentence, then English translation)

### Usage

1. **Select a language**: Choose Dutch or Spanish from the dropdown
2. **Choose word ranges**:
   - Click individual range buttons (e.g., "0-100", "100-200")
   - Multiple ranges can be selected (they'll be combined)
   - Or enter a custom range in the "From/To" fields
3. **Start learning**: Click "Start Learning" to load the flashcards
4. **Study modes**: Switch between Flashcards, Quiz, and Type modes

### Deployment to GitHub Pages

When you push to GitHub, the app will automatically work on GitHub Pages because:

1. All CSV files are served directly from the repository
2. The `config.json` uses relative paths
3. No build process required - it's a static site

To enable GitHub Pages:
1. Go to your repository settings
2. Navigate to Pages
3. Select the `main` branch as the source
4. The app will be available at `https://yourusername.github.io/Fluency/`

### Adding New Languages

Edit `config.json` to add a new language:

```json
"french": {
  "name": "French",
  "sets": [
    { "range": "0-100", "path": "French/Vocabulary/ChatGPT_Sets/0-100.csv" }
  ],
  "csvFormat": "french",
  "wordColumn": "French",
  "posColumn": "POS",
  "sentenceColumn": "ChatGPT_Sentence",
  "referenceLinks": {
    "wordReference": "https://www.wordreference.com/fren/{word}",
    "reverso": "https://context.reverso.net/translation/french-english/{word}"
  }
}
```

Then update the language selector in `index.html`:

```html
<option value="french">French</option>
```

## Mobile Installation (PWA)

On mobile browsers (Safari/Chrome):
1. Open the app URL
2. Tap the "Share" button
3. Select "Add to Home Screen"
4. The app will open as a standalone application

## Local Development

To test locally:
```bash
python3 -m http.server 8080
```

Then open `http://localhost:8080` in your browser.

## Notes

- Reference links open in new tabs for easy cross-referencing
- Progress statistics are session-based (reset on page reload)
- Shuffle feature randomizes card order for varied practice
- All data stays local - no server-side processing required
