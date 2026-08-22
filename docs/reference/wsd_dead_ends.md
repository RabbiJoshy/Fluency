# WSD dead ends — measured, not guessed

> **2026-08-22: one entry on this list was wrong, and it was wrong for a reason
> that invalidates how everything else here was measured.** The canonical
> 24,675-item gold is every SpanishDict sense's OWN example sentence — 1.02
> examples per sense, 23,636 senses contributing exactly one. It is UNIFORM over
> senses by construction. A sense-frequency prior therefore has nothing to
> predict on it and cannot possibly help, which is why `menu_pos` was rejected.
> On 144 hand-labelled OpenSubtitles sentences the true sense is the FIRST menu
> entry **82%** of the time and the shipped gloss argmax scored **65%**. The
> prior is now stage 0 of v5. Before trusting any row below, ask whether it was
> measured on the dictionary gold and whether that gold can see the effect.

Every entry here was implemented and measured. Re-running one costs a day and
returns the same answer. The canonical accuracy split it all sits against, on
24,675 SpanishDict gold items:

    tuple (lemma+POS)        88.66%     <- what the stack was tuned on
    gloss (POS+translation)  56.70%
    exact leaf (sense id)    53.09%     <- what the card prints

Tuple was nearly saturated; the leaf is a coin flip. Almost everything below is
an attempt to move the leaf number, and almost nothing does.

## Measured 2026-08-19/20

| attempt | result |
|---|---|
| **Query windowing** — embed target ±3 tokens instead of the sentence | leaf 53.09% → **47.31%** on 24,675 gold. Locality is not the problem. |
| **Target marking** — `"una" en: <sentence>` (`--query mark_prefix`) | tuple +0.3, leaf −0.7. Noise. |
| **Window + marking** | leaf 45.86%. Worst of the four query modes. |
| **Feature re-ranker** — same calibrator features, one row per candidate leaf, 113k rows | +1.6pp leaf on held-out. Most features (`n_tup`, `n_leaf`, `sent_len`, `pred_is_verb`) are CONSTANT across an item's candidates, so they carry no ranking information. |
| **Cross-lingual gloss similarity** — mBERT, Spanish token vector vs English gloss vector, no alignment | Rewrote 38 of 54 correct picks on hand-graded speech cards. Similarity sits in a narrow 0.58–0.74 band for everything; the argmax is near-arbitrary. |
| **Leaf exemplars** — 1-NN against each leaf's own example sentence (99.9% of leaves have one) | Net negative, and gating on the margin made it *worse* (at gate 0.05: 0 error-touches, 9 correct picks rewritten). One example is a point dominated by that sentence's topic — `agradas` → *to like each other* matched "Mónica y Bernardo se agradan mucho". This is why prototypes are pooled at tuple level; the constraint is signal quality, not just leave-one-out. |
| **MLM substitution + per-sense synonyms** — mask the target with BETO, match predicted fillers against the sense's SpanishDict synonyms | Fires on 10% of items; proposals are mostly lateral moves inside a near-duplicate gloss group (*to waste* → *to squander*). ~2 fixes, ~2 breaks in a 100-item sample. |
| **Sense enrichment (full replacement)** — frontier model writes a discriminative description per leaf, embed that instead of the gloss | 5 better / 11 worse / 14 neutral on hand-graded changes. A 20-word description makes the vector about the TOPIC, not the label: `aves` → *poultry (culinary)*, `argumento` NOUN → VERB. |
| **Sense enrichment (same-gloss tie-break only)** — use the description solely to choose between leaves sharing (POS, gloss) | 2 better / 3 worse / 4 neutral. Ceiling is the 3.6pp gloss-vs-leaf gap and it does not reach it. |
| **Sense cue words** — frontier model lists 3-6 Spanish collocates per sense, matched lexically against the sentence (discrete, so it cannot dilute a vector) | Fires on 17%, and 0 fixes / 3 breaks on graded cards. Matches are presence without RELATION: `Apaga eso para poder comer` picked *to wane* because "poder" is a cue for the power sense but is the verb here; `callejón sin salida` picked *passage* on "salida". Spanish sentences are short enough that bare co-occurrence is near-random. First attempt also had the model return inflected forms of the target itself as cues (`agradecería` -> `agradece, agradecen`), which always match. |
| **Sense enrichment blended** (alpha=0.8 gloss / 0.2 description) | 3 good / 2 bad / 3 neutral on 8 graded changes -- better than replacing (5/11) but unresolved at that sample size. The dilution diagnosis is right; keeping the gloss dominant recovers most of it. Left open rather than shipped. |
| **Alignment guards** — clause/relative-position and translation-length constraints on the aligned-English signal | No effect: 4.1 → 4.4 fix:break at best, dropping fixes as fast as breaks. |

## Corrected 2026-08-22

| attempt | earlier verdict | what it actually is |
|---|---|---|
| **Menu-position prior** | rejected twice (as a standalone prior and as a calibrator feature) | **Correct as a calibrator feature, wrong as a score term.** Both rejections were measured on the uniform-over-senses dictionary gold. In the SCORE, `+0.02 * 0.5^rank` takes the OpenSubtitles panel 65.3% -> 84.7%. A prior belongs in the score, not in the confidence — the calibrator rejection still stands and is a different claim. |
| **POS menu filter** | abandoned as "not good enough; fails when most needed" | **A tagset mismatch, not tagger error.** spaCy is Universal Dependencies; SpanishDict publishes 17 DET senses in 96,279 and files determiners/possessives as ADJ. The filter read "tagged DET, sense is ADJ" as a contradiction and deleted the correct sense on `esta`, `este`, `otro`, `mío`, `nuestros` — the commonest words in the corpus, hence "when most needed". Unbridged: fires on 70 of 144 panel items, kills every acceptable sense on 7 (10%). Bridged (`sense_compatible_bridged`): 63 fires, 1 kill (2%), worth +2.8pp. A better tagger was NOT the answer — `es_dep_news_trf` already scores 12/12 on a hard ambiguous-surface probe where `es_core_news_lg` scores 8/12. |
| **Per-word z-scoring of the cosines** before the prior | untried | Measured and rejected: 77.8% at best against 84.7% for raw cosine + prior. The per-word spread carries information; flattening it destroys it. |
| **Subtracting the word's mean corpus context** from each gloss score | untried | NOT tested — `examples_raw.json` keeps only 3 sentences per word and the larger sentence bank is unembedded. Open, not dead. |

## The pattern

A short gloss embedded by a frontier model is a strong baseline, and **every
attempt to add information also added noise**, because the added text is topical
while the decision is lexical. Nearly every row above lost to plain gloss-cosine.

Sharper statement of the same thing, which is the useful takeaway: every failed
signal matched on **presence** (this topic is nearby, this cue is in the
sentence, this example resembles the line) and the one that worked matched on
**relation** -- aligned English is a word-to-word correspondence, so it says
something about THIS token rather than about the sentence's subject matter.
`argumento` matched *argumental*; the cue for `poder` matched a different
`poder`. Anything further in this direction needs syntactic relation (does the
target actually govern that word), which is a parse, not a lexicon.

The two things that DID work in the same session both left the gloss text alone
and changed *who decides*:

- **Gated BETO tuple vote** (`--tuple-vote beto --tuple-vote-min-gap 0.02`):
  60 better / 13 worse on all 88 changed picks; +2.40pp tuple on gold. Ungated
  it is a wash (20/13) — the gate is the finding.
- **Aligned English** (mBERT SimAlign + gloss-head match): 49 better / 12 worse
  on 100 fresh hand-graded speech cards. Not built into the pipeline.

## Rejection curves (why leaf accuracy cannot be bought by cutting)

Ranking by tuple-target confidence, held out on 10,462 items:

    reject 50%  ->  tuple 98.5%   gloss 60.0%   leaf 56.9%
    reject 60%  ->  tuple 99.1%   gloss 59.3%   leaf 56.4%
    reject  0%  ->  tuple 82.4%   gloss 52.3%   leaf 48.9%

Tuple accuracy responds sharply to rejection; **leaf accuracy is flat across the
whole curve**. Leaf errors are near-synonym shuffles that occur everywhere, not
hard sentences that can be filtered out.

Selection bias from rejecting 50%: 52% of distinct gold tuples retained, kept
items have LARGER menus than dropped ones (17.8 vs 13.6 leaves), and the POS mix
shifts mildly (adjectives dropped ~1.6x more than nouns). For senses with >=4
gold sentences, the median sense keeps 67% of its own sentences — so rejection is
a property of the SENTENCE, recoverable by harvesting more, except for the 15% of
senses where no sentence ever clears the bar.
