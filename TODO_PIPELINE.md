# Fluency — Pipeline / Data TODO (Claude-owned)

<!-- Claude's backlog for the pipeline/data engine. Codex's app/UI backlog is TODO.md.
     Ownership + rules: COLLABORATION.md. Don't start items without Josh's go-ahead. -->

## Key
**Priority:** `now` = next up | `soon` = near-term | `idea` = someday
**Size:** `S` hours | `M` half-day | `L` multi-session

---

## Architecture: persistent, audited tag pipeline (Josh's reframe, 2026-07-26)

- **[now] Turn routing from a one-shot gate into a persistent tag layer (L) [cross-lang]**
  The recurring pain is routing being an imperative one-shot decision with no oversight —
  every tweak means a rerun and Josh can't see what changed. Reframe: **every word carries
  a set of TAGS with provenance/evidence, accumulated across steps** (word_routing bucket,
  english_loanwords, cognates, detected_proper_nouns, spanish_forms, en_50k, corpus_count,
  word==translation, and later Gemini-added tags). Any step may add/adjust a tag or attach
  evidence; the final routing bucket is a RESOLVER over the tag set, not a hard-coded call.
  Design requirements:
  - **Tags persist end-to-end** and are the audit surface (largely a front-end concern too:
    Main vs Extra vs loanword/PN grouping reads them). Fine-grained meanings allowed.
  - **Multi-evidence, never collapsed:** a word can hold MANY tag assertions from different
    sources at once (word + tag + source + evidence) — cheap to store, keep them all as the
    audit trail (e.g. "english (en-list)" AND "spanish-word (Gemini)" can coexist). A separate
    **configurable evidence hierarchy** resolves conflicts into the effective bucket. Same
    shape as `util_6a_method_priority.py` (assignments coexist additively; priority decides
    the winner, never overwrites) — a trusted pattern, applied to routing tags.
  - **Over-tag > under-tag** — a false tag lands in Extra, not oblivion (the architecture
    change that makes aggressive detection safe now; the old routing was de-tuned precisely
    because false positives HID cards — that tradeoff is gone).
  - **Tag-based-rerun store, minimal + targeted:** a tag/rule change queues a word ONLY if
    the resolved routing now FLIPS it into a needs-Gemini state (exclude→classifier /
    sense_discovery) it has no cached result for. Moving a word TO an exclude bucket, or
    between states it's already been classified in, queues nothing. Queued words go into an
    explicit `tag_based_reruns` list that Josh runs as a targeted pass — never an automatic
    Gemini call. Cached Gemini results (incl. Extra ones) are kept and never re-paid.
  - **Absorbs per-use loanword tagging** (the lean class): a word can have SOME occurrences
    tagged loanword and others target-language. Feasible without violating the counts rule
    because homographs are a small set → classify ALL their occurrences (not a capped
    sample). This lives in the tag layer, not a step_8b hack.
  - **Oversight dashboard (v1 SHIPPED 2026-07-26):** `pipeline/artist/tool_4a_tag_dashboard.py`
    → `Artists/<artist>/data/reports/routing_tags_dashboard.html`. Sortable/filterable table
    of every routed word + its tags + conflict flags; mark rows wrong + pick corrected bucket
    → exports `routing_corrections.json` that feeds the next routing-rule audit. First run
    (Bad Bunny): 619 flagged — homograph-en-es 315, missed-loanword 292, propn-maybe-wrong
    205, loanword-layer-unrouted 198, high-count-excluded 103. This IS the "what needs work"
    list, now interactive.

- **[now] Counts must be corpus-derived, never example-cap-gated (M) [cross-lang]**
  The example cap exists only to avoid translating `para` 800× through Gemini — it must NOT
  affect any count/frequency/rank anywhere, steps 1–9, any language. Known leak: `step_8b`
  splits a word's `corpus_count` across lemma-groups **proportionally to assigned example
  weights** (capped) — so multi-lemma count splits are example-gated today. Audit every step
  for counts derived from the sampled/assigned example set instead of step-2 corpus
  occurrences, and cut them over to true counts. (This is why the earlier evidence-based
  representative-selector attempt was wrong — it ranked by capped example counts.)

## Bugs found

- **[implemented 2026-07-27; coordinated deck rebuild pending] Plural self-headwords and diminutive-family identity (M) [spanish]**
  SpanishDict explicitly exposed `besitos` as an inflection of `besito`, but its
  parallel self-headword analysis also created `besitos|besitos`. Step 7a and
  both builders now consolidate regular nominal/adjectival plural twins under
  the singular lemma while preserving all existing sense IDs, so no Gemini
  rerun is required. Diminutives are deliberately not collapsed into their
  semantic base: a conservative audited relation layer links `besito` to
  `beso`, and the app labels that relationship without sharing card progress.

- **[~mostly fixed] Gemini-3.1 slang proposals were being dropped before the deck (L) [artist/spanish]**
  CORRECTED 2026-07-27 (supersedes the earlier "5,807 words bypass the classifier / 63% menu
  coverage / TOP QUALITY LEVER" writeup, which was WRONG). That number measured the *shared*
  normal-mode menu (`Data/Spanish/layers/sense_menu`, 9,945). The **per-artist** menu
  (`Artists/.../data/layers/sense_menu/spanishdict.json`, 8,915) DOES cover the slang, and
  gemini-3.1 DID classify it: `guagua`/`charro`/`chilla` each had a correct gap-fill proposal
  (car/van/truck, scrub/jerk/loser, side chick) sitting in `sense_assignments`. The bug was that
  those off-menu proposals were dropped three times over (step_7a split, priority tie-break,
  step_8b assembly). Fixed + deck rebuilt in commit `a30a6250` — those words now render right.
  REMAINING (smaller, real): words with no correct proposal to salvage —
  `trapero` (spanishdict-flash-lite menu-pick only, 3.1 accepted a wrong menu sense, no proposal
  → needs a re-classify to get "trap rapper") and `tequi` (spanishdict-auto single-sense default,
  priority 0, never really classified). Plus apostrophe/elision forms (`na'`/`to'`/`mirá'`) that
  `step_6c` skips by design. These need a targeted Gemini rerun (or, for elisions, routing work),
  NOT a menu rebuild.

- **[now] SpanishDict fuzzy-spelling matches create a wrong-lemma card (M) [artist/spanish] — needs curation, NOT auto-fixable**
  When SD has no exact entry for a surface word it returns a spell-corrected neighbour with no
  morphological link: `manín`→`maní` "peanut", `beibe`→`bebe`, `celu`→`celo`, `chulito`→`culito`,
  `foke`→`fake`. Post-`a30a6250` the correct gap-fill meaning now renders (`manín`→"my man"), but
  the fuzzy menu card still shows alongside it. Signal explored 2026-07-27: `surface_cache.json`
  has `possible_results` (per surface, with `heuristic:conjugation/inflection` justifying a real
  lemma, e.g. `cantamos`→`cantar`); a fuzzy match like `manín`→`maní` has `possible_results: []`.
  BUT this is NOT a safe auto-rule: empty `possible_results` also covers legit clitic/reflexive
  forms (`darnos`→`dar`, `mamar`→`mamarse`), and prefix/edit-distance relatedness misfires in
  BOTH directions — it wrongly ties `manín`~`maní` (shared "mani" prefix) yet misses `luces`~`luz`
  (real plural, no shared prefix). Every automatic signal reintroduces wrong cards. RECOMMEND: a
  curated suppression layer (surface|bad_headword pairs the menu-build/step_8b drops). A
  high-precision candidate list (~111 gap-fill words × fuzzy menu headword, with the real meaning
  shown) is regenerable from `surface_cache` + `sense_assignments` (script logic in this session's
  history; scratchpad `fuzzy_menu_candidates.json`). Watch the false positives in it: `asi`→`así`
  and `cash`→`efectivo` are actually CORRECT and must not be suppressed.
  (Was filed as "homograph de-dup / assembly picks wrong entry"; the real cause is SD fuzzy
  matching, not homograph selection. Related surfaces: `vine`→"vid", `tar`, `quiles`.)

- **[now] Syllable-repeat adlib non-words not caught as noise (S) [artist/spanish]**
  `tera` (from `entera-tera`), `rrear` (from `perrear, -rrear`), `nio` (from `ni`) survive as
  cards. Add a step_2a noise rule for trailing-syllable repeats. (Josh's flag note.)


- **[now] Lemma-mapping misses leave inflected forms stranded (M) [artist/spanish]**
  Spotted 2026-07-26 in Bad Bunny Extra: `vengamos` (→ venir), `estuviésemos` (→ estar),
  `dolares` (→ dólar/dólares), `abaje` (→ abajar?) appear as standalone one-off cards instead
  of merging into their recurring lemma. These are conjugated/inflected forms `step_7a` (lemma
  mapping) / `conjugation_reverse` coverage missed — accents (`estuviesemos`→`estuviésemos`,
  `dolares`→`dólares`) and subjunctive/rare forms are the likely gaps. Fixing this also removes
  them from the "one-off" longtail (they become part of a Main lemma). Distinct from tagging.

## The gate (do before scaling anything)

- **[now] Routing / classification correctness — designed cross-language (L) [es+fr+nl]**
  Josh is not yet convinced the pipe is ~99% correct at routing every word to the right
  bucket: cognate vs proper-noun vs real-word vs English/loanword vs slang. Goal: a
  **measured** accuracy number, not a vibe, and cheap heuristics carrying the confident
  majority so Gemini use stays minimal.
  **Design cross-language from the start — do NOT perfect on Spanish then port.** The
  routing scaffold (`word_routing.json`, `cognates.json`, `english_loanwords.json`,
  homograph) currently exists for **Spanish only**, and leans on **SpanishDict**; French
  and Dutch are **Wiktionary-only** with a messier dict backbone and none of those layers.
  So treat the **dictionary backbone as a pluggable per-language component**, and lean
  harder on the dict-agnostic heuristics (caps-rate, translation-identity) which is exactly
  what carries FR/NL where the dictionary signal is weaker.
  Roles: **Spanish = accuracy oracle** (only language with flags/curations ground truth);
  **French = concurrent real-data stress test** (12k entries, Wiktionary-backed — keeps
  Spanish assumptions from leaking in); **Dutch = bootstrap check** (100-word stub — prove
  the scaffold stands up from scratch, don't chase deck quality yet).
  - Build a routing-accuracy harness scored against ground truth we already have:
    in-app FlaggedWords + `shared/curated_translations.json` (regression set) + known
    homograph/proper-noun overrides.
  - Push deterministic heuristics for the high-confidence majority:
    * **capitalisation RATE** across occurrences (mid-sentence caps → proper noun), not
      any single capital;
    * **translation == source word** → transparent cognate or proper noun (disambiguate
      by capitalisation + dictionary presence);
    * dictionary/known-vocab presence → real word vs noise.
  - **Loanword / slang / register tags:** do NOT add a separate Gemini pass. Ride them
    along in the EXISTING classify-or-propose sense call (one call, structured output),
    per the "solve in one call" principle.
  - Make it language-parameterised (per-language cognate reference, caps rules, known
    list) so French/Dutch inherit it.
  - Output: routing accuracy % + a short list of the residual cases that genuinely need
    Gemini.

  **AUDIT FINDINGS (2026-07-26, routing subagent) — two high-leverage fixes:**
  1. **`lean`/`leer` is a ROUTING bug, not a representative-selector bug (confirmed 2026-07-26).**
     The `leer` card displays `lean` because the representative selector (`step_8b:1456`,
     `step_8a:1015`) picks `max(corpus_count)`, and `lean`=24 (9/10 lines are the English drug
     noun; only 1 is "read", vs `leer`=3 assigned). **Tried and REVERTED** ranking by assigned-
     example evidence: assigned counts are capped per sense, so it can't tell `lean` (off-lemma)
     from `hacer` (legit high-freq, low-assignment) — sandbox-tested on the live BB deck, it
     flipped 84 lemmas incl. clear regressions (`hacer`→`hago`, `igual`→`iguales`). Both have a
     ~24:1 count:evidence ratio; only routing/sense knows `lean`'s occurrences are a different
     word. **Correct fix = route the drug-`lean` occurrences to a separate English-loanword noun
     entry so they never inflate `leer`'s group — then the plain `max(corpus_count)` rule is
     right.** So this folds into the loanword-routing work below (fix #2). Note: `lean` is NOT in
     `english_loanwords.json`, and it collides with a valid Spanish inflection, so catching it
     is the hard residue — likely needs the per-example evidence check or a small targeted Gemini
     pass on the ambiguous surface. No front-end change needed once routing is fixed.
  2. **`english_loanwords.json` exists (1,606 Wiktionary-etymology entries) but is UNUSED in
     routing** — it's only a post-hoc UI stamp behind a toggle. Wiring it into `step_4a` routing
     is the generalizable loanword lever (worse in FR: week-end/parking/shopping/cool). Root
     cause of the miss: `step_4a:599-612` Phase-4 English fallback only fires `if w in en_50k
     and w NOT in spanish_forms`, so any English word Wiktionary also lists as a Spanish form
     (or that collides with an inflection, like `lean`) bypasses it. Add: loanword-layer
     membership + **translation-identity** (`word == translation`, ~free) + en_50k-with-freq-
     thresholds. Hard residue (code-switched slang not in Wiktionary, e.g. `lean`) needs the
     evidence check from fix #1 or Gemini.
  - Proper-noun detection (`detected_proper_nouns.json`) over-fires on line-initial caps
    (polluted with verb forms/interjections) → cheap fix: caps-RATE on non-line-initial tokens
    + exclude `spanish_forms` verbs/adjs. Ground-truth file: `sd_insufficient_review.json`
    (1,785 Gemini-typed items: 916 slang / 98 loanword / …; note `type=slang` on a normal word
    is a proposed extra sense, NOT a mis-route).

## Sense-assignment quality (the other half of the gate)

- **[now] Confirm sense-assignment prompt + model are locked (M) [spanish]**
  Validate that gemini-3.1-flash-lite classify-or-propose is good enough to scale on.
  Known residuals: F4 sense-lumping (all a form's examples on one sub-sense), ambiguous
  forms routed as noise (e.g. `des` = dar-subjunctive). Decide: accept, reprompt, or
  strong-model the flagged minority. Explore (don't commit yet) per-morphological-category
  sense assignment + word tagging as part of "is it granular/correct enough".

## Scaling / new inputs (after the gate)

- **[soon] Parsimony pass — cheap reruns (M)** so new artists/languages don't require
  painful full reruns (cache reuse, skip flags, ID stability).
- **[now, concurrent with routing] French + Dutch onto the new architecture (L)** — NOT
  after the gate; developed *alongside* routing so it's designed cross-language (see gate
  item). French is far along (12k entries, sense assignments done) and mostly needs
  architecture alignment + a routing layer; Dutch is a 100-word stub and is closer to
  greenfield. Both are Wiktionary-only — the open structural question is the dict backbone
  (cf. the `prompts/french_dict_equivalent.md` design doc). Spanish stays the accuracy
  oracle; FR/NL accumulate their own flags/ground truth over time.
- **[soon] New artist / Spanish playlist onboarding (M)** — bring in more artists once
  the pipe is parsimonious + confirmed correct.
- **[now-ish, not secondary] Normal-mode Spanish full pipeline regeneration (L)** — the
  half-clean state after the accent-twin fix (full detail in `TODO.md`'s Data/Pipeline
  section). Downstream of the gate: once prompt/model/routing are confirmed, this is
  "just run the confirmed engine".

## Data for the Extra-mode redesign (feeds Codex's presentation)

- **[soon] Emit Extra-scope group tags (M)** — Josh wants Extra split into meaningful
  groups (all English words / proper nouns / once-only / region-specific slang, e.g.
  Puerto Rico). That grouping is a CLASSIFICATION output of the routing work above.
  Deliverable: clean group-label tags in the deck data (documented in
  `docs/pipeline_data_shapes.md`) so Codex can render the groups and Josh can drop the
  "show only once" user toggle. Depends on good proper-noun + English + slang detection.
