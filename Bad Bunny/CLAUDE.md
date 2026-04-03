# Bad Bunny Pipeline — Technical Reference

This file documents the pipeline internals for AI assistants. For a human-readable overview, see `README.md`.

All scripts are run from the **project root** (`Fluency/`), not from inside `Bad Bunny/`. The virtual environment is at `.venv/bin/python3`.

---

## Directory layout

```
Bad Bunny/
├── run_pipeline.py                     # Orchestrator (--from-step, --to-step, --skip)
├── BadBunnyvocabulary.json             # Final output (consumed by app)
├── bad_bunny_albums_dictionary.json    # Album metadata for UI
│
├── scripts/                            # Pipeline step scripts (numbered 1-8)
│   ├── 1_download_lyrics.py            # Scrape Genius API
│   ├── 2_rescrape_nulls.py             # Re-scrape failed songs
│   ├── 3_count_words.py                # Tokenise, count, extract examples, detect MWEs
│   ├── 4_detect_proper_nouns.py        # Gemini proper noun detection
│   ├── 5_merge_elisions.py             # Caribbean s-elision merging
│   ├── 6_llm_analyze.py               # Gemini: POS, lemma, translations
│   ├── 7_flag_cognates.py             # Transparent cognate flagging
│   └── 8_rerank.py                    # Frequency-based reranking + MWE annotation
│
├── data/
│   ├── input/                          # Corpus input data
│   │   ├── batches/                    # Raw Genius API downloads
│   │   │   ├── batch_001_page_1.json ... batch_023_page_23.json
│   │   │   └── done_song_ids.json
│   │   ├── duplicate_songs.json        # Duplicate/non-Spanish song exclusions (curated)
│   │   └── DEDUP_INSTRUCTIONS.md       # How to maintain duplicate_songs.json (on request only)
│   │
│   ├── word_counts/                    # Step 3 outputs + curated data
│   │   ├── vocab_evidence.json         # Word counts + examples
│   │   ├── mwe_detected.json           # MWE detection output
│   │   ├── curated_mwes.json           # Manually verified expressions + translations
│   │   ├── skip_mwes.json              # Literal phrases to exclude (la noche, etc.)
│   │   └── conjugation_families.json   # Maps conjugated forms to canonical family
│   │
│   ├── proper_nouns/                   # Step 4 outputs + curated data
│   │   ├── detected_proper_nouns.json  # Gemini output
│   │   ├── propn_progress.json         # Gemini progress tracker
│   │   ├── known_proper_nouns.json     # Always-proper words
│   │   └── not_proper_nouns.json       # Words protected from false positives
│   │
│   ├── elision_merge/                  # Step 5 outputs
│   │   ├── elision_mapping.json        # Elision merge log
│   │   └── vocab_evidence_merged.json  # Step 5 output
│   │
│   └── llm_analysis/                   # Step 6 outputs + curated data
│       ├── llm_progress.json           # Gemini word analysis progress
│       ├── sentence_translations.json  # Gemini sentence cache
│       ├── curated_translations.json   # Manual translation overrides
│       ├── proper_nouns.json           # Artist/brand/place names
│       ├── interjections.json          # Onomatopoeia (brr, skrt, etc.)
│       └── extra_english.json          # English words common in reggaeton
│
├── tools/                              # Supporting tools (not in pipeline)
│   ├── check_translations.py           # Translation quality audit
│   └── split_lang_audit.py            # Language classification audit
│
├── Images/                             # Album cover art (11 albums)
└── archive/                            # Old spaCy/Wiktionary pipeline (dead code)
```

---

## Pipeline steps

### Step 1 — `scripts/1_download_lyrics.py`

Scrapes all Bad Bunny songs from Genius API using `lyricsgenius`.

- Uses `genius.lyrics(song_id)` for reliable scraping by known ID
- Output: `data/input/batches/batch_NNN_page_N.json`
- Progress tracked in `data/input/batches/done_song_ids.json`

### Step 2 — `scripts/2_rescrape_nulls.py`

Re-scrapes songs that previously got null lyrics. Supports `--skip-variants`, `--add-ids`, `--dry-run`.

**Song deduplication & exclusion**: `data/input/duplicate_songs.json` lists duplicates, placeholders, and non-Spanish songs to exclude. This file is maintained manually — only update it when Josh explicitly requests a dedup pass. See [`data/input/DEDUP_INSTRUCTIONS.md`](data/input/DEDUP_INSTRUCTIONS.md) for the full logic.

### Step 3 — `scripts/3_count_words.py`

Tokenises all lyrics, counts word frequencies, selects example sentences, and detects multi-word expressions.

- **Tokeniser**: `[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+(?:'[…]+)*'?`
- **Genius cleaning**: strips editorial descriptions, section headers, footer markers, Spanish placeholder lyrics ("letra completa")
- **English line filter**: Uses `lingua` language detector (confidence >= 0.70, min 4 tokens)
- **Example selection**: max 1 example per song per word, scored by line quality, global song diversification
- **MWE detection**: counts n-grams (2-5) within phrase boundaries in the same pass as word counting. Two sources:
  - **Curated**: `data/word_counts/curated_mwes.json` — manually verified expressions with translations
  - **PMI-detected**: high pointwise mutual information expressions, filtered by min song spread (≥3 songs), no translations
- **Outputs**: `data/word_counts/vocab_evidence.json` + `data/word_counts/mwe_detected.json`

### Step 4 — `scripts/4_detect_proper_nouns.py`

Uses Gemini to classify words as proper nouns. Batches of 50 words per API call.

- Curated data in `data/proper_nouns/`: `known_proper_nouns.json`, `not_proper_nouns.json`
- Progress saved in `data/proper_nouns/propn_progress.json`
- **Requires**: `--api-key` (or `GEMINI_API_KEY` env var)

### Step 5 — `scripts/5_merge_elisions.py`

Merges Caribbean Spanish elided forms into canonical words. `display_form` preserves the elided spelling.

- Output: `data/elision_merge/vocab_evidence_merged.json`

### Step 6 — `scripts/6_llm_analyze.py`

Main Gemini analysis step: POS, lemma, word translation, sentence translation.

- Curated data in `data/llm_analysis/`: `curated_translations.json`, `proper_nouns.json`, `interjections.json`, `extra_english.json`
- Progress in `data/llm_analysis/`: `llm_progress.json`, `sentence_translations.json`
- Loads MWE data from `data/word_counts/mwe_detected.json` to annotate `mwe_memberships`
- **Requires**: `--api-key` (or `GEMINI_API_KEY` env var)

### Step 7 — `scripts/7_flag_cognates.py`

**Authoritative source for `is_transparent_cognate`**. Resets and recomputes using suffix-swap rules + near-identical matching.

### Step 8 — `scripts/8_rerank.py`

Sorts by corpus_count (desc) with tiebreakers: Spanish vocab rank, song count, cognate status, word length. Also **re-annotates `mwe_memberships`** from the latest step 3 MWE output, ensuring MWEs stay current even when step 6 is skipped.

---

## Orchestrator (`run_pipeline.py`)

```bash
# Full pipeline (steps 3-8)
.venv/bin/python3 "Bad Bunny/run_pipeline.py" --api-key KEY

# Partial run
.venv/bin/python3 "Bad Bunny/run_pipeline.py" --from-step 6

# Skip slow Gemini steps
.venv/bin/python3 "Bad Bunny/run_pipeline.py" --from-step 3 --skip 4 6

# Dry run
.venv/bin/python3 "Bad Bunny/run_pipeline.py" --dry-run
```

Steps 1-2 (Genius scraping) are manual and not registered in the orchestrator. The orchestrator runs steps 3 → 4 → 5 → 6 → 7 → 8.

API key is read from `.env` (`GEMINI_API_KEY=...`) or `--api-key` flag.

---

## Curated data files

Each step's curated data lives alongside its intermediates in its named folder:

| File | Step | Format | Purpose |
|------|------|--------|---------|
| File | Folder | Format | Purpose |
|------|--------|--------|---------|
| `curated_mwes.json` | `word_counts/` | `{"expr": "translation"}` | Verified MWE expressions + translations |
| `skip_mwes.json` | `word_counts/` | `["expr", ...]` | Literal article+noun phrases to exclude |
| `conjugation_families.json` | `word_counts/` | `{"expr": "family"}` | Maps conjugated forms to canonical family |
| `known_proper_nouns.json` | `proper_nouns/` | `["word", ...]` | Always-proper words |
| `not_proper_nouns.json` | `proper_nouns/` | `["word", ...]` | Protected from false positive proper noun detection |
| `curated_translations.json` | `llm_analysis/` | `{"word": "translation"}` | Manual overrides that always win over LLM |
| `proper_nouns.json` | `llm_analysis/` | `["word", ...]` | Artist/brand/place names |
| `interjections.json` | `llm_analysis/` | `["word", ...]` | Onomatopoeia |
| `extra_english.json` | `llm_analysis/` | `["word", ...]` | English words common in reggaeton |

---

## Output schema (`BadBunnyvocabulary.json`)

```json
{
  "id": "0039",
  "word": "eres",
  "lemma": "ser",
  "display_form": "ere'",
  "corpus_count": 312,
  "meanings": [
    {
      "pos": "AUX",
      "translation": "are",
      "frequency": "0.83",
      "examples": [
        {
          "song": "5305010",
          "song_name": "A Tu Merced",
          "spanish": "Tu ere' una pitcher...",
          "english": "You are a pitcher..."
        }
      ]
    }
  ],
  "most_frequent_lemma_instance": true,
  "is_english": false,
  "is_interjection": false,
  "is_propernoun": false,
  "is_transparent_cognate": false,
  "mwe_memberships": [
    {"expression": "tú ere'", "translation": "you are (elided)"},
    {"expression": "real hasta la muerte", "translation": ""}
  ]
}
```

MWE memberships with empty `translation` are PMI-detected (no human translation yet). The front-end shows them with just the expression and a matched lyric example.

---

## Common pitfalls

- **Running from wrong directory**: all scripts use relative paths from `Fluency/` root
- **Step 7 resets `is_transparent_cognate`**: any value set by step 6 is overwritten
- **Step 8 re-annotates MWE memberships**: always uses latest `data/word_counts/mwe_detected.json`
- **Long-running steps**: Steps 4 and 6 (Gemini) take 30-60+ minutes. Print the command for the user to run in their terminal
- **archive/ is dead code**: old spaCy/Wiktionary pipeline, safe to ignore
