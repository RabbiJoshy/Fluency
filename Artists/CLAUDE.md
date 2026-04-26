# Artists Pipeline — AI Reference

> **Don't bulk-read** `vocabulary_master.json`, `sense_assignments/*.json`, layer files — Grep them.
> **Deep reference**: see `docs/reference/sense_assignment_internals.md`, `docs/reference/builder_flags.md`, `docs/reference/method_priority.md`.

All scripts run from the **project root** (`Fluency/`), not from inside `Artists/`. For runnable commands and the typical run order for a new artist, see `docs/setup/artist-pipeline-quick-start.md`.

## Directory Layout

Artists live under a language subdirectory: `Artists/{lang}/{Name}/`.

```
Artists/
├── spanish/
│   ├── Bad Bunny/
│   ├── Rosalía/
│   └── Young Miko/
├── french/
│   └── TestPlaylist/            # Playlist-built French deck (keyword-only first pass)
├── curations/                   # Shared curated lists (Spanish-flavoured today)
├── tools/                       # Audit utilities
├── vocabulary_master.json       # Shared Spanish master vocab
├── vocabulary_master.json.meta.json
└── CLAUDE.md (this file)
```

The orchestrator (`run_artist_pipeline.py`) walks `Artists/*/*/artist.json` and resolves `--artist "Bad Bunny"` → `Artists/spanish/Bad Bunny/`. Names must be unique across languages.

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
| 4 | `pipeline/artist/4_filter_known_vocab.py` | `word_routing.json` | Classify words by treatment. 5 phases. schema_v2 output: `exclude.*`, `classifier.*`, `derivation_map`, `sense_discovery`, `clitic_merge`/`clitic_orphans`/`clitic_keep`. See `pipeline/CLAUDE.md` for the full schema. |
| 5 | `pipeline/artist/5_split_evidence.py` | `word_inventory.json`, `examples_raw.json` | Split evidence into inventory + examples layers. Carries `surface` field. |
| 6a | `pipeline/tool_6a_tag_example_pos.py --artist-dir ...` | `example_pos.json` | Tag examples with spaCy POS (es_dep_news_trf). Incremental. |
| 6 | `pipeline/artist/step_6a_assign_senses.py` | `sense_assignments.json` | Thin dispatcher around shared `step_6b` (keyword/biencoder) + `step_6c` (Gemini). One classifier per invocation; selected via `--classifier`. Gap-fill is independent. See `pipeline/CLAUDE.md` for the full dispatch table. |
| 6j | `pipeline/artist/judge_translations.py` | `translation_scores.json` | Judge Google Translate quality via Gemini, re-translate bad ones. Optional. |
| 7 | `pipeline/artist/7_rerank.py` | `ranking.json` | Sort order + per-example easiness scores |
| 8 | `pipeline/artist/8_fetch_lrc_timestamps.py` | `lyrics_timestamps.json` | Fetch synced lyrics from LRCLIB, match timestamps to examples |
| build | `pipeline/artist/build_artist_vocabulary.py` | `index.json`, `examples.json`, `clitic_forms.json`, monolith | Assemble all layers → front-end output. |

Cognates use a shared layer at `Data/Spanish/layers/cognates.json` — no per-artist step needed.

Shared helper: `pipeline/artist/_artist_config.py` — `add_artist_arg()`, `load_artist_config()`.

## Sense Assignment Architecture

Two files per artist:
- **`sense_menu.json`** — sense definitions from Wiktionary (en-wikt + es-wikt). The menu classifiers classify against. Built by normal-mode `build_senses.py`.
- **`sense_assignments.json`** — unified assignments from all methods. Each word keyed by bare word, each method keyed by name. Gap-fill senses inlined with `pos`/`translation`. Builder picks highest-priority method per word.

The `word_routing.json` controls which classifier runs on which words. `assign_senses.py` reads it automatically. Existing assignments are skipped by priority check — re-running is safe (zero work if already done).

Results merge additively into `senses_wiktionary.json` + `sense_assignments_wiktionary.json`. Methods coexist per word.

For method priorities, see `docs/reference/method_priority.md`.
For the dispatcher model and shared `step_6b` / `step_6c` classifiers, see `pipeline/CLAUDE.md` "Sense Assignment Model".
For deep internals (surface form normalization, orthogonal POS, keyword classifier specifics, SpanishDict cache), see `docs/reference/sense_assignment_internals.md`.

## Layer Files

All layers live in `Artists/{lang}/{Name}/data/layers/`. Schemas parallel normal mode where applicable.

| Layer | Schema | Normal-Mode Parallel |
|-------|--------|---------------------|
| `word_inventory.json` | `[{word, corpus_count, display_form, variants}]` | `word_inventory.json` |
| `examples_raw.json` | `{bare_word: [{id, spanish, title, surface?}]}` | `examples_raw.json` |
| `example_pos.json` | `{bare_word: {"idx": "POS", ...}, _example_ids: {...}}` | (none) |
| `example_translations.json` | `{spanish_text_line: {english, source}}` | (baked into examples in normal mode) |
| `senses_gemini.json` | `{word\|lemma: [{pos, translation, source}]}` (old) | `senses_wiktionary.json` |
| `senses_wiktionary.json` | `{word\|lemma: {sense_id: {pos, translation, source}}}` (new) | `senses_wiktionary.json` |
| `sense_assignments_wiktionary.json` | `{word: {method: [{sense, examples}]}}` (new) | `sense_assignments.json` |
| `sense_assignments.json` | `{word: [{sense_idx, examples, method}]}` (old) | `sense_assignments.json` (now uses unified format) |
| `sense_assignments_lemma/<source>.json` | `{word\|lemma: {method: [{sense, examples}]}}` | (none) — step 7a output |
| `unassigned_routing/<source>.json` | `{word\|lemma: [raw_example_idx, ...]}` | (none) — step 7a output |
| `translation_scores.json` | `{spanish_line: {score: 1-5}}` | (none) — consumed by builder |
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
- Migration/rebuild: `pipeline/artist/tool_8c_merge_to_master.py`
- **Spanish-only today.** Hex IDs are `md5(word|lemma)`, so cross-language collisions are possible (French "son" vs Spanish "son"). When a second language needs a master, split to `Artists/{lang}/vocabulary_master.json` and update `config/artists.json` `masterPath` per artist.

## Key Files Per Artist

```
Artists/{lang}/{Name}/
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
    vocab_evidence.json          # Step 2 output
    mwe_detected.json            # Multi-word expressions detected
  data/llm_analysis/
    curated_translations.json    # Artist-specific translation fixes (overrides shared/curated_translations.json)
    llm_progress.json            # Gemini word analysis cache (internal)
    sentence_translations.json   # Gemini sentence translation cache (internal)
  data/elision_merge/            # Step 3 output
  data/known_vocab/              # Step 4 output (skip_words.json)
  data/lrclib_cache/             # Step 9 LRCLIB response cache
```

## Shared Curations

`Artists/curations/` holds config shared across all artists:

| File | Purpose |
|------|---------|
| `elision_mapping.json` | Per-word elision merge rules. `action: merge` with `elision_pair`/`elided_only`/`same_word_dup` types routes elided forms to canonical targets. `action: skip` leaves a word unmerged. Manual overrides for non-s-elisions (e.g. `pa' → para`, `lu' → luz`) go here. |
| `multi_word_elisions.json` | Contractions that should split into multiple Spanish words at tokenization (`pal' → para el`). **Not yet wired into step 2a** — see TODO. |
| `extra_english.json` | English words (and English contractions like `goin'`, `fuckin'`) that leak into lyrics via code-switching. Step 4 uses this to route them to the `english` exclusion bucket. |
| `noise.json`, `proper_nouns.json`, `cognates.json` | Sectioned `{drop, keep}` curations used by step 4. drop = filter into the named bucket; keep = override (e.g. function words `a`/`o`/`y` in `noise.json.keep` survive the noise filter; false friends like `embarazada` in `cognates.json.keep` survive cognate exclusion). Loader: `load_curation_section()` in `util_1a_artist_config.py`. |
| `conjugation_families.json`, `curated_mwes.json`, `skip_mwes.json` | MWE and conjugation curation. |

## Other Directories

- `Artists/tools/` — audit utilities (`check_translations.py`, `split_lang_audit.py`, `scan_duplicates.py`)

## Adding a New Artist

See `docs/setup/new-artist-onboarding.md`.

## Provenance Tracking

Layer files track the method/source that produced each piece of data:
- `example_translations.json`: `source` field — `"genius"`, `"gemini"`, or `"google"`
- `sense_assignments.json`: `method` field — `"gemini"`, `"biencoder"`, or `"keyword"`
- `senses_gemini.json`: `source` field — `"gemini"` (always)
- `senses_wiktionary.json` (normal mode): `source` field — `"wiktionary"` or `"jehle"`
- `translation_scores.json`: Gemini judge scores (1-5) per sentence

For full `assignment_method` propagation rules, SENSE_CYCLE remainder behavior, surface form normalization, orthogonal POS labels, keyword classifier specifics, and SpanishDict cache coverage — see `docs/reference/sense_assignment_internals.md`.

## Pitfalls

- **Python 3.9** — do NOT use `str | None` union syntax. Use `Optional[str]` or no annotation.
- **Run from project root**, not from `Artists/` — the orchestrator handles paths.
- **Never delete curated overrides** — they serve as regression tests for pipeline quality.
- **Long-running steps** (especially step 6): print the command for Josh to run in his terminal instead of running inline.
- **Re-running a single step**: Each step writes only its own layer. Re-run it, then `--from-step build` to reassemble.
