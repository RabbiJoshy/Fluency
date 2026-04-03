# Bad Bunny Vocabulary Pipeline

Turns Bad Bunny's discography into a structured Spanish vocabulary deck for the [Fluency](../) flashcard app.

## Why

Reggaeton lyrics are surprisingly good for learning Spanish. They use high-frequency everyday vocabulary, Caribbean slang, and repetitive structures that reinforce memorisation. But raw lyrics need heavy processing to become useful flashcards: tokenisation, elision handling, lemmatisation, translation, deduplication, and quality filtering.

This pipeline does all of that automatically. The output is a single JSON file consumed by the Fluency app in Bad Bunny mode (`?mode=badbunny`).

## Pipeline overview

```
Genius API  -->  raw lyrics  -->  tokenise & count  -->  merge elisions
                                                              |
    final vocab  <--  rerank  <--  cognates  <--  LLM analysis
```

| Step | Script | What it does |
|------|--------|-------------|
| 1 | `1_download_lyrics.py` | Scrape lyrics from Genius API |
| 1b | `1b_rescrape_nulls.py` | Re-scrape songs that failed first time |
| 2 | `2_count_words.py` | Tokenise, count frequencies, select example lines |
| 2c | `2c_detect_proper_nouns.py` | Flag proper nouns via Gemini |
| 2d | `2d_detect_mwes.py` | Detect multi-word expressions (bigram/trigram frequency) |
| 3 | `3_merge_elisions.py` | Merge Caribbean elisions (ere' + eres -> eres) |
| 4 | `4_llm_analyze.py` | Gemini: POS, lemma, translation, sentence translation |
| 8 | `8_flag_cognates.py` | Flag transparent Spanish-English cognates |
| 9 | `9_rerank.py` | Sort by frequency with meaningful tiebreakers |

Orchestrator: `run_pipeline.py --api-key KEY` runs all steps in order. Supports `--from-step`, `--to-step`, `--skip`, `--dry-run`.

## Quick start

```bash
# From project root (Fluency/), not from inside this folder
.venv/bin/python3 "Bad Bunny/run_pipeline.py" --api-key YOUR_GEMINI_KEY
```

## Key concepts

- **Caribbean elisions**: Puerto Rican Spanish drops final -s (`eres` -> `ere'`). Step 3 merges these, keeping the elided spelling in `display_form`.
- **Multi-word expressions**: Frequent collocations like "pa' que", "de verdad", "lo que sea" are detected and annotated on component words as `mwe_memberships`.
- **LLM analysis (step 4)**: Uses Gemini to determine POS, lemma, word translation, and sentence translations. Saves progress incrementally so it's restartable.
- **Cognate flagging**: Transparent cognates (especial/special, imposible/impossible) are flagged so the app can deprioritise them — they're "free" vocabulary for English speakers.

## Output

`BadBunnyvocabulary.json` — one entry per (word, lemma) pair with meanings, translations, example lyrics, and metadata flags. See `CLAUDE.md` for the full schema.

## Supporting tools

| Script | Purpose |
|--------|---------|
| `check_translations.py` | Audit translation quality (mismatches, empty translations) |
| `dedup_songs.py` | Detect duplicate songs (remixes, live versions) |
| `2b_split_lang_and_junk_lingua.py` | Standalone audit: classify words by language |
