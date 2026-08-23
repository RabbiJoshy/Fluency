# The WSD algorithm, as settled 2026-08-22 (v5)
> **v5 adds two stages before everything below, and they are worth more than
> everything below.** On 144 hand-labelled OpenSubtitles sentences: v3 65.3%
> sense-id / 74.3% card-gloss / 14 of 26 rare senses; v5 **86.8% / 87.5% / 15 of
> 26**. Hand-graded on a fresh random 50 from the diff set: **23 better, 5 worse,
> 22 lateral**.
>
> **Stage 0 — menu prior.** SpanishDict orders senses commonest-first. The score
> adds `0.02 * 0.5^rank`. Do not raise it: by 0.05 rare-sense accuracy collapses
> 54% -> 19% while the overall number barely moves. It is a dial between the
> sentence and the dictionary's ordering.
>
> **Stage 0b — POS filter.** Leaves whose part of speech contradicts the tag for
> THAT occurrence are pruned, via `sense_compatible_bridged` (NOT
> `sense_compatible_with_example_pos` — see wsd_dead_ends.md on the UD/SpanishDict
> tagset mismatch). It is the only signal measured that RAISES rare-sense
> accuracy (54% -> 62% alone), which is what pays for the prior's cost.
>
> **What the embeddings are now for.** Ablated out entirely — POS filter, then
> take the top surviving entry — the panel scores 82.6% overall but 19% on rare
> senses. The embeddings are worth ~2pp overall and are the ENTIRE rare-sense
> capability. Their only remaining job is deciding when to overrule the ordering,
> and on the diff set they do that at roughly 10 fixes / 7 breaks.
>
> **Known-stale below:** the confidence calibrator is trained on the dictionary
> gold (uniform over senses) and applied to real speech, so its bands are
> pessimistic and 58% of the v5 deck lands in "low". Retraining it on
> real-distribution labels is the outstanding item. Do not read v5 bands.
>
> ---
>
> ## The v3 stack, unchanged below this line

One sentence: **embeddings propose a leaf, BETO overrules the lemma+POS where it
is confident, a calibrator scores the result, and you choose per run what happens
to a low score.**

Everything below is `pipeline/step_6e_assign_senses_calibrated.py` unless noted.
Measurements are on 24,675 SpanishDict gold items or hand-graded rendered cards;
failed alternatives are in `wsd_dead_ends.md` and should not be re-tried.

## The stages

| # | stage | what it does | measured worth |
|---|---|---|---|
| 1 | **Gloss scoring** | gemini-embedding-001 (`SEMANTIC_SIMILARITY`, 3072d) on the sentence and on every leaf's `"word" (POS): gloss — context`; argmax over leaves | the baseline everything else failed to beat; tuple 88.7% / leaf 53.1% |
| 2 | **Clitic gate** | prunes `X`/`Xse` halves using the proclitic cluster (`--gate se-only`) | 96.8% correct where it fires, on 64% of reflexive-ambiguous items |
| 3 | **BETO tuple vote** | where the whole menu has token prototypes AND BETO's own top-two margin >= 0.02, BETO **decides** the (headword, POS); embeddings then pick the leaf inside it | +2.40pp tuple on gold; 60 better / 13 worse on all 88 changed lyric picks. **Ungated it is a wash (20/13)** |
| 4 | **Leaf repair** | `select_display_leaf`: never emit an empty gloss or a leaf whose "used with X" note the line does not satisfy; stays inside the won tuple | removes 186 blank cards + 29 broken notes per playlist build |
| 5 | **Confidence** | calibrator (`feature_version 5`) -> P(**leaf** correct); bands are precision targets (90% high, 70% medium) | top-decile precision 49.4%->89.1%; retargeting from tuple to leaf moved a graded deck 160/200 -> 177/200 |
| 6 | **Disposition** | what happens to a low score: nothing, reject, or escalate. A per-run choice in BOTH modes -- see below | |
| 7 | **Provenance** | every claim stamped `sd-beto-cal-v3` / `-esc-v3` + `run_ts`; a pinned policy admits one run and rejects the rest | prevents the builder unioning senses across methods |

## Stage 6 is a choice you make per run, in either mode

Nothing here is mode-dependent. `--escalate low --escalate-budget N` and
`--min-confidence T --keep-best N` both work with or without `--artist-dir`,
and they compose -- escalate the worst, then drop whatever is still weak.
`--artist-dir` selects which layer directory is read and has no other effect;
`test_step_6e_disposition_not_mode_gated.py` pins that, because this section
previously read "artist escalates, speech rejects" and that was a default
someone chose written down as though it were a constraint.

What the choice actually trades:

| run | flags | Gemini cost | what happens to a weak pick |
|---|---|---|---|
| **neither** | (none) | none | it stands, stamped `sd-beto-cal-v3`, low band |
| **reject** | `--min-confidence T [--keep-best N]` | none | the claim is dropped; the example loses its card slot |
| **escalate** | `--escalate low --escalate-budget 0.20` | $0.047 per 1k picks escalated (measured) | flash-lite re-picks from the closed menu |
| **both** | all four | same as escalate | escalate the worst N%, then cut what is still under T |

**No Gemini at all.** Either leave the flags off, or reject. Rejecting is not
free -- coverage is the price, measured on 3,000 subtitle sentences:

    min-conf 0.30 -> 94% of picks kept, 98% of words still have a card
    min-conf 0.35 -> 85% kept, 93% of words
    min-conf 0.40 -> 73% kept, 85% of words
    min-conf 0.50 -> 47% kept, 63% of words

Two things rejection does NOT buy: leaf accuracy is flat across the whole
rejection curve (53-60%), and tuple accuracy is what responds (82.4% -> 98.5% at
50% rejection). And rejection is a property of the SENTENCE, not the sense: the
median sense keeps 67% of its own sentences, so harvesting deeper recovers what
a threshold drops -- except for the 15% of senses that never clear the bar in
any sentence.

**Escalation on.** `--escalate low --escalate-budget 0.20` sends the least
confident fifth to gemini-3.5-flash-lite as a closed-set pick. Use a budget, not
a band: the band cuts are PRECISION targets read off the calibrator's held-out
curve, so on a hard corpus the low band is 69% of the deck, which makes the
escalator the main path rather than the fallback. Escalated cards graded ~88%
against ~76% for locally-decided ones.

How much it moves, measured 2026-08-22 at a 20% budget in both modes:

    artist (31-song playlist)  602 escalated, 499 picks changed (83%),  $0.028
    speech (subtitle corpus) 5,848 escalated, 4,076 picks changed (70%), $0.273

Gemini disagrees with the local path on most of what it is shown, in both
corpora. That is the point -- the budget selects the picks the calibrator ranks
worst -- but it also means escalation is not a light touch-up: a fifth of the
deck gets a different answer, from a different model, and only the escalated
share carries the `-esc-v3` id that says so.

**Which to choose is about the corpus, not the mode.** A fixed corpus -- a
playlist, a user upload -- cannot re-draw a bad sentence, so escalating buys back
an example that rejection would simply delete. A harvestable corpus can draw
another sentence for the same sense, so rejection costs less there. Those are
defaults worth knowing, not rules: a lyric deck built with no escalation is
equally possible and equally supported, it just carries fewer examples.

## Graceful degradation

Each rung falls back to the one below it; nothing errors.

| condition | behaviour |
|---|---|
| full stack available | stages 1-7 as above |
| **no BETO prototypes** for the word (menus are only ~36% fully scoreable) | stage 3 silently skipped; embeddings decide the tuple |
| **no parallel English** (artist mode, user uploads, 9 of 31 playlist songs) | the aligned-English correction cannot run; nothing else changes |
| **no calibrator** on disk | confidence falls back to the raw tuple gap; bands become meaningless, so rejection/escalation thresholds must be re-chosen |
| **word has no sense menu** | step_6e skips it by construction; `sd-lexical-v2-g35` gap-fill invents senses for those words only |
| **menu has one leaf / one tuple** | gate and vote are no-ops; the single leaf is emitted |
| **escalation unavailable** (no key, throttled) | the local pick stands; the claim is stamped `sd-beto-cal-v3`, never silently blank |

## Stage 8: aligned-English leaf correction (`step_6f_align_english_leaf.py`)

mBERT SimAlign aligns the Spanish target to its English subtitle word; where a
candidate leaf's gloss head is that word, that leaf is taken. Measured before it
was built: 49 better / 12 worse on 100 fresh hand-graded speech cards, firing on
~16%.

It is the only added signal that has beaten plain gloss-cosine here, and the
reason is in `wsd_dead_ends.md`: every rejected signal matched on PRESENCE (this
topic is nearby, this cue is in the sentence), while alignment matches on
RELATION -- it says which English word IS this token.

Mechanically it is a CORRECTOR, not a classifier. It reads step_6e's claims and
authors one only where it changes the pick, stamped `sd-beto-cal-align-v4`;
every untouched occurrence keeps its `sd-beto-cal-v3` claim. The builder
resolves per example, so a card's provenance names the run that actually decided
it. It abstains where several leaves share the aligned word as a head, and it
does not overturn a `sd-beto-cal-esc-v3` pick (escalated picks graded ~88%; the
alignment result was measured against the local path).

The aligner itself lives in `util_6f_alignment.py` and is shared, so anything
else that wants word alignment -- attaching English morphology to senses, for
one -- uses the same tokenization and the same cached alignments rather than a
second, subtly different one. Alignments are cached on disk by (model, layer,
method, source, target); a re-run of the corpus is I/O.

Requires parallel text. Speech mode has it for every sentence; artist mode has
it for the songs with a scraped translation and not the rest, which is why
`--artist-dir` is accepted but not the default.

## Commands

Pick a disposition; the mode does not pick it for you.

    # no Gemini at all
    step_6e_assign_senses_calibrated.py [--artist-dir "Artists/spanish/<Name>"]

    # reject the weak
    step_6e_assign_senses_calibrated.py [--artist-dir ...] \
        --min-confidence 0.35 --keep-best 2

    # escalate the weakest fifth
    step_6e_assign_senses_calibrated.py [--artist-dir ...] \
        --escalate low --escalate-budget 0.20

    # optional, needs parallel text: correct the leaf from the aligned English
    step_6f_align_english_leaf.py [--artist-dir ...] --report changes.tsv

    # then, both modes
    step_7a_map_senses_to_lemmas.py --language spanish
    step_8a_assemble_vocabulary.py --prompt-policy speech-beto-cal-v4-pinned \
        --drop-unrenderable
    step_8b_assemble_artist_vocabulary.py --artist-dir ... --prompt-policy testplaylist-beto-cal-pinned

Defaults already encode the measured configuration: `--tuple-vote beto`,
`--tuple-vote-min-gap 0.02`, `--gate se-only`, `--hub off`.
