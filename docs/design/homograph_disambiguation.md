---
title: Homograph lemma disambiguation
status: implemented
created: 2026-04-09
updated: 2026-04-09
---

# Homograph Lemma Disambiguation

## Problem

When a surface form maps to multiple lemmas (e.g. "como" -> como|como + como|comer),
both entries in the word inventory receive identical corpus_count values because the
raw frequency CSV counts surface forms, not lemma-disambiguated tokens. This causes
rare lemma pairings like como|comer to appear as top-frequency flashcards when the
verb "I eat" reading accounts for maybe 15% of actual usage.

1,104 homograph surface forms in the Spanish inventory, producing 2,241 entries total.

## Approaches tried

### spaCy es_core_news_lg (adopted for majority)

Run over Tatoeba sentences (144K Spanish sentences). For each homograph surface form,
find up to 20 matching sentences, run spaCy, tally which lemma it assigns.

**Results**: Works well for noun/verb splits (trabajo 89% noun, hecho 71/29, espera
91/9, estado 95.5/4.5). Fails on verb/verb homographs — gives 100/0 for fue (ser/ir),
ven (ver/venir), como (como/comer) because the tagger has a strong prior for the
dominant reading and never considers the alternative.

807 of 1,104 homographs are "self-lemma + conjugation" type (one lemma equals the
word itself). 297 are "verb/verb" (neither lemma equals the word). spaCy handles
both categories but is unreliable when both readings are common.

### Stanza (rejected — same quality)

Tested same 10 pairs. Identical failure modes to spaCy — both use Universal
Dependencies training data for Spanish. Stanza additionally produced ghost lemmas
("sento" for siento, which isn't a real Spanish word).

### Gemini 2.5 Flash Lite (tested, not adopted for bulk)

Two tests:
1. **Vibes-based**: Asked for frequency estimates without sentences. Gave plausible
   ratios but some were off (trabajo 50/50 when noun clearly dominates, acuerdo
   50/50 when noun dominates).
2. **Sentence-based**: Fed 20 Tatoeba sentences per word, asked for per-sentence
   classification. Better results — correctly classified fue/ir cases, como/comer.
   Some errors on fue (classified "Fue al mercado?" as ser when it's clearly ir).

Cost would be negligible (~$0.05 for all 1,104 homographs) but accuracy wasn't
clearly better than spaCy + manual overrides for the overall task.

### Deterministic heuristic "self-lemma wins" (rejected)

If word == lemma for one entry (como|como) and word != lemma for another (como|comer),
flag the non-self as minor. Breaks down for: verb/verb cases (fue — neither is
self-lemma), cases where self-lemma is the rare one (vino|vino "wine" is less common
than vino|venir "came"), and the ir/ser family (32 shared forms, none self-lemma).

## Decision

**spaCy for all 1,104 homographs + manual overrides file for corrections.**

spaCy resolves ~990 homographs with usable ratios. For the ~100 with no Tatoeba
coverage, equal split is applied. For cases where spaCy gives wrong 100/0 splits
(primarily verb/verb collisions and common noun/verb pairs), manual ratios are
maintained in `Data/Spanish/layers/homograph_overrides.json`.

Overrides take priority over spaCy. The file is a JSON dict mapping surface form
to `{lemma: ratio}` where ratios sum to 1.0.

## Implementation

**Where**: `pipeline/build_inventory.py` — `compute_homograph_ratios()`
runs as part of step 1 of the normal-mode pipeline.

**Flow**:
1. Load CSV, build entries with raw corpus_count
2. Group by surface form to identify homographs
3. Load manual overrides (applied first, take priority)
4. Run spaCy over Tatoeba for remaining homographs
5. Multiply corpus_count by ratio for each entry
6. Write `homograph_ratio` field to inventory entries

**Files**:
- `pipeline/build_inventory.py` — disambiguation logic
- `Data/Spanish/layers/homograph_overrides.json` — manual corrections (~108 entries)
- `Data/Spanish/layers/word_inventory.json` — output with adjusted counts
- `Data/Spanish/corpora/tatoeba/spa.txt` — sentence source for spaCy

**Flags**: `--skip-homographs` skips the entire disambiguation step (faster rebuilds
when frequency doesn't matter).

## Override categories

The 108 manual overrides fall into these groups:

- **ir/ser family** (8 forms: fue, fui, fueron, fuiste, fuimos, fuese, fueran, fueras)
  — spaCy always picks one verb, never the other
- **Common noun/verb pairs** where verb is non-trivial (sal/salir, traje/traer,
  oído/oír, apoyo/apoyar, ganas/ganar, etc.)
- **"Yo form = noun" pattern** (desayuno/desayunar, almuerzo/almorzar, comienzo/comenzar,
  regreso/regresar) — both readings genuinely common
- **ver/ir/venir overlaps** (ve, ven) — spaCy picks one verb exclusively

Words left at spaCy's 100/0 are genuinely rare verb forms (esposa/esposar,
equipo/equipar, campo/campar, estrella/estrellar, soldado/soldar).

## Adapting for other languages

The approach generalises to any language with:
1. A frequency CSV with word|lemma pairs (the homograph source)
2. A sentence corpus for spaCy to disambiguate against (Tatoeba works)
3. A spaCy model for the target language
4. Manual overrides for the cases spaCy gets wrong

The override file will be different per language — verb systems vary. French would
have similar ir/etre overlaps; Italian would have similar noun/verb homographs.
Expect 50-150 manual overrides per language depending on morphological complexity.

The spaCy failure mode (100/0 for verb/verb homographs) is consistent across
languages because it's a limitation of the tagger architecture, not the language
model. Budget time for manual review of 100/0 splits.
