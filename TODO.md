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

- **[soon] Conjugation table on card back (M) [shared]**
  Display conjugation data on the card back for verb entries. Data layer exists
  (`build_conjugations.py` generates `conjugation_reverse.json` and `conjugations.json`
  from verbecc + Jehle CSV). Front-end needs to load and render the table.

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

- **[soon] Normal mode translation quality — "a|a" still wrong (S) [normal]**
  Most top-word translation issues fixed algorithmically in `build_senses.py` (see Decisions
  Made). Remaining: "a|a" (preposition) has no usable Wiktionary entry — needs a curated
  override in the senses layer or a different source.

- **[soon] Homograph lemma filtering — minor lemma flag (S) [shared]**
  When a surface form maps to multiple lemmas (e.g. "como" → como|como + como|comer),
  flag the less common lemma pairing so it can be filtered or deprioritized. Currently
  como|comer shows as a top-frequency word when it's actually rare. Inverse of
  `most_frequent_lemma_instance` (which picks the best *form* per lemma — this picks
  the best *lemma* per form). Could use POS-tagged corpus frequency or conjugation
  reverse lookup to determine which lemma dominates.

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

- **Word highlight fix** — DONE. Added Unicode-aware word boundaries (`\p{L}\p{N}`
  lookbehind/lookahead) to the highlight regex in `flashcards.js`. Short words like "a"
  no longer highlight every occurrence of that letter in example sentences.

- **Mode switching button** — DONE. Added "Lyrics Mode" / "Normal Mode" toggle button in the
  top bar. In normal mode shows artist picker dropdown if multiple artists configured; in
  artist mode links back to the base URL.

- **Normal mode parity** — DONE for Spanish. `vocabulary.index.json` already has meanings
  arrays, and `loadVocabularyData()` builds `isMultiMeaning:true` cards for both modes.
  The legacy `parseQuizlet`/`parseCSV` paths only applied to non-Spanish languages (all
  languages already use JSON with meanings arrays) — removed as dead code.

- **Normal mode translation quality** — Mostly DONE. Multiple algorithmic fixes in
  `build_senses.py`: fixed sense merge bug (stop-word-only translations no longer incorrectly
  merged); fixed alt-of extraction (rescued al, muy); deprioritized letter-name NOUN senses
  (de→"of" ranks above "letter D"); improved verbose translation cleaning via colon/semicolon
  pattern extraction (lo→"the, that which is", tu→"you", me→"me"); fixed pronoun form-of
  extraction (nos→"us", les→"them"). Top 100 words much improved. Only "a|a" remains
  unfixable algorithmically (preposition genuinely missing from Wiktionary).

- **Normal mode lemma/translation inconsistency** — DONE. Added conjugation-based POS
  filtering in `build_senses.py`. When `conjugation_reverse.json` confirms a word is a verb
  form (e.g. como is conjugated form of comer), non-VERB senses are removed. Prevents
  verb-lemma cards from showing noun/conjunction/adverb translations.

- **Conjugation data layer** — DONE. `build_conjugations.py` generates conjugation data from
  verbecc + Jehle CSV. Pipeline renumbered: step 3 = build_conjugations, step 4 =
  build_senses, step 5 = match_senses, step 6 = build_vocabulary. Front-end display of
  conjugation tables tracked separately above.
