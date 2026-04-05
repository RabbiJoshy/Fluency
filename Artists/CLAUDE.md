# Artists Pipeline — AI Reference

All scripts run from the **project root** (`Fluency/`), not from inside `Artists/`.

## Quick Start

```bash
.venv/bin/python3 Artists/run_pipeline.py --artist "Bad Bunny"
.venv/bin/python3 Artists/run_pipeline.py --artist "Rosalia" --from-step 6 --words-only
.venv/bin/python3 Artists/run_pipeline.py --artist "Anuel" --no-gemini
```

## Pipeline Steps

Scrape lyrics (Genius) -> tokenise & count (with dedup) -> scrape Genius translations (3b) -> detect proper nouns (Gemini) -> merge Caribbean elisions -> Gemini LLM analysis (POS, lemma, translation) -> flag cognates -> rerank.

| Step | Script | What it does |
|------|--------|-------------|
| 1 | `scripts/1_download_lyrics.py` | Scrape lyrics from Genius API |
| 1b | (manual) | Curate `duplicate_songs.json` — see `DEDUP_INSTRUCTIONS.md` |
| 3 | `scripts/3_count_words.py` | Tokenise, count, filter excluded songs |
| 3b | `scripts/3b_scrape_translations.py` | Scrape Genius community English translations |
| 4 | `scripts/4_detect_proper_nouns.py` | Detect proper nouns (Gemini) |
| 5 | `scripts/5_merge_elisions.py` | Merge Caribbean elisions (e.g. pa' -> para) |
| 6 | `scripts/6_llm_analyze.py` | Main analysis: POS, lemma, translation, examples (Gemini + Genius) |
| 7 | `scripts/7_flag_cognates.py` | Flag transparent cognates. **Authoritative** — resets any upstream `is_transparent_cognate` |
| 8 | `scripts/8_rerank.py` | Final reranking by frequency + easiness |

Shared helper: `scripts/_artist_config.py` — `add_artist_arg()`, `load_artist_config()`.

## Key Files Per Artist

```
Artists/{Name}/
  artist.json                    # {"name", "genius_query", "vocabulary_file"}
  {Name}vocabulary.json          # Monolith output (pipeline produces this)
  {Name}vocabulary.index.json    # Auto-split: metadata only (no examples)
  {Name}vocabulary.examples.json # Auto-split: examples keyed by hex ID
  data/input/
    lyrics/                      # Raw lyrics per song
    translations/translations.json  # Genius community translations
    duplicate_songs.json         # Songs to exclude from corpus
  data/word_counts/
    vocab_evidence.json          # Step 3 output (word counts + evidence)
    mwe_detected.json            # Multi-word expressions detected
    conjugation_families.json    # Verb family groupings
    curated_mwes.json            # Curated MWE additions
    skip_mwes.json               # MWEs to exclude
  data/llm_analysis/
    curated_translations.json    # Manual translation fixes (NEVER delete these)
    sentence_translations.json   # Gemini sentence translation cache (Layer 2)
  data/elision_merge/            # Step 5 output
  data/proper_nouns/             # Step 4 output
```

## Modes

- **Full run**: All steps, Gemini API required. Produces complete vocabulary with POS/lemma/translations.
- **`--no-gemini`**: Skips all Gemini calls. Uses Genius translations + curated overrides only. Free. Lower quality (no POS/lemma).
- **`--words-only`**: Gemini word analysis but skips sentence translation. Cheaper. Good when Genius covers sentences.
- **`--from-step N`**: Resume from step N (useful after manual curation or partial runs).

Typical cheap workflow: `--no-gemini` first, then `--words-only` to add word translations.

## Sentence Translation Layers

Step 6 checks two sources in order:
1. **Genius index** (Layer 1): Built from `translations.json`. Free. ~40% coverage for Bad Bunny.
2. **Gemini cache** (Layer 2): `sentence_translations.json`. Expensive. Only called for lines Genius doesn't cover.

Genius never overwrites Gemini translations. Each example has `translation_source: "genius"|"gemini"`.

Line alignment is section-aware: splits at empty lines, only zips sections where line counts match.

## Adding a New Artist

1. Create `Artists/NewArtist/artist.json` with `name`, `genius_query`, `vocabulary_file`
2. Run step 1 to download lyrics
3. Curate `duplicate_songs.json` (see `DEDUP_INSTRUCTIONS.md`)
4. Copy reusable curated data from existing artist (conjugation_families, skip_mwes, etc.)
5. Run pipeline (`--no-gemini` for free, then `--words-only` to add translations)
6. Pipeline auto-splits monolith into index + examples files
7. Add artist to `artists.json` at project root
8. Shared words get translations via client-side merge — no Gemini needed for overlapping vocab

## Pitfalls

- **Python 3.9** — do NOT use `str | None` union syntax. Use `Optional[str]` or no annotation.
- **Run from project root**, not from `Artists/` — the orchestrator handles paths.
- **Step 7 resets `is_transparent_cognate`** — don't set it in earlier steps.
- **`strip_plural` over-strips** — removes `-s` from "famous", "serious", etc. Step 7 accounts for this.
- **Never delete curated overrides** — they serve as regression tests for pipeline quality.
- **Long-running steps** (especially step 6): print the command for Josh to run in his terminal instead of running inline.
