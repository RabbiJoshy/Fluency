# Fluency — Pipeline / Data TODO (Claude-owned)

<!-- Claude's backlog for the pipeline/data engine. Codex's app/UI backlog is TODO.md.
     Ownership + rules: COLLABORATION.md. Don't start items without Josh's go-ahead. -->

## Key
**Priority:** `now` = next up | `soon` = near-term | `idea` = someday
**Size:** `S` hours | `M` half-day | `L` multi-session

---

## The gate (do before scaling anything)

- **[now] Routing / classification correctness audit (L) [spanish first, language-agnostic]**
  Josh is not yet convinced the pipe is ~99% correct at routing every word to the right
  bucket: cognate vs proper-noun vs real-word vs English/loanword vs slang. Goal: a
  **measured** accuracy number, not a vibe, and cheap heuristics carrying the confident
  majority so Gemini use stays minimal.
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
- **[soon] French + Dutch onboarding (L)** — validate the language-agnostic routing +
  sense engine generalises. This is the generalisation TEST of the gate work above.
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
