# Fluency — AI Reference

Vocabulary flashcard PWA. Vanilla JS front-end (no framework/bundler/build step). Static JSON data. No backend. Artist vocabulary pipeline generates decks from song lyrics via NLP + Gemini.

## Repository Layout

```
Fluency/
├── index.html                   # App shell (HTML only, CSS + JS extracted)
├── css/style.css                # All CSS
├── js/                          # ES modules — see js/CLAUDE.md
├── artists.json                 # Artist configs for lyrics mode
├── config.json                  # Language config and file path mappings
├── manifest.json / service-worker.js
├── GoogleAppsScript.js          # Apps Script backend (deploy manually)
├── secrets.json                 # Google Apps Script URL (not in git)
├── Data/                        # Vocabulary JSON files — see Data/CLAUDE.md
└── Artists/                     # Pipeline scripts + per-artist data — see Artists/CLAUDE.md
```

## Common Tasks — Start Here

| Task | Start at |
|------|----------|
| Flashcard display issue | `js/flashcards.js` → `updateCard()` (~line 950) |
| Filtering / deck logic | `js/vocab.js` → `buildFilteredVocab()` |
| Multi-artist merge | `js/vocab.js` → `mergeArtistVocabularies()` |
| Setup UI flow | `js/ui.js` → `renderLevelSelector()`, `renderRangeSelector()` |
| TTS / speech | `js/speech.js` → `speakWord()` |
| Auth / progress saving | `js/auth.js` → `saveWordProgress()`, `loadUserProgressFromSheet()` |
| CSS changes | `css/style.css` (single file) |
| Pipeline word analysis | `Artists/scripts/6_llm_analyze.py` |
| Pipeline reranking | `Artists/scripts/8_rerank.py` |
| Add/exclude songs | `Artists/{Name}/data/input/duplicate_songs.json` |
| Artist config | `artists.json` (root) + `Artists/{Name}/artist.json` |
| Curated translation fixes | `Artists/{Name}/data/curated/curated_overrides.json` |

## Detailed Docs

- **Pipeline work?** Read `Artists/CLAUDE.md`
- **Front-end JS work?** Read `js/CLAUDE.md`
- **Data schemas / IDs / progress?** Read `Data/CLAUDE.md`

## Working with the Human

**Long-running commands:** Pipeline steps and other slow processes (>30s) should NOT be run inline. Print the command for Josh to run in his terminal — saves tokens and shows real-time progress.

**No browser previews:** Do NOT use preview tools or Claude-in-Chrome. Service worker caching makes previews unreliable. Josh tests in his own browser.

**Parallel agents:** Use sub-agents for independent tasks that don't touch the same files. Group work into waves. Keep the main conversation going across waves — agents get their own context windows.

**When to suggest a new conversation:** Only when context is genuinely stale (very long chat, topic shift). When suggesting, provide a ready-to-paste prompt with: task, files involved, and decisions that carry forward.

## Dependencies

```
google-genai              # Gemini API (pipeline step 4, 6)
lyricsgenius              # Genius API scraper (step 1)
lingua-language-detector  # English line filter (step 2, 2b)
```

Python 3.9+ via `.venv/bin/python3`. Dev server: `python3 -m http.server 8765` from project root.
