# Pipeline Notes

This folder now uses a phase-based naming scheme shared across normal mode and artist mode.

## Naming

- `step_<phase><letter>_*.py`
  Active pipeline steps that an orchestrator can call directly.
- `tool_<phase><letter>_*.py`
  Optional/manual scripts tied to a phase.
- `util_<phase><letter>_*.py`
  Helper modules mostly supporting a phase.
- `legacy_<phase><letter>_*.py`
  Deprecated scripts kept for reference.
- `bench_*`
  Evaluation and diagnostics.

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
- Lemma consolidation should happen after assignment, not before it.

## Normal Mode

Entry point:

- `run_normal_pipeline.py`

Current main steps:

- `step_2a_build_inventory.py`
- `step_5a_build_examples.py`
- `step_5b_build_conjugations.py`
- `step_5c_build_senses.py`
- `step_5d_build_mwes.py`
- `step_6a_assign_senses.py`
- `step_7a_map_senses_to_lemmas.py`
- `step_7b_flag_cognates.py`
- `step_8a_assemble_vocabulary.py`

Supporting tools/utils:

- `tool_5c_enrich_sense_menu_metadata.py`
- `tool_6a_classify_senses.py`
- `tool_6a_refine_pos.py`
- `tool_6a_tag_example_pos.py`
- `util_6a_method_priority.py`
- `util_6a_pos_menu_filter.py`

## Artist Mode

Entry point:

- `artist/run_artist_pipeline.py`

Current main steps:

- `artist/step_1a_download_lyrics.py`
- `artist/step_1b_scrape_translations.py`
- `artist/step_2a_count_words.py`
- `artist/step_3a_merge_elisions.py`
- `artist/step_4a_filter_known_vocab.py`
- `artist/step_5a_split_evidence.py`
- `artist/step_6a_assign_senses.py`
- `artist/step_7a_map_senses_to_lemmas.py`
- `artist/step_7b_rerank.py`
- `artist/step_8a_fetch_lrc_timestamps.py`
- `artist/step_8b_assemble_artist_vocabulary.py`

SpanishDict sidecar:

- `artist/tool_5c_build_spanishdict_menu.py`
- `artist/tool_6b_assign_spanishdict_senses.py`

Key artist helpers:

- `artist/util_1a_artist_config.py`
- `artist/util_5c_sense_menu_format.py`

## Practical Rule

If a script is part of the main pipeline, prefer making it a `step_*`.
If it is optional or experimental, keep it as `tool_*`.
Do not add new unnumbered pipeline scripts in this folder.
