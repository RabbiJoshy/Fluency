# The WSD algorithm, as settled 2026-08-20

One sentence: **embeddings propose a leaf, BETO overrules the lemma+POS where it
is confident, a calibrator scores the result, and what happens to a low score
depends on whether the corpus can be re-drawn.**

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
| 6 | **Disposition** | mode-dependent -- see below | |
| 7 | **Provenance** | every claim stamped `sd-beto-cal-v3` / `-esc-v3` + `run_ts`; a pinned policy admits one run and rejects the rest | prevents the builder unioning senses across methods |

## Stage 6 depends on one question: can you re-draw the sentence?

    corpus is FIXED (artist mode, user uploads)   -> escalate the worst N%
    corpus is HARVESTABLE (speech mode)           -> reject and take another sentence

**Artist / uploads — escalate.** `--escalate low --escalate-budget 0.20` sends the
least confident fifth to gemini-3.5-flash-lite as a closed-set pick. A budget, not
a band: precision-defined bands put 69% of a hard corpus in the low band, which
makes the escalator the main path rather than the fallback. Escalated cards graded
~88% vs ~76% for locally-decided ones.

**Speech — reject.** `--min-confidence T [--keep-best N]` drops unconfident picks
instead of paying for them. Coverage cost, measured on 3,000 subtitle sentences:

    min-conf 0.30 -> 94% of picks kept, 98% of words still have a card
    min-conf 0.35 -> 85% kept, 93% of words
    min-conf 0.40 -> 73% kept, 85% of words
    min-conf 0.50 -> 47% kept, 63% of words

Rejection is a property of the SENTENCE, not the sense: the median sense keeps 67%
of its own sentences, so harvesting deeper recovers what a threshold drops --
except for the 15% of senses that never clear the bar in any sentence.

Two things rejection does NOT buy: leaf accuracy is flat across the whole
rejection curve (53-60%), and tuple accuracy is what responds (82.4% -> 98.5% at
50% rejection, ranked by a tuple-target model).

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

## Not in the pipeline, but measured and worth building

**Aligned English** (speech mode only). mBERT SimAlign aligns the Spanish target to
its English subtitle word; if a leaf's gloss HEAD is that word, take that leaf.
49 better / 12 worse on 100 fresh hand-graded speech cards; fires on ~16%.
Requires parallel text, so it is structurally unavailable in artist mode.

## Commands

    # artist (fixed corpus -> escalate)
    step_6e_assign_senses_calibrated.py --artist-dir "Artists/spanish/<Name>" \
        --escalate low --escalate-budget 0.20

    # speech (harvestable corpus -> reject)
    step_6e_assign_senses_calibrated.py --min-confidence 0.35 --keep-best 2

    # then, both modes
    step_7a_map_senses_to_lemmas.py --language spanish
    step_8a_assemble_vocabulary.py --prompt-policy speech-beto-cal-v3-pinned
    step_8b_assemble_artist_vocabulary.py --artist-dir ... --prompt-policy testplaylist-beto-cal-pinned

Defaults already encode the measured configuration: `--tuple-vote beto`,
`--tuple-vote-min-gap 0.02`, `--gate se-only`, `--hub off`.
