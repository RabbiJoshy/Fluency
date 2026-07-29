---
title: Sense-assignment provenance (prompt registry + resolution order)
status: research
language: cross-lang
created: 2026-07-27
updated: 2026-07-29
---

# Sense-assignment provenance

## Implemented — structure-first (2026-07-29)

The provenance *structure* is now in place end-to-end; the tier-based
**resolution re-rank (§3) is deliberately NOT wired yet** (the resolver still
picks the highest method priority — see "remaining"). What landed:

- **`config/prompt_registry.json`** — the registry (`sd-cop-v1`, `sd-cop-v2`,
  `legacy-unknown`) with `capability_tier`/`model`/`family`/`notes`.
- **Per-assignment stamp** — items now carry `prompt_id` + `run_ts`.
  - *Go-forward:* `step_6c_assign_senses_gemini.py` stamps every item it writes
    with `--prompt-id` (default `sd-cop-v2`) + a UTC `run_ts`
    (`util_6a_assignment_format.stamp_provenance`).
  - *Backfill:* `pipeline/tool_6a_backfill_provenance.py` stamped 242,289
    historical items across 21 files. **Correction to the original plan:** the
    persisted format does *not* keep `type`/`construction`, so the only provable
    3.1-run signal is the **`gap-fill` method key** → `sd-cop-v2`; everything
    else → `legacy-unknown`. `run_ts` best-effort from each file's
    `.meta.json` `generated_at` (epoch → ISO).
- **Threading to the card** — `resolve_best_per_example` carries `prompt_id`/
  `run_ts` (additively; winner selection unchanged); `step_8b` emits per-sense
  `sense_prompt_ids` / `sense_run_ts` in the index (keyed off an authoritative
  `sense_id → provenance` map, `resolve_sense_provenance`, since assignment sids
  are menu-local and remap to master sense_ids). `merge_items` now preserves
  extra fields (was silently dropping `pos`/`translation`/`example_ids` on
  sense-id collisions — latent bug, now fixed).
- **Card info panel** — JST-gated `ⓘ` button on the card back
  (`buildProvenancePanelHTML` / `toggleProvenancePanel`) resolves each sense's
  `prompt_id` against `window._promptRegistry` (loaded in `config.js`) and shows
  model · family · tier · run date · notes.

**Coverage is honest, not total:** only senses a *tracked classifier*
(flash-lite / gap-fill that survived `min_priority` and went through the
resolve path) carry provenance. Senses shown via fallback display
(keyword-filtered by `min_priority=50`, or unclassified menu senses) legitimately
show none — the index's per-sense `sense_methods` was already all-`None`, so this
matches the pre-existing method-tracking coverage.

**Remaining (the deferred "full fix"):** wire §3 resolution order into
`resolve_best_per_example` so `capability_tier` (not raw method priority) decides
the winner — this is what actually re-ranks a newer run's answers above stale
ones, and it changes deck output (needs a rebuild). Broad per-sense provenance
coverage for menu-picks rides on that same rework.



## Problem

Each item in `sense_assignments/{source}.json` records only *what* was assigned
(`sense`, `examples`, and for discoveries `translation`/`pos`/`type`/…). It records
nothing about *who* assigned it — no model, no prompt version, no run timestamp.

The method key (`spanishdict-flash-lite`) is identical whether the run was
Gemini 2.5 or 3.1, and whether the prompt was a bare menu-pick or the newer
classify-or-propose architecture. So when a deck accumulates assignments across
several reruns, there is **no way to tell which run produced any given item**, and
conflicts between runs are resolved by an accident of dict/file order.

This surfaced concretely (2026-07-27): a 3.1 classify-or-propose rerun produced
correct off-menu proposals (guagua=car/van/truck, charro=scrub/jerk/loser), but
those lost the equal-priority tie-break to older literal menu-picks, and the deck
displayed the wrong sense. See the barebones fix below and the commit that landed
it.

### Why "most recent wins" is not enough

The first instinct is "newest run wins." But the intended distinction is really
about **model capability and prompt architecture**, not raw recency:

- A *prompt upgrade on the same model* (3.1 with a better prompt) should beat the
  older 3.1 run — but both are "gemini-3.1-flash-lite", so a model-name key can't
  separate them.
- A cheap re-run on a *weaker* model should NOT clobber a good answer from a
  stronger earlier run just because it happened later.

So the resolution axis is "which prompt/run is more trustworthy", with recency as
a tiebreaker *within* the same trust tier — not the primary key.

## Barebones fix (landed 2026-07-27)

Implemented as behavior, ahead of the full schema, to salvage the existing deck
without a rerun:

- **Proposal beats stale menu-pick.** `gap-fill` priority 50 → 51 in
  `util_6a_method_priority.py`, so an off-menu proposal (the 3.1 classify-or-propose
  signature — it carries `type`/`construction`) wins a same-example tie against a
  flash-lite menu-pick instead of losing on file order.
- **Off-menu discoveries survive consolidation.** `util_7a_lemma_split.py` now
  routes items whose sense ID matches no menu analysis to `word|<inline lemma>`
  (gated on a non-empty inline gloss), instead of dropping them.
- **Off-menu senses/lemmas render.** `step_8b` synthesizes a sense slot
  (`_ensure_sense_in_group`) and, for menu words, a group for any `word|lemma` key
  the menu never carried (e.g. `manín|manín` when the menu only knew `manín|maní`).

This is the *tier* idea expressed through the existing priority number: "proposal
family" sits one tick above "menu-pick family". The full schema below generalizes
that from a single hard-coded tick into a declared, extensible provenance record.

## Proposed schema

### 1. A prompt registry — `config/prompt_registry.json`

Append-only, human-authored. The key is an opaque unique id you mint whenever the
prompt changes; the entry *describes* that run so the data can point at it.

```json
{
  "sd-cop-v1": {
    "family": "spanishdict-menu-pick",
    "capability_tier": 10,
    "model": "gemini-2.5-flash-lite",
    "date": "2026-05",
    "notes": "menu-pick only; no off-menu proposal path"
  },
  "sd-cop-v2": {
    "family": "classify-or-propose",
    "capability_tier": 20,
    "model": "gemini-3.1-flash-lite",
    "date": "2026-07",
    "notes": "adds sense=null + proposed/type/construction/pos off-menu path"
  }
}
```

- `family` — the prompt *architecture* (the shape of what it asks for), independent
  of exact wording. Changes only when the call shape changes.
- `capability_tier` — integer trust rank. Higher wins. Chosen over a hand-ordered
  list so there's no ordering to reshuffle when a new prompt lands; leave gaps
  (10, 20, …) so intermediate tiers can be inserted. **Open question — confirm the
  integer-tier choice over an ordered list before implementing.**
- `model`, `date`, `notes` — descriptive; not used by the resolver except `model`
  as a tiebreaker.

### 2. Per-assignment stamp

Each item carries a tiny join key, not the whole story:

```json
{ "sense": "a9a", "examples": [0, 1, 4], "prompt_id": "sd-cop-v2", "run_ts": "2026-07-26T20:37Z" }
```

`prompt_id` joins into the registry; `run_ts` breaks ties between two runs of the
*same* `prompt_id`.

### 3. Resolution order (per example)

Replaces the current single `METHOD_PRIORITY` number in `resolve_best_per_example`:

1. **Manual / curated override** — always wins (curated translations, human edits).
2. **`capability_tier`** (from the registry via `prompt_id`) — higher wins.
3. **`model` rank**, then **`run_ts`** recency — tiebreakers within a tier.
4. **Legacy fallback** — items with no `prompt_id` get a `legacy-unknown` tier
   below every real prompt, so any stamped run supersedes them.

`METHOD_PRIORITY` stays for methods that aren't prompt-driven (biencoder, keyword,
auto) — it feeds the same tier axis so the two systems compose.

### 4. Backfill for the existing deck

No timestamps exist on current data, so backfill best-effort:

- Items with the off-menu signature (`type`/`construction` present) → stamp
  `sd-cop-v2` (provably the 3.1 classify-or-propose run).
- Everything else → `legacy-unknown` (lowest tier). Do **not** guess 2.5-vs-3.1 for
  bare menu-picks — the format can't tell them apart, and `legacy-unknown` already
  gives the right behavior (any future stamped run supersedes them).

This backfill reproduces the barebones behavior (proposals outrank legacy picks)
and makes every future run cleanly supersede via `run_ts` + `capability_tier`.

## What this future-proofs beyond the current bug

- **Prompt upgrades on the same model** resolve correctly (tier, not model name).
- **Partial / incremental reruns** — each item knows its own run, so a targeted
  rerun of a subset doesn't need to touch or out-rank the rest.
- **Provenance for audits** — a wrong card can be traced to the exact prompt/run
  that produced it, instead of guessing.
- **Safe reruns** — because a rerun stamps a new `prompt_id`/`run_ts` and supersedes
  cleanly, re-running stops being a destructive "hope it's better" operation.

## Open questions

1. `capability_tier` integer vs hand-ordered family list. (Leaning integer.)
2. Where the resolver reads the registry — inject into `resolve_best_per_example`,
   or resolve to a numeric tier once at load time and keep the hot path numeric.
3. Whether `step_6c` writes `run_ts` per item or once per file with a run header
   the loader stamps onto items.
4. Manual-override representation — a reserved top-tier `prompt_id`
   (`manual`) vs a separate override layer that always wins.

## Implementation touch-points

- `config/prompt_registry.json` (new)
- `pipeline/step_6c_assign_senses_gemini.py` — stamp `prompt_id`/`run_ts` on write
- `pipeline/util_6a_method_priority.py` — tier lookup that composes registry tiers
  with the existing method priorities
- `pipeline/util_6a_assignment_format.py` — `resolve_best_per_example` resolution
  order
- one-shot backfill script for existing `sense_assignments/*.json`
