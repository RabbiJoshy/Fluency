# Layers — AI Reference

Intermediate data layers produced by pipeline steps. Each layer captures one aspect of vocabulary analysis. The final `build_vocabulary.py` step joins layers into `vocabulary.json`.

## Design Principle: Provenance

**Always add new layers rather than overwriting existing ones.** When trying a new method (e.g. a different cognate detection approach), create a new layer file (e.g. `cognates_experimental.json`) alongside the existing one. This preserves provenance so Josh can compare methods and validate which works best. The build script chooses which layers to consume — unused layers stay in the directory as references.

This also applies to the artist pipeline layers in `Artists/{Name}/data/layers/`.

## Layer Files

| File | Key format | Value | Producer | Pipeline step |
|------|-----------|-------|----------|--------------|
| `word_inventory.json` | Array of objects | `{word, lemma, id, corpus_count, most_frequent_lemma_instance, homograph_ratio?}` | `build_inventory.py` | Step 1 |
| `examples_raw.json` | Array of objects | `{id, word, lemma, examples: [{id, spanish, english, source}]}` | `build_examples.py` | Step 2 |
| `conjugations.json` | infinitive | Full conjugation table `{translation, gerund, past_participle, moods: {...}}` | `build_conjugations.py` | Step 3 |
| `conjugation_reverse.json` | conjugated form | List of `{lemma, mood, tense, person}` | `build_conjugations.py` | Step 3 |
| `senses_wiktionary.json` | `word\|lemma` | List of `{pos, translation, detail?}` | `build_senses.py` | Step 4 |
| `mwe_phrases.json` | hex ID | List of `{expression, translation, source, corpus_freq?, count?}` — unified, all sources with provenance | `build_mwes.py` | Step 5 |
| `sense_assignments.json` | hex ID | List of `{sense_idx, examples: [int]}` | `match_senses.py` | Step 6 |
| `sense_merges.json` | metadata | `{fingerprint, threshold, merges: {target_idx→source_idx}}` | `match_senses.py` | Step 6 |
| `cognates.json` | `word\|lemma` | `{score: float, cognet: bool, gemini?: bool}` — unified cognate signals | `flag_cognates.py` (via `shared/flag_cognates.py`) | Step 7 |
| `homograph_overrides.json` | surface form | `{lemma: ratio}` pairs summing to 1.0 | Manual | — |

## Artist Pipeline Layers

Artist layers live at `Artists/{Name}/data/layers/` and follow the same pattern:

| File | Key format | Value | Producer |
|------|-----------|-------|----------|
| `word_inventory.json` | Array | Same as normal mode | `2_count_words.py` (step 2) |
| `examples_raw.json` | bare word | `[{id, spanish, title}]` | `5_split_evidence.py` (step 5) |
| `example_translations.json` | Spanish text line | `{english, source}` — source: `"genius"\|"gemini"\|"google"` | `6_llm_analyze.py` (step 6) |
| `senses_gemini.json` | `word\|lemma` | List of `{pos, translation, source}` | `6_llm_analyze.py` (step 6) |
| `sense_assignments.json` | `word\|lemma` | List of `{sense_idx, examples: [int], method}` — method: `"gemini"\|"biencoder"\|"keyword"` | Step 6 / 6b |
| `ranking.json` | top-level | `{order: [words], easiness: {word: {m: [[scores]]}}}` | `7_rerank.py` (step 7) |
| `lyrics_timestamps.json` | top-level | `{_meta: {...}, timestamps: {song: {line: {ms, confidence}}}}` | `8_fetch_lrc_timestamps.py` (step 8) |
| `translation_scores.json` | Spanish text line | `{score: 1-5}` — Gemini quality scores | `judge_translations.py` (step 6j) |

## How Layers Are Consumed

`build_vocabulary.py` (normal mode) and `build_artist_vocabulary.py` (artist mode) join layers by key (`word|lemma` or hex ID) to produce the final `vocabulary.json` / artist vocab files. Not all layers are required — missing layers are skipped gracefully.

The artist builder also loads the **shared cognates layer** from `Data/Spanish/layers/cognates.json` — there is no per-artist cognate detection step.

The front-end loads `vocabulary.index.json` + `vocabulary.examples.json` (or the monolith `vocabulary.json`); it never reads layer files directly.
