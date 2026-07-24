# Lemma example/frequency pooling audit (2026-07-24)

## Finding

Lemma mode compared unlike quantities. `buildFilteredVocab()` summed raw
`corpus_count` tokens across every surface form, while
`poolLemmaSiblingExamples()` deduplicated lyric/example lines and then capped
each host meaning at 25 examples. The card front displayed the raw-token sum.

Bad Bunny's `gastar` lemma demonstrates the mismatch:

- 41 raw token occurrences across 9 indexed forms;
- 28 unique example lines across those forms;
- only 25 examples retained by the old front-end cap;
- `gasté` displayed frequency 41.

Across Bad Bunny lemma representatives, the median raw-token/unique-line ratio
is 1.0, but the 90th percentile is 3.0. Repeated chorus/refrain words produce
much larger gaps, so the mismatch is structural rather than a one-word error.

## Multi-artist defects

`joinWithMaster()` keeps only senses used by an artist and records their
original `_masterSenseIndex`. The merge ignored that index and combined the
shortened arrays by compact position. In the three current Spanish artist
indexes, 1,878 shared word IDs have different used-sense index sequences, so
position-based merging can attach examples to the wrong sense or drop them.

Per-artist `most_frequent_lemma_instance` flags were also retained after union.
The three-artist merge therefore had 700 lemmas with more than one distinct
representative surface-form ID, defeating one-card-per-lemma mode.

## Resolution

- Pool all unique example lines (remove the 25-example truncation).
- Derive `lemma_example_count` / `pooled_frequency` from that same unique-line
  union and use it on the card front; retain `lemma_total_count` as the raw-token
  diagnostic only.
- Load the example layer before computing lemma-mode setup ranges.
- Merge master senses by `_masterSenseIndex`, deduplicate merged examples, and
  rebuild master-indexed example buckets after the full merge.
- Recompute exactly one combined-corpus representative per merged lemma.

The frequency-partition follow-up should use `pooled_frequency` in lemma mode
and `corpus_count` otherwise.
