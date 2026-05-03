# Layers — AI Reference

> **Don't bulk-read** layer files — most are 100 KB to 10 MB. Grep them by `word|lemma` or hex ID.

Intermediate data layers produced by pipeline steps. Each layer captures one aspect of vocabulary analysis. The final `step_8a_assemble_vocabulary.py` step joins layers into `vocabulary.json`.

**Critical run-order dependency**: `step_8a` reads `sense_assignments_lemma/` — the lemma-keyed version produced by `step_7a`. Whenever step_6 (sense assignment) is run or re-run, `step_7a_map_senses_to_lemmas.py` must run before `step_8a`. Same applies to artist mode (`step_8b` reads from the artist's `sense_assignments_lemma/`).

## Design Principle: Provenance

**Always add new layers rather than overwriting existing ones.** When trying a new method (e.g. a different cognate detection approach), create a new layer file (e.g. `cognates_experimental.json`) alongside the existing one. This preserves provenance so Josh can compare methods and validate which works best. The build script chooses which layers to consume — unused layers stay in the directory as references.

This also applies to the artist pipeline layers in `Artists/{lang}/{Name}/data/layers/`.

## Layer Files (Normal Mode)

| File | Key format | Value | Producer |
|------|-----------|-------|----------|
| `word_inventory.json` | Array of objects | `{word, lemma, id, corpus_count, most_frequent_lemma_instance, homograph_ratio?}` | `step_2a_build_inventory.py` |
| `examples_raw.json` | word | `[{id, target, english, source, easiness}]` — corpus examples; `id` is 12-char SHA-256 of `(target, english)` | `step_5a_build_examples.py` |
| `example_store.json` | 12-char content-hash ID | `{target, english, source, easiness}` — append-only; examples survive step_5a rebuilds | `step_5a_build_examples.py` |
| `conjugations.json` | infinitive | Full conjugation table `{translation, gerund, past_participle, moods: {...}}` | `step_5b_build_conjugations.py` |
| `conjugation_reverse.json` | conjugated form | List of `{lemma, mood, tense, person}` | `step_5b_build_conjugations.py` |
| `senses_spanishdict.json` | `word\|lemma` | List of `{pos, translation, context?, detail?, source}` | `step_5c_build_senses.py` |
| `senses_wiktionary.json` | `word\|lemma` | List of `{pos, translation, detail?}` | `step_5c_build_senses.py` |
| `mwe_phrases.json` | hex ID | List of `{expression, translation, source, corpus_freq?, count?}` | `step_5d_build_mwes.py` |
| `sense_assignments/spanishdict.json` | `word` or `word\|lemma` | `{method: [{sense, examples: [int], example_ids: [str]}]}` | `step_6b/6c_assign_senses_*.py` |
| `sense_assignments/wiktionary.json` | same | same | same |
| `sense_assignments_lemma/spanishdict.json` | `word\|lemma` | same format — **this is what step_8a reads** | `step_7a_map_senses_to_lemmas.py` |
| `sense_assignments_lemma/wiktionary.json` | same | same | `step_7a_map_senses_to_lemmas.py` |
| `cognates.json` | `word\|lemma` | `{score: float, cognet: bool, gemini?: bool}` | `step_7c_flag_cognates.py` |
| `homograph_overrides.json` | surface form | `{lemma: ratio}` pairs summing to 1.0 | Manual |

## Artist Pipeline Layers

Artist layers live at `Artists/{lang}/{Name}/data/layers/` and follow the same pattern:

| File | Key format | Value | Producer |
|------|-----------|-------|----------|
| `word_inventory.json` | Array | Same as normal mode | `step_2a_count_words.py` |
| `word_routing.json` | top-level buckets | `{exclude.*, classifier.*, sense_discovery, clitic_merge, ...}` — routes each word to the right classifier | `step_4a_filter_known_vocab.py` |
| `examples_raw.json` | bare word | `[{id, spanish, title, surface}]` — lyric examples; `id` is content-hash | `step_5a_split_evidence.py` |
| `example_translations.json` | Spanish text line | `{english, source}` — English translation cache | `step_6a_assign_senses.py` (via step_6c) |
| `senses_spanishdict.json` | `word\|lemma` | List of `{pos, translation, context?, detail?}` | `step_5c_build_senses.py --artist-dir` |
| `senses_wiktionary.json` | `word\|lemma` | same | `step_5c_build_senses.py --artist-dir` |
| `sense_assignments/spanishdict.json` | `word` or `word\|lemma` | `{method: [{sense, examples: [int], example_ids: [str]}]}` | `step_6a_assign_senses.py` |
| `sense_assignments_lemma/spanishdict.json` | `word\|lemma` | same — **step_8b reads this** | `artist/step_7a_map_senses_to_lemmas.py` |
| `ranking.json` | top-level | `{order: [words], easiness: {word: {m: [[scores]]}}}` | `step_7b_rerank.py` |
| `lyrics_timestamps.json` | top-level | `{_meta: {...}, timestamps: {song: {line: {ms, confidence}}}}` | `step_8a_fetch_lrc_timestamps.py` |

## How Layers Are Consumed

`step_8a_assemble_vocabulary.py` (normal) and `step_8b_assemble_artist_vocabulary.py` (artist) join layers by key (`word|lemma` or hex ID) to produce the final `vocabulary.json` / artist vocab files. Not all layers are required — missing layers are skipped gracefully.

**step_8a reads `sense_assignments_lemma/` as its primary assignments source**, falling back to `sense_assignments/` only if the lemma version doesn't exist. Always run `step_7a_map_senses_to_lemmas.py` after any step_6 run and before step_8a/8b.

The artist builder also loads the **shared cognates layer** from `Data/Spanish/layers/cognates.json` — there is no per-artist cognate detection step.

The front-end loads `vocabulary.index.json` + `vocabulary.examples.json` (or the monolith `vocabulary.json`); it never reads layer files directly.
