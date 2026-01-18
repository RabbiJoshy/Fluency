# Language Flashcard App

A modern web-based flashcard application for learning Dutch and Spanish vocabulary with advanced features for effective language learning.

## Features

### Core Features
- **Multi-language support**: Dutch and Spanish with CEFR-level organization
- **CEFR Level Selection**: Choose your proficiency level (A1, A2, B1, B2) to study appropriate vocabulary
- **Flexible set sizes**: Study in groups of 25, 50, or 100 cards at a time
- **Multi-meaning support**: Words with multiple meanings show all definitions with usage percentages
- **Lemma integration**: See base forms of conjugated words (e.g., "estaba (estar)")
- **Swipe gestures**: Natural mobile interaction - swipe right for correct, left for incorrect
- **Keyboard shortcuts** (Desktop):
  - `←` Left Arrow: Mark incorrect
  - `→` Right Arrow: Mark correct
  - `Space` or `Enter`: Flip card
- **Progress tracking**: Monitor cards studied, correct answers, and accuracy
- **Review system**: Review incorrect cards at the end of each session
- **Mobile-optimized**: Responsive design with touch-friendly controls
- **PWA support**: Install as a standalone app on your phone

### Study Interface
- **Front of card**: Spanish/Dutch word with frequency rank
- **Back of card**:
  - Word with lemma in brackets (if different)
  - Multiple meanings with percentages and part of speech
  - Example sentences with translations
  - Quick reference links (SpanishDict, Reverso, Conjugation)
  - Desktop: Correct/Incorrect buttons integrated into interface
- **Navigation**: Previous/Next buttons on both sides of card
- **Flip direction toggle**: Switch between Spanish→English and English→Spanish

## File Structure

```
Fluency/
├── index.html              # Main application
├── config.json             # Language configuration and file mappings
├── manifest.json           # PWA manifest
├── service-worker.js       # PWA service worker
├── Spanish New Frmat/      # New multi-meaning format files
│   ├── 1-100_new_format.txt
│   ├── 100-200_new_format.txt
│   ├── 200-300_new_format.txt
│   ├── 300-400_new_format.txt
│   ├── 400-500_new_format.txt
│   ├── 500-600_new_format.txt
│   ├── 600-700_new_format.txt
│   ├── 700-800_new_format.txt
│   ├── 900-1000_new_format.txt
│   └── 2500-2750_new_format.txt
├── Spanish/
│   └── Vocabulary/
│       └── Quizlet Sets/   # Legacy format files
└── Dutch/
    └── Vocabulary/
        └── Quizlet Sets/
```

## Data Formats

### New Multi-Meaning Format (pipe-delimited)
```
rank|word|lemma|pos|meaning|percentage|targetSentence|englishSentence
103|estaba|estar|VERB|was (temporary state/location)|1.00|Estaba en mi trabajo.|I was at my job.
110|hace|hacer|VERB|does/makes|0.60|¿Qué hace él?|What does he do?
110|hace|hacer|VERB|ago|0.25|Hace dos años.|Two years ago.
110|hace|hacer|VERB|is (weather)|0.15|Hace calor.|It is hot.
```

**Columns:**
- `rank`: Frequency rank (1-5000)
- `word`: The word as it appears in text (may be conjugated)
- `lemma`: Base form/infinitive (empty if same as word)
- `pos`: Part of speech (VERB, NOUN, ADJ, ADV, etc.)
- `meaning`: English translation
- `percentage`: How often this meaning is used (0.0-1.0)
- `targetSentence`: Example sentence in target language
- `englishSentence`: Translation of example sentence

### Legacy Quizlet Format (tab-delimited)
```
word	translation
*inflected* (base)	translation
Target sentence in Spanish
English translation of sentence
```

## Configuration

The `config.json` file controls which files are loaded for each language and CEFR level:

```json
{
  "languages": {
    "spanish": {
      "name": "Spanish",
      "cefrLevels": [
        {
          "level": "A1",
          "description": "Beginner",
          "comprehension": "~65% of spoken language",
          "wordCount": "0-800",
          "sets": [
            {
              "range": "0-100",
              "path": "Spanish New Frmat/1-100_new_format.txt",
              "format": "multiMeaning"
            }
          ]
        }
      ],
      "referenceLinks": {
        "spanishDict": "https://www.spanishdict.com/translate/{word}",
        "reverso": "https://context.reverso.net/translation/spanish-english/{word}",
        "conjugation": "https://www.spanishdict.com/conjugate/{word}"
      }
    }
  }
}
```

## Usage

### Getting Started
1. **Choose Language**: Select Spanish or Dutch
2. **Select CEFR Level**: Pick your proficiency level (A1-B2)
3. **Choose Set Size**: Select 25, 50, or 100 cards per session
4. **Pick a Range**: Click on a numbered range to start studying

### Study Session
- **Mobile**:
  - Tap the word to flip the card
  - Swipe right to mark correct
  - Swipe left to mark incorrect
  - Tap meaning boxes to see different example sentences
- **Desktop**:
  - Click the word or press Space/Enter to flip
  - Use arrow keys (← →) or click buttons to mark correct/incorrect
  - Click meaning boxes to switch between definitions

### End of Session
After completing a set, you'll see:
- Total correct and incorrect answers
- Accuracy percentage
- Option to review incorrect cards
- Option to restart all cards
- Mark complete and exit

## Deployment

### GitHub Pages
The app works as a static site and can be deployed to GitHub Pages:

1. Push all files to your repository
2. Go to Settings → Pages
3. Select `main` branch as source
4. Access at `https://yourusername.github.io/Fluency/`

### Local Development
```bash
# Start a local server
python3 -m http.server 8080

# Open in browser
open http://localhost:8080
```

## Mobile Installation (PWA)

### iOS (Safari)
1. Open the app in Safari
2. Tap the Share button
3. Select "Add to Home Screen"
4. Tap "Add"

### Android (Chrome)
1. Open the app in Chrome
2. Tap the menu (⋮)
3. Select "Add to Home Screen"
4. Tap "Add"

The app will now open as a standalone application without browser UI.

## Adding New Content

### Adding New Spanish Files
1. Create a file in the multi-meaning format
2. Name it with the range (e.g., `800-900_new_format.txt`)
3. Place it in the `Spanish New Frmat/` folder
4. Update `config.json`:
```json
{
  "range": "800-900",
  "path": "Spanish New Frmat/800-900_new_format.txt",
  "format": "multiMeaning"
}
```

### Adding a New Language
1. Create folder structure: `NewLanguage/Vocabulary/`
2. Add data files
3. Update `config.json` with new language configuration
4. Add language tab in the HTML (search for `lang-tab`)

## Technical Details

### Technologies
- Vanilla JavaScript (no frameworks)
- CSS Grid and Flexbox for layout
- CSS Animations for card interactions
- Service Worker for PWA functionality
- LocalStorage for session data

### Browser Compatibility
- Modern browsers (Chrome, Firefox, Safari, Edge)
- Mobile browsers (iOS Safari 12+, Android Chrome)
- Progressive Web App support on all major platforms

### Performance
- Lazy loading of vocabulary data
- Efficient DOM updates
- Smooth 60fps animations
- Minimal memory footprint

## Features Roadmap

- [ ] Spaced repetition algorithm
- [ ] User accounts with cloud sync
- [ ] Audio pronunciation
- [ ] Dark mode toggle
- [ ] Export progress data
- [ ] Custom deck creation
- [ ] Offline mode improvements

## License

This project is for personal educational use.

## Contributing

To contribute new vocabulary sets or features:
1. Fork the repository
2. Create a feature branch
3. Add your changes
4. Submit a pull request

## Support

For issues or questions, please open an issue on the GitHub repository.
