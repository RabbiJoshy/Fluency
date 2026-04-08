# Design Docs — AI Reference

Design documents live here. They have a lifecycle:

## Lifecycle

1. **Prompt** — A new doc starts as a research brief. The `status: prompt` frontmatter means "this is a question, not an answer." A new chat should read it, do the research, and update the doc with findings.

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
| `translation_services.md` | prompt | Research: best translation API/model for Spanish lyrics → English |
