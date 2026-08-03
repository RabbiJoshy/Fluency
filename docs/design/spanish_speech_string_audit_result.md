# Spanish Speech deterministic string audit — result

## Decision

Reject raw bilingual string matching as the SpanishDict WSD or sense-prominence
system. Preserve it as a cheap candidate-retrieval layer only.

Do not compile its counts into a learner deck. The active Spanish deck and all
immutable historical runs remain unchanged.

## Full-run result

The `2026-08-03_v1` run scanned all 61,434,251 locally aligned OpenSubtitles
lines with no model, embeddings, training, or API calls.

- 11,729 app cards and 9,453 distinct app surfaces
- 9,412 surfaces with SpanishDict menus
- 89,914 stable SpanishDict leaves
- 302,551,875 matched surface/line pairs
- 49,554,992 unique-English-cue matches (16.4%)
- 38,328 leaves observed by at least one cue

Those 49.6 million matches are not valid sense counts. English and Spanish
subtitles are aligned by sentence, not by word, so the English cue may translate
another Spanish token in the same line.

## Precision audit

A deterministic 60-row sample of assigned occurrences from polysemous surfaces
contained at least 14 plainly wrong or unusable attachments. That establishes a
precision ceiling of about 77% before debatable SpanishDict-context distinctions
are counted. This is far below a safe learner-facing sense attachment threshold.

Examples that demonstrate the failure:

| Surface and assigned leaf | Spanish subtitle | English subtitle | Why it fails |
|---|---|---|---|
| `hacer` → “to think” | `Creo que deberías hacer pociones nomás, Gaius.` | `I think that you should stick to cooking up potions, Gaius.` | “think” translates `creo`, not `hacer`. |
| `mano` → “way” | `Y la forma más rápida es levantar la mano.` | `And the quickest way is to show off hands.` | “way” translates `forma`; `mano` is “hand.” |
| `daba` → “to press” | `Si alguna vez la presionaba ... me daba esa mirada.` | `If I ever tried to press ... She gave me that look.` | “press” translates `presionaba`, not `daba`. |
| `planta` → “floor” | `Lo llevé a la segunda planta.` | `Take it up to the second floor.` | Correct; a distinctive concrete cue works well. |
| `banco` → “school of fish” | `¡Jefe, es un banco de sardinas!` | `Chief, it's a school of bluefish!` | Correct; the bilingual phrase supplies strong evidence. |

There is a second independent failure: an English gloss can itself be
polysemous. For example, `salir` + English “get out” was routed to SpanishDict's
leaf glossed “to get” in the context “to get a result.” The literal word matches
while the SpanishDict context does not.

## What survives

The run is still useful for:

- retrieving a large candidate bank for later WSD;
- finding especially distinctive bilingual phrases;
- measuring where literal dictionary glosses have any corpus support;
- constructing human-review or word-alignment benchmarks.

It cannot safely determine which senses to show, estimate their ordering, or
attach arbitrary television examples directly to stable SpanishDict IDs.

## Recommended next bounded experiment

Keep SpanishDict as the authoritative menu and canonical-example source. Test a
pretrained bilingual **word aligner** on a stratified subset of these retrieved
candidates. SimAlign performs inference from pretrained multilingual embeddings
without parallel-data training; AWESOME-Align provides pretrained multilingual
BERT alignment extraction and separately supports optional fine-tuning:

- [SimAlign paper](https://arxiv.org/abs/2004.08728)
- [AWESOME-Align paper](https://aclanthology.org/2021.eacl-main.181/)

Word alignment directly addresses the demonstrated wrong-token failure by
identifying which English token corresponds to the Spanish surface. It is
necessary but not sufficient: a semantic gate must still compare the full
SpanishDict translation **and context** because English cues such as “get” are
themselves polysemous. Compare aligner + closed-set semantic WSD with abstention
against the retained audit sample before any second full-corpus run.

The acceptance gate should be at least 95% exact-leaf precision on a manually
reviewed, POS- and frequency-stratified sample. Coverage is secondary because the
corpus bank is extremely large and the product needs only good examples and broad
prominence evidence, not an assignment for every occurrence.
