# Pipeline Notes

> **Don't bulk-read** layer files in `Data/Spanish/layers/` or `Artists/{lang}/{Name}/data/layers/` — Grep them.
> **Deep reference**: `docs/reference/builder_flags.md`, `docs/reference/sense_assignment_internals.md`, `docs/reference/method_priority.md`.

This folder uses a phase-based naming scheme shared across normal mode and artist mode.

## Naming

- `step_<phase><letter>_*.py` — Active pipeline steps that an orchestrator can call directly.
- `tool_<phase><letter>_*.py` — Optional/manual scripts tied to a phase.
- `util_<phase><letter>_*.py` — Helper modules mostly supporting a phase.
- `legacy_<phase><letter>_*.py` — Deprecated scripts kept for reference.
- `bench_*` — Evaluation and diagnostics.

## Shared Phases

1. `Acquire`
2. `Extract`
3. `Normalize`
4. `Route`
5. `Build Menus`
6. `Build Assignments`
7. `Consolidate`
8. `Assemble`

The important distinction is:

- Phase 5 builds candidate structures like inventories, examples, sense menus, and MWEs.
- Phase 6 assigns evidence to those menus.
- Lemma consolidation happens after assignment, not before it.

## Practical Rule

If a script is part of the main pipeline, prefer making it a `step_*`. If it is optional or experimental, keep it as `tool_*`. Do not add new unnumbered pipeline scripts in this folder.

## Normal Mode

Entry point: `run_normal_pipeline.py`

Current main steps:

- `step_2a_build_inventory.py`
- `step_5a_build_examples.py`
- `step_5b_build_conjugations.py`
- `step_5c_build_senses.py`
- `step_5d_build_mwes.py`
- `step_6a_assign_senses.py` (thin dispatcher; calls shared `step_6b` + `step_6c`)
- `step_6b_assign_senses_local.py` (shared; bi-encoder / keyword classifier)
- `step_6c_assign_senses_gemini.py` (shared; Gemini Flash Lite classifier + gap-fill)
- `step_7a_map_senses_to_lemmas.py`
- `step_7c_flag_cognates.py`
- `step_8a_assemble_vocabulary.py`

Supporting tools/utils:

- `tool_5c_enrich_sense_menu_metadata.py`
- `tool_6a_classify_senses.py`
- `tool_6a_refine_pos.py`
- `tool_6a_tag_example_pos.py`
- `legacy_6a_assign_senses.py` (pre-split monolithic normal-mode classifier, kept for reference)
- `util_4a_routing.py` (shared clitic + derivation helpers; used by both 4a scripts)
- `util_5c_sense_menu_format.py` (shared analysis/sense-menu helpers; used by both modes)
- `util_6a_method_priority.py`
- `util_6a_pos_menu_filter.py`

## Artist Mode

Entry point: `artist/run_artist_pipeline.py`

Current main steps:

- `artist/step_1a_download_lyrics.py`
- `artist/step_1b_scrape_translations.py`
- `artist/step_2a_count_words.py`
- `artist/step_3a_merge_elisions.py`
- `artist/step_4a_filter_known_vocab.py`
- `artist/step_5a_split_evidence.py`
- `artist/step_6a_assign_senses.py` (thin dispatcher; calls shared `step_6b` + `step_6c`)
- `artist/step_7a_map_senses_to_lemmas.py`
- `artist/step_7b_rerank.py`
- `artist/step_8a_fetch_lrc_timestamps.py`
- `artist/step_8b_assemble_artist_vocabulary.py`

Shared step 6 classifiers (live in `pipeline/`, called by both normal and artist dispatchers):

- `step_6b_assign_senses_local.py` (bi-encoder / keyword; `--artist-dir` optional)
- `step_6c_assign_senses_gemini.py` (Gemini Flash Lite + gap-fill; `--artist-dir` optional)

SpanishDict sidecar:

- `step_5c_build_senses.py --sense-source spanishdict [--artist-dir PATH]` (shared; replaces old artist tool)
- `artist/tool_6b_assign_spanishdict_senses.py`

Key artist helpers:

- `artist/util_1a_artist_config.py`
- `util_5c_sense_menu_format.py` (shared; used by both modes)

## Sense Assignment Model (step 6)

Normal mode and artist mode both use the same dispatcher model. **One classifier runs per invocation; gap-fill is independent.**

Flags on `step_6a_assign_senses.py` (normal) and `artist/step_6a_assign_senses.py`:

- `--classifier {keyword, biencoder, gemini}` — required
- `--gap-fill / --no-gap-fill` — default: on for gemini, off for keyword/biencoder
- `--sense-source {wiktionary, spanishdict}` — default spanishdict (SpanishDict is the primary source for Spanish; wiktionary stays supported for future non-Spanish languages)
- `--max-examples N` — per-word example cap sent to Gemini (default 10)
- `--force` — re-classify everything
- `--gemini-model MODEL` — default gemini-2.5-flash-lite

Old combinations map cleanly:

- `--keyword-only --no-gemini` → `--classifier keyword`
- `--no-gemini` → `--classifier biencoder`
- `--all-gemini` → `--classifier gemini`

### What runs for each classifier

| classifier | gap-fill | step_6b runs | step_6c runs |
|---|---|---|---|
| keyword | off (default) | yes (keyword mode) | no |
| keyword | on | yes (keyword) | yes, `--skip-classification` |
| biencoder | off (default) | yes (bi-encoder) | no |
| biencoder | on | yes (bi-encoder) | yes, `--skip-classification` |
| gemini | on (default) | no | yes (full: classification + gap-fill) |
| gemini | off | no | yes, `--skip-gap-fill` |

### Step_6b routing

`step_6b_assign_senses_local.py` reads `word_routing.json` for `exclude.*` and `clitic_merge` only. The `biencoder` / `gemini` sub-buckets are metadata — the chosen classifier processes every non-excluded, non-clitic-merge word.

### Step_6c filters

`step_6c_assign_senses_gemini.py`:
- Skips `word_routing.exclude.*` entries.
- Skips `clitic_merge` entries (unless `--include-clitics`).
- Skips words containing apostrophes (they're elision forms merged by step 3).
- Does NOT skip by length — core function words (de, no, y, en, me, lo) get Gemini classification too.
- `--skip-classification` and `--skip-gap-fill` let the dispatcher pick which half runs.

### Example-level incrementality

`step_6c` tracks coverage per `(word, method)` so `--max-examples N` runs incrementally: re-running with a larger N only sends new indices to Gemini. `--force` wipes prior entries for the current method and re-classifies.

## Assignment File Format (step 6 output)

On-disk at `sense_assignments/{source}.json` and `sense_assignments_lemma/{source}.json`:

```json
{
  "word": {
    "method-name": [
      {"sense": "abc", "examples": [0, 1, 5]},
      {"sense": "def", "examples": [2, 3]}
    ],
    "another-method": [...]
  }
}
```

Method is the dict key, not a per-item field. Items only carry `sense` + `examples` (and inline sense fields for gap-fill discoveries). Multiple methods coexist per word; the builder's `resolve_best_per_example` picks the highest-priority `(method, sense)` claim per example at build time.

`load_assignments` in `util_6a_assignment_format.py` auto-detects the new dict form AND the legacy flat-list form, so old files still read cleanly. `dump_assignments` writes the new form.

## Builder Flags (step 8)

`step_8a_assemble_vocabulary.py` (normal) and `artist/step_8b_assemble_artist_vocabulary.py` share two orthogonal flags:

- `--remainders` — emit SENSE_CYCLE remainder buckets for unassigned examples. Default: off.
- `--min-priority N` — drop assignments whose method priority is below N. Auto-assignments (`*-auto`) are exempt.

Defaults are language-specific (Spanish: 50). Full detail — including combined behavior, meaning dedup, context disambiguation, and step_7a routing rules — in `docs/reference/builder_flags.md`.
