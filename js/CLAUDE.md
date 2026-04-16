# Front-end JS — AI Reference

Vanilla JS with native ES modules. No framework, no bundler, no build step.

## Module Map

| File | Purpose | Key functions |
|------|---------|--------------|
| `main.js` | Entry point, imports all modules, registers SW | |
| `state.js` | Shared mutable state + globalThis proxy | (35+ state variables) |
| `vocab.js` | Vocabulary loading, filtering, ID generation | `buildFilteredVocab()`, `loadVocabularyData()`, `getWordId()`, `mergeArtistVocabularies()` |
| `flashcards.js` | Card rendering, flip, swipe, keyboard, init | `initializeApp()`, `updateCard()`, `flipCard()`, `nextCard()`, `handleSwipeAction()`, `selectMeaning()`, `cycleExample()` |
| `ui.js` | Setup panel: language tabs, level selector, sets | `renderLanguageTabs()`, `renderLevelSelector()`, `renderRangeSelector()` |
| `config.js` | Config loading, CEFR helpers | `loadConfig()`, `loadPpmData()` |
| `auth.js` | Login, Google Sheets sync | `submitLogin()`, `saveWordProgress()`, `loadUserProgressFromSheet()` |
| `progress.js` | Coverage bars | `calculateCoveragePercent()` |
| `estimation.js` | Level estimation — adaptive staircase | `startEstimation()`, `handleAnswer()`, `showEstimationResult()`, `revealTranslation()` |
| `speech.js` | Text-to-speech | `speakWord()` |
| `artist-ui.js` | Album art, artist backgrounds | `updateArtistBackground()` |

## Critical Architecture: globalThis Proxy

`state.js` installs a globalThis proxy for every state variable. Bare names like `flashcards`, `progressData`, `currentUser` work in every module without imports.

**NEVER** add module-level `let`/`const` for variables that exist in `state.js` — they shadow the proxy and create split-brain bugs.

## Cross-Module Function Calls

Each module exposes functions on `window` (e.g. `window.buildFilteredVocab = buildFilteredVocab`). Inline `onclick` handlers in template literals rely on this (`selectMeaning(idx)`, `cycleExample(event)`).

## Entry Points

- `index.html` — normal vocabulary mode
- `index.html?artist=bad-bunny` — artist/lyrics mode (loads from `artists.json`)
- `index.html?mode=badbunny` — legacy alias

## Key State Variables

| Variable | Type | Notes |
|---|---|---|
| `flashcards` | Array | Current deck of flashcard objects |
| `currentIndex` | number | Visible card index |
| `activeArtist` | object\|null | null = normal mode, object = artist config |
| `progressData` | object | `fullId -> { correct, wrong, lastCorrect, lastWrong, lastSeen, word, language }` |
| `selectedLanguage` | string | Key into `config.languages` |
| `isFlipped` | boolean | Flip **direction** (target->English vs English->target), NOT card flip state |

## Setup UI Flow

```
Step 1: Language tabs → Step 2: CEFR level → [inline toggles: lemma, cognate] → Step 3: Choose set
```
Note: Lemma/cognate toggles are inline containers (`lemmaToggleContainer`/`cognateToggleContainer`) between step 2 and the range selector. DOM `id="step4"` is the range/set selector (visual step 3).

## Main Call Flow

```
loadConfig() → renderLanguageTabs()
  [click language] → loadPpmData() → renderLevelSelector()
  [click level] → renderRangeSelector() → buildFilteredVocab()
  [click set] → loadVocabularyData() → buildFilteredVocab() → initializeApp() → updateCard()
  [interaction] → flipCard() / nextCard() / handleSwipeAction() → saveWordProgress()
```

## buildFilteredVocab() — Central Filter

Filter order: blank/dupe removal → artist flags (is_english, is_interjection, is_propernoun) → cognates → single-occurrence → lemma mode.

Assigns `displayRank` (1-based, continuous). Range buttons use `displayRank`, NOT the JSON's `rank`.

## Flashcard Object Shape

```js
{ targetWord, lemma, id, fullId, rank, corpusCount, isMultiMeaning, meanings: [{ pos, meaning, percentage, targetSentence, englishSentence, allExamples }], translation, links }
```

## Artist / Lyrics Mode Differences

- Vocab, paths, colors from `artists.json` (not hardcoded)
- Language tabs hidden, auto-selects artist's language
- Filters: is_english, is_interjection, is_propernoun removed
- hideSingleOccurrence: true by default
- Album artwork backgrounds (`updateArtistBackground()` in `artist-ui.js`)
- Multiple lyric examples per card; tap to cycle
- Google Sheets tab: `'Lyrics'`

## Artist Index Format + joinWithMaster()

Artist vocab files use a master-aligned split format. `joinWithMaster()` in `vocab.js` detects this via `sense_frequencies` on the first index entry and reconstructs full entries from the master vocab + per-artist statistics.

Per-sense flags set by `joinWithMaster()`:
- `meaning.assignment_method` — set if `idx.sense_methods[i]` is non-null (keyword/weak assignment). Used for sense pill display.
- `meaning.unassigned = true` — set if `sense_methods[i]` is null **and** `idx.unassigned` is true (random bucket, no real assignment).
- Neither flag — strong/auto assignment; meaning gets a border.

**Per-example assignment method**: Each example object in the examples file carries its own `assignment_method` (e.g. `"spanishdict-keyword"`). This is the authoritative source for per-example UI decisions:
- **Example box border** (`flashcards.js`): `example.assignment_method` present → solid accent border. For strong methods (Gemini/biencoder) without per-example stamps, falls back to `!meaning.unassigned`.
- **English keyword highlight**: Only fires when `example.assignment_method` includes `'keyword'`. Highlights translation fragments ≥ 2 chars of `currentMeaning.meaning` in the English sentence.
- **Sense row border**: `!m.unassigned` → solid accent border on selected row.

**Copy-through in `buildFilteredVocab()`**: Meanings are rebuilt from scratch at the filter stage (two places, ~line 430 and ~line 776). Both paths must copy `assignment_method` through, otherwise it is silently dropped before it reaches the card. `joinWithMaster()` in `vocab.js` sets `assignment_method` from `idx.sense_methods[i]`; `buildFilteredVocab()` must preserve it.

**`currentExample` scope**: `updateCard()` in `flashcards.js` uses a hoisted `currentExample` variable (set when `activeExamples.length > 0`) for per-example decisions like the English highlight and example-box border. These references live outside the `if (activeExamples.length > 0)` block, so they must not reference the inner `example` const directly.

## Cache-busting for ES Modules

`index.html` imports `js/main.js?v=YYYYMMDDx`. `main.js` imports `./flashcards.js?v=YYYYMMDDx` and `./vocab.js?v=YYYYMMDDx`. Bump every `v=…` tag whenever any JS module changes substantively — the ES module cache survives page reloads and service-worker resets, so only a URL change forces browsers to re-import. All three version tags should stay in sync.

## Multi-Artist Merge

`mergeArtistVocabularies()` in `vocab.js`: merges by hex ID, sums corpus_count, unions examples (tagged with `artist` slug), discards `--no-gemini` placeholders when Gemini analysis exists. After merge, recalculates meaning `frequency` from example counts (not stale Gemini line assignments).

Album art in multi-artist mode: `artist-ui.js` stores per-artist default art in `artistDefaultArt` map. `updateArtistBackground()` reads the example's `artist` slug to pick the correct fallback image.

## Pitfalls

- `isFlipped` is direction, not card flip state (CSS `.flipped` class controls that)
- `displayRank` vs `rank` — always filter before slicing by range
- `initializeApp()` is idempotent via `isAppInitialized` guard
- Inline `onclick` in templates — functions must stay on `window`
