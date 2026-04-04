# Front-end JS — AI Reference

Vanilla JS with native ES modules. No framework, no bundler, no build step.

## Module Map

| File | Purpose | Key functions |
|------|---------|--------------|
| `main.js` | Entry point, imports all modules, registers SW | `initializeApp()` |
| `state.js` | Shared mutable state + globalThis proxy | (35+ state variables) |
| `vocab.js` | Vocabulary loading, filtering, ID generation | `buildFilteredVocab()`, `loadVocabularyData()`, `getWordId()`, `mergeArtistVocabularies()` |
| `flashcards.js` | Card rendering, flip, swipe, keyboard | `updateCard()`, `flipCard()`, `nextCard()`, `handleSwipeAction()`, `selectMeaning()`, `cycleExample()` |
| `ui.js` | Setup panel: language tabs, level selector, sets | `renderLanguageTabs()`, `renderLevelSelector()`, `renderRangeSelector()` |
| `config.js` | Config loading, CEFR helpers | `loadConfig()`, `loadPpmData()` |
| `auth.js` | Login, Google Sheets sync | `submitLogin()`, `saveWordProgress()`, `loadUserProgressFromSheet()` |
| `progress.js` | Coverage bars | `calculateCoveragePercent()` |
| `estimation.js` | Level-estimation quiz flow | |
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
| `isBadBunnyMode` | boolean | Getter: `!!activeArtist`. Do not set directly. |
| `progressData` | object | `fullId -> { correct, wrong, lastCorrect, lastWrong, lastSeen, word, language }` |
| `selectedLanguage` | string | Key into `config.languages` |
| `isFlipped` | boolean | Flip **direction** (target->English vs English->target), NOT card flip state |

## Setup UI Flow

```
Step 1: Language tabs → Step 2: CEFR level → Step 3: Lemma toggle → Step 4: Cognate toggle → Step 5: Choose set
```
Note: DOM `id="step4"` renders as visual step 5. Steps 3/4 use `lemmaToggleContainer`/`cognateToggleContainer`.

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

## Multi-Artist Merge

`mergeArtistVocabularies()` in `vocab.js`: merges by hex ID, sums corpus_count, unions examples (tagged with `artist` slug), discards `--no-gemini` placeholders when Gemini analysis exists.

## Pitfalls

- `isFlipped` is direction, not card flip state (CSS `.flipped` class controls that)
- `displayRank` vs `rank` — always filter before slicing by range
- `initializeApp()` is idempotent via `isAppInitialized` guard
- Inline `onclick` in templates — functions must stay on `window`
