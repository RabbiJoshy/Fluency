# Fluency — Technical Reference for AI Assistants

This document describes the full architecture, pipeline logic, data schemas, and design decisions for the Fluency project. Read this before touching any code.

---

## Project Overview

Fluency is a browser-based vocabulary flashcard PWA. The front-end is vanilla JS split across native ES modules (`js/`) with no framework, no bundler, and no build step. All vocabulary data is static JSON — there is no backend.

The interesting part is the **data pipeline** that generates the vocabulary JSON, particularly the Bad Bunny pipeline which processes song lyrics using NLP to produce a Spanish vocabulary deck.

---

## Repository Layout

```
Fluency/
├── index.html                      # App shell: 647 lines of HTML only (CSS + JS extracted)
├── css/
│   └── style.css                   # All CSS (extracted from old monolith)
├── js/
│   ├── main.js                     # Entry point: imports all modules, registers SW, init
│   ├── state.js                    # Shared mutable state + globalThis proxy
│   ├── auth.js                     # Login, Google Sheets sync, saveWordProgress
│   ├── vocab.js                    # buildFilteredVocab, loadVocabularyData, getWordId
│   ├── flashcards.js               # Card rendering, flip, swipe, keyboard shortcuts
│   ├── ui.js                       # Setup UI: language tabs, level selector, range buttons
│   ├── config.js                   # loadConfig, loadPpmData, CEFR helpers
│   ├── progress.js                 # Coverage bars, calculateCoveragePercent
│   ├── estimation.js               # Level-estimation quiz flow
│   ├── speech.js                   # speakWord, voice preload
│   └── artist-ui.js                # Album art lookup, updateArtistBackground
├── artists.json                    # Artist configs for lyrics mode (paths, colors, album art)
├── config.json                     # Language config and file path mappings
├── manifest.json / service-worker.js  # PWA support
├── GoogleAppsScript.js             # Source copy of the Apps Script backend (deploy manually)
├── cefr_levels.json                # CEFR level metadata
├── estimation_checkpoints.json     # Vocabulary checkpoints for level-estimation quiz
├── secrets.json                    # Google Apps Script URL (not committed to git)
├── Data/
│   ├── Spanish/vocabulary.json     # 11 136 entries with rank + id fields
│   ├── Swedish/vocabulary.json     # 2 001 entries
│   ├── Italian/vocabulary.json     # 600 entries
│   ├── Dutch/vocabulary.json       # 100 entries
│   └── Polish/vocabulary.json      # 300 entries
├── Artists/                        # Shared pipeline + per-artist data
│   ├── run_pipeline.py             # Shared orchestrator (--artist "Bad Bunny")
│   ├── scripts/                    # Single set of pipeline scripts (1-8)
│   │   ├── _artist_config.py       # Shared helper (add_artist_arg, load_artist_config)
│   │   ├── 1_download_lyrics.py    # All scripts accept --artist-dir
│   │   └── ...
│   ├── shared/                     # Curated data shared across all artists (with source tags)
│   ├── tools/                      # check_translations.py, split_lang_audit.py
│   ├── DEDUP_INSTRUCTIONS.md       # How to maintain duplicate_songs.json (shared)
│   ├── Bad Bunny/                  # Artist data
│   │   ├── artist.json             # {"name", "genius_query", "vocabulary_file"}
│   │   ├── BadBunnyvocabulary.json # Final output consumed by the app
│   │   ├── bad_bunny_albums_dictionary.json
│   │   ├── data/...                # Pipeline intermediates + curated overrides
│   │   └── Images/...              # Album cover art
│   └── Rosalía/                    # Artist data (pipeline run, --words-only)
│       ├── artist.json
│       ├── Rosaliavocabulary.json   # Monolith output from pipeline
│       ├── Rosaliavocabulary.index.json   # Split: metadata only
│       ├── Rosaliavocabulary.examples.json # Split: examples only
│       └── data/...
└── .venv/                          # Python venv — activate with .venv/bin/python3
```

All pipeline scripts are run from the **project root** (`Fluency/`), not from inside subdirectories.

**Dev server:** `python3 -m http.server 8765` from the project root (configured in `.claude/launch.json`).

---

## Artist Vocabulary Pipeline

The pipeline turns an artist's discography into a structured vocabulary deck. Steps: scrape lyrics (Genius API) -> tokenise & count (with dedup filtering) -> scrape Genius translations (step 3b) -> detect proper nouns (Gemini) -> merge Caribbean elisions -> Gemini LLM analysis (POS, lemma, translation) -> flag cognates -> rerank.

**Shared scripts** live in `Artists/scripts/`. Each artist has a data directory under `Artists/` with an `artist.json` config file.

Key files:
- `Artists/run_pipeline.py` — shared orchestrator
- `Artists/scripts/3b_scrape_translations.py` — scrapes community English translations from Genius
- `Artists/scripts/6_llm_analyze.py` — main analysis step (Gemini + Genius translations)
- `Artists/Bad Bunny/artist.json` — artist config (name, genius_query, vocabulary_file)
- `Artists/Bad Bunny/BadBunnyvocabulary.json` — final output consumed by the app
- `Artists/Bad Bunny/data/input/translations/translations.json` — Genius community translations
- `Artists/DEDUP_INSTRUCTIONS.md` — how to maintain duplicate_songs.json for any artist

Quick run:
```bash
.venv/bin/python3 Artists/run_pipeline.py --artist "Bad Bunny"
.venv/bin/python3 Artists/run_pipeline.py --artist "Rosalía" --from-step 6 --words-only
.venv/bin/python3 Artists/run_pipeline.py --artist "Anuel" --no-gemini  # Free: Genius translations only
```

### `--no-gemini` and `--words-only` modes

`--no-gemini` skips all Gemini API calls. Uses only Genius community translations (from step 3b) + curated overrides. No API key needed. Produces a valid but lower-quality vocabulary (no POS/lemma/sense analysis). Useful for cheaply ingesting a new artist's corpus.

`--words-only` runs Gemini word analysis (POS, lemma, translation) but skips sentence translation. Much cheaper than a full run. Useful when Genius already covers example sentences and you just need word-level data. Typical workflow: `--no-gemini` first to get everything free, then `--words-only` to add word translations.

### Sentence translation layers

Step 6 uses two translation sources, checked in order:
1. **Genius index** (Layer 1): Built fresh every run from `translations.json` + batch files. Free. Covers ~40% of lines for Bad Bunny (190/537 songs have Genius translations).
2. **Gemini cache** (Layer 2): Persistent `sentence_translations.json`. Expensive but high quality. Only called for lines Genius doesn't cover.

Genius never overwrites existing Gemini translations. Each example in the output has a `translation_source` field ("genius" or "gemini") for auditing.

**Important for MWEs**: The Gemini cache only covers ~15,600 unique lines (those used as word examples). The full corpus has ~33,800 lines. Genius translations cover an additional ~2,300 lines that Gemini never translated. This matters when building MWE example sentences — many MWE-containing lines exist only in the Genius index.

**Alignment approach**: Line alignment uses section-aware matching — splits lyrics at empty lines (section boundaries), only zips sections where Spanish and English line counts match exactly. This avoids cascading misalignment from a translator splitting/merging a line (e.g. "bebé" on its own line). Currently recovers ~7,500 lines. ~4,900 lines in mismatched sections are skipped. **Future improvement**: embedding-based sentence alignment (e.g. `vecalign` or Gemini `text-embedding-004`) could recover those skipped lines by finding best 1:1 matches across languages. Cost would be essentially free (~80K tokens). Low priority since section-aware covers the majority.

### Adding a new artist
1. Create `Artists/NewArtist/artist.json` with `name`, `genius_query`, `vocabulary_file`
2. Run step 1: `.venv/bin/python3 Artists/scripts/1_download_lyrics.py --artist-dir "Artists/NewArtist"`
3. Curate `duplicate_songs.json` (see `Artists/DEDUP_INSTRUCTIONS.md`)
4. Copy reusable curated data from an existing artist (conjugation_families, skip_mwes, etc.)
5. Run pipeline: `.venv/bin/python3 Artists/run_pipeline.py --artist "NewArtist"` (or `--no-gemini` for free, then `--words-only` to add translations cheaply)
   - Step 3 filters out excluded songs via `duplicate_songs.json` before counting
   - Step 3b scrapes Genius translations (only for surviving songs)
   - Steps 4-8 continue as normal
6. The pipeline auto-splits the monolith into index + examples files at the end of every run
7. Add the artist to `artists.json` at project root with paths, colorTheme, maxLevel
8. Shared words with existing artists get translations automatically via client-side merge — no need to run Gemini for overlapping vocabulary

---

## Working with the Human

**Long-running commands:** Pipeline steps, model loading, embedding passes, and other slow processes (>30 seconds) should NOT be run inline via tool calls. Instead, print the command for Josh to run in his own terminal. This lets him see real-time progress and saves context tokens. Resume analysis after he shares the output.

**No browser previews:** Do NOT use preview tools (preview_start, preview_screenshot, etc.) or Claude-in-Chrome to test front-end changes. The service worker caching makes previews unreliable — cached JS/HTML persists across reloads and wastes tokens debugging stale files. Josh will test in his own browser instead.

**Suggest new conversations:** Proactively recommend that Josh start a new conversation when the current one has completed a logical unit of work (e.g., a feature is done, a bug is fixed, a pipeline run is finished and committed). Fresh conversations save tokens and avoid context bloat. When suggesting, **always provide a ready-to-paste prompt** for the next conversation. The prompt should include:
- What the task is and why (enough rationale so the new session understands the goal)
- Which part of the codebase is involved (Bad Bunny pipeline, front-end normal mode, front-end Bad Bunny mode, etc.)
- Specific files or functions to start looking at
- Any decisions or context from the current conversation that the new session needs

Example: "Start a new chat with this prompt: *I want to prioritise Bad Bunny example lyrics so sentences containing recently-studied or recently-wrong words appear first. This touches step 8 rerank (`Artists/scripts/8_rerank.py`) for static pre-sorting and `js/flashcards.js` `updateCard()` for dynamic re-sorting at display time. The example data lives in each word's `meanings[].allExamples[]` array. A two-layer approach was discussed: static pipeline sort by nearby-rank overlap, then dynamic front-end re-score using `progressData`.*"

---

## Dependencies

```
google-genai        # Gemini API (step 4, main analysis)
lyricsgenius        # Genius API scraper (step 1)
lingua-language-detector  # Used in step 2 (English line filter) and 2b (audit tool)
```

Python 3.9+ required (project uses `.venv/bin/python3`).

---

## Common Pitfalls

- **Running scripts from the wrong directory**: all scripts should be run from `Fluency/` root. The shared orchestrator handles this: `.venv/bin/python3 Artists/run_pipeline.py --artist "Bad Bunny"`.
- **Step 7 resets `is_transparent_cognate`**: any cognate flag set upstream is overwritten. Step 7 is always the authoritative pass; do not set `is_transparent_cognate` in earlier steps expecting it to survive.
- **`strip_plural` over-strips**: the function removes terminal `-s` from any word. English words like `"famous"`, `"serious"`, `"previous"` all lose their `s`. Step 7 accounts for this by checking suffix rule results against both the stripped and unstripped English form.

---

## Front-end Architecture

### Overview

The front-end is vanilla JS served as static files — no build step, no framework, no bundler. `index.html` (647 lines) is HTML only; all CSS lives in `css/style.css` and all JS is split across native ES modules in `js/`.

**Entry points:**
- `index.html` — standard vocabulary mode (Spanish, Swedish, Italian, Dutch, Polish)
- `index.html?artist=bad-bunny` — artist/lyrics mode (loads config from `artists.json`)
- `index.html?mode=badbunny` — legacy alias for `?artist=bad-bunny`

---

### Module System

`js/main.js` is the single `<script type="module">` tag in `index.html`. It imports all other modules in dependency order. All modules import `./state.js` first.

**globalThis proxy pattern** — the key architectural decision for cross-module state:

`js/state.js` declares a `state` object holding all 35+ mutable globals and then installs a `globalThis` proxy for each key:
```js
Object.defineProperty(globalThis, key, {
    get() { return state[key]; },
    set(v) { state[key] = v; },
});
```
This means **bare variable names** (`flashcards`, `progressData`, `currentUser`, etc.) work in every module without any import — reads and writes go through the proxy to the shared `state` object. Zero changes were needed to function bodies when extracting the modules.

**Window exports** — cross-module function calls:

Each module exposes its functions on `window` (e.g. `window.buildFilteredVocab = buildFilteredVocab`). Since all module-level code runs before any user interaction, by the time any function is called all modules are loaded and their window exports are available. Inline `onclick` handlers in template literals (`onclick="selectMeaning(${idx})"`, `onclick="cycleExample(event)"`) rely on this — `selectMeaning` and `cycleExample` are exposed on `window` from `flashcards.js`.

**Critical**: never add module-level `let`/`const` declarations in any module for variables that also exist in `state.js` — they will shadow the globalThis proxy and create a split-brain bug where that module's reads/writes are invisible to all other modules.

---

### `config.json` Schema

Loaded on startup by `loadConfig()`. Drives language-specific behaviour.

```json
{
  "languages": {
    "spanish": {
      "name": "Spanish",
      "dataPath": "Data/Spanish/vocabulary.json",
      "ppmDataPath": "Data/Spanish/SpanishRawWiki.csv",
      "exampleTargetField": "example_spanish",
      "exampleEnglishField": "example_english",
      "colorTheme": { "primary": "#C8102E", "secondary": "#FFCC00" },
      "cefrLevels": [
        { "level": "A1", "description": "Beginner", "wordCount": "1-800" },
        ...
      ],
      "referenceLinks": {
        "wordReference": "https://www.wordreference.com/es/en/translation.asp?spen={word}",
        ...
      }
    }
  }
}
```

Key fields:
- `dataPath` — JSON vocabulary file for this language
- `ppmDataPath` — CSV with `rank,occurrences_ppm` columns (optional; enables % coverage mode)
- `exampleTargetField` / `exampleEnglishField` — keys inside each meaning's `examples[]` for sentence display
- `hasData: false` — marks a language as coming soon (grays out the tab)

---

### Word IDs and the Composite `fullId`

Every vocabulary JSON entry has a 4-digit **hex** `id` field, computed as `md5(word|lemma)[:4]` — the first 4 hex characters of the MD5 hash of `word|lemma`. This is consistent across all vocabulary files:
- **Artist vocab**: assigned by pipeline step 6 via `make_stable_id(word, lemma)`
- **Normal vocab files** (Spanish, Swedish, Italian, Dutch, Polish): migrated from rank-based to md5-based IDs via `scripts/migrate_vocab_ids.py`. Migration mappings in `Data/{lang}/id_migration.json`.
- **Collision resolution**: if two different word|lemma pairs hash to the same 4 hex chars, a suffix is appended before rehashing: `md5(word|lemma|1)[:4]`, `md5(word|lemma|2)[:4]`, etc.
- **Same word = same ID across artists**: "que|que" → `ed68` in both Bad Bunny and Rosalía. This enables client-side multi-artist vocabulary merging.

At flashcard-load time, `vocab.js` builds a **composite `fullId`** for every card:

```
fullId = {2-char ISO lang code}{0=normal | 1=lyrics}{4-digit hex id}
```

| Example | Meaning |
|---|---|
| `"es0ed68"` | Spanish normal, word "que" (md5 id ed68) |
| `"es1ed68"` | Spanish artist/lyrics mode, same word "que" |
| `"sv06b7f"` | Swedish normal, word "och" |

Language codes (`LANG_CODES` in `vocab.js`): `spanish→es`, `swedish→sv`, `italian→it`, `dutch→nl`, `polish→pl`, `french→fr`, `russian→ru`.

`getWordId(item)` in `vocab.js` computes the fullId from any raw vocab item (needs `selectedLanguage` and `activeArtist` from state). It is exposed on `window` so `ui.js` can call it for mastery checks.

**Why `fullId` not bare hex:**
- Bare hex IDs like `"0039"` get auto-converted by Google Sheets to the integer `39`, breaking row-matching. Composite IDs always contain letters, so Sheets leaves them as strings.
- Mode digit separates normal vs. lyrics progress for the same language in the same sheet row-namespace.
- Same word in both modes shares the same hex portion, differentiated by mode digit — allows future cross-mode analytics.

**All `progressData` is keyed by `fullId`**, not bare hex or rank. `card.fullId` is set on every flashcard object. `saveWordProgress` sends `wordId: card.fullId` to Google Sheets. All mastery lookups use `progressData[getWordId(item)]` or `progressData[card.fullId]`.

---

### Key Global Variables

All declared in `js/state.js` and accessible as bare names everywhere via the globalThis proxy:

| Variable | Type | Purpose |
|---|---|---|
| `flashcards` | `Array` | Current active deck — objects shaped `{ targetWord, lemma, id, rank, meanings[], ... }` |
| `currentIndex` | `number` | Index into `flashcards` for the visible card |
| `currentMeaningIndex` | `number` | Which POS meaning is selected on the back face |
| `currentExampleIndex` | `number` | Which lyric example is shown (Bad Bunny mode) |
| `isFlipped` | `boolean` | Flip **direction** toggle (target→English vs English→target); not card-flip state |
| `stats` | `object` | `{ studied: Set, correct, incorrect, total, cardStats: { [idx]: {correct,incorrect} } }` |
| `config` | `object\|null` | Loaded `config.json` |
| `selectedLanguage` | `string` | Key into `config.languages` (e.g. `"spanish"`) |
| `selectedLevel` | `string\|null` | CEFR level string (e.g. `"A1"`) or null |
| `groupSize` | `number` | Cards per set (25 or 50) |
| `useLemmaMode` | `boolean` | One card per lemma if true |
| `excludeCognates` | `boolean` | Skip transparent cognates if true |
| `percentageMode` | `boolean` | % coverage mode (vs CEFR level mode) |
| `ppmData` | `Array\|null` | `[{ rank, ppm, id }]` — frequency data for coverage calculations |
| `totalPpm` | `number` | Sum of all ppm values for coverage % denominator |
| `activeArtist` | `object\|null` | null = normal mode, object = artist config from `artists.json` |
| `isBadBunnyMode` | `boolean` | Backward-compat getter: `!!activeArtist`. Do not set directly. |
| `currentUser` | `object\|null` | `{ initials, isGuest }` — null until auth resolves |
| `progressData` | `object` | `wordId → { correct, wrong, lastCorrect, lastWrong, lastSeen, word, language }` |
| `levelEstimates` | `object` | `language → rank` — high-water mark from estimation quiz |
| `estimationState` | `object` | Mutable state for the level-estimation quiz flow |
| `isAppInitialized` | `boolean` | Guards `initializeApp()` so event listeners are only attached once |

---

### Setup UI Flow (5 steps)

The setup panel (`#setupPanel`) shows steps sequentially:

```
Step 1: Language tabs (#languageTabs)
   → user clicks a language tab
   → loadPpmData() fetches ppm CSV if available
   → step 2 appears

Step 2: CEFR level / % coverage (#levelSelector, inside #step2)
   → user clicks a level button (e.g. "A1")
   → selectedLevel is set
   → renderRangeSelector() builds the set buttons
   → step 3 appears (if lemma data available)

Step 3: Cards per Lemma (#lemmaToggleContainer)
   → toggle 1 card/lemma vs. all forms
   → sets useLemmaMode

Step 4: Exclude Cognates (#cognateToggleContainer)
   → toggle include vs. exclude cognates
   → sets excludeCognates
   → Only shown if cognateFieldAvailable (vocabulary has is_transparent_cognate)

Step 5: Choose Set (#step4 in DOM, displayed as step 5)
   → range buttons: "1–25", "26–50", etc.
   → clicking a range button calls loadVocabularyData(rangeString)
   → on success: #setupPanel hides, #appContent shows, initializeApp() called
```

Note: the DOM element `id="step4"` is visually rendered as step number 5. Steps 3 and 4 (lemma/cognate toggles) use container IDs `lemmaToggleContainer` / `cognateToggleContainer`, not `step3`/`step4`.

---

### Main Function Call Flow

```
loadConfig()                         # fetches config.json → state.config
  └─ renderLanguageTabs()            # builds language tab buttons

[user clicks language tab]
  └─ loadPpmData(language)           # optional; fetches ppm CSV
  └─ renderLevelSelector(language)   # builds A1/A2/B1... or % buttons
  └─ updateLemmaToggleVisibility()   # fetches vocab to check lemma field
  └─ updateCognateToggleVisibility() # fetches vocab to check cognate field

[user clicks level button]
  └─ renderRangeSelector()           # calls buildFilteredVocab() on full vocab
                                     # slices to level's rank range
                                     # builds "1-25", "26-50" set buttons

[user clicks a set button]
  └─ loadVocabularyData(rangeString) # fetches vocab JSON
       └─ buildFilteredVocab()       # applies all filters (English, cognate, lemma, single-occ)
       # filters by displayRank range
       # filters out mastered words (progressData)
       # converts to flashcard objects
       # setTimeout 800ms → hides setup panel, shows #appContent
       └─ initializeApp()            # updateCard() + attaches all event listeners (once)

[flashcard interaction loop]
  └─ updateCard()                    # renders current card (front + back)
  └─ flipCard()                      # toggles .flipped class on #flashcard
  └─ nextCard() / previousCard()     # advances currentIndex, calls updateCard()
  └─ handleSwipeAction('correct'|'incorrect')
       └─ recordCardResult()         # updates stats
       └─ saveWordProgress()         # writes to progressData + Google Sheets + localStorage
       └─ nextCard() or showEndOfDeckOptions()
```

---

### `buildFilteredVocab(vocabData)` — Central Filter

Applied to the full vocabulary array before slicing to a rank range. Returns `{ vocab, counts }`.

Filter order:
1. Remove blank words, duplicates, entries with no meanings
2. Artist mode: remove `is_english`, `is_interjection`, `is_propernoun`
3. `excludeCognates`: remove `is_transparent_cognate`
4. `hideSingleOccurrence`: remove `corpus_count <= 1` (artist mode only, enabled by default)
5. `useLemmaMode`: keep only `most_frequent_lemma_instance === true`

After filtering, assigns `displayRank` (1-based continuous rank across the filtered set). Range buttons use `displayRank` for set boundaries, **not** the original `rank` from the JSON. This means set 1–25 always contains exactly 25 words regardless of what was filtered out.

---

### `progressData` Schema

```js
progressData[fullId] = {   // fullId e.g. "es00001", "es10039", "sv00001"
  correct: 3,              // times marked correct in any session
  wrong: 1,                // times marked wrong in any session
  lastCorrect: "2025-01-15T10:23:00.000Z",  // ISO timestamp or null
  lastWrong: "2025-01-10T08:00:00.000Z",    // ISO timestamp or null
  lastSeen: "2025-01-15T10:23:00.000Z",
  word: "eres",
  language: "spanish"
}
```

A word is considered **mastered** if `progressData[fullId].correct > 0` and `progressData[fullId].language === selectedLanguage`. Mastered words are filtered out of sets by `loadVocabularyData()`.

`levelEstimates[language]` is a rank high-water mark — all words with `item.rank <= estimate` are also treated as mastered without needing individual progress records.

Progress is stored in two places:
- **Google Sheets** (for logged-in users) via a Google Apps Script URL loaded from `secrets.json`
- **localStorage** (for guest users) under key `flashcard_progress_guest`

---

### Google Sheets Integration

**Backend**: `GoogleAppsScript.js` is the source of the Apps Script web app. It must be copy-pasted into the Apps Script editor and **redeployed as a new version** every time it changes — editing the file in the repo does not update the live endpoint.

**Sheet layout** (columns A–H): `User | Word | WordId | Language | Correct | Wrong | LastCorrect | LastWrong`

Two sheets: `UserProgress` (normal vocab) and `Lyrics` (artist/lyrics mode). Selected via `sheet: activeArtist ? 'Lyrics' : 'UserProgress'` in every request. The old `BadBunny` sheet is auto-renamed to `Lyrics` on first access.

**Save flow** (`saveWordProgress` in `auth.js`):
1. Uses `card.fullId` as `wordId` — always a letter-containing string, never auto-converted by Sheets
2. Updates local `progressData[card.fullId]` first, then POSTs to the Apps Script
3. Guest mode: falls back to `saveToLocalStorage(wordId, isCorrect)` instead

**Load flow** (`loadUserProgressFromSheet` in `auth.js`):
- Called once from `main.js` after `await loadSecrets()` and `checkAuthentication()`
- Resets `progressData = {}` then populates from every row for the logged-in user
- `progressData[item.wordId] = {...}` — keys are fullIds as returned from Sheets (strings with letters, no mangling)

**Apps Script matching**: uses `==` (loose equality) in `saveProgress` when matching `data[i][2] == wordId` — provides a safety net for any legacy rows with numeric IDs.

**Sentinel row**: `word = '_LEVEL_ESTIMATE_'`, `wordId = rank` — matched on `user + word + language`, not on `wordId`. Used to persist the level-estimation high-water mark.

**`secrets.json`** (not in git): `{ "googleScriptUrl": "https://script.google.com/macros/s/.../exec" }`. If missing, Sheets sync silently disables — `GOOGLE_SCRIPT_URL` stays `""` and all fetches are skipped.

---

### Flashcard Object Shape

Created by `loadVocabularyData()`, stored in `flashcards[]`:

```js
{
  targetWord: "eres",       // display form (may use elided form from display_form)
  lemma: "ser",
  id: "0057",               // stable hex ID from vocabulary JSON
  fullId: "es10057",        // composite ID: {2-char lang}{0=normal|1=lyrics}{4-digit hex}
  rank: 57,                 // original rank from vocabulary JSON (pipeline sort order)
  corpusCount: 312,         // null for non-Bad-Bunny vocab
  isMultiMeaning: true,
  meanings: [
    {
      pos: "AUX",
      meaning: "are",       // English translation
      percentage: 0.83,     // fraction of corpus occurrences with this POS
      targetSentence: "Tu ere' una pitcher...",
      englishSentence: "You are a pitcher...",
      allExamples: [{ song, song_name, spanish, english }, ...]
    }
  ],
  translation: "are",       // meanings[0].translation (convenience copy)
  links: { wordReference: "...", ... }
}
```

---

### Artist / Lyrics Mode

Activated by `?artist=bad-bunny` (or legacy `?mode=badbunny`) in the URL. `activeArtist` is set from `artists.json`.

Key differences from normal mode:
- Vocabulary, paths, and colors loaded from `artists.json` (not hardcoded)
- Language tabs hidden; auto-selects the artist's language
- Filters out `is_english`, `is_interjection`, `is_propernoun` entries
- `hideSingleOccurrence: true` by default (hides words seen only once in corpus)
- Album artwork shown as card background (`updateArtistBackground()` in `js/artist-ui.js`)
- `corpusCount` is shown on cards (how many times word appears across discography)
- Multiple lyric examples per card (`allExamples[]` can have >1 entry); tap example to cycle
- Google Sheets tab: `'Lyrics'` (auto-renamed from old `'BadBunny'` tab)

**`artists.json`** at project root holds all artist configs. Each entry has: `name`, `language`, `dataPath`, `indexPath`, `examplesPath`, `albumsDictionary`, `albumImageMap`, `defaultAlbumArt`, `colorTheme`, `maxLevel`.

**Multi-artist mode**: Users select multiple artists via checkboxes in the settings modal. Selected slugs persist in `localStorage.selected_artists`. `mergeArtistVocabularies()` in `vocab.js` merges by hex ID — same word+lemma = same ID across artists. The merge:
- Sums `corpus_count` across selected artists
- Unions examples, tagging each with an `artist` slug
- Discards `--no-gemini` placeholder meanings (`pos=X, translation=''`) when a real Gemini analysis exists from another artist
- Sorts by combined corpus count descending

**Vocabulary file format**: Each artist must have a split-file format matching Bad Bunny's:
- `{Artist}vocabulary.json` — monolith (pipeline output)
- `{Artist}vocabulary.index.json` — lightweight metadata (meanings without examples)
- `{Artist}vocabulary.examples.json` — examples keyed by ID: `{ "ed68": { "m": [[...], ...] } }`

The monolith is the pipeline's direct output. The index + examples split is auto-generated by `run_pipeline.py` at the end of every pipeline run (via `split_vocabulary()`). The index is ~4x smaller, enabling faster front-end loading.

---

### Authentication Flow

1. `loadSecrets()` — fetches `secrets.json` to get `GOOGLE_SCRIPT_URL`
2. `checkAuthentication()` — checks `localStorage.flashcardUser`; either calls `showUserInfo()` or shows guest/login UI
3. `submitLogin(initials)` — posts to Google Sheets to look up user; on success sets `currentUser` and calls `loadUserProgressFromSheet()`
4. `enterGuestMode()` — sets `currentUser = { initials: 'GUEST', isGuest: true }`; reads localStorage progress

---

### Common Front-end Pitfalls

- **`isFlipped` ≠ card flip state**: `isFlipped` controls the *direction* (Spanish→English vs English→Spanish). The actual card flip (show front vs. back) is controlled by the `.flipped` CSS class on `#flashcard`.
- **`displayRank` vs. `rank`**: Range buttons use `displayRank` (post-filter sequential). The vocabulary JSON's `rank` field reflects pipeline sort order. Always filter with `buildFilteredVocab()` before slicing by range.
- **Step 5 DOM ID is "step4"**: The range selector div has `id="step4"` but displays as step 5. There is no `id="step3"` element — steps 3 and 4 use `lemmaToggleContainer` and `cognateToggleContainer`.
- **`initializeApp()` is guarded**: It sets up all flashcard event listeners and is idempotent via `isAppInitialized`. Only runs once per page load; safe to call multiple times.
- **Inline `onclick` in template literals**: `selectMeaning(idx)` and `cycleExample(event)` are emitted inside dynamically-built HTML strings. These must remain globally accessible if the JS is ever split into modules.
