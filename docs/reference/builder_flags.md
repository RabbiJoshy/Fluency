# Builder Flags — Reference

`step_8a_assemble_vocabulary.py` (normal) and `artist/step_8b_assemble_artist_vocabulary.py` (artist) share two orthogonal flags that control deck composition.

## `--remainders`

Emit `SENSE_CYCLE` remainder buckets for unassigned examples.

- **Default**: off (cleaner cards).
- **On**: every orphan example (no keyword/biencoder/Gemini claim) lands in a `SENSE_CYCLE` row attached to its routed `word|lemma`, grouped by spaCy POS.

## `--min-priority N`

Drop assignments whose method priority is below N. Auto-assignments (`*-auto`) are exempt regardless of priority — they're "trivially correct" single-sense defaults.

Useful values:
- `15` — skip keyword-tier
- `30` — biencoder and above
- `50` — Gemini only

**Default is language-specific**, resolved from `config/config.json` → `languages.<lang>.pipelineDefaults.minPriority` via `pipeline/util_pipeline_config.py`:

- **Spanish** opts in to `50` (Gemini Flash Lite covers every word, so keyword-tier noise like `para|parir` is dropped by default).
- Languages without the `pipelineDefaults.minPriority` key fall back to `0` — keyword claims show by default until the language opts in.

`step_8a` hardcodes `language="spanish"`; `step_8b` reads `artist.json.language` (default `"spanish"`). The resolved value is printed at startup alongside its source (config vs. explicit flag).

See `docs/reference/method_priority.md` for the full priority table.

## Combined behavior — orthogonal flags

| Flags | Result |
|---|---|
| `--min-priority 50 --remainders` | Gemini-only claims + catch-all buckets for everything else |
| `--min-priority 50` (no remainders) | Sparsest trusted deck |
| `--min-priority 0 --remainders` | Full evidence + catch-all |
| (defaults: lang min-priority, no remainders) | Standard Spanish deck |

## Meaning dedup + context disambiguation

`step_8a` dedupes meaning rows by `(pos, translation, context)` where `context` comes from SpanishDict's sub-sense labels.

When two rows share `(pos, translation)` but differ in context (e.g. `uno` PRON "one" as numeral vs impersonal), the context is rendered parenthetically on the visible translation:

- `one (numeral or indefinite)`
- `one (impersonal use)`

Singletons keep their clean translation.

## Step_7a (lemma split + unassigned routing)

`pipeline/step_7a_map_senses_to_lemmas.py` is unified between normal and artist modes. The artist-specific `pipeline/artist/step_7a_*.py` is now a thin subprocess wrapper that forwards `--artist-dir` to the shared script.

Both modes produce:

- `sense_assignments_lemma/{source}.json` — splits `word` assignments into `word|lemma` keys using sense-id ownership.
- `unassigned_routing/{source}.json` — routes unassigned raw examples to a `word|lemma` key based on spaCy POS. Used by builders to populate `SENSE_CYCLE` remainder buckets when `--remainders` is on.

For deeper internals on routing rules and `SENSE_CYCLE` behavior, see `docs/reference/sense_assignment_internals.md`.
