# Fluency — TODO

<!-- Guide for Claude
This is Josh's backlog. Items are NOT instructions to start working.
- Do NOT start any item without Josh explicitly asking in the current conversation.
- DO mention relevant items when they come up naturally ("this relates to X on the todo, want to tackle it?").
- "idea" items: don't suggest unless Josh brings them up.
- When completing an item, move it to Decisions Made with a summary of what was done and why.
- UPDATE this file when working on items — record what was tried, what was learned, and why decisions were made.
- Do NOT use preview mode. Service worker caching makes previews unreliable — Josh tests in his own browser.

For items needing investigation before implementation, create a design doc at `docs/design/`
with `status: prompt`. See `docs/design/CLAUDE.md` for the lifecycle. Items marked [design doc]
below have enough complexity to warrant this treatment when the time comes.
-->

## Key

**Priority:** `now` = next up | `soon` = near-term | `idea` = someday/maybe
**Size:** `S` = hours | `M` = half-day | `L` = multi-session
**Mode:** `artist` = artist mode only | `normal` = normal mode only | `shared` = both

---

## UI / Front-End

- **[idea] Conjugation table UI polish (S) [shared]**
  Conjugation data layer is done (`conjugations.json` + `conjugation_reverse.json`).
  Front-end renders the table on card back but the UI needs improvement.

- **[soon] Cross-mode progress + estimation (M) [shared] [design doc]**
  Two related tasks: (1) Use base Spanish frequency list for level estimation in artist
  mode (less genre bias). (2) Share/migrate progress between normal and artist modes.
  Both blocked on the same plumbing — fullId prefixes differ (`es0` vs `es1`) but hex IDs
  are shared. Needs design: how to map general-rank result to artist deck position,
  mark-as-known sync direction, on-demand vs automatic.

- **[idea] Album-specific mode (M) [artist]**
  Let users choose specific albums. Options range from light (filter example lyrics to chosen
  albums, keep full corpus count) to heavy (album-only deck with album-specific corpus count).
  Long-term extension: user provides their own song list and gets a custom deck. Probably far
  out — depends on the pipeline being easy to run for arbitrary input.

- **[now] Surface per-word "known lyrics %" in settings (S) [artist]**
  Show what percentage of an artist's lyrics the user can understand the whole line for based on known words.

---

## Data / Pipeline

- **[soon] Move elision resolution before tokenization (M) [artist] [design doc]**
  Elision merging currently happens in step 5, after step 3 caps examples at 10.
  Should resolve elisions in a preprocessing pass on raw lyrics so step 3 counts
  canonical forms directly. Eliminates step 5, gives exact counts, and lets
  ambiguous elisions (ve'→vez/ves) disambiguate on every occurrence.
  See [`elision_resolution_refactor.md`](docs/design/prompts/elision_resolution_refactor.md).

- **[soon] English word list filter for step 4 (S) [artist]**
  Lingua misses short/common English words (babies, boobies, wannabes, fit, etc.) at 0.90
  threshold. Add a common English word list (top 20-30k) as a supplementary filter after
  the 50k Spanish wordlist removal — by that point Spanish homographs (no, pan, solo) are
  already gone, so false positive risk is low. Existing design doc covers the general
  filtering problem: [`new_artist_filter_design.md`](docs/design/new_artist_filter_design.md).

- **[soon] Homograph lemma filtering — minor lemma flag (L) [shared] [design doc]**
  When a surface form maps to multiple lemmas (e.g. "como" → como|como + como|comer),
  flag the less common lemma pairing so it can be filtered or deprioritized. Currently
  como|comer shows as a top-frequency word when it's actually rare. Inverse of
  `most_frequent_lemma_instance` (which picks the best *form* per lemma — this picks
  the best *lemma* per form). Could use POS-tagged corpus frequency or conjugation
  reverse lookup to determine which lemma dominates.

- **[idea] Artist sense pipeline: Wiktionary-sourced senses (L) [artist] [design doc]**
  Switch artist mode from "Gemini invents senses" to "pick from Wiktionary senses + classify."
  Would eliminate sense proliferation and cross-artist inconsistency. MWEs cover most idiomatic
  gaps. Gemini fallback only for words Wiktionary doesn't have. See `docs/design/artist_sense_pipeline.md`.

- **[idea] Run MWE corpus frequency on full OpenSubtitles (S) [shared]**
  Currently using 10% sample (`SAMPLE_STRIDE=10` in `build_mwes.py`). Full corpus would
  give better granularity for ordering. Change `SAMPLE_STRIDE` to 1 and re-run:
  ```bash
  # Edit Data/Spanish/Scripts/build_mwes.py: SAMPLE_STRIDE = 1
  .venv/bin/python3 Data/Spanish/Scripts/build_mwes.py
  .venv/bin/python3 Artists/run_pipeline.py --artist "Bad Bunny" --from-step build
  .venv/bin/python3 Artists/run_pipeline.py --artist "Rosalía" --from-step build
  .venv/bin/python3 Artists/run_pipeline.py --artist "Young Miko" --from-step build
  ```
  Estimated ~5 minutes for the full 105M lines. Tatoeba adds negligible signal over full OpenSubs.

- **[idea] Improve cognate flagger (M) [shared]**
  Converged into `shared/flag_cognates.py`. Could improve: add more suffix rules,
  tune similarity threshold, reduce false positives on short words, add LLM flagging
  to normal mode pipeline.

- **[idea] Sense dedup polish — English conjugation (S) [shared]**
  Generated 3rd-person translations say "he/she go" instead of "he/she goes".
  Would need English conjugation logic in `merge_to_master.py:choose_canonical_translation()`.

- **[idea] Auto-populate album dictionaries from Genius (M) [artist]**
  Scrape Genius album pages to auto-assign songs to albums. Currently manually curated.
  Not urgent — only 2 artists and their dictionaries are complete.

- **[idea] Multi-language generalization (L) [shared] [design doc]**
  Generalize `build_examples.py` to accept language as argument.
  Download Tatoeba pairs for Italian, Swedish, etc.
  Generate per-language frequency ranks and vocabulary.json.
  Spanish/Swedish/Italian/Dutch/Polish vocabs already exist in Data/ but only Spanish has
  the full pipeline.

---

## Vocabulary Issues

Items noticed while using the app. When fixing, investigate whether it's a symptom of a bigger
pipeline/data problem. Delete items from this list once resolved.

(none currently)

---

## Songs to Exclude

Songs that shouldn't be in the corpus (remixes, live versions, non-artist songs, etc.).
Add to `duplicate_songs.json` and check for similar songs. Delete once resolved.

120 DRILL
Calm Down / Party (Mixed)
  [197/302] Otra Vez (Remake)                         52/88 lines matched
  [198/302] Otra Vez (Remix)                          56/71 lines matched
  [199/302] Otra Ve’ (Remix)                          no synced lyrics
PASA EL TIEMPO (TE MUDASTE) 
---

## Decisions Made

Resolved items. Detail in `docs/design/` where linked; small fixes inline.

- **Shared master vocabulary** — See [`master_vocabulary_architecture.md`](docs/design/master_vocabulary_architecture.md)
- **Layered architecture** — See [`layered_pipeline_architecture.md`](docs/design/layered_pipeline_architecture.md)
- **Sense dedup/mapping** — See [`sense_dedup_mapping.md`](docs/design/sense_dedup_mapping.md)
- **Normal mode translation quality** — See [`translation_quality_normal_mode.md`](docs/design/translation_quality_normal_mode.md)
- **Conjugation-based POS filtering** — See [`conjugation_pos_filtering.md`](docs/design/conjugation_pos_filtering.md)
- **Level estimation algorithm** — See [`level_estimation.md`](docs/design/level_estimation.md)
- **Per-artist verse filtering** — Decided against. See [`verse_filtering.md`](docs/design/verse_filtering.md)
- **Alternative translation sources** — See [`alternative_translation_sources.md`](docs/design/alternative_translation_sources.md)
- **Sense-to-example distribution** — See [`wsd_benchmark_results.md`](docs/design/wsd_benchmark_results.md)
- **Per-sense frequency** — Implemented in both `match_senses.py` and `match_artist_senses.py` (5% min threshold)
- **Conjugation data layer** — `build_conjugations.py` generates from verbecc + Jehle CSV
- **Example cycling in normal mode** — Click on example box cycles; Spanish tap triggers breakdown only
- **Word highlight fix** — Unicode-aware word boundaries in `flashcards.js`
- **Mode switching button** — "Lyrics Mode" / "Normal Mode" toggle in top bar
- **Normal mode parity** — Both modes use JSON with meanings arrays; legacy CSV/Quizlet paths removed
- **Service worker strategy** — Network-first. Cache is offline fallback only.
- **Unified curated translations** — Migrated artist/normal curated overrides to `shared/curated_translations.json` with per-entry mode tags (`shared`/`artist`/`normal`). Both pipelines load from same file. Fixed "a|a" = "bishop" → "to, at" in normal mode.
- **Sense-matched example prioritization** — Already implemented: `sense_assignments.json` partitions examples to senses at build time in both pipelines. No front-end change needed.
- **Spotify lookup for Rosalía** — Completed.
- **Gemini lemma hallucinations** — Deleted 5 corrupted master entries. No runtime correction needed — word|lemma pairs are unique identities, so different lemmas don't clash. Clean up junk entries from master periodically.
- **OpenSubtitles integration** — Tatoeba primary, OpenSubtitles fills gaps. Stride-sampled, subtitle junk/OCR filters, trivial sentence filter, diversity sampling. 100% coverage.
- **Quality filtering for corpus examples** — Implemented in `build_examples.py`: trivial sentence filter (rejects top-100-only sentences), subtitle junk regex (OCR noise, music cues, timecodes).
- **Conjugation table on card back** — Data layer and front-end rendering done. UI polish remaining (tracked as idea).
- **iOS Safari Spotify button fix** — `onclick` never fired on iOS due to click synthesis failure inside `touch-action: none` card. Fixed with inline `ontouchend` handler. See [`ios_touch_events.md`](docs/design/ios_touch_events.md).
