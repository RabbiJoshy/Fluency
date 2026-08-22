# Open defects, 2026-08-22 (evening)

Each entry: the symptom, the evidence, and how to tell it is fixed. The seven
recorded this morning are all closed; what is left below is what this session
opened or left standing, plus what closing them taught.

## Closed 2026-08-22

| # | defect | what it was | verify |
|---|---|---|---|
| 1 | 468 cards show an empty meaning | TWO causes, not one — see below | `dame` shows *give me*; deck has 0 empty pos-X meanings |
| 2 | 89 unclassified sentences | 66 words with no menu, no claim, no gloss | `layers/unrenderable_cards.json`; deck has 0 unattributed example slots |
| 3 | escalate-vs-reject documented as a mode rule | it never was one in the code | `wsd_algorithm.md` "Stage 6 is a choice"; `test_step_6e_disposition_not_mode_gated.py` |
| 4 | `--gate dative-aware` unvalidated | still unvalidated — see below | — |
| 5 | TV examples name the episode | `title.episode.tsv.gz` was not downloaded | a speech card reads `Without a Trace — Voir Dire (2009)` |
| 6 | `--out` outside the repo raises after writing | `relative_to` in the final print | `util_pipeline_meta.display_path`; scratch runs exit 0 |
| 7 | `--max-examples` does not bind in artist mode | the cap was per surface, the card is per lemma | `dar` carries 10; 0 artist cards over the cap |

### What defect 1 actually was

The morning's note said one defect with one cause. It was two, and neither was
the one recorded.

**472 ghost cards.** `known_lemmas` comes from the conjugation reverse lookup,
which has no entry for an inflected adjective or determiner and answers with the
surface itself: `algún -> ["algún"]`, while every claim and every menu analysis
says `alguno`. That minted a SECOND card for the surface with no senses and no
claims, sitting beside the real one and swallowing `word_examples[:5]` as an
untranslated, unattributed meaning. This was 90% of the 523 and it was a
duplicate-card bug, not a missing-gloss bug.

**18 surface-headword cards.** `dame`, `apúrate`, `váyanse`. SpanishDict files
these as their own lexical entries — `dame` is a PHRASE glossed *give me*, not a
sense of `dar` — and step_7a routes the form onto its verb lemma. So the card key
is `dame|dar`, the claim is `dame|dar -> 1fb` at confidence 0.68, and
`get_senses_for_lemma` asked the menu for analyses headed `dar` and found none.
The classifier had already decided against the `dame` analysis; the builder threw
the menu away.

The generalisable shape, and the reason it took a morning to see: **both are the
builder discarding a correct upstream decision, and neither is visible from the
symptom.** A blank card looks like a classification failure. Nothing had failed
to classify.

## Still open

### A. `--gate dative-aware` is still unvalidated

22 changed picks hand-graded: 9 better, 6 worse, 7 lateral. Three real bugs were
found and fixed while measuring it (dropped empty-cluster rule, imperative
syncretism inverting the agreement test, de-accented lookup against an accented
conjugation index), so that ratio is the flag's honest score, not a broken one.

Nothing changed this session except that the measurement now lives in the flag's
own `--help`, so it cannot be switched on by someone who has not read it. The
criterion is unchanged: a graded sample where fixes clearly exceed breaks, or the
flag is removed. Hand-grading is the blocking step and it is not something this
side of the keyboard can do.

### B. An alignment-corrected pick has no calibrated confidence

`sd-beto-cal-align-v4` claims carry method, prompt_id and run_ts but no
`confidence` or `band`, so the provenance panel shows a run and no score on the
2,420 example slots it authored. This is correct rather than convenient: the
calibrator scores P(leaf correct) for the leaf the EMBEDDING proposed, and
carrying that number onto a different leaf would be exactly the mis-scoring v2
was built to stop.

Two honest fixes exist and neither is free: retrain the calibrator with an
alignment feature (which makes it a v5 stack, not a corrector), or surface the
aligned English word itself as the card's evidence — more informative than a
number, but it needs a `js/` change and that is Codex's boundary.

**Verify fixed.** A corrected card shows either a score the calibrator actually
produced for that leaf, or the aligned word that chose it.

### C. Clitic detection misses `dame`-shaped forms

`dame` is in no routing bucket at all — it is not detected as a clitic form.
`load_wiktionary_clitic_data` gates on the gloss containing "combined with";
`dame` is filed as *"inflection of dar: second-person… voseo"* with the pronoun
present only in `links`.

Measured: widening the gate to link-evidence plus surface confirmation catches
14 more inventory forms, of which 9 are real (`dame, dale, dales, danos, date,
dámela, dámelo, estate, vete`) and 5 are false positives (`vela, velo, velas,
revela, senos` — real words that end in a pronoun string). `vela` is genuinely
ambiguous with *ve + la*, so no cheap guard separates them: requiring the
remainder to be a valid imperative keeps `vela` in, because *ve* is one.

Deliberately not fixed. The payoff is 9 forms and the risk is mis-tagging
`vela` (candle) as a verb form. Recorded so the next pass does not re-derive it.

### D. `word_routing.json` is at step_version 1 and carries no clitic tag

`classify_clitics` computes `clitic_info` and `step_4a_route_clitics` writes it
as `clitic_roles` — parent, base, pronouns, roles, reflexive, source, for every
detected form regardless of which bucket it lands in. That is the tag a run needs
in order to decline to spend WSD compute on clitics.

The file on disk predates it (generated 2026-04, `step_version: 1`; the code is
at 3). So no tag exists today and nothing downstream can gate on clitic-ness.

Regenerating is one fast local command with no API — but versions 2 and 3 also
changed routing behaviour (infinitive+enclitic decomposition; SpanishDict parents
replacing the literal-`se` reflexive test), so it churns the live deck's clitic
buckets rather than merely adding a field.

**Verify fixed.** `word_routing.json` carries `clitic_roles`, and the
merge/keep/orphan diff against the v1 file has been looked at rather than
absorbed.

## The pattern worth carrying forward

Three of the seven closed defects — 1, 2 and 7 — were the same shape: **a correct
decision computed upstream and discarded, narrowed or duplicated by the
builder.** The clue in each case was that the evidence layer already held the
right answer. Before writing new detection for a bad card, check whether the
claim is already there and the assembler is failing to find it.
