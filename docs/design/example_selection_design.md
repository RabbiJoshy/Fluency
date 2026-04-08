---
title: Example sentence selection
status: implemented
created: 2026-04-07
updated: 2026-04-07
---

# Example Sentence Selection — Design Notes

Reference for how `build_examples.py` picks example sentences and what needs to change.

## Current behavior (2026-04-07)

`select_examples()` scores candidates on two metrics, sorted lexicographically:

```python
scored.sort(key=lambda x: (-x["_prox"], x["easiness"]))
```

1. **Proximity score** (primary): `sum(1/(1 + |target_rank - token_rank|))` for every inventory word in the sentence. Higher = more nearby-rank words.
2. **Easiness** (tiebreaker only): median frequency rank of all tokens. Lower = easier sentence.

After sorting, diversity sampling picks from thirds of the top candidates.

### Problem

Proximity is an unnormalized sum over all tokens. Longer sentences have more tokens, so they accumulate higher proximity scores regardless of quality. A 25-word sentence with 8 nearby-rank words always beats a clean 6-word sentence with 2. This produces sentences that are too long to fit on a flashcard and harder to read than necessary.

The underlying goal of proximity scoring — making sure the sentence contains words the user is studying alongside the target — doesn't require density. It requires 1-2 co-occurring words from a tight rank window.

## Requirements

Three goals, in rough priority order:

### 1. Deck overlap (co-study words)

The sentence should contain at least 1-2 words that will appear in the same study set as the target word. Since the user filters dynamically (cognates on/off, lemma mode, etc.), we can't know the exact deck. But words within ±10 rank of the target will almost always end up in the same set of 25, regardless of filter settings.

- Count inventory words within ±10 rank of target
- Cap benefit at 2-3 (more doesn't help)
- This is a tier/threshold signal, not a continuous score

### 2. Easiness (progressive difficulty)

The `easiness` metric (median rank of tokens in the sentence) already works well. The front-end re-scores with `computePersonalEasiness()` to exclude known words, so sentences get harder as the user progresses.

- Keep easiness as a quality metric
- Lower easiness = easier sentence = preferred within a tier

### 3. Sentence length (fits on card)

Sentences must fit on the flashcard. Currently there's a hard cap of `MAX_SENTENCE_WORDS = 25` at the candidate level and a `truncateText(text, 20)` in the front-end. But even 20 words can be too long for comfortable reading on mobile.

- Prefer shorter sentences when other metrics are equal
- Soft penalty above ~12-15 words, not just a hard cutoff
- The front-end truncation is a safety net, not the primary control

## Proposed scoring

Replace the lexicographic sort with a combined score:

```
overlap_tier = min(count of inventory words within ±10 rank, 2)
length_penalty = max(0, word_count - 12) * PENALTY_WEIGHT
score = overlap_tier * OVERLAP_WEIGHT - easiness - length_penalty
```

Sort by `(-score)`. This gives overlap tiers priority but lets easiness and length differentiate within tiers. Weights TBD — need to test on a few words (e.g., `separado`) to calibrate.

## Diversity sampling

Current approach: pick from thirds of the top candidates. This works and should be kept — it ensures a mix of easy/medium/hard sentences per word. The change is only in how candidates are ranked before bucketing.

## Open questions

1. Should the rank window for overlap be ±10 or ±25? Tighter = more likely to land in the same set, but fewer candidates.
2. Should we add an explicit length cap lower than 25? E.g., reject sentences > 18 words entirely?
3. Is the median-rank easiness metric the right one, or should it be the count/proportion of unknown words?
4. Does OpenSubtitles produce systematically shorter sentences than Tatoeba? If so, the source balance matters for length control.
