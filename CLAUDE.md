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
│   └── badbunny.js                 # Album art lookup, updateBadBunnyBackground
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
├── Bad Bunny/                      # Bad Bunny pipeline (see below)
└── .venv/                          # Python venv — activate with .venv/bin/python3
```

All pipeline scripts are run from the **project root** (`Fluency/`), not from inside subdirectories.

**Dev server:** `python3 -m http.server 8765` from the project root (configured in `.claude/launch.json`).

---

## Bad Bunny Pipeline

### Directory Layout

```
Bad Bunny/
├── 1_download_lyrics.py
├── 2_count_words.py
├── 2b_split_lang_and_junk_lingua.py   # Standalone audit tool (not part of main pipeline)
├── 3_merge_elisions.py
├── 4_add_spacy_info.py
├── 5_add_translations.py
├── 6_fill_translation_gaps.py
├── 7_dedup_same_word.py
├── 8_flag_cognates.py
├── 9_rerank.py
├── expand_examples.py                 # Optional: expand to 3 examples per POS
├── BadBunnyvocabulary.json            # Final output consumed by the app
├── bad_bunny_albums_dictionary.json   # Album metadata
├── bad_bunny_genius/                  # Raw Genius API downloads
│   └── batch_*.json
└── intermediates/
    ├── 2_vocab_evidence.json
    ├── 3_elision_mapping.json
    ├── 3_vocab_evidence_merged.json
    ├── 4_spacy_output.json
    └── old_vocabulary_cache.json      # Translation + flag cache from previous run
```

### Full Pipeline Reference

#### Step 1 — `1_download_lyrics.py`
Downloads Bad Bunny lyrics from Genius API. Run once. Produces `bad_bunny_genius/batch_*.json`.

---

#### Step 2 — `2_count_words.py`
**Input:** `bad_bunny_genius/batch_*.json`
**Output:** `intermediates/2_vocab_evidence.json`

- Custom regex tokeniser: `[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+(?:'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)*`
- Strips Genius boilerplate (section headers, "Read More", contributor lines)
- Scores lines for quality: prefers 7–16 token lines with connectors
- Max 1 example per song per word (song diversification)
- Output format per entry: `{word, corpus_count, occurrences_ppm, examples: [{id, line, title}]}`

Example IDs have the format `"songId:lineNumber"`.

---

#### Step 2b — `2b_split_lang_and_junk_lingua.py`
**Standalone audit tool — not part of the main pipeline.**
Classifies words into `_es.json`, `_en.json`, `_mixed.json`, `_junk.json`, `_noevidence.json` using Lingua line-level language detection + a token-level `ENGLISH_ONLY_WORDS` set. Useful for diagnosing what's leaking through.

---

#### Step 3 — `3_merge_elisions.py`
**Input:** `intermediates/2_vocab_evidence.json`
**Output:** `intermediates/3_vocab_evidence_merged.json`

Caribbean Spanish s-elision merging. Bad Bunny's lyrics frequently use elided forms:
- `ere'` → canonical `eres`, display_form `ere'`
- `to'` → `todo`, `pa'` → `para`

The elided form is preserved in `display_form` so the flashcard can show the lyric spelling. Corpus counts are summed across the elided and canonical forms. Elisions are only merged for the s-elision pattern; words like `pa'` (→ `para`) are in a protected exception list.

---

#### Step 4 — `4_add_spacy_info.py`
**Input:** `intermediates/3_vocab_evidence_merged.json`
**Output:** `intermediates/4_spacy_output.json`

Key responsibilities:
1. **English detection** via `wordfreq`: `en_freq / (en_freq + es_freq) >= 0.85`. Spanish diacritics always override (hard False). Words unknown to wordfreq default to not-English. Threshold is intentionally high to protect Spanish/English homographs (`solo`, `no`, `real`).
2. **spaCy lemmatisation and POS tagging**: uses `es_core_news_lg` with NER and parser disabled. Processes example lines via `nlp.pipe()`. Normalises tokens with `normalize_for_match()` before matching against the target word.
3. **Elision substitution for spaCy**: before passing lines to spaCy, replaces elided forms (e.g. `ere'`) with their canonical form so the model lemmatises correctly.
4. **Groups by lemma**: one output entry per `(word, lemma)` pair, with `pos_summary.pos_counts` and a `matches[]` list.
5. **Fallback**: if spaCy finds no token match, produces a fallback entry with `pos: "X"`.

Output entry schema (abbreviated):
```json
{
  "key": "eres|ser",
  "word": "eres",
  "lemma": "ser",
  "language_flags": {"is_english": false, "confidence": 0.99, "reason": "wordfreq_ratio"},
  "pos_summary": {"match_count": 12, "pos_counts": {"AUX": 10, "VERB": 2}},
  "matches": [{"example_id": "...", "token_text": "eres", "lemma": "ser", "pos": "AUX"}],
  "senses": [{"sense_id": "...", "example_ids": [...]}],
  "evidence": {"examples": [{...}]}
}
```

---

#### Step 5 — `5_add_translations.py`
**Input:** `intermediates/4_spacy_output.json`
**Output:** `Bad Bunny/BadBunnyvocabulary.json`

Key responsibilities:
1. **Flag merging**: combines spaCy-derived flags with curated flags from `old_vocabulary_cache.json`:
   - `is_english`: from `language_flags.is_english` OR old cache
   - `is_propernoun`: from `pos_counts["PROPN"] / total > 0.5` OR old cache
   - `is_interjection`: from `pos_counts["INTJ"] / total > 0.5` OR old cache
   - `is_transparent_cognate`: old cache only (step 8 is authoritative for this)
2. **Translation skipping**: entries flagged as `is_english`, `is_interjection`, or `is_propernoun` skip translation (for English words, `word_translation = word` itself).
3. **Meaning construction**: one meaning per POS, ordered by `pos_counts` frequency descending. Max 1 example per POS (`MAX_EXAMPLES_PER_POS = 1`).
4. **Cache mode**: `CACHE_ONLY = True` by default — all translations come from `old_vocabulary_cache.json`. No live API calls. Run step 6 to fill gaps.
5. **`most_frequent_lemma_instance`**: post-pass groups by lemma and marks the highest-frequency word form per lemma.

The `old_vocabulary_cache.json` file is the previous run's `BadBunnyvocabulary.json` renamed. It serves as both a translation cache and a curated flag store (manually set `is_propernoun`, `is_interjection`, etc. values persist across regenerations).

---

#### Step 6 — `6_fill_translation_gaps.py`
**Input/Output:** `BadBunnyvocabulary.json` (in-place)

Fills any `""` translation or example `english` fields using live Google Translate (`deep_translator`). Saves progress every 100 translations so it can be safely interrupted and restarted. Skips entries flagged as `is_english`, `is_interjection`, or `is_propernoun`.

---

#### Step 7 — `7_dedup_same_word.py`
**Input/Output:** `BadBunnyvocabulary.json` (in-place)

spaCy sometimes produces hallucinated lemmas for slang words (e.g. `loca` → lemma `locar`, which isn't a real Spanish verb). This step detects multiple entries with the same `word` but different lemmas, scores each lemma candidate for plausibility, and keeps the best one, merging the others into it.

---

#### Step 8 — `8_flag_cognates.py`
**Input/Output:** `BadBunnyvocabulary.json` (in-place); also runs on `Data/Spanish/vocabulary.json`

**This is the authoritative source for `is_transparent_cognate`.** It resets the flag to `False` for every entry before recomputing — so any value set in step 5 is overwritten.

Detection logic in `is_transparent_cognate(spanish, english)`:
1. Normalise both strings (lowercase + strip diacritics)
2. Strip common plural suffixes (`strip_plural`)
3. Exact match after normalisation
4. Suffix-swap rules (see `SUFFIX_RULES` list): e.g. `-ción → -tion`, `-oso → -ous`, `-ible → -ible`. Checks result against both `e` (original) and `e0` (de-pluraled) — important because `strip_plural` incorrectly removes the `s` from words like `"famous"`.
5. **Near-identical fallback** (`difflib.SequenceMatcher >= 0.85`): catches cases like `espectacular → spectacular`, `imposible → impossible`, `profesión → profession` (double-s mismatch) where no suffix rule applies.

The `split_english_glosses()` function handles multi-gloss translations like `"ice cream / frozen dessert"` by splitting on `/` and `,` and checking each gloss individually, which is important for words with multiple valid translations.

---

#### Step 9 — `9_rerank.py`
**Input/Output:** `BadBunnyvocabulary.json` (in-place)

Re-ranks entries after all processing. Sort key (tuple, evaluated left to right):
1. `corpus_count` descending (primary)
2. Spanish general vocabulary rank ascending (lower = more common Spanish word = more important to learn)
3. Distinct song count descending (words appearing in more songs are more generalisable)
4. Cognate status: `False` before `True` (cognates sort last — they're "free" for learners)
5. Word length ascending

Preserves the pre-rerank value in `original_rank`.

---

### Final Output Schema (`BadBunnyvocabulary.json`)

```json
{
  "rank": 57,
  "original_rank": 63,
  "word": "eres",
  "lemma": "ser",
  "display_form": "ere'",
  "meanings": [
    {
      "pos": "AUX",
      "translation": "are",
      "frequency": "0.83",
      "examples": [
        {
          "song": "5305010",
          "song_name": "A Tu Merced",
          "spanish": "Tu ere' una pitcher, pero yo estoy puesto pa' la nueva entrada",
          "english": "You are a pitcher, but I am ready for the new inning"
        }
      ]
    }
  ],
  "most_frequent_lemma_instance": true,
  "is_english": false,
  "is_interjection": false,
  "is_propernoun": false,
  "is_transparent_cognate": false,
  "corpus_count": 312
}
```

---

### Running the Pipeline

All commands from the project root (`Fluency/`):

```bash
# Step 1: Download lyrics (once only)
.venv/bin/python3 "Bad Bunny/1_download_lyrics.py"

# Step 2: Tokenise and count
.venv/bin/python3 "Bad Bunny/2_count_words.py" \
    --batch_glob "Bad Bunny/bad_bunny_genius/batch_*.json" \
    --out "Bad Bunny/intermediates/2_vocab_evidence.json"

# Steps 3–9: run sequentially
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/3_merge_elisions.py"
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/4_add_spacy_info.py"
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/5_add_translations.py"
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/6_fill_translation_gaps.py"   # slow, restartable
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/7_dedup_same_word.py"
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/8_flag_cognates.py"
PYTHONUNBUFFERED=1 .venv/bin/python3 "Bad Bunny/9_rerank.py"
```

**Partial re-runs**: if only step 4 onwards changed (e.g. English detection logic update), run steps 4 → 5 → (6 only if new translation gaps) → 7 → 8 → 9.

---

## Key Design Decisions

### Why `CACHE_ONLY = True` in step 5
Google Translate has rate limits and costs. Step 5 always runs from cache; step 6 is the only step that makes live API calls. This means step 5 is instant and idempotent regardless of vocabulary size.

### Why `old_vocabulary_cache.json` exists
Between pipeline runs, manually curated flag values (`is_propernoun`, `is_interjection`, etc.) need to survive. The cache file is just the previous run's vocabulary renamed. Step 5 loads it and merges curated flags back in. Translation strings are also cached here so step 6 doesn't re-translate already-translated words.

### Why spaCy has NER and parser disabled
The parser adds significant overhead and isn't needed (we don't use dependency trees). NER was disabled originally for speed. Re-enabling NER would improve proper noun detection but is slow — worth considering if running the pipeline overnight.

### Why the `is_english` threshold is 0.85 not 0.5
Spanish and English share many surface forms: `solo`, `no`, `real`, `me`, `come`, `pan`. A 0.5 threshold would nuke these as English. At 0.85, only words that are overwhelmingly English in corpus usage get flagged — this correctly handles reggaeton loanwords (`baby`, `shit`, `flow`, `trap`) while protecting Spanish words.

### Why cognates sort last in step 9
Transparent cognates are effectively "free" vocabulary for English speakers — they don't need to be studied in the same way. Placing them later in the deck means learners encounter genuinely new vocabulary first.

### Caribbean Spanish elisions
Puerto Rican Spanish drops final `-s` and sometimes final `-d`. Bad Bunny's lyrics are full of:
- `ere'` (eres), `to'` (todo), `pa'` (para), `na'` (nada), `ve'` (vez)
Step 3 merges these. The `display_form` field preserves the elided spelling so the flashcard shows the lyric as written, while the `word` field holds the canonical form for lemmatisation and lookup.

### Hallucinated lemmas (step 7)
`es_core_news_lg` is trained on news text. When it encounters reggaeton slang, it sometimes invents nonexistent infinitives as lemmas. Step 7 catches these by looking for multiple `(word, lemma)` entries with the same surface word and scoring which lemma is most plausible.

---

## Working with the Human

**Long-running commands:** Pipeline steps, model loading, embedding passes, and other slow processes (>30 seconds) should NOT be run inline via tool calls. Instead, print the command for Josh to run in his own terminal. This lets him see real-time progress and saves context tokens. Resume analysis after he shares the output.

---

## Dependencies

```
spacy               # NLP (lemmas, POS tags)
es_core_news_lg     # Spanish model: python -m spacy download es_core_news_lg
wordfreq            # English/Spanish frequency ratio for English detection
lingua-language-detector  # Used in 2b (audit tool)
deep_translator     # Google Translate wrapper (step 6 only)
```

Python 3.9+ required (project uses `.venv/bin/python3`).

---

## Common Pitfalls

- **Running scripts from the wrong directory**: all scripts use relative paths from `Fluency/` root. Running from inside `Bad Bunny/` will break all path references.
- **Forgetting to update the cache**: after a full pipeline run, copy `BadBunnyvocabulary.json` to `intermediates/old_vocabulary_cache.json` before the next run to preserve translations and curated flags.
- **Step 8 resets `is_transparent_cognate`**: any cognate flag set upstream is overwritten. Step 8 is always the authoritative pass; do not set `is_transparent_cognate` in earlier steps expecting it to survive.
- **`strip_plural` over-strips**: the function removes terminal `-s` from any word. English words like `"famous"`, `"serious"`, `"previous"` all lose their `s`. Step 8 accounts for this by checking suffix rule results against both the stripped and unstripped English form.
- **spaCy POS tags are noisy for slang**: `es_core_news_lg` assigns `X` (unknown) to a lot of slang, brand names, and English loanwords. The `pos_counts` in step 4 output should be treated as a signal, not ground truth.

---

## Front-end Architecture

### Overview

The front-end is vanilla JS served as static files — no build step, no framework, no bundler. `index.html` (647 lines) is HTML only; all CSS lives in `css/style.css` and all JS is split across native ES modules in `js/`.

**Two entry points:**
- `index.html` — standard vocabulary mode (Spanish, Swedish, Italian, Dutch, Polish)
- `index.html?mode=badbunny` — Bad Bunny mode (Spanish only, separate vocabulary file with song lyrics)

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

Every vocabulary JSON entry has a 4-digit zero-padded **hex** `id` field:
- **Bad Bunny vocab**: assigned by pipeline step 5 as `format(_next_id, '04x')`, keyed on `(word, lemma)`, stable across pipeline reruns via `old_vocabulary_cache.json`
- **All other vocab files** (Spanish, Swedish, Italian, Dutch, Polish): assigned as `format(rank, '04x')` — rank 1 → `"0001"`, rank 10 → `"000a"`, rank 256 → `"0100"`

At flashcard-load time, `vocab.js` builds a **composite `fullId`** for every card:

```
fullId = {2-char ISO lang code}{0=normal | 1=lyrics}{4-digit hex id}
```

| Example | Meaning |
|---|---|
| `"es00001"` | Spanish normal, rank/id 0001 |
| `"es10039"` | Spanish Bad Bunny lyrics, hex id 0039 |
| `"sv00001"` | Swedish normal, rank 1 |
| `"nl0000a"` | Dutch normal, rank 10 |

Language codes (`LANG_CODES` in `vocab.js`): `spanish→es`, `swedish→sv`, `italian→it`, `dutch→nl`, `polish→pl`, `french→fr`, `russian→ru`.

`getWordId(item)` in `vocab.js` computes the fullId from any raw vocab item (needs `selectedLanguage` and `isBadBunnyMode` from state). It is exposed on `window` so `ui.js` can call it for mastery checks.

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
| `isBadBunnyMode` | `boolean` | Computed from URL: `?mode=badbunny` |
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
2. Bad Bunny mode: remove `is_english`, `is_interjection`, `is_propernoun`
3. `excludeCognates`: remove `is_transparent_cognate`
4. `hideSingleOccurrence`: remove `corpus_count <= 1` (Bad Bunny mode only, enabled by default)
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

Two sheets: `UserProgress` (normal vocab) and `BadBunny` (lyrics mode). Selected via `sheet: isBadBunnyMode ? 'BadBunny' : 'UserProgress'` in every request.

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

### Bad Bunny Mode Differences

Activated by `?mode=badbunny` in the URL. Key differences:
- Vocabulary file: `Bad Bunny/BadBunnyvocabulary.json` (not `Data/Spanish/vocabulary.json`)
- Language tabs hidden; jumps straight to level/set selection
- Filters out `is_english`, `is_interjection`, `is_propernoun` entries
- `hideSingleOccurrence: true` by default (hides words seen only once in corpus)
- Album artwork shown as card background (`updateBadBunnyBackground()`)
- `corpusCount` is shown on cards (how many times word appears across discography)
- Multiple lyric examples per card (`allExamples[]` can have >1 entry); tap example to cycle

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
