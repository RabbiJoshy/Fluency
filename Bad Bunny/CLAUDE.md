# Bad Bunny Pipeline — Technical Reference

This file documents the pipeline internals for AI assistants. For a human-readable overview, see `README.md`.

All scripts are run from the **project root** (`Fluency/`), not from inside `Bad Bunny/`. The virtual environment is at `.venv/bin/python3`.

---

## Directory layout

```
Bad Bunny/
├── Pipeline scripts (run in order)
│   ├── 1_download_lyrics.py          # Scrape Genius API
│   ├── 1b_rescrape_nulls.py          # Re-scrape failed songs
│   ├── 2_count_words.py              # Tokenise, count, extract examples
│   ├── 2c_detect_proper_nouns.py     # Gemini proper noun detection
│   ├── 2d_detect_mwes.py             # Multi-word expression detection
│   ├── 3_merge_elisions.py           # Caribbean s-elision merging
│   ├── 4_llm_analyze.py              # Gemini: POS, lemma, translations
│   ├── 8_flag_cognates.py            # Transparent cognate flagging
│   └── 9_rerank.py                   # Frequency-based reranking
│
├── Supporting tools (not in main pipeline)
│   ├── run_pipeline.py               # Orchestrator with --from-step/--to-step
│   ├── check_translations.py         # Translation quality audit
│   ├── dedup_songs.py                # Duplicate song detection
│   └── 2b_split_lang_and_junk_lingua.py  # Language classification audit
│
├── Data files
│   ├── BadBunnyvocabulary.json       # Final output (consumed by app)
│   ├── bad_bunny_albums_dictionary.json  # Album metadata for UI
│   └── duplicate_songs.json          # Duplicate song mappings (curated)
│
├── bad_bunny_genius/                 # Raw Genius API downloads
│   ├── batch_001_page_1.json ... batch_023_page_23.json
│   └── done_song_ids.json           # Progress tracker
│
├── intermediates/                    # Pipeline intermediate outputs
│   ├── 2_vocab_evidence.json         # Step 2 output
│   ├── 2c_detected_proper_nouns.json # Step 2c output
│   ├── 2c_propn_progress.json        # Step 2c Gemini progress
│   ├── 2d_mwe_detected.json          # Step 2d output
│   ├── 3_elision_mapping.json        # Elision merge log
│   ├── 3_vocab_evidence_merged.json  # Step 3 output
│   ├── 4_llm_progress.json           # Step 4 Gemini progress
│   └── 4_sentence_translations.json  # Step 4 sentence cache
│
├── Images/                           # Album cover art (11 albums)
├── archive/                          # Old pipeline versions (spaCy/Wiktionary era)
├── Makefile                          # OUTDATED — use run_pipeline.py instead
└── BadBunnyvocabulary_old.json       # Previous pipeline output (can be deleted)
```

---

## Pipeline step details

### Step 1 — `1_download_lyrics.py`

Scrapes all Bad Bunny songs from Genius API using `lyricsgenius`.

- Uses `genius.lyrics(song_id)` for reliable scraping by known ID
- `--include-remixes` drops the variant filter
- `--retry-nulls` re-queues songs that previously got null lyrics
- Output: `bad_bunny_genius/batch_NNN_page_N.json`
- Progress tracked in `done_song_ids.json` (skips already-scraped songs)
- Song record: `{id, title, artist, url, lyrics}`

**`1b_rescrape_nulls.py`** is a targeted version that finds null-lyrics songs in existing batches and re-scrapes them in-place. Supports `--skip-variants`, `--add-ids`, `--dry-run`.

### Step 2 — `2_count_words.py`

Tokenises all lyrics and counts word frequencies across the entire corpus.

- **Tokeniser**: `[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+(?:'[…]+)*'?` — letters with optional internal apostrophes
- **Genius cleaning**: strips editorial descriptions (after "Lyrics" marker), "Read More" blurbs, section headers `[Chorus]`, Cyrillic homoglyph obfuscation, footer markers
- **English line filter**: Uses `lingua` language detector (confidence >= 0.70, min 4 tokens)
- **Example selection**: max 1 example per song per word, scored by line quality (7-16 tokens preferred, connector words bonus), global song diversification
- **`corpus_count`**: counts every token occurrence from every line of every song (not just example lines)
- Output: `{word, corpus_count, examples: [{id: "songId:lineNo", line, title}]}`

### Step 2c — `2c_detect_proper_nouns.py`

Uses Gemini to classify words as proper nouns. Batches of 50 words per API call.

- `NOT_PROPER_NOUNS` frozenset (~80 entries): common Spanish words that look like proper nouns (alto, real, mercedes, mami, baby, etc.)
- `KNOWN_PROPER_NOUNS` frozenset: always-proper words
- `--refilter` flag: re-applies filters to cached results without API calls
- Progress saved in `intermediates/2c_propn_progress.json`
- Output: `intermediates/2c_detected_proper_nouns.json`

### Step 2d — `2d_detect_mwes.py`

Detects multi-word expressions from bigram/trigram frequency.

- `CURATED_MWES` dict (~100 expressions with translations): manually verified expressions like "pa' que", "de verdad", "lo que sea"
- `SKIP_MWES` frozenset: literal article+noun phrases excluded (la noche, el mundo, etc.)
- `CONJUGATION_FAMILIES` dict: maps conjugated forms to canonical family (voy a/va a/vas a -> "ir a"), keeps only highest-frequency member
- Auto-detected candidates above frequency threshold listed separately for manual review
- Thresholds: bigrams >= 20, trigrams >= 12
- Output: `intermediates/2d_mwe_detected.json` with `{mwes: [...], candidates: [...]}`

### Step 3 — `3_merge_elisions.py`

Merges Caribbean Spanish elided forms into canonical words.

- Pattern: final -s dropped and marked with apostrophe (`ere'` -> `eres`)
- `display_form` preserves the elided spelling for the flashcard UI
- Corpus counts are summed across elided + canonical forms
- Protected exceptions for words like `pa'` (-> `para`) that aren't s-elision
- Output: `intermediates/3_vocab_evidence_merged.json`

### Step 4 — `4_llm_analyze.py`

The main analysis step. Uses Gemini to determine POS, lemma, word translation, and sentence translations.

**Key responsibilities:**
1. **Word analysis**: POS tag, lemma, English translation for each word
2. **Sentence translation**: translates Spanish example lines to English
3. **Flag merging**: combines LLM results with curated flags from prior runs
4. **Interjection auto-detection**: regex patterns catch onomatopoeia (brr, skrt, jaja, etc.) without LLM cost
5. **MWE annotation**: loads `2d_mwe_detected.json`, builds reverse index word -> [mwe], annotates entries with `mwe_memberships`
6. **Proper noun integration**: loads `2c_detected_proper_nouns.json` to flag proper nouns

**Progress tracking:**
- `intermediates/4_llm_progress.json`: word-level analysis progress
- `intermediates/4_sentence_translations.json`: sentence translation cache
- Both are incremental — safe to interrupt and restart

**Flags set by this step:**
- `is_english`: from LLM analysis
- `is_propernoun`: from step 2c output or LLM
- `is_interjection`: from regex auto-detection or LLM
- `mwe_memberships`: from step 2d output (list of `{expression, translation}`)

**Requires**: `--api-key GEMINI_KEY` (or `GEMINI_API_KEY` env var)

### Step 8 — `8_flag_cognates.py`

**Authoritative source for `is_transparent_cognate`**. Resets the flag to `False` for every entry before recomputing.

Detection logic:
1. Normalise (lowercase + strip diacritics)
2. Strip common plural suffixes
3. Exact match after normalisation
4. Suffix-swap rules: `-ción` -> `-tion`, `-oso` -> `-ous`, `-ible` -> `-ible`, etc.
5. Near-identical fallback: `difflib.SequenceMatcher >= 0.85`

Also runs on `Data/Spanish/vocabulary.json` (general Spanish vocab).

### Step 9 — `9_rerank.py`

Sort key (tuple, left to right):
1. `corpus_count` descending (primary)
2. Spanish general vocabulary rank ascending (cross-references `Data/Spanish/vocabulary.json`)
3. Distinct song count descending
4. Cognate status: non-cognate before cognate
5. Word length ascending

Strips any leftover `rank`/`original_rank` fields — array position IS the rank.

---

## Output schema (`BadBunnyvocabulary.json`)

```json
{
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
  "mwe_memberships": [
    {"expression": "tú ere'", "translation": "you are (elided)"}
  ]
}
```

**Word IDs**: Each entry gets a stable 4-digit hex `id` field (e.g. `"0039"`), keyed on `(word, lemma)`, preserved across pipeline reruns via the progress cache. The front-end builds a composite `fullId` as `es1{id}` (e.g. `"es10039"`) for progress tracking.

---

## Orchestrator (`run_pipeline.py`)

```bash
# Full pipeline
.venv/bin/python3 "Bad Bunny/run_pipeline.py" --api-key KEY

# Partial run
.venv/bin/python3 "Bad Bunny/run_pipeline.py" --api-key KEY --from-step 4

# Skip steps
.venv/bin/python3 "Bad Bunny/run_pipeline.py" --api-key KEY --skip 2c 2d

# Dry run (show plan)
.venv/bin/python3 "Bad Bunny/run_pipeline.py" --dry-run

# Reset progress for LLM steps
.venv/bin/python3 "Bad Bunny/run_pipeline.py" --api-key KEY --from-step 4 --reset
```

Steps defined: 2 -> 2c -> 2d -> 3 -> 4 -> 8 -> 9. File freshness checking warns if outputs are older than inputs.

---

## Supporting tools

### `check_translations.py`
Audits `BadBunnyvocabulary.json` for translation quality issues:
1. Empty word translations
2. Empty sentence translations
3. Content word mismatches (translation doesn't appear in any example sentence)
4. Sentence coherence issues (likely hallucinations)

Uses `SKIP_MISMATCH_CHECK` to avoid false positives on function words and polysemous verbs. Supports `--output` for JSON export, `--verbose` for full details.

### `dedup_songs.py`
Detects duplicate songs by normalising titles (strips remix/live/mixed/version tags). Writes `duplicate_songs.json` with human-readable mappings. Prefers the version with the most lyrics content. Supports `--dry-run`.

### `2b_split_lang_and_junk_lingua.py`
Standalone audit tool (not part of main pipeline). Classifies words into `_es.json`, `_en.json`, `_mixed.json`, `_junk.json` using lingua line-level language detection. Useful for diagnosing what English/junk words are leaking through.

---

## Key design decisions

### Why Gemini instead of spaCy + Wiktionary
The original pipeline (archived in `archive/`) used spaCy for lemmatisation and Wiktionary dumps for translations. This produced many errors: hallucinated lemmas for slang, wrong sense selection, no contextual disambiguation. Gemini handles all of this in one pass with much better quality, especially for Caribbean Spanish slang and code-switching.

### Why `corpus_count` counts all occurrences, not just examples
`corpus_count` reflects how often a word actually appears across the entire discography (every token from every line of every song). Example lines are a curated subset. This gives accurate frequency data for ranking even when only 1-3 example lines are kept per word.

### Why cognates sort last
Transparent cognates (especial/special) are "free" for English speakers — they don't need flashcard study. Placing them later means learners encounter genuinely new vocabulary first.

### Why interjection detection is regex-based
Regex catches ~50 onomatopoeia (brr, skrt, jaja, prr, etc.) for free, no API cost. The patterns are: single repeated character (aaa), triple letter (brr), and specific Caribbean/reggaeton interjection patterns. An `_INTERJECTION_EXCEPTIONS` set protects real words that match patterns (bro, bo, ye).

### Progress files and restartability
Steps 2c and 4 save progress after each API batch. Safe to Ctrl+C and restart — they pick up where they left off. The `--reset` flag clears progress to force a full re-run.

---

## Common pitfalls

- **Running from wrong directory**: all scripts use relative paths from `Fluency/` root. Running from inside `Bad Bunny/` breaks all path references.
- **Step 8 resets `is_transparent_cognate`**: any value set by step 4 is overwritten. Step 8 is always authoritative.
- **Makefile is outdated**: references old spaCy-based steps (4_add_spacy_info, 5_add_translations, etc.) that no longer exist in the main pipeline. Use `run_pipeline.py` instead.
- **`archive/` is dead code**: contains the old spaCy/Wiktionary pipeline. Safe to delete but kept for reference.
- **`BadBunnyvocabulary_old.json` is a leftover**: previous pipeline output kept as backup. Can be deleted once you're confident in the current output.
- **Long-running steps**: Step 4 (Gemini analysis) takes 30-60+ minutes. Print the command for the user to run in their terminal so they see real-time progress.

---

## Batch file format (`bad_bunny_genius/batch_*.json`)

Each batch is a JSON array of song records:

```json
{
  "id": 3627151,
  "title": "I Like It",
  "artist": "Bad Bunny",
  "url": "https://genius.com/...",
  "lyrics": "279 ContributorsTranslations...I Like It Lyrics..."
}
```

Raw lyrics include Genius boilerplate (contributor counts, editorial descriptions, "Read More" blurbs). Step 2's `clean_genius_lyrics()` strips all of this. The `id` field is the Genius song ID, used throughout the pipeline as the primary song identifier.

---

## Intermediate file formats

### `2_vocab_evidence.json`
```json
[{"word": "que", "corpus_count": 6710, "examples": [{"id": "11292773:8", "line": "...", "title": "..."}]}]
```

### `2d_mwe_detected.json`
```json
{"mwes": [{"expression": "pa' que", "translation": "so that", "count": 134}], "candidates": [...]}
```

### `3_vocab_evidence_merged.json`
Same schema as step 2 output but with elided forms merged. Entries may have `display_form` if the surface form differs from canonical `word`.

### `4_llm_progress.json`
Incremental cache of Gemini word analysis results. Keyed by word. Do not edit manually.
