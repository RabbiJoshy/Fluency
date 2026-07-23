# Fluency — TODO

<!-- Don't start items without explicit ask. Mention relevant items naturally; update them in-place when worked on; move to Decisions Made when done. [design doc] items get a docs/design/ prompt before implementation. -->

## Key

**Priority:** `now` = next up | `soon` = near-term | `idea` = someday/maybe
**Size:** `S` = hours | `M` = half-day | `L` = multi-session
**Mode:** `artist` = artist mode only | `normal` = normal mode only | `shared` = both
**Language:** `spanish` | `french` | `cross-lang` (orthogonal to mode — a `[shared] [cross-lang]` item affects both modes in every language; a `[artist] [spanish]` item is Spanish artist-mode only)

---

## UI / Front-End

- **[now] UI overhaul batch — requested 2026-07-22 (L) [shared] [cross-lang]**
  Run as SEQUENTIAL worktree agents (all touch `css/style.css` + the cache-version files, so
  one at a time; merge each before the next). Specs locked with Josh:
  1. **Card/popup polish** (in progress): raise contrast of the lemma on the card back; clearer
     selected-sense indicator (current subtle border → tint/accent-bar/check); restyle the
     end-of-set popup to match the app's modal aesthetic.
  2. **Artist picker → radial "clock of pictures"**: artist images arranged around a circle,
     tap one to pick. Replaces the `main.js` `showArtistPicker` dropdown.
  3. **Level selector → horizontal zoomed scrubber**: drag a ruler/timeline left-right along the
     corpus-frequency axis, showing a magnified focused slice instead of all bands crammed in
     (declutter `renderLevelSelector`/range UI in `ui.js`).
  4. **Sense-level flagging**: the in-card audit/flag menu lets you flag a specific sense
     mapping (that pill = "this word→meaning is wrong"), with easier up/down navigation through
     the senses. Extends the FlaggedWords flow (`auth.js`/`flashcards.js`).
  5. **Offline + sync (biggest)**: full offline function (service worker caches the deck DATA,
     not just JS/CSS), progress + flags save to a local write-queue while offline and flush/sync
     to Sheets on reconnect, plus an offline/sync-pending indicator.

- **[now] Notes-app UI batch — requested 2026-07-24 [shared unless noted]**
  Easy items already SHIPPED this session (v55): "Collapse Lemmas" On/Off rename, short
  Cognates labels, brighter in-study progress bar. Remaining (non-trivial), roughly easy→hard:
  1. **(S) [normal] Flash the active step number** — on the setup/landing screen (both modes),
     slowly pulse the `.step-number` of the step awaiting a decision (pick language / pick set),
     so it's obvious where to act. CSS pulse is trivial; the work is toggling an `--active`
     class as the user advances through step1 → step2 → step4 (`ui.js`).
  2. **(S) [artist] Artist-mode help missing Lemma/Cognates tabs** — the step2 help tooltip has
     Level/Lemma/Cognates tabs (`index.html` ~L283), but they don't show in artist mode.
     Find where artist mode drops them and restore. Needs investigation.
  3. **(S) [shared/spanish] Highlight the "used with X" word in examples** — when a sense is
     tagged "used with X" (SpanishDict pattern, e.g. acostumbré → "used with a"), highlight that
     word wherever it appears in the example sentence, not just the headword.
     FEASIBILITY CONFIRMED (2026-07-24): the SD `context` field is structured — 5,567/5,854
     "used with" contexts match `used with "X"` (top tokens a/con/de/por/en/que/para…, small
     collocation tail like bien/grande). Josh's call: NO preposition whitelist — just parse the
     quoted token X and highlight whole-word occurrences of it in the example if present,
     whatever X is (a collocation word is fine to highlight). `context` is already on the card
     meaning (it's the "(used with a)" text), so this is front-end-only in `flashcards.js`.
     Optional cheap add: also stash the extracted X on the card/meaning object (e.g.
     `meaning.usedWith`) for later use — no UI needed now.
  4. **(M) [shared] Card back: POS pill above each section, not inside each row** — group senses
     by POS and render the POS-tag pill as a section header above the group (usually one POS +
     a few senses; scroll when many). Restructures the sense-list render in `updateCard()`
     (`flashcards.js`). Related to the card-back polish batch.
  5. **(M) [normal] Language picker → radial button** — replace the normal-mode language
     toggle/tabs with a button that opens a radial "clock of pictures" like the artist picker
     (`main.js showArtistPicker`). Reuse that component.
  6. **(M) [normal] Roll progress into the language box** — after a language is picked, in
     standard mode merge the progress section into the language box: language name beside the
     tiny % stats, progress bar directly underneath. Saves vertical space. Artist-mode top box
     stays as-is.
  7. **(M) [artist] Level scrubber granularity in the long tail** — in artist mode the `≥2`
     band is basically the entire long tail, so there's no resolution there. Explore a smarter
     split (sub-divide the low-integer tail by card-count within `≥2`/`≥3`, or a log split of
     the tail) so scrubbing the rare end is meaningful (`computeSmartLevelRanges` in `ui.js`).
     Design question — Josh asked "is there something smarter I could do?"
  8. **(M) [shared] Card-front frequency vs pooled examples mismatch** — in one-card-per-lemma
     mode the displayed frequency doesn't match the pooled example count (Josh saw `gasté`
     showing a much higher front-of-card frequency than its ≥2-tier / example reality). Make the
     card-front frequency reflect the same pooled basis as the examples. Related to the pooled-
     examples item below.

- **[soon] Pool examples per lemma in one-card-per-lemma mode (M) [shared] [cross-lang]**
  When the lemma-collapse filter is on (one card per lemma), the surviving card should pool
  examples from all the collapsed surface forms (quiero/quieres/quiere → querer card shows
  examples from each), not just the representative form's own examples. Requested 2026-07-12.
  SHIPPED 2026-07-13 (`poolLemmaSiblingExamples()` in js/vocab.js) — awaiting Josh's
  in-browser verification before moving to Decisions Made.

- **[idea] Conjugation table UI polish (S) [shared] [spanish]**
  Conjugation data layer is done (`conjugations.json` + `conjugation_reverse.json`).
  Front-end renders the table on card back but the UI needs improvement. French
  conjugations not in the pipeline yet — this item is Spanish only until they are.

- **[idea] Album-specific mode (M) [artist] [cross-lang]**
  Let users choose specific albums. Options range from light (filter example lyrics to chosen
  albums, keep full corpus count) to heavy (album-only deck with album-specific corpus count).
  Long-term extension: user provides their own song list and gets a custom deck. Probably far
  out — depends on the pipeline being easy to run for arbitrary input.

- **[now] Surface per-word "known lyrics %" in settings (S) [artist] [cross-lang]**
  Show what percentage of an artist's lyrics the user can understand the whole line for based on known words.

- **[idea] Find-word should open filter-excluded cards (M) [shared] [cross-lang]**
  Current search (top-bar magnifier) only jumps to words present in the currently-filtered
  deck; words removed by cognate/lemma/mastered filters show a "not available for this ranking"
  message and nothing happens. Make a click on any search result pull up a one-off "preview
  card" for that word regardless of filters, not counted toward progress.
  Preferred approach (option 1 from the 2026-04-16 discussion): extract a `buildSingleCard(item)`
  helper from the inline card-building logic in `loadVocabularyData()` (`js/vocab.js`, ~L565 and
  ~L859 — the normal and multi-artist paths both duplicate this logic). Then the search's
  "off-deck" click can call the helper, shove the result into `flashcards = [card]`, swap to
  card view, and flag the card so `saveWordProgress()` skips it. Non-trivial mostly because of
  the extraction work across two codepaths.

- **[idea] Synonym + antonym viewer (M) [shared] [spanish]**
  SpanishDict has a separate thesaurus endpoint at `/thesaurus/<word>` that returns rich
  structured synonym + antonym data in `thesaurusProps`. The relationship enum is clean:
  positive value = synonym (2 = strong, 1 = weak/related), negative = antonym (-2 / -1).
  For `bonito`: strong synonyms `lindo / guapo / hermoso / bello / precioso`,
  strong antonyms `horrible / feo`. Plan:
  - New scraper `pipeline/tool_5c_scrape_spanishdict_thesaurus.py` — same shape as
    `tool_5c_scrape_spanishdict_phrases.py`. ~10k words × 0.35s = ~1 h one-off, free.
    Writes `Data/Spanish/senses/spanishdict/thesaurus_cache.json` (gitignored).
  - New builder (or extension to tool_5d/5e): 4-way join on `senses` + `senseLinks` +
    `linkedWords` + headword to produce per-headword `{word, pos, strength}` lists.
    Partition by sign. Write to `Data/Spanish/layers/synonyms.json` keyed by word ID.
  - `step_8a` / `step_8b` attach `synonyms` + `antonyms` fields to each entry, same
    pattern as `morphology` / `cognate_obj`.
  - Front-end: add a button next to the conjugation button. Panel similar to conjugation
    table — synonyms in one column (strong bigger, related smaller), antonyms in another.
    Bonus: tap a synonym to jump to that word's card via the existing search mechanism.
  Unlike the conjugation button (verbs only), this applies to every POS, so it'd light
  up on most cards.

- **[idea] Unify PHRASE POS tag with MWE rows (M) [shared] [cross-lang]**
  Today there are two row shapes for phrase-like entries on cards: regular rows with
  `pos = "PHRASE"` (38 in Spanish vocab today, sourced from sense data) and MWE rows
  (`pos = "MWE"`, with `allMWEs`, expression pill, counter). They render differently —
  standard POS pill vs. expression pill — and have different data lineages (one lives in
  `meanings[]`, the other in `mwe_memberships[]`). Eventually these should collapse into a
  single phrase-row renderer that handles both, with a consistent pill width and layout.
  Opened after pulling PHRASE out of the shared POS-pill `min-width` constraint on
  2026-04-20 — the split widths (tight POS pill vs. wider expression pill) are a stopgap
  until the row types merge.

---

## Data / Pipeline

- **[idea] Evaluate Musixmatch translations as a supplementary/better translation source (L) [artist] [cross-lang]**
  Far future. Spotify's in-app lyric translations (global since 2026-02-04) are powered by
  Musixmatch, NOT Genius or Spotify-native — and Rosalía was one of the first artists covered.
  They are NOT on Spotify's public Web API (no lyrics endpoint); the only legitimate source is
  the **Musixmatch developer API**, whose translations + full/synced lyrics + any commercial use
  require a **paid, licensed tier** (free tier = 30% preview only). Reverse-engineered scrapers
  exist but violate ToS / are fragile — don't build on them. Low value right now: Genius+Gemini
  already cover ~98.7% of lines and `gemini-3.1-flash-lite` proposes senses well even with the
  translation field empty. Revisit only if (a) translation quality becomes a classifier
  bottleneck, or (b) a licensed Musixmatch plan is on the table. Investigated 2026-07-22.

- **[idea] Stamp `is_propernoun` in step 8b based on POS, not just step 4a routing (S) [artist] [cross-lang]**
  Currently `is_propernoun=true` only on entries that step_4a put in the
  `exclude.proper_nouns` bucket (Wiktionary-only-name + curated drops).
  Frequent proper nouns that survive into Gemini classification come back
  with `meaning.pos === 'PROPN'` but `is_propernoun=false`, so the flag on
  disk doesn't match what's actually a proper noun in the deck. The
  front-end works around this in `buildFilteredVocab` by also catching
  entries where every meaning has `pos === 'PROPN'` (2026-05-04). Pipeline
  fix: in `step_8b_assemble_artist_vocabulary.py` near line 1001, also set
  `is_propernoun = True` when every meaning's POS is PROPN. Then drop the
  runtime workaround. Same shape as the `is_english` provenance issue.

- **[idea] Properly deprecate `legacy_llm_analyze.py` — `is_english` provenance (M) [artist] [spanish]**
  The `is_english` flag on artist-mode entries currently still traces back to
  `pipeline/artist/legacy_llm_analyze.py` (the pre-split monolithic classifier).
  That file is named "legacy" and the rest of step 6 has moved to the
  `step_6a_assign_senses.py` dispatcher + `step_6b/6c` shared classifiers,
  but `is_english` (along with `is_propernoun` / `is_interjection`) hasn't
  been re-homed. Goal: make `is_english` come from a real, supported
  pipeline source — either a dedicated step (mirroring `step_7c_flag_cognates.py`
  for English-borrowing detection) or roll it into one of the existing
  step_6 classifiers — and then actually delete `legacy_llm_analyze.py`.
  Until then, the flag is set by deprecated code that's not part of the
  documented pipeline graph in `pipeline/CLAUDE.md`. Not blocking — flag
  works correctly today via the legacy path; this is hygiene + provenance.

- **[idea] Finish "Normal mode" → "Standard mode" rename (S) [shared] [cross-lang]**
  User-facing UI strings were renamed on 2026-04-18: About-page heading
  ("Standard mode (subtitles)"), top-bar toggle ("Standard Mode"), and
  About-page demo alt text. Everything else still uses "normal": internal
  identifiers (`activeArtist === null` means standard mode), code comments
  ("normal mode" in 20+ places), design-doc filenames
  (`translation_quality_normal_mode.md`), TODO `[normal]` mode tag,
  CLAUDE.md references, pipeline step labels ("Normal Mode" header in
  `pipeline/CLAUDE.md`), `run_normal_pipeline.py` entry point,
  `_step_defs_normal_mode` / `normal_only` flags, `spanish_normal_vocab`
  references, `normal_vocab` variables, `--normal-only` CLI flag. Worth
  a sweep in one commit when there's time; not urgent because the user
  never sees these.

- **[soon] Better handling of SpanishDict phrasebook analyses (M) [normal/artist] [spanish]**
  Implemented a patch on 2026-04-16 that routes phrase-only self-analyses (e.g.
  the `headword=está` PHRASE analysis) into the inventory's `known_lemmas[0]`
  so `está` shows as `está|estar` instead of a dead `está|está`. Works for
  está / estoy / vamos / vete / dame / sé etc. but it has rough edges:
  - The phrasebook senses (`he's`, `she's`, `it's`, ...) get **dropped** from
    the card because `get_senses_for_lemma` in `step_8a_assemble_vocabulary.py`
    only returns senses whose headword matches the lemma. Those pedagogically
    useful glosses aren't surfaced anywhere. Ideally the conjugation-specific
    phrase glosses should be shown on the `está|estar` card alongside the base
    verb senses — maybe as a separate "conjugation notes" section or attached
    to the relevant verb sense via the sense ID mapping.
  - Ambiguous forms (e.g. `sé` = saber 1sg *or* ser imperative 2sg) still
    produce two entries (`sé|saber` + `sé|ser`) because the classifier genuinely
    picks both analyses' senses. Known_lemmas from step_5b's conjugation reverse
    lookup misses secondary readings like this. Consider enriching the reverse
    lookup or doing a post-merge when two word|lemma entries both exist and
    one of them came purely from classifier assignments (not the inventory).
  - Only wired into normal-mode `step_7a_map_senses_to_lemmas.py`. The artist
    variant (`pipeline/artist/step_7a_map_senses_to_lemmas.py`) still calls
    `split_word_assignments` without passing `known_lemmas`. Add the same
    inventory load there when we want the fix in artist mode.
  - Root-cause fix would be at menu-build time: rewrite the phrase analysis's
    headword during `build_spanishdict_menu` so the sense_menu on disk is
    already consistent, instead of patching at step_7a. Keep that as a bigger
    refactor if we ever want to simplify.
  - Mixed-POS self-analyses still slip through: surface forms like `ve`,
    `escucha`, `vaya`, `pon`, `saca`, `toca`, `limpia` have a single self-
    analysis whose senses mix NOUN + PHRASE (e.g. `ve` = the letter V + the
    phrase gloss). The NOUN half legitimately lives under `ve|ve`, so
    `_is_phrase_only_self_analysis` correctly skips them, but the PHRASE
    senses inside the same analysis are still misattributed. Splitting
    *within* one analysis by POS would require menu-layer surgery and is
    covered by the root-cause refactor bullet above.

- **[soon] Spanish full pipeline regeneration after accent-twin fix (L) [normal] [spanish]**
  Spanish vocabulary is in a half-clean state after the 2026-04-26 accent-twin
  fix. **What we did:** plumbed `--word` into step_5a / step_6a / step_6c with
  per-word seeded RNG (`zlib.crc32(word)`) for deterministic reruns; removed
  `strip_accents` fallbacks from step_5a's sentence index and step_5c's
  Wiktionary index/`lookup_senses`; removed the `analyses[0]` fallback in
  step_8a's `get_senses_for_lemma`; language-scoped curated_translations.
  These code changes are language-agnostic — French already ran a full
  rebuild and is end-to-end clean. For Spanish, instead of regenerating
  examples (which would have churned 11k Gemini classifications and lost the
  user's example continuity), a one-shot helper
  (`/tmp/filter_accent_contamination.py`) walked existing `examples_raw.json`,
  identified entries whose target text didn't contain the literal target
  word as a token, and removed 5382 contaminated index references from
  `sense_assignments/spanishdict.json` (393 of 411 affected unaccented
  words). Existing clean examples + paid Gemini classifications preserved.
  Backup at `Data/Spanish/layers/_backups/spanishdict.before-accent-filter.json`.

  **Why semi-stale:** `Data/Spanish/layers/examples_raw.json` still physically
  contains the contaminated example entries on disk. They're orphaned (no
  assignment references them, don't appear in `vocabulary.json`) but remain
  until the next step_5a run.

  **Full rebuild plan** (do after new co-study scoring is validated on French
  and after inventory-artifact cleanup — the audit flagged ~411 unaccented
  entries like `mio`, `lastima`, `africa`, `frio`, `publico`, `abandono`,
  `iras` with 100% example contamination, suggesting the unaccented form is
  never legitimate Spanish for many of these and they should be deleted from
  `word_inventory.json` first):
  ```bash
  # Step_5a with new defaults (50k candidates / ±50 window / tier cap 10).
  # 30-60 min, no API.
  .venv/bin/python3 pipeline/step_5a_build_examples.py --language spanish

  # Full Gemini reclassification on cleaner examples — supersedes the
  # filter's preserved-but-imperfect classifications. ~$15-20, ~30-60 min.
  .venv/bin/python3 pipeline/step_6a_assign_senses.py \
      --language spanish --classifier gemini --sense-source spanishdict --force

  .venv/bin/python3 pipeline/step_7a_map_senses_to_lemmas.py --language spanish
  .venv/bin/python3 pipeline/step_8a_assemble_vocabulary.py \
      --language spanish --sense-source spanishdict
  ```
  After this, Spanish matches French's end-to-end cleanliness and benefits
  from the new co-study-rich scoring. The big-corpus run with the new params
  should also massively improve example quality (the French audit showed
  >90% of old examples were tier-0 under the co-study rubric).

- **[soon] Audit step_5d MWE strip_accents fallbacks (S) [shared] [cross-lang]**
  Closing gap from the 2026-04-26 accent-twin fix. With step_5a, step_5c,
  and step_8a all going strict-literal on accents, `pipeline/step_5d_build_mwes.py`
  is the last holdout: lines 127-128 and 173 still use `strip_accents` as a
  fallback when matching MWE parent words to the inventory. An MWE parent
  like `"más allá"` could silently fall back to the unaccented inventory
  entry `"mas"` if `"más"` isn't in the inventory, misattributing the MWE.
  Probably benign in practice (most MWE parents are well-formed accented
  words that match directly) but worth tightening for consistency. Replace
  the `strip_accents` fallbacks with literal lookups; if a legitimately
  accented MWE parent fails to match, surface as a warning rather than
  silently accent-stripping.

- **[I think this is done] Wire multi-word elision split into tokenization (M) [artist] [spanish]**
  Config exists at `Artists/curations/multi_word_elisions.json` mapping contracted
  surface forms to expanded Spanish (e.g. `"pal'" -> "para el"`). Step 2a
  (count_words) needs to consume this config and do pre-tokenization substitution
  so counts go to each expanded word. The original contracted form should stay
  visible in example sentences (not replaced in display), and the `surface` field
  on each expanded word should retain the original contracted form. After wiring,
  add entries for common Caribbean two-word contractions beyond `pal'` / `pa'l`.

- **[this might be done] Generic s/z elision handling (S) [artist] [spanish]**
  Currently `lu' -> luz` is a manual override in the elision mapping because the
  automatic merger only handles s-elisions (word-final s replaced by `'`).
  Generalise to also match z-elisions (`luz -> lu'`, `cruz -> cru'`, etc.) and any
  other systematic patterns. Watch for false positives — not every `x'` is an
  elision of `xz` or `xs`.

- **[dumb] Map remaining SpanishDict POS labels instead of dropping to X (S) [shared] [spanish]**
  `normalize_pos()` in `pipeline/util_5c_spanishdict.py` falls through to `"X"` for
  any SpanishDict POS label it doesn't recognize. Currently X senses are mostly
  morphological prefixes (des-, di-, neo-) which are legitimately noise, but there
  may be useful categories getting lost too. Scan every distinct SpanishDict label
  that produces X and decide per-label: add a proper mapping, fold into an existing
  category, or leave as noise. See also `_ORTHOGONAL_POS` in
  `pipeline/util_6a_pos_menu_filter.py` — if any new category is orthogonal to
  grammar (like PHRASE/CONTRACTION), add it there.

- **[soon] Move elision resolution before tokenization (M) [artist] [spanish] [design doc]**
  Elision merging currently happens in step 5, after step 3 caps examples at 10.
  Should resolve elisions in a preprocessing pass on raw lyrics so step 3 counts
  canonical forms directly. Eliminates step 5, gives exact counts, and lets
  ambiguous elisions (ve'→vez/ves) disambiguate on every occurrence.
  See [`elision_resolution_refactor.md`](docs/design/prompts/elision_resolution_refactor.md).

- **[soon] Find better English frequency list (S) [artist] [cross-lang]**
  English 50k wordlist filter is implemented in step 4 (catches 85 words for Bad Bunny,
  ~3 false positives). Current source is hermitdave/FrequencyWords OpenSubtitles-derived
  list — contains foreign words that leaked into English subtitle files (gare, pali, vou).
  Find a cleaner source: COCA, BNC, or Google Books ngrams. The list just needs to be
  common English words an English speaker would recognise. Currently at
  `Data/English/en_50k_wordlist.txt`.

- **[soon] Homograph lemma filtering — minor lemma flag (L) [shared] [cross-lang] [design doc]**
  When a surface form maps to multiple lemmas (e.g. "como" → como|como + como|comer),
  flag the less common lemma pairing so it can be filtered or deprioritized. Currently
  como|comer shows as a top-frequency word when it's actually rare. Inverse of
  `most_frequent_lemma_instance` (which picks the best *form* per lemma — this picks
  the best *lemma* per form). Could use POS-tagged corpus frequency or conjugation
  reverse lookup to determine which lemma dominates.

- **[idea] Artist sense pipeline: Wiktionary-sourced senses (L) [artist] [cross-lang] [design doc]**
  Switch artist mode from "Gemini invents senses" to "pick from Wiktionary senses + classify."
  Would eliminate sense proliferation and cross-artist inconsistency. MWEs cover most idiomatic
  gaps. Gemini fallback only for words Wiktionary doesn't have. See `docs/design/artist_sense_pipeline.md`.
  (Already the default for French — artist_sense_pipeline.md describes the Spanish version.)

- **[idea] Run MWE corpus frequency on full OpenSubtitles (S) [shared] [spanish]**
  Currently using 10% sample (`SAMPLE_STRIDE=10` in `build_mwes.py`). Full corpus would
  give better granularity for ordering. Change `SAMPLE_STRIDE` to 1 and re-run:
  ```bash
  # Edit pipeline/build_mwes.py: SAMPLE_STRIDE = 1
  .venv/bin/python3 pipeline/build_mwes.py
  .venv/bin/python3 pipeline/artist/run_pipeline.py --artist "Bad Bunny" --from-step build
  .venv/bin/python3 pipeline/artist/run_pipeline.py --artist "Rosalía" --from-step build
  .venv/bin/python3 pipeline/artist/run_pipeline.py --artist "Young Miko" --from-step build
  ```
  Estimated ~5 minutes for the full 105M lines. Tatoeba adds negligible signal over full OpenSubs.

- **[idea] Improve cognate flagger (M) [shared] [cross-lang]**
  Converged into `shared/flag_cognates.py`. Could improve: add more suffix rules,
  tune similarity threshold, reduce false positives on short words, add LLM flagging
  to normal mode pipeline.

- **[idea] Separated reflexive clitic detection (L) [shared] [spanish] [design doc]**
  When a reflexive clitic is separated from its verb (e.g. "se vuelo", "me voy"), the
  pipeline currently has no way to know the verb should be matched against reflexive
  senses (volarse, irse) rather than the base form (volar, ir). Attached clitics are
  already handled (morphologically visible). Separated clitics need dependency parsing
  or heuristic co-occurrence detection to link the pronoun to its verb. Discovered via
  the "vuelo" case in Bad Bunny — keyword fallback assigned "cogiendo vuelo" to volarse
  sense "to fly off" (fixed by per-example POS filtering), but the underlying problem
  remains for genuine separated-clitic verb uses.

- **[idea] Sense dedup polish — English conjugation (S) [shared] [cross-lang]**
  Generated 3rd-person translations say "he/she go" instead of "he/she goes".
  Would need English conjugation logic in `merge_to_master.py:choose_canonical_translation()`.

- **[idea] Auto-populate album dictionaries from Genius (M) [artist] [cross-lang]**
  Scrape Genius album pages to auto-assign songs to albums. Currently manually curated.
  Not urgent — only 2 artists and their dictionaries are complete.

- **[idea] Multi-language generalization (L) [shared] [cross-lang] [design doc]**
  Generalize `build_examples.py` to accept language as argument.
  Download Tatoeba pairs for Italian, Swedish, etc.
  Generate per-language frequency ranks and vocabulary.json.
  Spanish/Swedish/Italian/Dutch/Polish vocabs already exist in Data/ but only Spanish has
  the full pipeline.

---

## French

Items specific to French vocabulary, pipeline, or dictionary sources.

- **[idea] SpanishDict-equivalent for French (L) [artist] [french] [design doc]**
  After the 2026-04-18 Wiktionary enrichment, the French sense menu has
  `context` / `register` / `example` fields parsed out of Kaikki, plus a
  Wiktionary-phrase tier (c'est / j'ai / qu'il stay as their own cards). The
  enwiktionary French slice has coverage gaps though — missing conjugations
  (e.g. `a` as avoir 3sg), thin on colloquial/regional French, and `context`
  is whatever Wiktionary editors happened to write rather than a curated
  sub-sense label. Staged plan:
  (1) ship the enrichment and see if real French use surfaces friction;
  (2) if coverage gaps hurt, add the Kaikki French-Wiktionnaire (`fr-extract`)
      as a supplement layer — mirrors the Spanish `eswiktionary` dialect
      supplement, ~1 day, free;
  (3) if we want true SpanishDict parity, scrape Le Robert into
      `pipeline/util_5c_lerobert.py` mirroring `util_5c_spanishdict.py`
      (1–2 weeks; best-quality free French sense data).
  Paid APIs (Oxford £50/mo, Lexicala enterprise) surveyed but not recommended.
  See [`prompts/french_dict_equivalent.md`](docs/design/prompts/french_dict_equivalent.md).

- **[idea] French conjugation layer (M) [shared] [french]**
  French pipeline has no `conjugation_reverse.json` today — so step_5c's
  conjugation-based POS filter (which prunes non-VERB senses from confirmed
  verb forms in Spanish) is a no-op for French. French conjugator candidates:
  `verbecc` supports French; `spacy-lefff` gives UD-style lemmas from spaCy.
  Would also enable the card-back conjugation table for French.

- **[idea] Broader French test corpus (S) [artist] [french]**
  TestPlaylist is one playlist. Once a real French artist is picked (Aya
  Nakamura, Angèle, …), rerun the pipeline on their catalog to see what the
  first-pass output actually looks like at scale.

---

## Vocabulary Issues

Items noticed while using the app. When fixing, investigate whether it's a symptom of a bigger
pipeline/data problem. Delete items from this list once resolved.

(none currently)

---

## Songs to Exclude

Songs that shouldn’t be in the corpus (remixes, live versions, non-artist songs, etc.).
Add to `duplicate_songs.json` and check for similar songs. Delete once resolved.

(none currently)
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
