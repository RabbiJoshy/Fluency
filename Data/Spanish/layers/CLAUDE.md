# Layers — AI Reference

Intermediate data layers produced by pipeline steps. Each layer captures one aspect of vocabulary analysis. The final `build_vocabulary.py` step joins layers into `vocabulary.json`.

## Design Principle: Provenance

**Always add new layers rather than overwriting existing ones.** When trying a new method (e.g. a different cognate detection approach), create a new layer file (e.g. `cognates_cognet.json`) alongside the existing one. This preserves provenance so Josh can compare methods and validate which works best. The build script chooses which layers to consume — unused layers stay in the directory as references.

This also applies to the artist pipeline layers in `Artists/{Name}/data/layers/`.

## Layer Files

| File | Key format | Value | Producer | Pipeline step |
|------|-----------|-------|----------|--------------|
| `word_inventory.json` | Array of objects | `{word, lemma, id, corpus_count, most_frequent_lemma_instance, homograph_ratio?}` | `build_inventory.py` | Step 1 |
| `senses_wiktionary.json` | `word\|lemma` | List of `{pos, translation, detail?}` | `build_senses.py` | Step 4 |
| `sense_assignments.json` | hex ID | List of `{sense_idx, examples: [int]}` | `match_senses.py` | Step 5 |
| `sense_merges.json` | metadata | `{fingerprint, threshold, merges: {target_idx→source_idx}}` | `match_senses.py` | Step 5 |
| `cognates.json` | `word\|lemma` | `float` (0.0–1.0) — suffix/similarity score | `flag_cognates.py` | Step 7 |
| `cognates_cognet.json` | `word\|lemma` | `true` — CogNet database match (word+translation pair exists in CogNet) | `flag_cognates.py` | Step 7 |
| `conjugations.json` | infinitive | Full conjugation table `{translation, gerund, past_participle, moods: {...}}` | `build_conjugations.py` | Step 3 |
| `conjugation_reverse.json` | conjugated form | List of `{lemma, mood, tense, person}` | `build_conjugations.py` | Step 3 |
| `homograph_overrides.json` | surface form | `{lemma: ratio}` pairs summing to 1.0 | Manual | — |
| `mwe_phrases.json` | hex ID | List of `{expression, translation, source, corpus_freq?, count?}` — unified, all sources with provenance | `build_mwes.py` + merge | Step 1 |

## Artist Pipeline Layers

Artist layers live at `Artists/{Name}/data/layers/` and follow the same pattern:

| File | Key format | Value | Producer |
|------|-----------|-------|----------|
| `word_inventory.json` | Array | Same as normal mode | Step 3 (`3_build_vocab.py`) |
| `senses_gemini.json` | `word\|lemma` | List of `{pos, translation, detail?}` | Step 6 (`6_llm_analyze.py`) |
| `cognates.json` | `word\|lemma` | `float` or `true` — intersection of LLM flag + suffix rules | `7_flag_cognates.py` |
| `examples_raw.json` | `word\|lemma` | List of raw lyric examples | Step 3 |
| `example_translations.json` | `word\|lemma` | Gemini-translated examples | Step 6 |
| `ranking.json` | `word\|lemma` | Ranking data | Step 8 (`8_rerank.py`) |
| `sense_assignments.json` | hex ID | Same as normal mode | Step 6b |
| `lyrics_timestamps.json` | song key | Timestamp data | Step 3 |

## How Layers Are Consumed

`build_vocabulary.py` (normal mode) and `build_artist_vocabulary.py` (artist mode) join layers by key (`word|lemma` or hex ID) to produce the final `vocabulary.json` / artist vocab files. Not all layers are required — missing layers are skipped gracefully.

The front-end loads `vocabulary.json` only; it never reads layer files directly.
