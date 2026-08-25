# WSD: open threads

Companion to `wsd_design.md`, which holds the goals and the philosophy. This file
holds the things that were proposed, partly measured, and **not ruled out** —
the live ends of the rope.

Read it as leads, not a backlog. Nothing here is a task list; several of these
are mutually exclusive and at least one is probably wrong. What each entry gives
you is the evidence that exists, why it stopped, and what would settle it.

**Things that ARE ruled out live in `wsd_dead_ends.md`.** Check there before
reviving anything, and note the warning at the top of that file about how its
older rows were measured.

---

## Part one: the specialists

The idea behind these is that SpanishDict's `context` field is not one kind of
thing. It carries domain labels (*medicine*, *nautical*), construction notes
(*used with "por"*), grammatical marks (*imperative; second person singular*) and
plain semantic paraphrases (*to be available*). Different types are decidable by
different evidence, so each gets its own small specialist rather than one scorer
trying to cover all of them.

The catch, measured, is at the bottom of this section. It does not invalidate the
approach; it bounds it.

### On the CONTEXT axis — which usage is this?

**1. Domain / register.** *medicine, legal, sports, nautical.* ~3.5% of
decisions. Match the domain label topically against the sentence.

> **Measured and dead as a separate term.** In isolation it is excellent: 92.6%
> at picking the right domain from a word's candidates against a 43% prior, on
> 500 dictionary examples. But adding it on top of the existing score is flat
> through weight 0.20 and negative beyond, because on the items where two or more
> real domains compete **the baseline is already 90.9%**. The domain word is
> inside the concatenated gloss text and the encoder recovers it fine.
>
> The useful residue: this killed the *dilution hypothesis* — that burying
> "medicine" as one token in eight wastes it. It does not. That also removes the
> main argument for embedding gloss and context separately.

**2. Companion note — `used with "X"`.** ~0.8% of decisions. Veto a leaf whose
companion word is absent from the line.

> **Measured positive, not built as a gate.** +2 items on the 200-item panel;
> earlier, 1 fix / 0 breaks across weights 0.02–0.20. `companion_of` already
> parses the note and `companion_satisfied` already evaluates it — but only
> inside leaf repair, i.e. to fix a leaf after it has been rendered, never to
> stop it being chosen. Moving it earlier is a small change with a measured
> number attached.

**3. Grammatical marks.** *imperative, second person singular, plural,
reflexive.* ~0.6% of decisions. Decidable from morphology and the conjugation
tables the repo already builds.

> **Partly built.** The `se`-only clitic gate is in and is 96.8% correct where it
> fires. Person and number agreement are not, though `verbecc` and
> `conjugation_reverse.json` make them cheap. `--gate dative-aware` exists and
> remains **unvalidated** — 9 better / 6 worse / 7 lateral on a hand-graded
> sample, which is the honest score, not a broken one. It needs a graded sample
> where fixes clearly exceed breaks, or removal.

**4. Frame / construction.** *used in comparisons, before adjective, used to
introduce a subordinate clause.* Decide from a dependency parse: does the target
take a direct object, which preposition governs it, is there a clausal
complement.

> **Tested crudely; mixed and worth revisiting.** Four binary features over
> silver labels showed no separation for `echar` — whose five contexts (*lay off,
> oust, estimate, propel, indicating an action*) all look like "verb + object" —
> but real separation for `haber` (auxiliary vs existential *hay*), `estar`
> (locative via `en`) and `seguir` (xcomp vs object).
>
> The diagnosis matters more than the result: what discriminated was **the
> lexical identity of the argument**, not the frame shape. `tener cuidado`,
> `echar un vistazo`, `echar la culpa`. That is collocation reached through a
> syntactic relation — which is the "relation not presence" pattern that works
> here — and it was never tested properly.

**5. Functional.** *used to indicate cause, used to express possession.* ~1.7% of
decisions. **Never attempted.** Probably semantic rather than structural, and
small enough that it may not deserve its own path.

**6. Paraphrase.** *to possess, to be available, to arrange to see.*
**73.6% of decisions.**

> **No specialist is possible and this is the important finding.** 4,408 distinct
> context strings; the top 25 cover 8.9% of the bucket. There is no small set of
> categories to write specialists for — it is a flat vocabulary of one-offs, and
> the strings are the meanings restated rather than a type system.
>
> This is what COMMIT exists for. When you cannot decide better, publish less.

### On the GLOSS axis — which English word is this?

**7. Aligned English.** Which English word does this token correspond to.

> **The strongest unexploited signal in the repo.** A *perfect* aligner decides
> 42% of items outright and **51% of current failures**. Historically it is also
> the only added signal that ever beat plain gloss-cosine here: 49 better / 12
> worse on 100 hand-graded speech cards.
>
> Two reasons it is worth returning to. First, speech mode has a parallel English
> translation for **every** sentence, it is already carried into the WSD request,
> and nothing reads it. Second, the earlier attempt used it as a per-occurrence
> *corrector* firing on ~16%; using it as an **aggregation key over the corpus**
> — group every occurrence of a word by the English word it aligns to — is a
> different and untested proposition.
>
> The honest limit: 42% is a ceiling assuming perfection, and real aligners are
> worst exactly on the function words (`por`, `como`, `una`) that dominate the
> hard cases.

**8. Multiword gloss as a competing candidate.** **Built and shipped** — the only
specialist that made it in. 15 wins of 29 panel occurrences carrying one, 12 good
by hand-grading. Recorded here so nobody rebuilds it.

**9. Exact gloss-string equality.** Not a scorer but a metric correction: when a
pick differs from gold by sense id yet the gloss string is identical, no card
changes. That is ~9% of errors, provably invisible. Worth applying to any
future measurement so it does not count invisible differences as regressions.

### The bound on the whole approach

Specialists 1–5 together reach about **5% of decisions**. That is the number that
stopped the piecewise plan being *the* answer.

It is not a reason to skip them. Each is cheap, each is permanent, and several
have measured numbers. It is a reason not to expect them to sum to a solution —
the mass is in paraphrase contexts, which is COMMIT's problem, not RANK's.

---

## Part two: threads outside the specialist frame

**10. Reject and redraw.** The disposition nobody implemented. If an occurrence
is uncertain, don't get cleverer — take a different sentence. The bank holds
42,650 and a card needs three.

> Aimed at the right axis, which is the whole point: **leaf accuracy is flat
> across the entire rejection curve while tuple accuracy climbs 82% → 98% at 50%
> rejection.** So rejecting because you are torn between *to end* and *to finish*
> wastes a sentence and changes nothing; rejecting because you may have the wrong
> lemma is exactly what rejection buys.
>
> Free in speech mode, unavailable in artist mode where the corpus is a user's
> fixed upload — which is where escalation substitutes. Limit: ~15% of senses
> never clear the bar in any sentence, so redrawing cannot rescue them.

**11. Method agreement as the escalation trigger.** 89.6% correct when the prior,
the embeddings and the prototypes agree; **18.8% when all three differ.** Routing
on it reached **91% accuracy at 41% escalation**.

> This matters because the trigger that *was* implemented — the tuple margin — is
> broken. It is non-monotonic against tuple correctness: the highest-margin
> bucket scores worst, because a single-analysis menu has a margin of 1.0 by
> construction and its errors are inventory gaps rather than choice errors. So
> the escalation path currently has no working trigger, and this is the measured
> replacement.

**12. A corpus-measured sense prior.** The menu prior is the single largest win
ever recorded here (65% → 85%), and it is a *proxy*: `0.02 × 0.5^rank` over
SpanishDict's ordering. Real per-sense frequencies, estimated from the corpus by
self-training over confident picks, would be grounded rather than assumed, and
**per-word rather than one global dial**. Untested.

**13. Usage prototypes, revisited at depth.** Representing a sense by the mean
contextual vector of its real uses scored *below* baseline — but the depth curve
is the finding, not the headline:

    <=5 examples behind the correct sense   -11.5pp vs the prior
    6-12                                     +7.7
    13+                                     +10.7  (89.3% vs 78.5%)

> The deck's median is **4**. So it was measured in the regime where it cannot
> work. A deeper harvest is the precondition, and the harvest is capped at 5
> sentences per word by config, having discarded 436,000 clean occurrences.

**14. Multiplicative combination of the marginals.** Scoring a leaf by the product
of its tuple, glosskey and leaf marginals rather than by its raw score. **+8 items
on the hard panel, +1 on the unstratified one.** Unresolved — the gap between
those two numbers is the panel bias in thread 16, not a refutation.

**15. Distillation from a frontier teacher.** Flash-Lite 3.5 scores **94.0%** and
DeepSeek **93.0%** on the hard panel, against 78.4% for the shipped stack, at
~$0.063 per 1k picks. Prototypes land ~3pp under whatever teacher produced their
labels — which is what distillation does — so the path is worth exactly as much
as the teacher. Distilling the current stack into itself is pointless; distilling
a 94% teacher is not. Blocked behind thread 13's depth problem.

---

## Part three: the instrument

**16. A frequency-sampled panel.** `pipeline/wsd_harness/panels/hard_200_2026-08-23`
is stratified on auxiliaries, reflexive pairs and high-polysemy words, which
over-samples words whose correct answer sits in a **large** menu entry. Any
heuristic that quietly favours the biggest entry therefore flatters itself there.

> Caught by testing sum-pooling across three panels: **+8** on the stratified
> panel, **+1** on an unstratified one. Every number from the hard-200 is soft in
> the same direction, **including the AUX fix's +14**.
>
> This gates threads 2, 11 and 14 honestly. It is the cheapest thing that
> unblocks the most, and it costs hand-labelling rather than money.

**17. The `no_menu` gap — coverage and lookup, NOT inventory.** `no_menu` is 1%
over the top 500 surfaces and **24% over the top 2,000**. That number was
previously written up here as a sense-inventory gap. It is not, and the
correction matters because it changes who has to fix it.

Auditing all 480 `no_menu` cards from the 2,000-surface run against the pinned
snapshot:

    138  inflected verb forms whose infinitive IS ALREADY in headword_cache
         (estabamos/estar, ocurrio/ocurrir, oi/oir, sucedio/suceder,
          vere/ver, creia/creer, terminado/terminar). The data is on disk
          and unread -- conjugation_reverse.json resolves them.
    342  ordinary words never fetched into the snapshot. surface_cache holds
         6,513 surfaces; the run asked for 2,000 mostly outside it. These
         are words like espada, excelente, maravilloso, sorpresa, decision,
         abuelo, detective -- SpanishDict plainly has entries for all of them.
      ?  genuinely absent from SpanishDict: UNMEASURED. We have never asked.

> So the real sense-inventory gap is **unknown**, and every published `no_menu`
> figure is an upper bound contaminated by a lookup bug and a partial scrape.
> Two cheap things settle it: wire `conjugation_reverse.json` into menu lookup
> (no network), then extend the snapshot to cover the surfaces actually
> requested. Measure the residue after that, and only then talk about inventory.
>
> Artist mode is where a true inventory gap would bite, and that argument still
> stands -- but it cannot be sized until these two are done.

---

## What to take from this

If forced to pick two: **the panel (16)**, because it is what makes the others
believable, and then **aligned English (7)**, because the data is already in the
request and it is the only signal with a history of beating the baseline.

But the framing that has held up better than any individual mechanism is in
`wsd_design.md`: *whether a mistake matters depends on the sentence, not on the
pair of senses.* Three mechanisms died on that rock. Anything proposed here
should be checked against it before it is built.
