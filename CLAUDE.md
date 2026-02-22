# Fluency — Technical Reference for AI Assistants

This document describes the full architecture, pipeline logic, data schemas, and design decisions for the Fluency project. Read this before touching any code.

---

## Project Overview

Fluency is a browser-based vocabulary flashcard PWA. The front-end (`index.html`, `service-worker.js`, `manifest.json`) is vanilla JS with no framework. All vocabulary data is static JSON — there is no backend.

The interesting part is the **data pipeline** that generates the vocabulary JSON, particularly the Bad Bunny pipeline which processes song lyrics using NLP to produce a Spanish vocabulary deck.

---

## Repository Layout

```
Fluency/
├── index.html                      # Entire front-end application
├── config.json                     # Language config and file path mappings
├── manifest.json / service-worker.js  # PWA support
├── cefr_levels.json                # CEFR level metadata
├── Data/
│   └── Spanish/
│       └── vocabulary.json         # General Spanish frequency vocabulary (used by 9_rerank.py)
├── Bad Bunny/                      # Bad Bunny pipeline (see below)
└── .venv/                          # Python venv — activate with .venv/bin/python3
```

All pipeline scripts are run from the **project root** (`Fluency/`), not from inside subdirectories.

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
