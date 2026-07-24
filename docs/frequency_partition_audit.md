# Frequency partition audit (2026-07-24)

## Corrected distribution

Measured through the front-end's default artist filters after the lemma-pooling
fix, using `corpus_count` for form mode and unique pooled example lines for
lemma mode:

| Artist | Form cards | Forms at 2–3 | Lemma cards | Lemmas at 1–3 |
| --- | ---: | ---: | ---: | ---: |
| Bad Bunny | 4,022 | 44.4% | 2,069 | 44.9% |
| Rosalía | 980 | 49.7% | 599 | 59.4% |
| Young Miko | 1,418 | 45.6% | 865 | 51.1% |

Pooling correction removes the raw-token/example mismatch, but it confirms
that the low-integer tail genuinely contains roughly half the teachable deck.
A single `≥2` or `≥1` final band therefore cannot provide useful scrub
resolution.

The source order is not a reliable frequency order either. The current Young
Miko filtered form deck contains 83 places where frequency rises between
adjacent source entries (for example, a 19-count card before a later 90-count
card). Percentage mode now explicitly sorts on its effective frequency while
retaining source `rank` as the stable ID/tie-breaker.

## Partition design

The scrubber creates ten bands:

1. Start each boundary at an equal-card quantile.
2. Snap it to a real frequency cliff when that cliff is within one quarter of
   the ideal band size.
3. Otherwise keep the quantile, intentionally splitting a large tied tier.
4. Label cliff boundaries `≥N`; label a cut within a tied tier with both facts,
   for example `2× · 3.2k`.
5. Compute coverage from the same effective frequency that ordered the deck:
   raw corpus occurrences for forms, unique pooled example lines for lemmas.

This keeps the head semantically aligned to natural cliffs while giving the
long tail several honest, similarly sized study bands. Smart levels use
post-filter `displayRank` end-to-end; source rank remains available for word
identity, progress, and legacy CEFR ranges.
