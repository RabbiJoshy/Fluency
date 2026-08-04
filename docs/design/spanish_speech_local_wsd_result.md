# Spanish Speech local WSD benchmark and fine-tune

## Decision

Do not replace the closed-set semantic gate with a locally hosted model. Neither
a zero-training multilingual reranker nor a small supervised fine-tune reaches
the 95% exact-leaf precision release gate, and both are beaten outright by the
already-benchmarked `gemini-3.5-flash-lite` gate, which scored 100% precision at
57.5% recall on the same panel.

This closes the "run it locally instead of paying per call" line of enquiry for
exact-leaf validation. Local models remain available for *retrieval* and for
diagnostic or consensus evidence, exactly as word alignment does — see
[spanish_speech_alignment_benchmark_result.md](spanish_speech_alignment_benchmark_result.md).

## Fixed benchmark

Both experiments were evaluated against the same frozen, manually labelled
60-row panel used by the alignment benchmark
(`Data/Spanish/Intermediates/speech_alignment_benchmark/2026-08-03_v1/panel.jsonl`):
40 valid exact-leaf attachments and 20 invalid ones, sense-stratified across
polysemous Spanish surfaces. Each model ranked only the SpanishDict leaves
available for that surface, scoring 891 candidate pairs per variant.

The panel was never used for training. In the fine-tune it is evaluation-only;
positives come from SpanishDict canonical examples and hard negatives from
sibling leaves of the same surface.

## Results

Reference point, from the prior benchmark:

| Method | Accepted | Precision | Recall of valid candidates | Panel coverage |
|---|---:|---:|---:|---:|
| Semantic same-leaf gate, medium/high | 23 | **100.0%** | 57.5% | 38.3% |

### Zero-training reranker — `tool_8h_benchmark_local_wsd`

`Alibaba-NLP/gte-multilingual-reranker-base`, revision
`a6258e9d2b1a11aa7bccdff9efde562bbca4393d`, on MPS.

| Variant | Accepted | Precision | Recall of valid candidates | Panel coverage |
|---|---:|---:|---:|---:|
| `definition` | 14 | 78.6% | 27.5% | 23.3% |
| `example` | 4 | 50.0% | 5.0% | 6.7% |
| `definition_example` | 10 | 80.0% | 20.0% | 16.7% |
| `definition_bilingual` | 31 | 74.2% | 57.5% | 51.7% |
| `definition_example_bilingual` | 25 | 80.0% | 50.0% | 41.7% |

Each variant completed the panel in 9–17 seconds at roughly 100 pairs/second.

### Supervised fine-tune — `tool_8i_finetune_local_wsd`

`bert-base-multilingual-cased`, revision
`3f076fdb1ab68d5b2880cb87a0886f315b8146f8`, on MPS. One epoch over 14,932
training pairs (5,000 positives selected from 95,568 available, two sibling
negatives per positive), batch size 16, learning rate 3e-05, lower 8 layers
frozen, 28,943,618 trainable of 177,854,978 parameters, 190.9 seconds of
training, final recent loss 0.466.

| Variant | Accepted | Precision | Recall of valid candidates | Panel coverage |
|---|---:|---:|---:|---:|
| `spanish_only` | 11 | 72.7% | 20.0% | 18.3% |
| `bilingual` | 54 | 68.5% | 92.5% | 90.0% |

## What the numbers say

The best local precision anywhere in either experiment is 80.0%, fifteen points
below the release gate and twenty below the semantic gate. Adding the aligned
English sentence buys recall but costs precision in every case, which is the
signature of a model keying on bilingual lexical overlap rather than resolving
the leaf.

The fine-tune's `bilingual` variant illustrates the failure most clearly: 92.5%
recall looks strong until you read the confusion matrix, where it accepts 54 of
60 rows and retains only 3 of 20 true negatives. It has largely learned to say
yes. `spanish_only` is the honest measure of what the fine-tune actually
learned, and at 72.7% precision it is worse than the untrained reranker's 78.6%.

Three hours of training and inference work did not move the task. The
distinguishing signal for close SpanishDict leaves is not present in these
models at this scale.

## Product consequence

Keep the architecture from the alignment benchmark unchanged: literal cues
retrieve, the closed-set semantic gate validates the exact leaf, alignment and
local rerankers stay as optional audit evidence. The release gate remains at
least 95% exact-leaf precision on a 200+ row stratified panel before any
corpus-wide run.

If local hosting is revisited, the evidence says the next attempt needs a
materially different setup — a larger instruction-tuned multilingual model, or
substantially more supervision than 5,000 dictionary positives — not another
pass at this scale. Both runners are reproducible and pinned, so a rerun against
a new model is a flag change.

Outputs live under ignored `Data/Spanish/Intermediates/speech_local_wsd_benchmark/`
and `Data/Spanish/Intermediates/speech_local_wsd_finetune/`. No deck, active run,
or front-end asset was touched by either experiment.
