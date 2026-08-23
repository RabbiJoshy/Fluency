# Word sense disambiguation in Fluency — design, and where it stands

## What this is for

Fluency turns real Spanish — subtitles now, song lyrics as the destination — into
vocabulary cards. A card shows a word, what it means, and a real sentence it was
used in. Word sense disambiguation is the step that decides *which* meaning goes
on the card for *this* sentence, out of the several a dictionary lists.

The project is half a product Josh wants to use and half an exercise in learning
how this kind of NLP actually behaves. Both halves matter. A solution that works
but teaches nothing is only half the point, and so is an elegant idea that never
reaches a card.

## The shape the solution has to have

**Expensive offline, near-free online.** Precomputation, embedding a whole
corpus, training something — all fine, they happen once. What is being protected
is the cost of the *next* deck. The destination is someone handing the app a
playlist or a set of films they are about to watch and getting a deck back
quickly and cheaply. Speech mode does not need that today — it is one fixed
corpus, built once — but a design that only works because the corpus is fixed is
the wrong design, so amortisation is treated as a requirement even while it is
not yet binding.

**Escalation to a frontier model is legitimate, and shrinking it is the work.**
There will always be a hard tail that only a good model gets right, and paying
for that tail is fine. The interesting problem is the middle: everything that is
too hard for the naive answer and too easy to be worth an API call. The
long-running task is to keep moving work out of the expensive bucket and into
the cheap one, and to know which bucket each item belongs in.

**It has to survive a menu that is wrong or absent.** Speech mode mostly gets a
usable dictionary entry. Lyrics will not: slang, regional usage and invented
senses are the norm, and sometimes the right answer is simply not in the
inventory. That is a separate problem from picking well among the options, and it
is deliberately kept separate — but any design that assumes the answer is always
in the menu is a design that will not port to the mode that matters most.

**It does not need to be perfect, and chasing perfection is the wrong instinct.**
Where a dictionary splits one meaning into near-identical readings, picking the
wrong one costs nothing a learner would notice. What is worth eliminating is
*classes* of consistent error — a whole category of words that reliably goes
wrong — not aggregate points. And there is one hard line: getting the **wrong
word** (wrong lemma, wrong part of speech) is never acceptable, because a learner
does notice a card for a different word than the one they read.

**Complexity is a cost to trade, not a limit.** A bigger mechanism that lets
several existing stages be deleted is a good outcome. Ten heuristics stacked on
each other, each worth a point, is not — not in something intended to run live.

**No loyalty to any provider or method.** Frontier API, open weights, a classical
technique, or nothing at all — whatever is actually best for the job. Embeddings
have earned their place partly because the labs keep improving them, so the repo
gets better without anyone doing anything; that property is worth real money and
counts against approaches that freeze a model someone then has to maintain.

## How the two modes relate

There is one sense inventory, and it is the same in both modes. Everything built
per-dictionary — vectors, priors, whatever is precomputed for a word — is shared,
built once, and does not care which mode consumes it. That is why work is done in
speech mode first: the menus have good coverage, every subtitle line has a
parallel English translation, and the corpus sits still long enough to measure
against.

What changes in artist mode is the surrounding economics and the failure modes.
The corpus is unbounded and user-supplied, so per-deck cost starts to matter and
caching by sentence begins to pay. The language is harder and less literal. And
the inventory stops being adequate — the missing-sense problem that speech mode
can mostly ignore becomes the main event.

So: speech mode is the laboratory, not the destination. A mechanism that only
works because the corpus is fixed, the language is plain, or the menu is complete
has not really been demonstrated.

## The difficulty landscape

It helps to hold the two ends fixed:

At one end, take the dictionary's first listed sense and accept it. This is free
and gets a surprising amount right, because dictionaries order senses by
frequency and common senses are common.

At the other, hand every occurrence to a frontier model with the menu and let it
choose. This is close to as good as the inventory allows, and cheap in absolute
terms, but it is a per-item cost that never amortises.

Everything worth building lives between those two. The design question is not
"how do we reach the top end" but "how much of the middle can be taken cheaply,
and how reliably can we tell which items are left".

## Vocabulary — use these words

The menu lives in `Data/Spanish/layers/sense_menu/spanishdict.json`:

```
"quedar":                          <- SURFACE FORM (the dict key; the word as it appears)
  [                                <- a LIST of ANALYSES, one per headword the form can be
    { "headword": "quedar",        <- HEADWORD (= lemma)
      "senses": {
        "a79": {                   <- SENSE ID; one entry here is a LEAF
          "pos":         "VERB",         <- SpanishDict's tagset, NOT Universal Dependencies
          "translation": "to be left",   <- the GLOSS
          "context":     "to be available", <- the CONTEXT (SpanishDict's usage note)
          "headword":    "quedar",
          "examples":  [ { "original": "...", "translated": "..." } ],
          "regions":   [...]              <- only 7.7% of leaves
        },
        "c63": { ... "translation": "to remain",       "context": "to be available" },
        "3c8": { ... "translation": "to be left over", "context": "to be available" }
      } } ]
```

| term | is | note |
|---|---|---|
| **surface form** | the inflected word as it appears | the dict key |
| **analysis** | one headword's senses for that surface | a surface can have several (`fuera` → `fuera`/`ser`/`ir`) |
| **headword** / **lemma** | dictionary form | |
| **leaf** | one sense id | `(pos, headword, gloss, context)` |
| **glosskey** | leaf with the context stripped | `(pos, headword, gloss)` |
| **contextkey** | leaf with the gloss stripped | `(pos, headword, context)` — the *sibling*, not a superset |
| **tuple** | `(pos, headword)` | what learner progress keys on; the existing repo term |
| **menu** | every leaf available for one surface form | |

Leaf, glosskey and contextkey form a lattice: both middle terms contain leaf,
neither contains the other. Mixing them up is easy and produces numbers that look
contradictory.

**Optimise glosskey.** Leaf is too fine — it counts *to say* → *to say* under a
different sense id as a regression. Contextkey is barely looser and is not the
unit a learner reads. Glosskey is the tightest metric that never punishes a
difference nobody can see.

Two properties of the schema that keep causing trouble:

- **`pos` is not Universal Dependencies.** SpanishDict files determiners as ADJ
  and has no AUX, NUM or PART at all. This mismatch has produced two separate
  silent bugs, and it will produce a third.
- **Nearly every leaf has exactly one example sentence.** Any plan that leans on
  the dictionary's own examples is leaning on a single sentence per sense.

Also worth knowing: the card **does** print the context, joined to the gloss by
`js/flashcards.js`. A wrong context is visible, not hidden.

## How the pipeline is organised

Whatever else changes, every mechanism here does exactly one of three jobs. This
is `pipeline/util_6g_v6.py`, and naming the three roles is most of what it does.

**Constrain.** Remove candidates that cannot be right — part of speech, clitics,
a multiword expression the line contains, a construction note the line violates.
These are hard vetoes, not scores. Every veto must record why it fired: a silent
veto that removes *everything* falls back to the full menu and becomes a no-op
with no symptom, which is precisely how one of them hid for months.

**Rank.** One score over whatever survives — the dictionary's own ordering as a
prior, plus semantic similarity between the sentence and each candidate's
description.

**Commit.** Decide *how specific* an answer to emit. This is the part worth
understanding, because it is the one idea here that is not a scoring trick.

A system that must always emit a leaf turns every uncertainty into a wrong card.
A system that can emit a leaf, or a glosskey, or just a tuple, turns uncertainty
into a *less specific* card instead:

```
confident throughout       ->  "está — is (location)"
unsure which context       ->  "está — is"
unsure which gloss too     ->  "estar — to be"
unsure of the word itself  ->  escalate
```

Escalation triggers on the **tuple** confidence alone. That follows directly from
the design goals: being torn between two synonyms is not worth an API call,
because the learner never sees the difference once the answer is emitted at
glosskey level. Being unsure *which word this is* always is, because that is the
one error that is never acceptable.

Declining to over-claim is always available and never wrong. Every mechanism that
has been tried and failed here was trying to *decide better*; this one sidesteps
the need to.

## A principle that keeps reasserting itself

**Whether a mistake matters depends on the sentence, not on the pair of senses.**

Two leaves can be freely interchangeable in one line and clearly distinct in the
next. This is why merging near-identical senses in advance is wrong, why a
precomputed "these two are close enough" table is wrong, and why every attempt to
decide *offline* which confusions are safe has failed. Judging whether an error
matters requires reading the sentence against both candidates — which is the
disambiguation task itself. There is no shortcut where a static property tells
you which decisions are safe to skip.

The corollary is the reason the Commit role exists: if you cannot cheaply know
whether being wrong would matter, then say less rather than guess.

---

# Measurements

> **Treat everything below as leads, not foundations.** These are one session's
> numbers, most of them from a single 200-item panel that is now known to carry a
> sampling bias (see the last part of this section). They are recorded so nobody
> re-derives them, not because they are settled. Where a number here contradicts
> your own measurement, believe yours.

## Where the current stack sits

On a deliberately hard 200-item panel of subtitle occurrences, stratified toward
auxiliaries, reflexive pairs and high-polysemy words
(`pipeline/wsd_harness/panels/hard_200_2026-08-23`):

| | glosskey accuracy | cost |
|---|---|---|
| dictionary's first sense | 67.3% | free |
| + part-of-speech filter | 74.4% | free |
| the shipped stack (v5) | 78.4% | free |
| Flash-Lite 3.5 / DeepSeek-chat | 94.0% / 93.0% | ~$0.06 per 1k picks |

Escalating on disagreement between the cheap methods reaches **91.0% at 41%
escalation** — 87% of the available gain for 41% of the spend. That is the only
measured way to occupy the middle, and it is a routing result rather than a new
mechanism.

Two corrections to `wsd_algorithm.md`, which still carries both errors: the gloss
embeddings are worth about **+11pp** on hard words, not the ~2pp its easier panel
implies; and its escalation cost is labelled "measured" but is a formula output,
and roughly a third low.

## What shipped

The part-of-speech filter had **no AUX entry in its tagset bridge**, so for any
token tagged AUX it rejected every leaf, hit the empty-set fallback, and became a
silent no-op on `haber, ser, estar, deber, saber` — the commonest verbs in
speech. Same mismatch as the DET→ADJ bug fixed before it. Now fixed and pinned by
a test.

`util_6g_v6.py` implements the three roles with everything unproven defaulted
off; it reproduces the shipped stack pick-for-pick. Turning on the construction-note
veto — a note the code already parses but only uses to repair a *rendered* leaf —
is worth a couple of items and is free.

## What was tried and did not work

**Usage prototypes** — representing a sense by the averaged contextual vector of
its real uses rather than by its gloss text — scored *below* the current stack.
The reason is depth: with five or fewer labelled examples behind a sense it is
worse than doing nothing; it only becomes strongly positive past a dozen. Deck
examples run to about four per sense.

**Aligned English** as the core mechanism. Even a *perfect* aligner decides
outright on well under half of items, because knowing which English word a token
is usually leaves several leaves still standing.

**A specialist per context category.** Domain labels are genuinely well predicted
by embeddings — over 90% in isolation — but only a small fraction of decisions
turn on a domain, and the great bulk of contexts are one-off semantic paraphrases
with no shared structure to exploit. The ceiling on this approach is a few
percent of decisions.

**Precomputed triage** — deciding in advance which confusions are harmless by
measuring how similar the candidate descriptions are. Separates at the extremes,
fails in the middle, for the reason in the principle above.

**Switching inventories** to WordNet or BabelNet. Those are *more* fine-grained
than a learner dictionary, so they make the granularity problem worse while
losing the slang coverage that motivated SpanishDict. Coverage was never the
problem. Consider this closed.

## The panel's bias, which affects everything above

Stratifying on auxiliaries, reflexives and polysemous words over-samples words
whose correct answer sits in a **large** menu entry. Any heuristic that quietly
favours the biggest entry therefore scores well on that panel and nowhere else —
which is how one promising result was caught being worth +8 items there and +1 on
an unstratified panel.

Every number from that panel is soft in the same direction, including the AUX
fix's headline size. The bug is real; its measured magnitude is inflated.

**The remedy, and the single most useful next piece of work: a second panel
sampled by corpus frequency rather than by difficulty class.** That one change
would firm up the commit thresholds, the AUX number, and the outstanding
scoring question in a single pass.

## Known and unfixed

- The multiword-expression layer is built, carries corpus frequencies, and the
  classifier never opens it. `junto a` reads as *together*; `sitio web` as
  *place*.
- The escalation prompt says "one line of song lyrics" even in speech mode.
- `wsd_algorithm.md` still carries both wrong numbers above.
- The missing-sense problem is untouched by design.
