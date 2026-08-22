# Open defects, 2026-08-22

Each entry: the symptom, the evidence, and how to tell it is fixed. No proposed
solutions beyond what the evidence already forces — the point is that the next
pass starts from a reproducible symptom rather than a memory of one.

## 1. 468 cards show an empty meaning although a sense was chosen

**Symptom.** `dame`, `apúrate`, `váyanse` and 465 others render one meaning with
`pos: "X"`, empty translation, no `sense_id`, and bare example sentences.

**Evidence.** Those words HAVE a SpanishDict menu, HAVE examples, and HAVE
`spanishdict-beto-cal-v3` claims (`clitic_forms.json` carries 524 v3
assignments). `step_8a` still takes its `if not senses:` fallback, which attaches
`word_examples[:5]` raw, so 1,428 example sentences carry no provenance and no
gloss. The claim exists; `get_senses_for_lemma` does not find senses for that
card key.

**Why it is one defect and not two.** The missing stamp and the empty gloss have
the same cause. Stamping that branch would print provenance under a meaning that
is still blank.

**Verify fixed.** `dame` shows *to give* (or whichever leaf v3 chose) with
`sd-beto-cal-v3` in the provenance panel, and the deck's count of `pos: "X"`
meanings holding claimed examples drops to zero.

**Context.** This is the lemma/clitic routing seam. Under surface-form identity a
clitic form is just another surface; the separation dates from lemma identity,
when a clitic form needed a parent verb to hang from.

## 2. 89 example sentences are genuinely unclassified

**Symptom.** Sentences on cards like `sr`, `ud` have no sense claim at all.

**Evidence.** 89 of 29,163 corpus sentences are absent from every
`spanishdict-beto-cal-v3` claim. Distinct from defect 1: here there is nothing in
the layer to attach.

**Verify fixed.** Either the count reaches zero, or these words are deliberately
excluded (abbreviations) and the exclusion is recorded in routing.

## 3. Escalate-vs-reject is documented as a mode rule; it is an option

**Symptom.** `wsd_algorithm.md` reads "artist escalates, speech rejects".

**Evidence.** Neither flag is mode-gated. `--escalate low --escalate-budget N`
and `--min-confidence T --keep-best N` both work with or without `--artist-dir`,
and combine (escalate the worst, then drop what stays weak). The split in the doc
is a default that was chosen, not a constraint that exists.

**Verify fixed.** The doc states the four combinations and their costs: no Gemini
at all (examples are cut), escalation on (examples kept, money spent), either in
either mode.

## 4. `--gate dative-aware` is unvalidated

**Symptom.** Flag exists, default off.

**Evidence.** 22 changed picks hand-graded: 9 better, 6 worse, 7 lateral. Three
bugs were found and fixed while measuring it (empty-cluster rule dropped,
imperative syncretism inverting the agreement test, de-accented lookup against an
accented conjugation index). The remaining ratio is not good enough to ship.

**Verify fixed.** A graded sample where fixes clearly exceed breaks, or the flag
is removed.

## 5. TV examples name the episode, not the series

**Symptom.** A speech card cites *Voir Dire (2009)* or *The Dog (2009)* — episode
titles, uninformative without the show.

**Evidence.** `tool_5a_build_subtitle_titles.py` resolves title_ids against IMDb
`title.basics.tsv.gz`. The episode-to-series link lives in `title.episode.tsv`,
which is not downloaded.

**Verify fixed.** Episode examples read as `Series — Episode (year)`.

## 6. `--out` outside the repo raises after writing

**Symptom.** `step_6e` exits non-zero with `ValueError: ... is not in the subpath
of ...` when `--out` points outside the repo.

**Evidence.** `out_path.write_text(...)` runs before
`print(f"wrote {out_path.relative_to(REPO)}")`, so the file is complete and
correct; only the final print fails. Cosmetic, but it makes scratch runs look
failed and hid a real failure once today.

**Verify fixed.** A scratch-path run exits 0.

## 7. `--max-examples` does not fully bind in artist mode

**Symptom.** With `--max-examples 10`, one word carried 11 examples.

**Evidence.** Observed on the 31-song playlist build; clitic merge appears to add
an example after the cap is applied in `step_2a_count_words`.

**Verify fixed.** No word exceeds the cap after a full artist rebuild.
