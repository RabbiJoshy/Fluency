Fluency — WSD, speech mode only. Ignore artist mode entirely.

Read `docs/reference/wsd_algorithm.md`, `wsd_dead_ends.md` and `open_defects.md`
first. Both of the first two were corrected on 2026-08-22 and carry a warning at
the top about how their older entries were measured — read that before trusting
any row in them.

## THE PROBLEM, AS I NOW UNDERSTAND IT

After part-of-speech filtering, the most common sense in the dictionary's own
ordering is usually the right reading. That much is close to solved. What is
left is two questions, and I think they are the entire remaining problem:

  1. WHEN should the common reading be overruled?
  2. WHICH uncommon sense should replace it?

Everything else is bookkeeping. I want to get as close to 100% as possible while
making the algorithm SIMPLER, not more elaborate — I would rather have three
things that work than nine that each contribute a point.

## START WITH AN AUDIT, NOT THE WORKFLOW

Before proposing or running anything, audit the current state and tell me
plainly whether anything obvious is being missed. Fresh eyes, not agreement.
Say if the architecture is wrong, if a stage does nothing, if something standard
is absent, or if the measurements do not support the conclusions drawn from
them. The last session found two large wins that way and both were things
already sitting in the repo, wrongly recorded as dead ends.

Be willing to overturn what was done on 2026-08-22. It was one session, some of
it was measured on one 144-item panel, and the hand-grading was done by the same
model that wrote the change. Treat it as a lead, not a foundation.

## WHERE THINGS STAND

Shipped as `sd-beto-cal-v5` (commit 78506bf6), live in the speech deck:
menu prior (+0.02 * 0.5^rank on SpanishDict's ordering) -> POS filter
(`sense_compatible_bridged`) -> se-only clitic gate -> gloss-cosine argmax ->
gated BETO tuple vote -> leaf repair -> calibrator.

Measured on 144 hand-labelled OpenSubtitles sentences:

    v3            65.3% sense-id   74.3% card gloss   14/26 rare senses
    v5            86.8%            87.5%              15/26

50 random changed cards graded 23 better / 5 worse / 22 lateral — BUT that
grading was self-assessment by the model that made the change, and is the
weakest number here. Re-grading it is cheap and is probably the first thing
worth doing: `Data/Spanish/Intermediates/wsd_prior_audit/grades_v2.json` holds
the sample with verdicts already filled in.

The single most useful measurement from that session, because it defines the
remaining problem: **ablate the embeddings entirely** — POS filter, then take
the top surviving menu entry — and the panel still scores 82.6% overall but only
19% on the rare-sense subset, against 58% with embeddings. The embeddings are
worth about 2 points in aggregate and are the whole of the rare-sense ability.
Where they fire against the prior they are right about 12 times and wrong about
10. That coin-flip is the thing to attack.

Of the 19 items v5 still gets wrong: 14 are same lemma+POS with the wrong gloss,
3 are right lemma wrong POS, 2 are wrong lemma. Note 5 of the 19 picked an
empty-gloss leaf, which the shipped leaf-repair stage fixes but the offline
panel harness does not run — so the deck is better than 86.8% by an unmeasured
amount, and that harness gap should be closed before any new number is trusted.

Known-broken and untouched: the confidence calibrator is trained on the
dictionary gold and applied to real speech, so 58% of the deck reads "low" and
the bands are meaningless. Rejection and escalation both depend on it and are
therefore both unusable as currently calibrated.

## EVALUATION ASSETS

- `Data/Spanish/Intermediates/wsd_sense_harness/2026-08-11_v1/` — 150-row
  labelled panels for opensubtitles and spanishdict, plus an UNLABELLED
  badbunny panel. Labels are "acceptable sets" (several sense ids per item),
  which means they are lenient and CANNOT see near-synonym or context-level
  errors. If a signal targets those, new labels naming one sense id are needed.
- `Data/Spanish/Intermediates/wsd_prior_audit/panel_scores_2026-08-22.json` —
  cached cosines, menus and gates for both panels. Re-scoring any variant is
  seconds and costs nothing.
- `pipeline/tool_8j_render_cards.py --artist-dir "Data/Spanish"` renders real
  speech cards. The rendered card is the only truth.
- The 24,675-item dictionary gold is NOT a valid eval for anything
  frequency-related: it is every sense's own example sentence, 1.02 examples per
  sense, uniform over senses by construction. Two "dead ends" were wrongly
  recorded because of this.

## WHAT HAS AND HAS NOT BEEN TRIED

This is an inventory, not a shortlist, and the answer may well be none of it.
Do not treat the untested column as a plan.

Measured and rejected (see `wsd_dead_ends.md` for why): query windowing, target
marking, feature re-ranking, cross-lingual gloss similarity, leaf exemplars, MLM
substitution, sense enrichment in three forms, sense cue words, alignment
guards, per-word z-scoring of cosines.

Measured and kept: gated BETO tuple vote, menu prior, POS filter with tagset
bridge.

Measured and held out: aligned-English leaf correction (`step_6f`, rebased to
v5, graded 18 better / 13 worse / 19 lateral; 9% of its corrections change the
part of speech and those graded 1 better / 3 worse, because it runs after the
POS filter without applying it). `--stay-in-tuple` exists and is untested.

Never tested at all: SpanishDict's construction notes as a VETO rather than as a
calibrator feature (on the panel, penalising a sense whose "used with X" the
line violates was 1 fix / 0 breaks and identical at weights from 0.02 to 0.20,
but only 24 of 144 items carry a note); agreement between two independent POS
taggers as a gate; subtracting the shared component between near-identical
glosses instead of adding descriptive text to them; subtracting a word's own
mean corpus context from each gloss score (blocked — `examples_raw.json` keeps
only 3 sentences per word and the larger sentence bank is unembedded).

The generalisation that has held so far: signals matching on PRESENCE (a topic
is nearby, a cue is in the sentence, an example resembles the line) fail;
signals matching on RELATION (which English word IS this token, what part of
speech IS this token) work. Test that generalisation rather than assuming it —
the menu prior is neither, and it was the largest win.

## SEPARATE THIS OUT, DO NOT RABBIT-HOLE ON IT

Some errors are caused by the sense menu not containing the right answer at all,
not by picking wrongly from it. `pares` ("Mejor que pares" — stop) has a menu of
nine `par` NOUN/ADJ leaves and no `parar`. Verified: SpanishDict's dictionary
endpoint genuinely does not offer it — the string "parar" is absent from the
whole response, `verb` is null, and it returns
`mismatchProps: {query: "pares", word: "par"}`. Their conjugator is a separate
product. Measured floor: 151 occurrences across 68 words where the tagger says
VERB and the menu holds no verb; the true figure is higher because
`examples_raw.json` samples only 3 sentences per word.

This is worth fixing on its own account and is NOT part of the when-to-overrule
problem. Keep it in a separate bucket, measure around it rather than through it,
and do not let it consume the session.

## WORKING RULES

- Report after every discrete unit of work. Four things, ten lines: what was
  done, THE NUMBER (n correct / n graded), a real rendered card, what's next.
- Decisions come to me one at a time, close to the work. At most one lean per
  set of options, and say what you don't know.
- Hand-grade. No automated LLM grader — that cost £10 and produced a 4.7pp
  regression that did not exist. If you grade your own change, label it as
  self-assessment every time you quote the number.
- Two different questions, two different samples: deck quality = random sample;
  is this signal any good = grade the DIFF SET it changes.
- One variable per pass, unless a change only works as two — then say so up
  front and define the ablation before running it.
- Write grades to a file as you go, so re-scoring a threshold is seconds.
- Verify before reporting success: read the log, not the exit code. Open a
  rendered card before declaring anything done.
- Any classifier change bumps the version and registers in BOTH
  `config/prompt_registry.json` and `pipeline/util_6a_method_priority.py`.
  Omitting the second silently drops every claim and builds an empty deck with
  exit code 0. That has now happened three times.
- Anything over a minute must be cached and resumable. Price any model spend
  before spending it. Print long commands for me to run rather than running them
  inline.
- If two consecutive iterations are fixing your own implementation rather than
  teaching us something about the data, stop and report.

## WHAT I WANT OUT OF IT

An improvement I can see on named cards in the deck, and an algorithm that is no
more complicated than the one it replaces. Not commits, not refactors, not
coverage numbers. If the honest answer is that the remaining 13% is mostly
lenient-metric noise and near-synonyms nobody would mark wrong, say that plainly
and stop — that is a useful result too.

## TWO OPERATIONAL TRAPS THAT COST TIME ON 2026-08-22

**A rebuilt deck is invisible in the app.** The service worker keeps deck JSON
in a `fluency-content-*` cache and nothing in a pipeline rebuild invalidates it,
so the app keeps serving the previous build's provenance and glosses until
someone bumps `CACHE_NAME`/`ASSET_VERSION` in `service-worker.js` by hand. That
file is Codex's boundary. Before concluding a change did not land, check the
files on disk (`grep` the prompt_id in `Data/Spanish/vocabulary.examples.json`)
or curl the JSON directly; then clear site data for localhost:8765.

**`step_8a` prints no line naming the `--prompt-policy` in effect**, even though
that policy decides which classifier authors every sense in the deck. A build
that silently admits or excludes the wrong run looks identical in the log.
Verify by grepping prompt_ids in the OUTPUT files, and never pipe a build log
through `grep` at launch — that discarded the evidence needed to diagnose a real
discrepancy where a policy-excluded run's claims survived into the deck anyway.
