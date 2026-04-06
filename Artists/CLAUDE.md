# Artists Pipeline — AI Reference

All scripts run from the **project root** (`Fluency/`), not from inside `Artists/`.

## Quick Start

```bash
.venv/bin/python3 Artists/run_pipeline.py --artist "Bad Bunny"
.venv/bin/python3 Artists/run_pipeline.py --artist "Rosalia" --from-step 6 --words-only
.venv/bin/python3 Artists/run_pipeline.py --artist "Anuel" --no-gemini
.venv/bin/python3 Artists/run_pipeline.py --artist "Bad Bunny" --from-step build  # re-assemble only
```

## Architecture: Layered Pipeline

Each step produces its own **layer file** in `data/layers/`. No step mutates another step's output. The builder assembles all layers into the final front-end files.

```
Steps 3-5b: Corpus processing → word_inventory.json, examples_raw.json
Step 6:     Gemini analysis    → senses_gemini.json, sense_assignments.json, example_translations.json
Step 7:     Cognate detection  → cognates.json
Step 8:     Ranking            → ranking.json
Builder:    Assembly           → index.json, examples.json, monolith (debug)
```

This mirrors the normal-mode pipeline (`Data/Spanish/layers/`). Same layer concepts, different data sources.

## Pipeline Steps

| Step | Script | Output Layer | What it does |
|------|--------|-------------|-------------|
| 1 | `scripts/1_download_lyrics.py` | (batches) | Scrape lyrics from Genius API |
| 1b | (manual) | `duplicate_songs.json` | Curate song exclusions — see `DEDUP_INSTRUCTIONS.md` |
| 3 | `scripts/3_count_words.py` | `vocab_evidence.json`, `mwe_detected.json` | Tokenise, count, filter excluded songs, detect MWEs |
| 3b | `scripts/3b_scrape_translations.py` | `aligned_translations.json` | Scrape Genius community English translations |
| 4 | `scripts/4_detect_proper_nouns.py` | `detected_proper_nouns.json` | Detect proper nouns, interjections, English (local) |
| 5 | `scripts/5_merge_elisions.py` | `vocab_evidence_merged.json` | Merge Caribbean elisions (e.g. pa' → para) |
| 5b | `scripts/5b_split_evidence.py` | `word_inventory.json`, `examples_raw.json` | Split evidence into inventory + examples layers |
| 6 | `scripts/6_llm_analyze.py` | `senses_gemini.json`, `sense_assignments.json`, `example_translations.json` | Gemini: POS, lemma, translation, sense disambiguation |
| 7 | `scripts/7_flag_cognates.py` | `cognates.json` | Flag transparent cognates (intersection: LLM + suffix rules) |
| 8 | `scripts/8_rerank.py` | `ranking.json` | Sort order + per-example easiness scores |
| build | `scripts/build_artist_vocabulary.py` | `index.json`, `examples.json`, monolith | Assemble all layers → front-end output |

Shared helper: `scripts/_artist_config.py` — `add_artist_arg()`, `load_artist_config()`.

## Layer Files

All layers live in `Artists/{Name}/data/layers/`. Schemas parallel normal mode where applicable.

| Layer | Schema | Normal-Mode Parallel |
|-------|--------|---------------------|
| `word_inventory.json` | `[{word, corpus_count, display_form, variants}]` | `word_inventory.json` |
| `examples_raw.json` | `{word: [{id, spanish, title}]}` | `examples_raw.json` |
| `example_translations.json` | `{spanish_line: {english, source}}` | (baked into examples in normal mode) |
| `senses_gemini.json` | `{word\|lemma: [{pos, translation}]}` | `senses_wiktionary.json` |
| `sense_assignments.json` | `{word: [{sense_idx, examples: [0,1,2]}]}` | `sense_assignments.json` |
| `cognates.json` | `{word\|lemma: true}` | (planned) |
| `ranking.json` | `{order: [words], easiness: {word: {m: [[scores]]}}}` | (planned) |

## Shared Master Vocabulary

**`Artists/vocabulary_master.json`** — single source of truth for word identity and senses across all artists.

- Keyed by 6-char hex ID (`md5(word|lemma)[:6]`, with suffix rehash for rare collisions)
- Each entry: `{word, lemma, senses: [{pos, translation}], flags, mwe_memberships}`
- Senses accumulate across artists — a new artist's Gemini run can discover new senses
- The **builder** handles master integration (ID assignment, sense merging, flag union)
- `--no-gemini` runs pull existing senses from the master instead of producing placeholders
- Migration/rebuild: `Artists/scripts/merge_to_master.py`

## Key Files Per Artist

```
Artists/{Name}/
  artist.json                    # {"name", "genius_query", "vocabulary_file"}
  {Name}vocabulary.json          # Monolith (debugging only, built by builder)
  {Name}vocabulary.index.json    # Compact index for front end (built by builder)
  {Name}vocabulary.examples.json # Examples keyed by ID (built by builder)
  data/layers/                   # Layer files — each step writes here
    word_inventory.json          # Step 5b
    examples_raw.json            # Step 5b
    example_translations.json    # Step 6
    senses_gemini.json           # Step 6
    sense_assignments.json       # Step 6
    cognates.json                # Step 7
    ranking.json                 # Step 8
  data/input/
    lyrics/                      # Raw lyrics per song
    translations/translations.json  # Genius community translations
    duplicate_songs.json         # Songs to exclude from corpus
  data/word_counts/
    vocab_evidence.json          # Step 3 output (word counts + evidence)
    mwe_detected.json            # Multi-word expressions detected
  data/llm_analysis/
    curated_translations.json    # Manual translation fixes (NEVER delete these)
    llm_progress.json            # Gemini word analysis cache (internal)
    sentence_translations.json   # Gemini sentence translation cache (internal)
  data/elision_merge/            # Step 5 output
  data/proper_nouns/             # Step 4 output
```

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

The `example_translations.json` layer tracks provenance: `source: "genius"|"gemini"`.

## Adding a New Artist

1. Create `Artists/NewArtist/artist.json` with `name`, `genius_query`, `vocabulary_file`
2. Run step 1 to download lyrics
3. Curate `duplicate_songs.json` (see `DEDUP_INSTRUCTIONS.md`)
4. Copy reusable curated data from existing artist (conjugation_families, skip_mwes, etc.)
5. Run pipeline (`--no-gemini` for free, then `--words-only` to add translations)
6. Builder auto-produces index + examples from layers
7. Add artist to `artists.json` at project root
8. Shared words get translations via client-side merge — no Gemini needed for overlapping vocab

## Pitfalls

- **Python 3.9** — do NOT use `str | None` union syntax. Use `Optional[str]` or no annotation.
- **Run from project root**, not from `Artists/` — the orchestrator handles paths.
- **Never delete curated overrides** — they serve as regression tests for pipeline quality.
- **Long-running steps** (especially step 6): print the command for Josh to run in his terminal instead of running inline.
- **Re-running a single step**: Each step writes only its own layer. Re-run it, then `--from-step build` to reassemble.
