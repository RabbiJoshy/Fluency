---
title: Word sense disambiguation
status: implemented
created: 2026-04-07
updated: 2026-04-08
---

# WSD (Word Sense Disambiguation) — Exploration Log

Reference for all approaches tried, decisions made, and current state.
Test set: `Data/Spanish/Scripts/wsd_benchmark.json` (25 hand-picked examples).

## Current architecture (2026-04-07)

**Recommended**: `match_senses.py --gemini` (default)
- Gemini 2.5 Flash Lite classifies examples against all unmerged Wiktionary senses
- 100% accuracy on 25-test benchmark
- ~$0.35-0.60 for full 8K-word run depending on examples/word
- Sense list dedup reduces prompt tokens ~25-30% (conjugations share senses)
- Sense merging OFF by default for Gemini (it handles fine-grained senses natively)

**Fallback**: `match_senses.py --biencoder`
- Bi-encoder cosine similarity (free, runs locally)
- 84% accuracy (best local model result)
- Uses sense merging (cached to `sense_merges.json`)
- Slow on CPU: ~4.5 hrs for 400K examples, ~4 min for 160K with all-MiniLM-L6

**Instant fallback**: `match_senses.py --keyword-only`
- Keyword overlap, no models, instant
- ~70% accuracy

## Benchmark results (25 examples)

| Rank | Approach | Accuracy | Speed | Cost |
|------|----------|----------|-------|------|
| 1 | **Gemini 2.5 Flash Lite** | **100% (25/25)** | ~5 min | ~$0.50 |
| 2 | Gemini 3.1 Flash Lite Preview | 96% (24/25) | ~5 min | ~$0.50 |
| 3 | bi-sent + bilingual + raw | 84% (21/25) | ~4.5 hrs | Free |
| 3 | all-MiniLM-L6 + bilingual + raw | 80% (20/25) | ~4 min | Free |
| 5 | token extraction + spanish + raw | 80% (20/25) | ~4.5 hrs | Free |
| 6 | xlm-r-large-xnli + pos_def_first | 76% (19/25) | ~4.5 hrs | Free |
| 7 | mmarco + pos_def_first | 72% (18/25) | ~38 min | Free |
| 8 | mmarco + raw | 60% (15/25) | ~38 min | Free |

## Approaches explored

### 1. Cross-encoders (rejected)

Scores each (example, sense) pair independently. N forward passes per sentence.

**mmarco-mMiniLMv2-L12-H384-v1** (33M params, IR model):
- 520 pairs/sec, ~38 min full run
- 60% raw, 72% with prompt engineering
- Fundamental problem: IR model has **length bias** — shorter sense texts score
  higher regardless of meaning. "to taste" (2 words) beats "to know, to
  understand (a fact), to realize" (8 words).
- Prompt fix (truncate to first translation + "Definition (pos):" template)
  partially compensates but doesn't fully solve it.

**joeddav/xlm-roberta-large-xnli** (550M params, NLI model):
- 73 pairs/sec, ~4.5 hrs full run
- 64% raw, 76% with prompt engineering
- Better at understanding entailment but too slow and still worse than bi-encoder.
- 9/9 on original 9-example test set — showed we were overfitting to tiny test.

**Lesson**: Cross-encoders are designed for pairwise relevance ranking, not WSD.
The per-pair architecture is fundamentally slow and doesn't outperform simpler
approaches on this task.

### 2. Bi-encoders (good free fallback)

Embeds all sentences and senses in batch, then cosine similarity. One forward
pass per sentence regardless of sense count.

**paraphrase-multilingual-mpnet-base-v2** (278M params):
- 84% accuracy (best local result)
- ~350 sent/sec, ~4.5 hrs for 400K examples on CPU
- Bilingual input critical: "{english} [Spanish: {spanish}]" — drops to 72%
  with Spanish-only because model needs English to match English sense texts.

**all-MiniLM-L6-v2** (23M params, English-only):
- 80% accuracy
- ~1,700 sent/sec, ~4 min for 160K examples
- English-only model works because input is bilingual and senses are English.
- Best speed/accuracy tradeoff for free local runs.

**paraphrase-multilingual-MiniLM-L12-v2** (118M params):
- 76% accuracy — surprisingly worse than the 6-layer model
- Not recommended.

### 3. Token extraction (explored, not adopted)

Extracts the contextualized embedding of the target Spanish word from the
sentence, then compares to sense embeddings. Theoretically the "proper" WSD
paradigm (what BEM, GlossBERT etc. do).

- 80% accuracy with paraphrase-multilingual-mpnet-base-v2
- Same speed as full-sentence bi-encoder (dominated by forward pass)
- Didn't beat bi-encoder because bilingual sentence embedding captures more
  signal from the English translation than the Spanish token alone.
- More complex to implement (need to find target word position in tokenized input).

### 4. Gemini (adopted as primary)

LLM-based classification. Actually understands meaning, not just similarity.

**gemini-2.5-flash-lite**: 100% (25/25), ~$0.50 full run, ~5 min
**gemini-3.1-flash-lite-preview**: 96% (24/25), similar cost

Optimizations implemented:
- **Word-grouped prompts**: senses listed once per word, all examples below.
- **Sense list dedup**: conjugations sharing the same lemma senses get a single
  ID (S1, S2...) defined at prompt top, referenced per word. Cuts sense tokens
  ~54%, overall prompt ~25-30%.
- **Batching**: 30 words per API call.

## Sense text formatting

Tested 6 prompt templates for how to present sense definitions to models:

| Template | Example | Best for |
|----------|---------|----------|
| raw | "verb: to know, to understand (a fact), to realize" | Bi-encoder |
| first_only | "to know" | — |
| pos_def_first | "Definition (verb): to know" | Cross-encoders |
| hypothesis | "This sentence means to know" | — |
| definition | "The word here means: to know" | — |
| example_of | "This is an example of the meaning: to know" | — |

**Key finding**: prompt engineering that helped on 9 examples hurt on 25.
Overfitting to a tiny test set was misleading. For bi-encoder, raw sense text
is best. For Gemini, format doesn't matter (100% regardless).

## Sense merging

Bi-encoder pre-merge step: collapses same-POS senses with cosine sim >= 0.70
using paraphrase-multilingual-mpnet-base-v2.

- Cached to `Data/Spanish/layers/sense_merges.json` (fingerprinted by senses
  file size + threshold + model).
- Reduces ~37K senses to ~31K (collapses ~6,500 across ~4,000 words).
- **On for bi-encoder** (helps avoid confusion between near-synonym senses).
- **Off for Gemini** (it handles fine-grained senses natively; more senses =
  better frequency breakdown at negligible cost increase).

## Sense quality issues

**Descriptive/encyclopedic senses**: Wiktionary includes non-translation senses
like "used to express wishes of misfortune against someone" (así) or "The name
of the Latin script letter D/d" (de). These attract false-positive classifications.

- 118 such senses identified (0.4% of total) via regex pattern matching.
- Filter not yet implemented in build_senses.py but patterns are ready.
- Patterns: starts with "used to", "a public", "the name of", "expression",
  "indicating", "stressed in", "feminine/masculine", "said of", "placed before/after".

## Pipeline architecture

```
build_examples.py    → examples_raw.json        (cached OpenSubtitles in cached_pairs.json.gz)
build_senses.py      → senses_wiktionary.json
match_senses.py      → sense_assignments.json   (cached merge in sense_merges.json)
build_vocabulary.py  → vocabulary.json + vocabulary.index.json + vocabulary.examples.json
```

Each step reads its inputs and is independently re-runnable. Only re-run a step
when its inputs change. `match_senses.py` is the main tuning target.

## Flags reference

**build_examples.py**:
- `--half` / `--tenth` — subsample corpus for faster iteration
- `--max-lines N` — control OpenSubtitles sample size
- First run builds `cached_pairs.json.gz`; subsequent runs load from cache

**match_senses.py**:
- `--gemini` — Gemini Flash Lite (default)
- `--biencoder` — local bi-encoder fallback
- `--keyword-only` — instant keyword overlap
- `--merge` / `--no-merge` — override default merge behavior
- `--limit N` — only classify first N words (by frequency rank)

## Artist mode (local sense matching)

Step 6b (`Artists/scripts/match_artist_senses.py`) uses bi-encoder sense
matching for artist lyrics when Gemini assignments don't exist. Much smaller
scale than normal mode (~600-3000 examples vs 400K).

**Model**: `paraphrase-multilingual-mpnet-base-v2` — handles both bilingual
(84% benchmark) and Spanish-only (72% benchmark) inputs.

**Sense source priority**: Gemini (this artist) > Wiktionary (normal mode) > Master vocab

**Measured results (Rosalía, vs Gemini ground truth)**:
- 59.8% raw agreement with Gemini on all multi-sense examples
- ~75% on truly distinct senses (28% of disagreements are near-synonym senses
  with identical translations, 23% are same-POS near-synonyms)
- Some "Gemini correct" cases are actually Gemini errors (e.g. "Zoom in on
  the face" classified as "expensive")
- 89 multi-sense words retained vs 0 without the step
- Runtime: 13.5s for Rosalía (3,415 words, 595 examples), 14s for Young Miko
  (4,748 words, 932 examples — fully Spanish-only)

**Key finding**: model choice (MiniLM vs mpnet) barely matters (~57% vs ~58%
agreement). The real bottleneck is near-synonym Gemini senses that should be
merged, and translation coverage for the bilingual path.

**Young Miko validation** (100% Spanish-only, zero English translations):
Spot-checked classifications look correct — "bajo el roof" (under) vs "bajo
hasta Aguadilla" (down to) vs "bajo perfil" (low profile). Demonstrates the
multilingual model handles Spanish-to-English-sense matching adequately.

## Open questions

1. Is 20 examples/word enough, or does 50 improve frequency estimates meaningfully?
2. Should the 118 descriptive senses be filtered in build_senses.py?
3. Would caching OpenSubtitles sentence index (not just pairs) speed up build_examples further?
4. Sentence-grouped Gemini prompts (one sentence, multiple words) — tested, works,
   but saves less than expected because sense lists dominate token count.
