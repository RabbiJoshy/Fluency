# Front-end JS — AI Reference

> **Don't bulk-read** large source files (`flashcards.js`, `vocab.js`) — use Grep + Read with offset for the function you need.

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
| `progress.js` | Card progress state + coverage bars | `getProgressState()`, `calculateCoveragePercent()` |
| `knowledge.js` | Sparse per-sense/expression knowledge layered over card progress | `getKnowledgeItemState()`, `buildFocusedReviewCard()`, `saveKnowledgeProgress()` |
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
| `progressData` | object | `fullId -> { correct, wrong, lastCorrect, lastWrong, lastSeen, srsStage, word, language }` |
| `itemProgressData` | object | Sparse `itemId ->` explicit sense/expression/clitic answers; whole-card progress remains the inherited baseline |
| `selectedLanguage` | string | Key into `config.languages` |
| `isFlipped` | boolean | Flip **direction** (target->English vs English->target), NOT card flip state |

## Setup UI Flow

```
Step 1: Radial language picker → Step 2: numbered level → [inline toggles: lemma, cognate] → Step 3: learn first stable set with unseen cards or review the level
```
The standard-mode language button opens the shared radial picker in `main.js`.
Hidden `.lang-tab` buttons remain as internal action targets so the existing
language loading/theme/progress handler in `ui.js` stays canonical.
After selection, `mergeStandardProgressIntoLanguageStep()` moves the personal
coverage wrapper into the step-1 header beside the language pill; artist mode
keeps the standalone coverage card.
Note: Lemma/cognate toggles are inline containers (`lemmaToggleContainer`/`cognateToggleContainer`) between step 2 and the set progress panel. DOM `id="step4"` is the automatic next-set panel (visual step 3).

## Main Call Flow

```
loadConfig() → renderLanguageTabs()
  [click language] → loadPpmData() → renderLevelSelector()
  [click level] → renderRangeSelector() → buildFilteredVocab() → auto-select first set with unseen cards
  [start set] → loadVocabularyData() → buildFilteredVocab() → initializeApp() → updateCard()
  [whole-card interaction] → flipCard() / nextCard() / handleSwipeAction() → saveWordProgress()
  [row knowledge action] → markCurrentKnowledge() → saveKnowledgeProgress()
```

## Progress and granular knowledge

`progressData` stores the word/card history. `getProgressState()` is the canonical
backward-compatible interpretation, including legacy count-only rows. Review
contains incorrect, partial, and due cards from the selected level; Learn new
contains only unseen cards. Due cards remain `known` for vocabulary coverage but
are not `learned`/current, so their set segment turns amber.

SRS v1 persists `srsStage` and uses intervals of 1, 3, 7, 14, 30, 60, and 120
days. A correct answer advances one stage and a wrong answer resets to zero.
Legacy rows without a stage derive a conservative initial stage from their counts;
undated legacy correct rows remain current rather than becoming instantly due.
The review queue is intentionally level- and current-source/configuration-scoped.

`itemProgressData` is deliberately sparse: it stores a row only after the learner
explicitly marks an individual sense, Expression, or clitic form. For an item,
`knowledge.js` merges the parent card record and item record and lets the newest
timestamp win. Thus a later whole-card correct resolves older item mistakes, while
a later item mistake reopens only that row. A partial card remains in Review and
its focused card includes explicit mistakes plus never-marked sibling items, while
known items stay hidden. Explicitly knowing every item promotes the parent card to
Known. The selected level's review deck is synthesized from unresolved rows;
ordinary learning cards remain word/lemma cards.

Knowledge IDs are `${parentFullId}~k1:<type>:<hash>`. The hash prefers the durable
pipeline `sense_id`/`id` now retained by both standard meanings and the artist
master. Legacy master-only senses receive deterministic `generated:artist-master:`
IDs; source IDs supersede generated IDs without dropping the old alias. The
front end still recognises pre-migration normalized POS + translation + context
IDs and stored `sense_id_aliases`, then writes the canonical ID on the learner's
next row answer. Preserve canonical IDs/aliases in future deck-schema work.

Google Apps Script schema v3 adds `SrsStage` and `LastSeen` as columns 9–10 of
`UserProgress`/`Lyrics`, plus `SrsStage` as column 13 of `ItemProgress`. Existing
sheets add these headers automatically on the first v3 request without rewriting
old rows. Copy `backend/GoogleAppsScript.js` and deploy a new Apps Script version
whenever this persistence contract changes.

## buildFilteredVocab() — Central Filter

Filter order: blank/dupe removal → artist flags (is_english, is_noise/is_interjection, is_propernoun) → cognates → single-occurrence → lemma mode.

Note: `is_noise` is the schema_v2 flag name; `is_interjection` is the legacy alias kept for vocabularies built before the rename. Both fields carry identical truth values — read either, the filter checks both.

`assignStableVocabularyRanks()` assigns `stableRank` before optional filters,
using corpus frequency plus source rank as a deterministic tie-breaker. Smart
levels and their fixed 20-position sets slice on `stableRank`; exclusions leave
holes instead of pulling later cards forward. In lemma mode the surviving card
is anchored to the best-ranked surface form in its lemma family. `displayRank`
remains the active-configuration rank shown on cards, while JSON `rank` remains
the source identity/tie-breaker and legacy CEFR basis.

## Flashcard Object Shape

```js
{ targetWord, lemma, id, fullId, rank, corpusCount, isMultiMeaning, meanings: [{ pos, meaning, percentage, targetSentence, englishSentence, allExamples }], translation, links }
```

## Artist / Lyrics Mode Differences

- Vocab, paths, colors from `artists.json` (not hardcoded)
- Language tabs hidden, auto-selects artist's language
- Filters: is_english, is_noise (alias is_interjection), is_propernoun removed
- Two exclusive vocabulary scopes: Main (`lemma_example_count > 1`) and Extra
  (`lemma_example_count <= 1`). Scope is lemma-based even when Merge Lemmas is
  off, so a 1x surface form in a recurring lemma remains in Main.
- Artist example splits may carry `r` (the unclassified one-off artist lyric)
  and `p` (compact shared Speech senses/examples). Extra uses these without a
  Gemini rerun and admits a lyric-only `EXAMPLE_ONLY` card when no translation
  exists. The old hide-single-occurrence toggle is retained only in legacy
  saved-session state and is not an artist-deck filter.
- Album artwork backgrounds (`updateArtistBackground()` in `artist-ui.js`)
- Multiple lyric examples per card; tap to cycle
- Google Sheets tab: `'Lyrics'`; sparse item overrides for both modes live in the
  shared `'ItemProgress'` tab and remain mode-separated through the parent fullId.

## Artist Index Format + joinWithMaster()

Artist vocab files use a master-aligned split format. `joinWithMaster()` in `vocab.js` detects this via `sense_frequencies` on the first index entry and reconstructs full entries from the master vocab + per-artist statistics.

Per-sense flags set by `joinWithMaster()`:
- `meaning.assignment_method` — set if `idx.sense_methods[i]` is non-null (keyword/weak assignment). Used for sense pill display.
- `meaning.unassigned = true` — set if `sense_methods[i]` is null **and** `idx.unassigned` is true (random bucket, no real assignment).
- Neither flag — strong/auto assignment; meaning gets a border.

**Per-example assignment method**: Each example object in the examples file carries its own `assignment_method` (e.g. `"spanishdict-keyword"`). This is the authoritative source for per-example UI decisions:
- **Example match treatment** (`flashcards.js`): `example.assignment_method` present → POS-coloured rail/tint. For strong methods (Gemini/biencoder) without per-example stamps, falls back to `!meaning.unassigned`.
- **English keyword highlight**: Only fires when `example.assignment_method` includes `'keyword'`. Highlights translation fragments ≥ 2 chars of `currentMeaning.meaning` in the English sentence.
- **Sense selection treatment**: every row gets a subtle POS-coloured tint; the selected row gets a stronger tint, left rail, border, and elevation. Match assignment remains available for linking the selected sense to its example, but is not labelled with a redundant chip.

**Artist expressions**: expressions remain pinned rows on the relevant word card;
they are not a separate ordinary card type. Step 2a pools the forms named in
`Artists/curations/conjugation_families.json` onto the union of distinct
`(song_id, normalized lyric line)` evidence. The artist index carries `family`,
`variants`, `variant_counts`, `count` (that unique-line union), `occurrence_count`
(raw diagnostic hits), `num_songs`, and exact examples with `matched_variant`
plus the original lyric `matched_surface`.
`joinWithMaster()` must preserve these fields. `updateCard()` keeps the familiar
representative expression label but filters and highlights against every observed
variant, including inconsistently spaced apostrophe elisions such as `vo' a` /
`vo'a`. High-signal `[PRON]` templates are supported; broad fragments ending at
the pronoun slot are rejected upstream.

The completed deterministic second pass is configured by
`Artists/curations/construction_templates.json`. Step 2a uses the shared
`conjugation_reverse.json` morphology to recognise inflected verb prefixes and
requires the configured complement shape: e.g. `ir + a` counts only when an
actual infinitive follows, including dropped-r lyric spellings such as `caga'`.
It also subtracts those longer hits from genuinely different standalone rows
such as `me voy`. Only translated curated/construction expressions and PMI
collocations with an exact existing dictionary translation reach assembly.
Untranslated PMI and `[PRON]` discoveries remain in `mwe_detected.json` as
diagnostics; step 8b never turns them into card rows or pads exact artist
evidence with looser fallback matches. Do not auto-promote the full dictionary
phrase list merely because its words are adjacent (`qué va` inside
`qué va a pasar` demonstrates why).

Card-back senses are grouped into POS sections. `updateCard()` emits one compact
`.back-pos-legend` beneath the word/lemma, then colour-codes each section's rows;
duplicate translation/context groups remain constrained to one POS. MWE and
CLITIC stay out of the legend because their pinned rows are self-explanatory.
The initial selection for a collapsed translation/context group is the
overarching group, not its first sub-sense; an explicit sub-row click pins that
narrower sense for the rest of the card visit.

Desktop lyric autoplay builds one card-wide queue of ordinary senses,
sub-senses, Expressions, clitics, and remainder senses. It speaks each English
gloss plus disambiguating context, then plays that item's eligible line-bounded
Spotify examples. Non-playable lyrics are skipped but `currentExampleIndex`
remains an index into the complete displayed list, so counters stay `6/8` rather
than becoming `6/6`. The control has a fallback slot when the active item has no
renderable sentence; mobile remains unsupported because exact stop boundaries
cannot be guaranteed after Spotify handoff.

On the card front, `.card-pos-list` renders one pill per grammatical POS rather
than a comma-separated combined pill. Morphology is nested under the VERB pill
as `.front-morph-tag` elements in the same colour family. In example sentences,
`.example-word-highlight` uses the active POS colour at low intensity for the
headword / `used with` companion; `.example-related-highlight` is quieter for
other study-set words and keyword-matched English fragments.

**Copy-through in `buildFilteredVocab()`**: Meanings are rebuilt from scratch at the filter stage (two places, ~line 430 and ~line 776). Both paths must copy `assignment_method` through, otherwise it is silently dropped before it reaches the card. `joinWithMaster()` in `vocab.js` sets `assignment_method` from `idx.sense_methods[i]`; `buildFilteredVocab()` must preserve it.

**`currentExample` scope**: `updateCard()` in `flashcards.js` uses a hoisted `currentExample` variable (set when `activeExamples.length > 0`) for per-example decisions like the English highlight and example-box border. These references live outside the `if (activeExamples.length > 0)` block, so they must not reference the inner `example` const directly.

## Cache-busting for ES Modules

The ES module cache keys by resolved URL and survives page reloads, service-worker resets, and even hard refreshes — only a URL change forces a re-import. So every entry-point import in `main.js` carries a `?v=YYYYMMDDx` query string, and `index.html`'s `js/main.js?v=…` reference matches. **Bump every `?v=` tag in lockstep whenever any module changes substantively** — even modules that look "minor" like `state.js`, `auth.js`, or `speech.js`. Missing the bump on a module that gained a new export (or new `window.x = …` assignment) means consumers run against the stale version and the new symbol is silently undefined.

Module-to-module imports inside `js/` (e.g. `flashcards.js` importing `./speech.js`) currently have no `?v=` tag. They share the same cache slot regardless of `main.js`'s version, so they only re-import when the browser's HTTP cache decides to. If you hit a "looks cached even after reload" bug, hard-refresh; if it persists, that import is the suspect — add a `?v=` tag matching `main.js`.

## Multi-Artist Merge

`mergeArtistVocabularies()` in `vocab.js`: merges by hex ID, sums corpus_count, unions examples (tagged with `artist` slug), discards `--no-gemini` placeholders when Gemini analysis exists. Master-format senses merge by `_masterSenseIndex` (never compact array position); after merge it deduplicates examples, recalculates meaning `frequency`, and stamps one combined-corpus `most_frequent_lemma_instance` per lemma.

In lemma mode, `lemma_total_count` is the raw pooled token diagnostic, while
`lemma_example_count` / `pooled_frequency` count the unique example lines that
`poolLemmaSiblingExamples()` actually attaches. The card front uses the latter.

Album art in multi-artist mode: `artist-ui.js` stores per-artist default art in `artistDefaultArt` map. `updateArtistBackground()` reads the example's `artist` slug to pick the correct fallback image.

## Pitfalls

- `isFlipped` is direction, not card flip state (CSS `.flipped` class controls that)
- `displayRank` vs `rank` — always filter before slicing by range
- `initializeApp()` is idempotent via `isAppInitialized` guard
- Inline `onclick` in templates — functions must stay on `window`
