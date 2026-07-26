# Fluency — Pipeline / Data TODO (Claude-owned)

<!-- Claude's backlog for the pipeline/data engine. Codex's app/UI backlog is TODO.md.
     Ownership + rules: COLLABORATION.md. Don't start items without Josh's go-ahead. -->

## Key
**Priority:** `now` = next up | `soon` = near-term | `idea` = someday
**Size:** `S` hours | `M` half-day | `L` multi-session

---

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
  1. **Lemma-representative selector is evidence-blind (architecture bug, all 3 languages).**
     `step_8b:1456-1460` (artist) and `step_8a:1015-1025` (normal) both pick the display form
     by `max(corpus_count)` = raw *homographic* surface count. That's why the `leer` card shows
     `lean` (surface count 24, but 9/10 examples are the English drug noun; only 1 is "read",
     while `leer` itself has 3 assigned). Fix = pick representative by **lemma-assigned example
     evidence** (builder already computes `assigned_weights`/`group_counts` at `step_8b:850-859`).
     Land the fix in **both `step_8a` and `step_8b`** so FR/NL inherit it (French already shows
     the same failure mode: 777/2533 multi-surface lemmas have a non-lemma representative).
     PAIRED front-end fix = `js/vocab.js:2139-2149` re-stamps the flag with the same flawed rule
     on multi-artist merge → **Codex's** (flag to him; only bites when merging 2+ artists).
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
