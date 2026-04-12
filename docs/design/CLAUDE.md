# Design Docs — AI Reference

Design documents live here. They have a lifecycle:

## Lifecycle

1. **Prompt** — A new doc starts as a research brief in `docs/design/prompts/`. The `status: prompt` frontmatter means "this is a question, not an answer." A new chat should read it, do the research, and update the doc with findings. Move out of `prompts/` into `docs/design/` when status advances past prompt.

2. **Research** — During investigation, findings get added below the original prompt. Status becomes `research`. The doc accumulates options, benchmarks, trade-offs.

3. **Decision** — Once an approach is chosen, the doc records what was picked and why. Status becomes `decided`. The original prompt and rejected alternatives stay for context.

4. **Implemented** — After code lands, the doc links to the implementation and records measured results. Status becomes `implemented`. It's now a living reference.

## Frontmatter

Every design doc has YAML frontmatter:

```yaml
---
title: Short descriptive title
status: prompt | research | decided | implemented
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

## How to use these docs

**Starting a new chat about a design doc:** Link to the file. If `status: prompt`, the chat should research and update. If `status: research`, the chat should continue investigation or push toward a decision. If `status: decided` or `implemented`, the chat should read it as context before making changes in that area.

**Creating a new design doc:** Write the question or research brief. Set `status: prompt`. Include enough context that a fresh chat can pick it up without the conversation that spawned it.

**Updating:** Always update the `updated` date. Append new sections rather than rewriting — the history of thinking is valuable. Move status forward when appropriate.

## Current docs

| Doc | Status | Topic |
|-----|--------|-------|
| `wsd_benchmark_results.md` | implemented | Word sense disambiguation — all approaches tried, Gemini chosen |
| `example_selection_design.md` | implemented | Example sentence scoring and selection |
| `new_artist_filter_design.md` | implemented | Known vocab filter chain (94% Gemini reduction) |
| `master_vocabulary_architecture.md` | implemented | Shared master vocab: ID scheme, sense accumulation, merge logic |
| `layered_pipeline_architecture.md` | implemented | Both pipelines use independent layer files + builder assembly |
| `sense_dedup_mapping.md` | implemented | Sense dedup via normalization + spaCy morphology |
| `translation_quality_normal_mode.md` | implemented | Wiktionary translation fixes for common words |
| `conjugation_pos_filtering.md` | implemented | Remove non-VERB senses from confirmed verb forms |
| `level_estimation.md` | implemented | Adaptive staircase algorithm for level estimation |
| `homograph_disambiguation.md` | implemented | Homograph lemma disambiguation — spaCy + manual overrides |
| `verse_filtering.md` | decided | Per-artist verse filtering — decided against |
| `alternative_translation_sources.md` | decided | Lyrics translation sources — Genius + Gemini chosen |
| `artist_sense_pipeline.md` | implemented | Artist sense pipeline: Wiktionary senses + Flash Lite classifier + method priority |
| `prompts/translation_services.md` | prompt | Research: best translation API/model for Spanish lyrics → English |
