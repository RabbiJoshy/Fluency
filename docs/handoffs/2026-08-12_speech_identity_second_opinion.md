# Second opinion wanted: card identity for Spanish speech mode

Read `docs/design/spanish_speech_layer_restructure.md` first. It has the full
argument and every supporting measurement. This file is only the question.

**Please argue with it rather than confirm it.** It was written by one model in one
long session, and the author had an obvious incentive to find its own reasoning
convincing. Two of that session's headline results turned out to be measurement
artifacts that the author caught only after acting on them, so treat the reasoning
as suspect until you have re-derived the parts that matter.

## The decision

Speech-mode cards are currently keyed on `word|lemma` — `md5(word|lemma)[:6]`. The
proposal is to key on the **surface form alone**, with lemma demoted to a label on
each sense, and a derived "roll-up" that credits knowing `poder` when you have
learned `puedo`.

## Two questions

1. **Is surface-form identity right?**
2. **Is it safe to land the layer restructure first, run speech mode on the current
   `word|lemma` scheme, and switch identity later?** The proposed safeguard is to key
   the new claim store on `(surface, sense_id)` from day one, so that only the deck
   assembler ever knows about lemma splitting and the later switch needs no data
   migration.

## The case for (compressed — detail in the design note)

- The product is an ordered curriculum. **Frequency is only observable at the
  surface**; there is no reliable most-common-lemma or most-common-sense list. A
  sense-keyed deck cannot be ordered at all.
- Lemma is *inferred and revised*; surface is *observed and permanent*. Keying on an
  inference means a disambiguation error mints a permanent card. Measured: **1,126
  surfaces** carry deck lemmas the inventory does not list (`nada→nadar`,
  `así→asir`, `era→erar`).
- **15% of corpus mass** sits on multi-lemma surfaces and is split *proportionally to
  how many examples each lemma happened to be assigned* (`step_8a` line 827). So
  frequency ranking is partly a function of classifier noise.
- Card size does not regress: median 2 meanings and p90 5 under either scheme.
  11,729 cards → 9,452 surfaces.
- The sense menu is **already surface-keyed with a `headword` on every sense**, so
  the "lemma as a label" model already exists in the data.

## The case against — take these seriously

- **Roll-up credit is load-bearing and unbuilt.** Without it, `puedo`, `puedes` and
  `podemos` are three separate cards and the learner studies `poder` repeatedly.
  `word|lemma` at least groups them today. If roll-up is harder than assumed, surface
  identity is strictly worse than the status quo.
- **"Partly known" cards complicate scheduling.** A card can have one sense known via
  its lemma and another not. The scheduler must move from "is this card learned" to
  "does this card have an unlearned sense worth showing". That is a real change to a
  system that currently works.
- **`word|lemma` handles lexicalisation for free.** `gracias` (thanks) vs `gracia`
  (grace) — the split scheme gives each its own card naturally. Surface identity
  needs an explicit decision about whether `gracias` rolls up to `gracia`.
- **The 17% tail is untouched.** Surfaces with >12 merged meanings (`salido`, `di`,
  `sale`, `salida`, `pico`) are single hyper-polysemous headwords. Neither scheme
  helps; the claim that surface identity is fine here rests on merging and
  progressive disclosure both working.
- **Migration cost is real.** Every card id changes; progress needs a merge rule when
  two cards collapse into one; the app's `id_migration_vN` localStorage gate must be
  bumped or existing users silently never migrate.
- **Is the diagnosis even right?** The `1,126 fabricated lemmas` and the proportional
  frequency split are bugs in `step_7a`/`step_8a`. A reviewer could reasonably argue:
  fix those two bugs and `word|lemma` is fine, and the identity change is a large
  migration solving a problem that better lemma routing would solve more cheaply.
  **That is the strongest counter-argument and it has not been rebutted.**

## Context you need

- App is single-language by design. Do **not** argue from cross-language transfer;
  it was raised and explicitly ruled out of scope.
- SpanishDict stays as the sense inventory. Gemini embeddings replaced the
  *classifier*, not the menu.
- Card-per-sense was considered and rejected (cannot be ordered).
- Progress today: `progressData[fullId]` where `fullId = es0 + md5(word|lemma)[:6]`,
  synced to Google Sheets. Sense-level `ItemProgress` exists but is barely used.

## Verify rather than trust

Every number above is reproducible from the repo. `pipeline/tool_snapshot_layers.py`
holds a verified snapshot (`2026-08-11_pre_rerun`) of the pre-run state if you need
to compare against the deck as it was.
