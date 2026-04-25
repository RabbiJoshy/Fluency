# Method Priority — Reference

Single source of truth for the priority numbers used by sense-assignment classifiers and translation sources.

Code: `pipeline/util_6a_method_priority.py` → `METHOD_PRIORITY`, `TRANSLATION_PRIORITY`, `best_method_priority()`.

## Sense-assignment method priority

Higher = better quality. Both pipelines use this — scripts skip words that already have an equal-or-higher priority assignment.

| Method | Priority | Source |
|---|---|---|
| `flash-lite-wiktionary` | 50 | Gemini Flash Lite classifier |
| `gap-fill` | 50 | Gemini gap-fill (when classifier finds no fit) |
| `gemini` | 40 | Normal-mode Gemini classifier (legacy label) |
| `biencoder` | 30 | Local sentence-transformers bi-encoder |
| `keyword-wiktionary` | 10 | Keyword overlap on Wiktionary senses |
| `keyword` | 10 | Keyword overlap (generic) |
| `wiktionary-auto` | 0 | Single-sense default — exempt from `--min-priority` |

`*-auto` methods (e.g. `wiktionary-auto`, `spanishdict-auto`) are "trivially correct" single-sense defaults and **always pass** the builder's `--min-priority N` filter regardless of N.

## Translation source priority

Used by the artist builder to sort which English translation appears first per example.

| Source | Priority |
|---|---|
| `gemini` | 50 (LLM re-translation) |
| `genius` | 40 (fan translations) |
| `google` | 10 (raw Google Translate) |

## How priorities are used

- **At assignment time**: each step 6 classifier checks existing assignments via `best_method_priority(word)` and skips if its own priority isn't higher.
- **At build time**: `step_8a` / `step_8b` apply `--min-priority N` to drop low-quality claims before assembling cards.
- **Per-example**: `resolve_best_per_example` in the builder picks the highest-priority `(method, sense)` claim per individual example when multiple methods overlap.

## Default `--min-priority` per language

Resolved from `config/config.json` → `languages.<lang>.pipelineDefaults.minPriority` via `pipeline/util_pipeline_config.py`.

- **Spanish**: opts in to `50` — Gemini Flash Lite covers every word, so keyword-tier noise like `para|parir` is dropped by default.
- **Other languages**: fall back to `0` until they explicitly opt in.

`step_8a` hardcodes `language="spanish"`; `step_8b` reads `artist.json.language` (default `"spanish"`).
