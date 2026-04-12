# Artists Pipeline — AI Reference

All scripts run from the **project root** (`Fluency/`), not from inside `Artists/`.

## Quick Start

```bash
.venv/bin/python3 pipeline/artist/run_pipeline.py --artist "Bad Bunny"
.venv/bin/python3 pipeline/artist/run_pipeline.py --artist "Rosalia" --from-step 6 --words-only
.venv/bin/python3 pipeline/artist/run_pipeline.py --artist "Anuel" --no-gemini
.venv/bin/python3 pipeline/artist/run_pipeline.py --artist "Bad Bunny" --from-step build  # re-assemble only
```

## Architecture: Layered Pipeline

Each step produces its own **layer file** in `data/layers/`. No step mutates another step's output. The builder assembles all layers into the final front-end files.

```
Steps 2-5: Corpus processing → word_inventory.json, examples_raw.json
Step 6:    Gemini analysis    → senses_gemini.json, sense_assignments.json, example_translations.json
Step 7:    Ranking            → ranking.json
Step 8:    LRC timestamps     → lyrics_timestamps.json
Builder:   Assembly           → index.json, examples.json, monolith (debug)
```

Cognates use a shared layer (`Data/Spanish/layers/cognates.json`).

This mirrors the normal-mode pipeline (`Data/Spanish/layers/`). Same layer concepts, different data sources.

## Pipeline Steps

| Step | Script | Output Layer | What it does |
|------|--------|-------------|-------------|
| 1 | `pipeline/artist/1_download_lyrics.py` | (batches) | Scrape lyrics + English translations from Genius API (`--no-translations` to skip) |
| 1b | (manual) | `duplicate_songs.json` | Curate song exclusions — see `DEDUP_INSTRUCTIONS.md` |
| 2 | `pipeline/artist/2_count_words.py` | `vocab_evidence.json`, `mwe_detected.json` | Tokenise, count, filter excluded songs, detect MWEs |
| 2b | `pipeline/artist/2b_scrape_translations.py` | `aligned_translations.json` | Extract translations from batches + align Spanish↔English lines |
| 3 | `pipeline/artist/3_merge_elisions.py` | `vocab_evidence_merged.json` | Merge Caribbean elisions (e.g. pa' → para) |
| 4 | `pipeline/artist/4_filter_known_vocab.py` | `word_routing.json` | Classify words by treatment. 6 phases: junk → known vocab → English → Wiktionary reclassify → NER → frequency. Also detects derivations (diminutives, gerund+clitics) and clitic forms (3-tier). Output grouped by treatment: `exclude`, `biencoder`, `gemini`, `clitic_merge`/`clitic_keep`. |
| 5 | `pipeline/artist/5_split_evidence.py` | `word_inventory.json`, `examples_raw.json` | Split evidence into inventory + examples layers |
| 6 | `pipeline/artist/assign_senses.py` | `sense_assignments.json` | Unified sense assignment. Dispatches to bi-encoder (biencoder-routed) then Gemini (gemini-routed, if API key set). Gap-fill reuses existing inline senses. Single output file. |
| 6j | `pipeline/artist/judge_translations.py` | `translation_scores.json` | Judge Google Translate quality via Gemini, re-translate bad ones. Optional. |
| 7 | `pipeline/artist/7_rerank.py` | `ranking.json` | Sort order + per-example easiness scores |
| 8 | `pipeline/artist/8_fetch_lrc_timestamps.py` | `lyrics_timestamps.json` | Fetch synced lyrics from LRCLIB, match timestamps to examples |
| build | `pipeline/artist/build_artist_vocabulary.py` | `index.json`, `examples.json`, `clitic_forms.json`, monolith | Assemble all layers → front-end output. Reads word_routing for clitic merge + flags. Writes clitic layer (MWE-style). |

Cognates use a shared layer at `Data/Spanish/layers/cognates.json` — no per-artist step needed.

Shared helper: `pipeline/artist/_artist_config.py` — `add_artist_arg()`, `load_artist_config()`.

## Sense Assignment Architecture

Two files per artist:
- **`sense_menu.json`** — sense definitions from Wiktionary (en-wikt + es-wikt). The menu classifiers classify against. Built by normal-mode `build_senses.py`.
- **`sense_assignments.json`** — unified assignments from all methods. Each word keyed by bare word, each method keyed by name. Gap-fill senses inlined with `pos`/`translation`. Builder picks highest-priority method per word.

The `word_routing.json` controls which classifier runs on which words. `assign_senses.py` reads it automatically. Existing assignments are skipped by priority check — re-running is safe (zero work if already done).

Results merge additively into `senses_wiktionary.json` + `sense_assignments_wiktionary.json`. Methods coexist per word.

### Method Priority

Defined in `pipeline/method_priority.py` (re-exported by `_artist_config.py`). Higher priority = better quality. Both pipelines use this — scripts skip words with equal-or-higher priority assignments.

```
flash-lite-wiktionary: 50   (Gemini classifier)
gap-fill:             50   (Gemini gap-fill)
gemini:               40   (normal-mode Gemini classifier)
biencoder:            30
keyword-wiktionary:   10
keyword:              10
wiktionary-auto:       0   (single-sense default)
```

Translation priority (artist builder uses for example sorting):
```
gemini:  50   (LLM re-translation)
genius:  40   (fan translations)
google:  10   (raw Google Translate)
```

### Typical run order for a new artist

```bash
# Steps 2-5 (corpus processing)
.venv/bin/python3 pipeline/artist/run_pipeline.py --artist "Name" --from-step 2 --to-step 5 --skip 2b --no-gemini

# Bi-encoder on all words with Wiktionary senses (free)
.venv/bin/python3 pipeline/artist/match_artist_senses.py --artist-dir "Artists/Name"

# Gemini on remaining non-normal words (~$0.05)
.venv/bin/python3 pipeline/artist/build_wiktionary_senses.py --artist-dir "Artists/Name" --new-only

# Build final output
.venv/bin/python3 pipeline/artist/build_artist_vocabulary.py --artist-dir "Artists/Name"
```

## Layer Files

All layers live in `Artists/{Name}/data/layers/`. Schemas parallel normal mode where applicable.

| Layer | Schema | Normal-Mode Parallel |
|-------|--------|---------------------|
| `word_inventory.json` | `[{word, corpus_count, display_form, variants}]` | `word_inventory.json` |
| `examples_raw.json` | `{bare_word: [{id, spanish, title}]}` | `examples_raw.json` |
| `example_translations.json` | `{spanish_text_line: {english, source}}` | (baked into examples in normal mode) |
| `senses_gemini.json` | `{word\|lemma: [{pos, translation, source}]}` (old) | `senses_wiktionary.json` |
| `senses_wiktionary.json` | `{word\|lemma: {sense_id: {pos, translation, source}}}` (new) | `senses_wiktionary.json` |
| `sense_assignments_wiktionary.json` | `{word: {method: [{sense, examples}]}}` (new) | `sense_assignments.json` |
| `sense_assignments.json` | `{word: [{sense_idx, examples, method}]}` (old) | `sense_assignments.json` (now uses unified format) |
| `translation_scores.json` | `{spanish_line: {score: 1-5}}` | (none) — consumed by builder for example quality sorting |
| `cognates.json` | `{word\|lemma: true}` (legacy per-artist; shared layer preferred) | `cognates.json` |
| `ranking.json` | `{order: [words], easiness: {word: {m: [[scores]]}}}` | (none) |
| `lyrics_timestamps.json` | `{_meta: {...}, timestamps: {song: {line: {ms, confidence}}}}` | (none) |
| `clitic_forms.json` | `{hex_id: {id, base_verb, base_id, lemma, translation, assignments: {method: [{sense, examples}]}, examples: [...]}}` | `clitic_forms.json` |
| `archive/clitic_id_migration.json` | `{old_clitic_id: base_verb_id}` | `archive/clitic_id_migration.json` |

## Shared Master Vocabulary

**`Artists/vocabulary_master.json`** — single source of truth for word identity and senses across all artists.

- Keyed by 6-char hex ID (`md5(word|lemma)[:6]`, with suffix rehash for rare collisions)
- Each entry: `{word, lemma, senses: [{pos, translation}], flags, mwe_memberships}`
- Senses accumulate across artists — a new artist's Gemini run can discover new senses
- The **builder** handles master integration (ID assignment, sense merging, flag union)
- `--no-gemini` runs pull existing senses from the master instead of producing placeholders
- Migration/rebuild: `Artists/pipeline/artist/merge_to_master.py`

## Key Files Per Artist

```
Artists/{Name}/
  artist.json                    # {"name", "genius_query", "vocabulary_file"}
  {Name}vocabulary.json          # Monolith (debugging only, built by builder)
  {Name}vocabulary.index.json    # Compact index for front end (built by builder)
  {Name}vocabulary.examples.json # Examples keyed by ID (built by builder)
  data/layers/                   # Layer files — each step writes here
    word_inventory.json          # Step 5
    examples_raw.json            # Step 5
    example_translations.json    # Step 6
    senses_gemini.json           # Step 6
    sense_assignments.json       # Step 6
    ranking.json                 # Step 7
  data/input/
    lyrics/                      # Raw lyrics per song
    translations/aligned_translations.json  # Genius community translations (step 2b)
    duplicate_songs.json         # Songs to exclude from corpus
  data/word_counts/
    vocab_evidence.json          # Step 2 output (word counts + evidence)
    mwe_detected.json            # Multi-word expressions detected
  data/llm_analysis/
    curated_translations.json    # Artist-specific translation fixes (overrides shared/curated_translations.json)
    llm_progress.json            # Gemini word analysis cache (internal)
    sentence_translations.json   # Gemini sentence translation cache (internal)
  data/elision_merge/            # Step 3 output
  data/known_vocab/              # Step 4 output (skip_words.json)
  data/lrclib_cache/             # Step 9 LRCLIB response cache
```

## Other Directories

- `Artists/tools/` — audit utilities (`check_translations.py`, `split_lang_audit.py`, `scan_duplicates.py` — finds copied verses + reports artist line attribution via section tags)

## Modes

- **Full run**: All steps, Gemini API required. Produces complete vocabulary with POS/lemma/translations.
- **`--no-gemini`**: Skips all Gemini calls. Uses Genius translations + curated overrides only. Free. Lower quality.
- **`--words-only`**: Gemini word analysis but skips sentence translation. Cheaper.
- **`--from-step N`**: Resume from step N. `--from-step build` re-assembles without re-running analysis.

Typical cheap workflow: `--no-gemini` first, then `--words-only` to add word translations.

## Sentence Translation Sources

Step 6 checks two sources in order:
1. **Genius index** (free): Built from `aligned_translations.json`. ~40% coverage for Bad Bunny.
2. **Gemini** (expensive): Cached in `sentence_translations.json`. Only called for lines Genius doesn't cover.

The `example_translations.json` layer tracks provenance: `source: "genius"|"gemini"|"google"`.

**Cost-optimized workflow**: For new artists, use `translate_sentences_google.py` (free) for all lines, then `judge_translations.py` to score quality and re-translate only bad ones via Gemini (~15-20% of lines). Flags lines scoring <=2 by default (`--threshold` to adjust). Use `--judge-only` to inspect scores before committing to re-translation.

## Provenance Tracking

Layer files track the method/source that produced each piece of data:
- `example_translations.json`: `source` field — `"genius"`, `"gemini"`, or `"google"`
- `sense_assignments.json`: `method` field — `"gemini"`, `"biencoder"`, or `"keyword"`
- `senses_gemini.json`: `source` field — `"gemini"` (always)
- `senses_wiktionary.json` (normal mode): `source` field — `"wiktionary"` or `"jehle"`
- `translation_scores.json`: Gemini judge scores (1-5) per sentence

## Adding a New Artist

1. Create `Artists/NewArtist/artist.json` with `name`, `genius_query`, `vocabulary_file`
2. Run step 1 to download lyrics
3. Curate `duplicate_songs.json` (see `DEDUP_INSTRUCTIONS.md`)
4. Copy reusable curated data from existing artist (conjugation_families, skip_mwes, etc.)
5. Run pipeline (`--no-gemini` for free, then `--words-only` to add translations)
6. Builder auto-produces index + examples from layers
7. Add artist to `config/artists.json`
8. Shared words get translations via client-side merge — no Gemini needed for overlapping vocab

## Pitfalls

- **Python 3.9** — do NOT use `str | None` union syntax. Use `Optional[str]` or no annotation.
- **Run from project root**, not from `Artists/` — the orchestrator handles paths.
- **Never delete curated overrides** — they serve as regression tests for pipeline quality.
- **Long-running steps** (especially step 6): print the command for Josh to run in his terminal instead of running inline.
- **Re-running a single step**: Each step writes only its own layer. Re-run it, then `--from-step build` to reassemble.
