# Speech mode — layer and identity restructure

> **Implemented 2026-08-15, with corrections.** See
> `docs/reference/surface_identity_migration.md` for what was actually built and
> how to roll it back. Two numbers below did not survive re-derivation: the
> "1,126 fabricated lemmas" are 89% real SpanishDict headwords for that surface
> (only 4 are fabrications), and the "15% of corpus mass" split proportionally
> falls to 3.1% once lemmas come from `word_inventory.known_lemmas`. The
> decision still stands, on the re-run blast radius instead: re-running the
> classifier destroyed 1,185 card IDs while only 52 surfaces changed.

Design note, 2026-08-12. Written from a working session that rebuilt speech mode
end to end, so every number here was measured on the repo rather than estimated.
The point of writing it down is that these decisions should not be re-litigated.

Artist mode already moved to immutable evidence + claims. Speech mode has not, and
this is what it should move to.

---

## 1. Why restructure

Not performance. The problem is that **derived facts are stored positionally and
identity is derived from decisions**, so changing anything cheap forces re-running
something expensive, and revising a decision silently destroys learner-facing data.

Four structural faults, all hit directly during the rebuild:

**Identity is derived from a decision.** Card id is `md5(word|lemma)`, and the lemma
comes from `sense_assignments_lemma`. So *which sense a classifier picked* decides
*what the card is*. Emptying the assignment layer deleted **1,649 cards**; only 22
appeared in `id_migration.json`, because a card that *disappears* produces no
migration entry, only a card that *changes* does.

**References are positional.** `{"sense": "abc", "examples": [0, 1, 5]}` indexes into
a list that gets rebuilt. Change the example set and every assignment silently points
at different sentences. This is the whole of "I can't change examples without
re-running everything" — it is not a speed problem, the reference is unstable.
`util_5a_example_id.example_id()` already computes a content hash; assignments just
don't key on it.

**No resolution policy.** Artist mode has evidence profiles, `method_priorities` and
prompt-acceptance policies. Normal mode had a hard-coded `METHOD_PRIORITY` dict and
*no policy hook at all* — `step_8a` called `resolve_best_per_example()` without
`accepted_model_prompt_ids`. That is precisely why old runs leaked into new decks
and why "serve only method X" was not expressible. A `--prompt-policy` flag was
added during this session as a stopgap.

**The build is all-or-nothing.** `step_8a` reads every layer and rewrites the whole
deck. There is no way to change one word's examples, or re-assign one word, and look
at it.

A fifth, smaller: the index is built from a field whitelist, so a new method's
metadata (confidence) never reaches the app without a patch tool.

---

## 2. The model: everything is a claim

One record shape, one store, one resolver.

```
{ subject, predicate, value, method, run_id, prompt_id, confidence, inputs_fingerprint }
```

- **Import is a claim.** *"run R, importer v2, admitted sentence S for word W,
  because it passed these gates at score 1.18."* You can then answer "why is this
  sentence in my corpus" — which is what makes swapping the selection algorithm safe.
- **Sense assignment is a claim.** *"run R, embed-v1, sentence S means sense 64a,
  confidence 0.049."*
- **POS, noise, elision, lemma attribution** are claims.
- **Progress is a claim stream too** — an observation, not a derived belief (§3).

Today the same idea is implemented three times, differently: `sense_assignments`
carries provenance, `examples_raw` carries none, POS lives in a separate layer with
none. Unifying them buys the property that actually matters:

> **Swapping an algorithm becomes a diff over claims, not a re-run.**
> "importer v3 admitted 400 sentences v2 didn't, dropped 120 it did" is a query.

Sentences are content-addressed and immutable. Nothing is deleted; claims are
superseded.

---

## 3. Identity: the surface form

**Card key = surface form. Lemma is a label on each sense, not a splitter.**

### Why not lemma, and why not sense

The product is an ordered curriculum — teach the most common words first. **Frequency
is only observable at the surface.** Reliable "most common surface forms" lists exist
for Spanish and every other language. There is no reliable most-common-lemma list and
certainly no most-common-sense list. A sense-keyed deck cannot be ordered at all, so
card-per-sense is ruled out however elegant it looks.

Surface is also the only thing known with certainty at import time. Lemma, sense and
POS are all inferred and revised. Keying on an inference creates a circular
dependency: identity needs the lemma, the lemma needs disambiguation, and
disambiguation is per-occurrence — `una` is the article here and could be `unir`
there. `word|lemma` was a hedge against this that materialises *every* hypothesis as
a permanent card.

### What the measurements say

| | |
|---|---|
| surfaces with >1 lemma | 2,123 → **2,277 extra cards (19%)** |
| corpus mass on those surfaces | **15%**, divided proportionally to *how many examples each lemma happened to be assigned* (`step_8a` line 827) |
| surfaces whose deck lemmas the inventory does not even list | **1,126** — `nada→nadar`, `así→asir`, `era→erar`, `para→parar` |
| cards | 11,729 → **9,452** surfaces |

So frequency ranking — the spine of the curriculum — is partly a function of
classifier noise, and a sixth of the splits are fabrications.

### Card size does not regress

| meanings per card | today (`word\|lemma`) | re-keyed on surface |
|---|---|---|
| mean | 2.3 | 2.8 |
| median | **2** | **2** |
| p90 | **5** | **5** |
| >8 meanings | 1.6% | 2.1% |

Median and p90 are identical. The lemma split was never doing size work.

### POS and level are never keys

Every sense already carries exactly one POS, so POS is derivable and adds no
information to a key — while importing the tagger's errors into identity. Level is a
property of the learner–item relationship, not the item.

### Progress: observe coarse, derive fine

- **Stored (immutable):** *"saw surface `puedo` in sentence S, correct."* Surface is
  observed and never revised, so this can never orphan.
- **Derived (recomputable):** *"therefore probably knows `poder`, therefore probably
  knows `puedes`."*

Lemma roll-up is **mandatory**, not optional — without it a learner studies `poder`
five times, which is what `word|lemma` was protecting against. But it is a *view*.
When WSD improves and a sense moves to a different lemma, the credit recomputes and
no stored progress moves.

A card can therefore be **partly known** — `una`'s "a/an" sense known via `un`, its
"unites" sense not. The scheduler asks "does this card have an unlearned sense worth
showing", not "is this card learned". This only bites on multi-headword surfaces;
49% have a single headword and stay fully binary.

---

## 4. The menu, and the provider seam

**The SpanishDict menu stays.** Gemini embeddings replace the *classifier*, not the
inventory. The thing that varies by language is where the menu comes from.

Crucially, the menu layer is **already surface-keyed and already carries the
headword on every sense**:

```
una      27 leaves   headwords: {una: 2, unir: 7, unirse: 6, un: 4, uno: 8}
puedo    27 leaves   headwords: {poder: 25, poderes: 2}
gracias  26 leaves   headwords: {gracias: 5, gracia: 21}
```

That is exactly the "lemma as a label on the sense" model — it exists today. Surface
identity does not create a larger menu; it stops carving the existing one into
`word|lemma` slices after the fact.

### Size is a redundancy problem, not an identity problem

| | leaves per surface |
|---|---|
| raw | mean 9.7, median 7 |
| merging identical glosses | mean 8.4 |
| + gated shared-context merge | **mean 7.5, median 5** |

But the tail is fat, and it is *not* caused by cross-lemma ambiguity:

| percentile | merged meanings |
|---|---|
| p50 | 5 |
| p75 | 10 |
| p90 | 16 |
| p99 | 34 |

**17% of surfaces exceed 12 merged meanings**, and the worst are `dado`, `salido`,
`di`, `sale`, `salida`, `pica`, `pico` — single hyper-polysemous headwords
(`salir`, `dar`, `picar`) plus participles doubling as adjectives and nouns. No
identity scheme touches that; only merging, share-ordering and progressive
disclosure do.

### UI consequence

1. merge equivalent leaves (9.7 → 5.0) — the biggest single win, gated by gloss-vector
   similarity on the **headword-free** rendering
2. order senses by measured share within the surface
3. hide senses with zero observed occurrences — newly possible, because share is now
   measured rather than inferred from a classifier assignment
4. progressive disclosure for the 17% tail

### Where SenseNet fits

As a **coarsening layer over** the menu, not as the menu. Evidence against
replacement, measured earlier: WordNet-family Spanish coverage is the hard ceiling
(~13% of cases had no correct option — `pavo` with no "turkey"), and naive
substitution of WordNet definitions moved accuracy 70% → 66% by homogenising sibling
senses. SpanishDict supplies Spanish-side coverage; a hierarchy supplies structure.

Store sense keys as `(provider, provider_sense_id)` so a later provider is a mapping,
not a rewrite. **BabelNet**: better Spanish coverage than OMW, but licensed for
commercial use, and its merged encyclopedic entries add junk options to menus — bad
for a "never attach an obviously wrong sense" metric. Ranked third, behind fixing
lemma routing and behind testing the `wiktionary` sense source already in the repo
and currently unused.

---

## 5. Explicitly not doing

- **Multi-language learners.** Not a product goal; do not pay design costs for it.
- **Card per sense.** Cannot be ordered — no curriculum.
- **POS or level in the key.**
- **Replacing SpanishDict with a WordNet-family inventory.**

---

## 6. Migration

Identity and restructure move together, once, with a migration — not incrementally.

1. Emit `old_id → new_id` for all ~11.7k cards. Every old card maps to exactly one
   surface, so this is provably total. The app already consumes
   `Data/{lang}/id_migration.json` (`js/auth.js`), gated behind an
   `id_migration_vN` localStorage flag — **bump the flag version** or existing users
   never run the new migration.
2. Snapshot first: `pipeline/tool_snapshot_layers.py snapshot`. Restore is one
   command and was round-trip verified (corrupted file restored byte-identical,
   intruder file removed).
3. `tool_snapshot_layers.py verify` after each stage — it diffs the word-id map and
   reports any card that moved or vanished.

### Known debt to fix during the move

- **Lemma routing** produces junk attachments (`una→unir`, `puedo→poderes`,
  `trabajo→trabajar` for the noun). Under surface identity these stop being phantom
  cards, but the sense still lands on the wrong headword.
- **2,589 empty-translation leaves** (2.7% of 96,279) — over-represented among errors
  because an empty gloss embeds as a near-random vector.
- **1,142 cards** in the current deck are justified solely by `legacy-unknown`
  evidence and vanish the moment a prompt policy is applied. That is the re-run
  backlog, and it should be an explicit list rather than a surprise.

### Backlog item agreed this session

Prefer originally-Spanish-language films for examples: join `title_id` (an IMDb id)
against IMDb's `title.akas.tsv.gz` to get original language/region, and add it as a
**scoring bonus, not a gate**, so supply never starves for rarer words.

---

## 7. Confidence, for reference

Absolute cuts transferred from the hand-labelled panel at
`Data/Spanish/Intermediates/wsd_sense_harness` — not quantiles of a run:

| band | cut | measured on panel |
|---|---|---|
| high | gap ≥ 0.035 | 100.0% acceptable |
| medium | gap ≥ 0.021 | 91.9% |
| low | below | 84.5% overall |

On the 2,500-sentence subtitle run: 8% high, 7% medium, 86% low. Subtitle sentences
score materially lower than dictionary examples, which is real and worth keeping
visible — a run-relative banding would have hidden it behind a comfortable 10/15/75.
