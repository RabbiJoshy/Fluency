# Fluency — TODO

<!-- Guide for Claude
This is Josh's backlog. Items are NOT instructions to start working.
- Do NOT start any item without Josh explicitly asking in the current conversation.
- DO mention relevant items when they come up naturally ("this relates to X on the todo, want to tackle it?").
- "idea" items: don't suggest unless Josh brings them up.
- When completing an item, move it to Decisions Made with a summary of what was done and why.
- UPDATE this file when working on items — record what was tried, what was learned, and why decisions were made.
- Do NOT use preview mode. Service worker caching makes previews unreliable — Josh tests in his own browser.
-->

## Key

**Priority:** `now` = next up | `soon` = near-term | `idea` = someday/maybe
**Size:** `S` = hours | `M` = half-day | `L` = multi-session
**Mode:** `artist` = artist mode only | `normal` = normal mode only | `shared` = both

---

## UI / Front-End

- **[now] Normal mode parity (L) [normal]**
  Easiness-based sorting and improved card layout. Artist mode is far ahead.
  Start: compare `loadVocabularyData()` and `updateCard()` paths for `activeArtist` vs normal.
  `isMultiMeaning` is always true in artist mode; normal still has legacy single-meaning paths.

- **[now] Mode switching button (S) [shared]**
  Add a UI button to switch between normal and artist modes. Currently mode is set via URL
  query params only (`?artist=bad-bunny`). No discoverable way to switch in-app.

- **[now] Word highlight fix — short words match everywhere (S) [shared]**
  When highlighting the target word in example sentences, single-letter words like "a" highlight
  every occurrence of that letter in the sentence. The regex in `flashcards.js` (~line 1172)
  uses `RegExp('(word)', 'gi')` without word boundaries (`\b`). Needs `\b` anchors, but must
  handle Spanish-specific edge cases (accented chars, elisions).

- **[soon] General vocab for level estimation (M) [shared]**
  Use base Spanish frequency list for estimation even in artist mode (less genre bias).
  Previously blocked on shared IDs — blocker resolved (both modes now use 6-char hex IDs).
  Open question: how to map general-rank result back to artist deck position.

- **[soon] Progress sharing across modes (M) [shared]**
  Button/UI to share or migrate progress between normal and artist modes. Currently stored in
  separate Google Sheets tabs (`UserProgress` vs `Lyrics`) with separate fullId prefixes
  (`es0` vs `es1`). Same 6-char hex IDs underneath, so mapping is possible. Needs design:
  mark-as-known sync? One-way or bidirectional? On-demand or automatic?

- **[idea] Album-specific mode (M) [artist]**
  Let users choose specific albums. Options range from light (filter example lyrics to chosen
  albums, keep full corpus count) to heavy (album-only deck with album-specific corpus count).
  Long-term extension: user provides their own song list and gets a custom deck. Probably far
  out — depends on the pipeline being easy to run for arbitrary input.

- **[idea] Surface per-word "known lyrics %" in settings (S) [artist]**
  Show what percentage of an artist's lyrics the user can understand based on known words.

---

## Data / Pipeline

- **[now] Normal mode translation quality — top words are wrong (M) [normal]**
  The top ~25 words have bad Wiktionary-sourced translations. Examples: "a" → "bishop" (chess
  piece instead of preposition), "de" → "the name of the Latin script letter D", "lo" → verbose
  nominalizer definition missing the pronoun sense, "por" missing "for". Root cause: Wiktionary
  (`kaikki-spanish.jsonl.gz` via `build_senses.py`) returns form-of entries, archaic defs, or
  wrong senses for common function words. Needs either: curated overrides for top N words,
  better sense selection logic in `build_senses.py`, or a Gemini pass on the worst offenders.
  Related: translations don't prioritize the most common meaning — verbose definitions bury it.

- **[now] Normal mode lemma/translation inconsistency (M) [normal]**
  Cards are split by lemma (e.g. "pulso" appears as both lemma="pulso" NOUN and lemma="pulsar"
  VERB), but translations aren't lemma-aware — both entries can show noun+verb senses. The raw
  inventory lemmatizes words but the Wiktionary sense layer doesn't match senses to lemmas
  properly, so you see verb-lemma cards with noun translations. This is a simpler, deterministic
  version of sense-to-sentence matching: it's lemma/word pairing to senses, not sense to
  sentence. Fix in `build_senses.py` or `match_senses.py` to align senses with the correct
  lemma entry.

- **[soon] Sense-matched example prioritization (M) [shared]**
  When a word has multiple meanings, prioritize example sentences that match the active sense.
  Process: check if Gemini tagged which sense each example demonstrates; prefer sense-matched
  examples, fall back to standard method if no match exists. Prevents confusing sense/example
  pairings.

- **[soon] OpenSubtitles integration (M) [normal]**
  Data downloaded to `Data/Spanish/corpora/opensubtitles/` but not integrated into pipeline.
  Parse Moses-format es-en parallel files, add as fallback corpus in `build_examples.py`
  (Tatoeba primary, OpenSubtitles fills gaps). Deduplicate across corpora.
  May need quality filtering for fragments/OCR artifacts/single-word lines.
  Measure: how many of the ~1,002 uncovered words get filled?

- **[soon] Spotify lookup for Rosalia (S) [artist]**
  Re-run `Artists/scripts/spotify_lookup.py` after rate limit resets.
  Front-end already wired. Credentials in `.env`. Bad Bunny done (248/302 matched).

- **[idea] Lemmatization pass (M) [shared]**
  spaCy `es_core_news_lg` to match conjugated corpus forms to lemmas.
  e.g. `disculpen` matches via `disculpar`. Estimated +4% coverage on top of accent
  normalization.

- **[idea] Quality filtering for corpus examples (S) [shared]**
  Drop sentences with too many unknown tokens, OCR noise, etc.

- **[idea] Sense-specific example distribution (L) [shared]**
  Distribute examples across meanings instead of duplicating to all senses.
  Options: spaCy POS matching, cheap Gemini pass for sense disambiguation,
  or heuristic (keyword overlap with translation).

- **[idea] Per-sense frequency from corpus (M) [shared]**
  Once sense-to-sentence mapping exists, compute how often each sense appears.
  Frequency = count per sense / total occurrences.

- **[idea] Cross-artist MWE detection (M) [artist]**
  Step 3 detects MWEs per-artist only. A shared pass across all artist corpora would find
  expressions below any single artist's frequency threshold. Master vocab already unions
  MWE memberships; detection itself is per-artist.

- **[idea] Converge cognate scripts (S) [shared]**
  `Artists/scripts/7_flag_cognates.py` and `Data/Spanish/Scripts/flag_cognates.py` are copies.
  Move to a shared root-level location so both pipelines use one script.

- **[idea] Sense dedup polish — English conjugation (S) [shared]**
  Generated 3rd-person translations say "he/she go" instead of "he/she goes".
  Would need English conjugation logic in `merge_to_master.py:choose_canonical_translation()`.

- **[idea] Auto-populate album dictionaries from Genius (M) [artist]**
  Scrape Genius album pages to auto-assign songs to albums. Currently manually curated.
  Not urgent — only 2 artists and their dictionaries are complete.

- **[idea] Multi-language generalization (L) [shared]**
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

(none currently)

---

## Decisions Made

Resolved items kept for context, not actionable.

- **Shared master vocabulary architecture** — DONE. `Artists/vocabulary_master.json` exists,
  keyed by 6-char hex IDs (`md5(word|lemma)[:6]`). Both pipelines share the same ID scheme.
  Senses accumulate across artists. `merge_to_master.py` handles sense dedup via
  normalization + spaCy morphology.

- **Layered architecture** — DONE for both pipelines. Each step writes its own layer file;
  builder assembles layers into front-end output. No step mutates another step's output.

- **Example cycling in normal mode** — DONE. Click target moved from English text to whole
  example box; Spanish tap triggers breakdown only (stopPropagation).

- **Sense dedup/mapping** — DONE (main implementation). Merged 271 duplicates via
  `normalize_translation()` + spaCy morphology in `merge_to_master.py`. Only polish remains
  (English 3rd-person conjugation, tracked above).

- **Per-artist verse filtering** — Decided against. Goal is understanding full songs.
  Feature verses help learners. Genius verse labels are unreliable. Existing filters
  (English stripping, exclusions, adlib removal) handle real quality problems.

- **Alternative translation sources** — Researched April 2025, none viable. Genius + Gemini
  (~$5/artist) remains best approach. Musixmatch blocked, LyricsTranslate too sparse,
  LyricFind enterprise-only. Revisit if Musixmatch unofficial API stabilizes.

- **Level estimation algorithm** — Adaptive staircase (one word at a time, step size halves
  on reversals, converges at step < 50 + 5 consecutive correct or 30 words max).

- **Service worker strategy** — Network-first for all assets. Cache is offline fallback only.
