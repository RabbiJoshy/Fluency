---
title: Artist pipeline architecture review — weaknesses before scale-out
status: research
language: cross-lang
created: 2026-07-28
updated: 2026-07-28
---

# Artist pipeline architecture review

Written 2026-07-28, before Josh scales to speech mode, other languages, and more
artists. Question asked: *is there a weakness in the architecture?* Yes — several,
ranked by how directly they threaten the scale-out. Grounded in the current code,
not memory.

## Tier 1 — structural, fix before ANY scale-out

### 1. No provenance on sense assignments (the foundational gap)
An assignment records *what* (`sense`, `examples`, gloss) but nothing about *who*:
no model, no prompt version, no run timestamp. Consequences already bit us:
- Ties between runs resolve by **dict/file order** (`resolve_best_per_example`),
  which is why correct 3.1 proposals lost to stale menu-picks (the guagua fiasco).
- You cannot answer "is this deck fully on the latest Gemini?" — the exact question
  Josh wants to guarantee — because the data doesn't know what produced it.
- Every rerun is a destructive gamble instead of a clean supersede.

At one artist this is annoying. At N artists × M languages × repeated model
upgrades it's unmanageable. **This is the single most important weakness.** Design
exists: `sense_provenance.md` (prompt registry + `prompt_id`/`run_ts` + resolution
by capability tier). Build it first — everything else compounds on top of it.

## Tier 2 — blocks multi-language quality specifically

### 2. Two divergent Gemini prompt paths
There are **two parallel classifiers** in `step_6c`:
- **SpanishDict path** (`classify_or_propose_batch`, called at ~1407): the modern
  unified "classify or propose" prompt, defaults to **gemini-3.1-flash-lite**,
  carries `type`/`construction`, and now the `proper_noun` slot.
- **Wiktionary path** (`classify_batch_gemini` ~1648 + `gap_fill_batch_gemini`
  ~1784 + `_repair_proposed_sense`): older, **split** classify-then-gapfill prompts
  on **gemini-2.5-flash-lite**, with none of the above improvements.

SpanishDict is Spanish-only. **Every non-Spanish artist uses Wiktionary → the old
path.** So the moment Josh adds a French/Dutch artist, sense quality silently drops
to the un-improved 2.5 classifier. Fix: unify all sense-sources onto the
classify-or-propose architecture (the menu is source-agnostic; the prompt need not
be SD-specific). This is the highest-leverage change for the multi-language goal.

### 3. Language-specific logic isn't behind a clean seam
SD fuzzy-match handling, SD phrasebook analyses, `spanish_forms.json`, homograph
overrides, clitic tiers, elision merging — all Spanish-specific and **scattered
across steps 3/4/5/7/8**, not isolated behind a "language adapter." A new language
re-proves all of it by trial and error. The pipeline is really "Spanish, with
Wiktionary bolted on," not "language-parameterised." Before language #2 is
comfortable, the language-specific pieces should sit behind one interface
(tokeniser/lemmatiser, sense-source, form tables, routing rules) with a documented
contract.

## Tier 3 — correctness debt that compounds at scale

### 4. Counts coupled to the example cap
The 10-example cap exists only to bound Gemini cost, but it **leaks into counts**:
`step_8b` splits `corpus_count` across lemma groups proportionally to *assigned
(capped) example weights*. Frequencies drive levels; if frequency is example-cap-
gated, level estimates are subtly wrong — and speech mode is *entirely* frequency-
driven. Counts must be corpus-derived everywhere (already flagged in
`TODO_PIPELINE.md`). Audit every count/rank for a sampled-set dependency.

### 5. Routing is a one-shot gate, not an audited tag layer
Routing (step_4a) is where most **per-artist tuning** happens, yet it's an
imperative one-shot decision: no oversight of what changed, every tweak needs a
rerun, and false positives *hide* cards (so detection was de-tuned). The most-tuned
layer is the least reusable/auditable — exactly backwards for onboarding artists.
Josh's own reframe (persistent multi-evidence tag layer + resolver, mirroring
`util_6a_method_priority`) is the fix and is already specced in `TODO_PIPELINE.md`.

## Tier 4 — smaller, but worth doing while here

### 6. No standing prompt-eval regression suite
The good prompt is "LOCKED, validated by scratchpad evals" — but those evals aren't
a gate. Josh wants to *rewrite prompts*; without an automated sufficiency eval on a
fixed labelled set, every reword risks a silent regression. Promote the scratchpad
evals to a committed `bench_*` suite run before/after any prompt change.

### 7. Model version is scattered and doc-stale
The current model is chosen per-path (3.1 for SD, 2.5 for wiktionary) and
`CLAUDE.md`/`pipeline/CLAUDE.md` still say "default 2.5-flash-lite." There's no
single source of truth for "the model we're on now." Folds naturally into the
prompt registry (#1): the registry entry names the model.

### 8. Example selection affects classification
Which ≤10 examples get sent shapes the dominant-sense decision. A word used 50× but
sampled 10× can mis-rank its senses. Worth a deliberate sampling strategy (spread
across songs/contexts) rather than first-N.

## How this maps to Josh's stated goals
- **"Everything on the latest Gemini"** → needs #1 (provenance) + #7 (model source
  of truth). Today you can't even *measure* it.
- **"Rewrite the prompt"** → do it once, unified (#2), gated by an eval (#6).
- **"Other languages"** → #2 and #3 are the blockers.
- **"Other artists"** → #5 (routing reuse) + #4 (counts) + #1 (safe reruns).
- **"Speech mode rerun"** → #4 (frequency truth) most of all.

## Recommended order
1. **Provenance / prompt registry (#1, #7)** — the substrate for everything else.
2. **Unify the two prompt paths (#2)** + stand up the eval suite (#6) — then do the
   prompt rewrite once, safely, for all languages.
3. **Counts decoupling (#4)** — before speech mode.
4. **Tag-layer routing (#5)** and **language seam (#3)** — before artist #4 / a new
   language.

None of this is a rewrite; it's paying down four pieces of structural debt in the
order that unblocks the scale-out. The pipeline is sound — its weakness is that the
parts that must vary at scale (model, prompt, language, routing) are the parts
currently hard-coded or unaudited.
