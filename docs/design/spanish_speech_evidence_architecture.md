---
title: Spanish Speech Mode evidence architecture
status: candidate-method
language: spanish
created: 2026-08-03
updated: 2026-08-03
---

# Spanish Speech Mode evidence architecture

## Product contract

Speech Mode needs only three published outputs:

1. important SpanishDict senses for a Spanish surface/headword;
2. honest approximate prominence, preferably broad bands rather than exact percentages;
3. one or more good examples attached to each displayed SpanishDict sense ID.

Personalised generation is not part of this architecture. Artist Mode remains a separate corpus-defined problem.

## Candidate method

SpanishDict is the sole authoritative sense inventory. Corpus sentences are assigned directly to stable SpanishDict leaf IDs or abstained. No WordNet, BabelNet, embedding cluster or generated inventory is allowed to sit between the sentence and the product sense. External WSD resources may later provide an auxiliary vote through sparse high-confidence mappings, but they cannot replace or mutate the SpanishDict menu.

Prominence sampling and example selection are separate consumers of the same assignment layer:

- Prominence uses random occurrences and keeps all abstentions in the denominator.
- The example bank may retrieve learner-friendly or source-specific sentences, but only accepts audited sense attachments.

This is now the intended Speech Mode direction. It remains versioned rather than replacing the
legacy deck in place: evidence can improve independently, while stable SpanishDict sense IDs and
reviewed examples can be ported forward without treating legacy percentages as truth.

## App adoption and reversibility

The first app-facing deck is immutable at:

`Data/Spanish/runs/speech_vnext/2026-08-03_pilot_v0_1/deck.json`

`index.html?speech=vnext` loads that artifact through the existing flashcard renderer. The ordinary
`index.html` route still reads `Data/Spanish/vocabulary.index.json` and
`Data/Spanish/vocabulary.examples.json`, so the prior method remains immediately recoverable.

The vNext deck records the old whole-word IDs and stable SpanishDict leaf IDs. It also retains all
non-displayed dictionary senses in the artifact, even though the learner route shows only selected
senses. Legacy numeric distributions, personalised frames and unaudited corpus attachments are
referenced but are not imported as vNext truth. This separation makes future migration selective:
useful reviewed work can be copied forward by stable ID without coupling the new method to the old
pipeline.

## v0.1 artifacts

`tool_8e_build_speech_evidence.py` creates an explicit experimental run with independent artifacts:

| Artifact | Authority | Mutable interpretation? |
|---|---|---|
| `config.json` | Requested surface/headword/POS/forms and sampling policy | No |
| `inventory.json` | Snapshot of SpanishDict senses, IDs and canonical examples | No |
| `occurrences.jsonl` | Random corpus evidence with stable IDs and exact provenance | No |
| `assignments.jsonl` | Replaceable classifier decisions and abstentions | Yes, by a new versioned method/run |
| `summary.json` | Derived counts, coverage and provisional bands | Yes, deterministic from assignments |
| `example_bank.jsonl` | High-confidence single-ID candidates | Review-only in v0.1 |
| `human_review_template.jsonl` | Stratified audit queue | Human evidence |
| `manifest.json` | Input hashes, model/prompt identity and artifact hashes | Run record |

The current tool has three commands:

```bash
python3 -B pipeline/tool_8e_build_speech_evidence.py prepare \
  --config Data/Spanish/Intermediates/speech_mode_evidence/config_v0_1.json \
  --run-dir Data/Spanish/Intermediates/speech_mode_evidence/runs/2026-08-03_v0_1

.venv/bin/python -B pipeline/tool_8e_build_speech_evidence.py classify \
  --run-dir Data/Spanish/Intermediates/speech_mode_evidence/runs/2026-08-03_v0_1 \
  --batch-size 25 --apply

python3 -B pipeline/tool_8e_build_speech_evidence.py summarize \
  --run-dir Data/Spanish/Intermediates/speech_mode_evidence/runs/2026-08-03_v0_1
```

Without `--apply`, `classify` makes no API call and writes only a prompt preview. Classification is resumable by stable occurrence ID.

## v0.1 measured run

The first generic run scanned all 61,434,251 aligned OpenSubtitles lines and reservoir-sampled 25 occurrences each for `banco`, `cola`, `cura` and `sierra`.

Gemini 3.5 Flash Lite received only the exact SpanishDict menu for the requested headword and POS. It could return one or more listed IDs or abstain. The derived example gate requires `assigned`, high confidence and exactly one ID.

| Target | Sampled | High/unique candidates | Coverage | First-pass counts |
|---|---:|---:|---:|---|
| `banco` noun | 25 | 25 | 100% | financial bank 22; bench 2; pew 1 |
| `cola` noun | 25 | 19 | 76% | tail 13; line/queue 6 |
| `cura` noun | 25 | 18 | 72% | priest 9; cure 9 |
| `sierra` noun | 25 | 14 | 56% | saw 10; mountain range 4 |

The counts are directionally plausible. `sierra` correctly fails the 70% assignment-coverage threshold because names and phonetic-code uses are common in the surface sample.

## Safety finding

Model-reported high confidence is not a sufficient publication gate. A manual spot check found good abstention behavior for `cura` as an inflected verb and `Sierra` as a person, but also found high-confidence `cola` attachments that overextended SpanishDict's animal-tail leaf to figurative phrases such as “kick your tail.”

Therefore v0.1 corpus example outputs are explicitly marked `not_for_app` and every example-bank
record is `candidate_requires_human_audit`. The learner-facing vNext pilot includes only exact
SpanishDict examples; none of these corpus candidates are shipped in it.

The next gate must require independent evidence, for example:

1. deterministic lemma/POS/proper-name filtering;
2. direct SpanishDict classifier;
3. bilingual lexical or auxiliary WSD vote;
4. exact agreement on a leaf, or human review;
5. a separately measured precision threshold before publication.

## TV-series consequence

Corpus provenance is part of the occurrence identity rather than presentation metadata. A later importer can use series/season/episode/subtitle/line fields instead of OpenSubtitles document paths. The WSD and example-bank stages do not need to change. This allows a user-selected show to become an example source without becoming a new sense inventory.

## Falsification gate

Freeze the next prompt and gates before selecting 50 unseen polysemous words. Human-label a
stratified 300-line audit across at least two domains. Do not make corpus-matched examples or
evidence-derived prominence the default full-deck experience unless:

- published attachment precision is at least 98%;
- important-sense recall is at least 95%;
- fewer than 5% of words receive a materially wrong prominence ordering;
- every published record retains recoverable source and classifier provenance.

## Backlog relationship

GitHub issue #18, “Add real OpenSubtitles examples to Speech-mode MWEs,” overlaps the example-source portion but does not cover the broader SpanishDict inventory, WSD and prominence architecture. No new issue or external issue update was made during v0.1 setup.
