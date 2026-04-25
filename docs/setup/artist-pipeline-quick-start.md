# Artist Pipeline — Quick Start

All commands run from the project root (`Fluency/`), not from inside `Artists/`.

## Common invocations

```bash
# Full pipeline for a known artist (Gemini API key required)
.venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "Bad Bunny"

# Resume from a step (e.g. after fixing curated overrides)
.venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "Rosalía" --from-step 6 --words-only

# Free / keyword-only first pass (no Gemini API key needed)
.venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "TestPlaylist" --classifier keyword --no-gap-fill

# Re-assemble only (after editing layer files manually)
.venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "Bad Bunny" --from-step build
```

## Typical run order for a new artist

```bash
# Steps 2-5 (corpus processing)
.venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist "Name" --from-step 2 --to-step 5 --skip 2b --no-gemini

# Bi-encoder on all words with Wiktionary senses (free)
.venv/bin/python3 pipeline/artist/match_artist_senses.py --artist-dir "Artists/{lang}/{Name}"

# Gemini on remaining non-normal words (~$0.05)
.venv/bin/python3 pipeline/artist/build_wiktionary_senses.py --artist-dir "Artists/{lang}/{Name}" --new-only

# Build final output
.venv/bin/python3 pipeline/artist/build_artist_vocabulary.py --artist-dir "Artists/{lang}/{Name}"
```

## Modes

- **Full run**: All steps, Gemini API required. Produces complete vocabulary with POS/lemma/translations.
- **`--no-gemini`**: Skips all Gemini calls. Uses Genius translations + curated overrides only. Free. Lower quality.
- **`--words-only`**: Gemini word analysis but skips sentence translation. Cheaper.
- **`--from-step N`**: Resume from step N. `--from-step build` re-assembles without re-running analysis.

Typical cheap workflow: `--no-gemini` first, then `--words-only` to add word translations.

## Cost-optimized translation workflow

For new artists:
1. Run `translate_sentences_google.py` (free) for all lines.
2. Run `judge_translations.py` to score quality (1–5 via Gemini).
3. Re-translate only bad ones via Gemini (~15–20% of lines).

Flags lines scoring ≤2 by default (`--threshold` to adjust). Use `--judge-only` to inspect scores before committing to re-translation.

## Pitfalls

- **Python 3.9** — do NOT use `str | None` union syntax. Use `Optional[str]` or no annotation.
- **Run from project root**, not from `Artists/` — the orchestrator handles paths.
- **Never delete curated overrides** — they serve as regression tests for pipeline quality.
- **Long-running steps** (especially step 6): print the command for Josh to run in his terminal instead of running inline.
- **Re-running a single step**: Each step writes only its own layer. Re-run it, then `--from-step build` to reassemble.

## Sentence translation sources

Step 6 checks two sources in order:
1. **Genius index** (free): Built from `aligned_translations.json`. ~40% coverage for Bad Bunny.
2. **Gemini** (expensive): Cached in `sentence_translations.json`. Only called for lines Genius doesn't cover.

The `example_translations.json` layer tracks provenance: `source: "genius" | "gemini" | "google"`.
