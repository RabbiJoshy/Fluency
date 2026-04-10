---
title: Artist mode sense discovery and assignment
status: research
created: 2026-04-08
updated: 2026-04-10
---

# Artist Mode Sense Pipeline — Design Notes

How senses are discovered and assigned to example sentences, artist mode vs normal mode. Explores whether artist mode should switch from LLM-generated senses to Wiktionary-sourced senses with LLM classification.

## Current approach: Artist mode

### Sense discovery (step 6)

Gemini sees each word with up to 6 example lyrics and **invents** senses from context. The prompt says: "Only split senses when the English translation genuinely differs." Gemini returns senses with line-number assignments in one shot — discovery and assignment happen together.

**Strengths:**
- Captures slang and contextual meanings Wiktionary doesn't have
- One API call does both discovery and assignment
- Understands Caribbean dialect (elisions, colloquialisms)

**Weaknesses:**
- Produces duplicates ("do" and "does" as separate senses)
- Inconsistent across artists — same word gets different sense inventories
- Senses accumulate in the master without dedup (now fixed with normalized matching)
- Occasionally produces garbage (entire sentence analyzed word-by-word instead of target word)

### Sense assignment fallback (step 6b)

For `--no-gemini` runs, senses come from the master (populated by prior artists) or Wiktionary. A local bi-encoder (`paraphrase-multilingual-mpnet-base-v2`) classifies each example to the best-matching sense via cosine similarity.

**Accuracy:** ~60% raw agreement with Gemini, ~75% on truly distinct senses. Near-synonym disagreements account for the gap.

## Current approach: Normal mode

### Sense discovery

Senses come from **Wiktionary** (`build_senses.py`). Comprehensive cleaning pipeline: strips archaic/obsolete senses, deduplicates by normalized translation, merges near-synonyms via Jaccard similarity, caps at 8 senses per word. Stable, deterministic, free.

### Sense assignment

Three options in `match_senses.py`:
- **Gemini Flash Lite** (default): 100% accuracy on 25-example benchmark, ~$0.50 per full run, ~30s with async parallelism
- **Bi-encoder**: 84% accuracy, free, ~4 min
- **Keyword overlap**: ~70% accuracy, instant, free

Gemini mode prompts the classifier with a sense list and batches of examples. It picks from the menu — no sense invention.

## The question

Should artist mode switch from "Gemini invents senses" to "pick from Wiktionary senses + classify"?

### Option A: Keep current (Gemini invents senses)

As-is. Front-end filters zero-frequency and low-frequency senses. Master dedup via normalized matching prevents accumulation.

**Pro:** Captures meanings Wiktionary misses.
**Con:** Inconsistent across artists. Duplicate/garbage senses still enter the master.

### Option B: Wiktionary senses + classifier for artist mode

Use Wiktionary as the sense inventory for all words that have Wiktionary entries. Use Gemini (or bi-encoder) purely as a **classifier** — given these senses, which one does this lyric line match? Fall back to Gemini sense invention only for words Wiktionary doesn't cover (slang, neologisms).

**Pro:**
- Cross-artist consistency — every artist shares the same sense inventory
- No sense proliferation in master
- Already proven in normal mode (100% Gemini classifier accuracy)
- Wiktionary senses are cleaner (pre-deduped, capped)

**Con:**
- Wiktionary may not capture the right sense for idiomatic uses (e.g., "hace tiempo" = "ago" doesn't map to any Wiktionary sense of "hacer")
- MWE detection already handles many of these cases, though
- Two-step process (discover from Wiktionary, then classify) vs one-shot Gemini

### Option C: Hybrid — Wiktionary primary, Gemini discovers missing senses

Use Wiktionary senses. Run classifier. If a significant fraction of examples don't match any Wiktionary sense well (low confidence), ask Gemini to propose additional senses for those examples only. Add those to the inventory and re-classify.

**Pro:** Best of both worlds — Wiktionary stability + Gemini's contextual understanding.
**Con:** More complex pipeline. Needs a confidence threshold to trigger Gemini fallback.

## Key data points

- Wiktionary covers ~95% of the 8K normal-mode vocabulary
- Artist-mode words not in Wiktionary are mostly slang/neologisms (~5%)
- MWEs already handle most idiomatic constructions (hace tiempo, de una, etc.)
- Gemini Flash Lite classifier: 100% accuracy, $0.50/run
- Bi-encoder classifier: 84% accuracy, free
- Current artist Gemini sense discovery: ~$0.50/artist but produces duplicates

## Infrastructure already in place

- `Data/Spanish/layers/senses_wiktionary.json` — ready to use as sense source
- `match_artist_senses.py` — already has Wiktionary fallback (priority 2 after senses_gemini)
- `match_senses.py` — Gemini classifier already built and benchmarked for normal mode
- Normalized matching in `_artist_config.py` — prevents dedup issues regardless of approach

## Open questions (original, pre-eval)

1. ~~How often do artist lyrics use a word in a sense Wiktionary doesn't list?~~ **Answered**: ~18% no Wiktionary match; ~8% genuinely missing (rest is English/propn/intj leakage)
2. Is the MWE system sufficient to cover idiomatic gaps, or do we need single-word sense fallback? **Still open**
3. Should Gemini still handle lemma/POS/flag detection even if sense discovery moves to Wiktionary? **Still open** — Wiktionary provides lemma and POS per sense, but flags (is_english, is_interjection, is_cognate) currently come from Gemini Pass B or steps 4/7. Need to decide source for each flag during implementation.
4. ~~Would Option C's confidence threshold be reliable enough to automate?~~ **Partially answered**: approach decided, threshold and exact mechanism need design during implementation

## Open design questions (for implementation chat)

5. How does confidence detection work for gap-fill triggering? What metric (max cosine similarity? entropy across senses?), what threshold?
6. Does lemma resolution change when Wiktionary provides the lemma instead of Gemini? Current Pass B determines lemma — if we skip Pass B for 82% of words, lemma comes from the Wiktionary key. Need to verify this is consistent with how the master vocabulary and front-end use lemma.
7. Default classifier: Gemini Flash Lite (100% accuracy, ~$0.50/run) or biencoder (84%, free)? May depend on whether user ran Pass A with Gemini or only has Google Translate.
8. How does `--no-gemini` mode work? Presumably: Wiktionary lookup + biencoder only, gap-fill skipped, words without Wiktionary match get no senses (or master fallback).
9. What happens to existing `senses_gemini.json` files and master vocabulary entries when the pipeline switches to Wiktionary senses? Migration path needed.

## Eval results (2026-04-10)

Ran `Artists/scripts/eval_wiktionary_cascade.py` against Bad Bunny. Key findings:

### Wiktionary coverage (raw file, not pre-extracted subset)

The pre-built `senses_wiktionary.json` only has 11K words (the normal-mode frequency list). The raw Wiktionary file (`kaikki-spanish.jsonl.gz`) has **760K unique words** and covers **82%** of Bad Bunny's post-filter vocabulary (word or lemma match).

Caribbean slang coverage: **80%** (24/30 test words). Wiktionary has good entries for perrear ("to dance to reggaeton; to twerk"), bellaco ("one who is horny"), bicho (including "penis"), corillo ("gang, crew, squad"), tiraera ("diss track"), janguear ("to hang out"), etc.

Not in Wiktionary: bellaquear (but IS in Spanish Wiktionary), bichota, cangri, frontear (IS in Spanish Wiktionary), guillar, safacón. Most missing words are either ultra-niche PR neologisms or English words that leaked through step 4 detection.

The **genuinely missing** words (not propn/intj/elided/English) are ~7.8% of post-filter vocabulary (~900 words), many of which are English leakage.

### Biencoder classification with different translation sources

Compared sense assignments using Wiktionary senses + biencoder across translation sources, using Gemini sentence translations as reference:

| Source | Per-example agreement | Dominant-sense agreement |
|--------|----------------------|--------------------------|
| Genius (human, free) | 80% | 80% |
| Spanish-only (no translation) | 69% | 71% |

Disagreements are mostly fine-grained near-synonyms: "to open" vs "to unlock", "to finish" vs "to end up", "boring" vs "bored." These don't matter for flashcards.

### Focus word results

| Word | Gemini classification | Notes |
|------|----------------------|-------|
| bicho | vulva 50%, penis 40%, beast 10% | Correctly avoids "bug" — but can't distinguish vulva/penis (both correct for PR slang) |
| rico | tasty/yummy 50%, proper noun 30%, rich 10% | Gemini nails contextual meaning; Spanish-only defaults to "rich" (70%) |
| candela | candela unit 43%, fire 43% | Genius defaults to "candle" (86%) — slang detection needs good translations |
| loco | crazy 80% | High agreement across all sources |
| tipo | guy/fellow 71% | High agreement |
| gata | cat 100% | Only 2 Wiktionary senses (cat, carjack) — "attractive woman" sense missing entirely |

### Key insight: different task than before

The old classifier task (Spanish lyrics → sense descriptions) was pure WSD — hard, 60-75% accuracy. The cascade task is fundamentally easier: **translated lyrics → sense descriptions**. When the translation says "My dick is like a Lambo" and the sense says "penis", the biencoder just matches "dick" to "penis" in embedding space. The translation already did the disambiguation. This is why 80% agreement is achievable even with Genius-only translations.

### Spanish Wiktionary (es.wiktionary.org) as supplement

Checked whether es.wiktionary.org covers gaps. It does add senses — bicho has 14 senses (vs 5 in English edition), frontear and bellaquear exist in Spanish edition but not English. However, **adding all senses from a second source creates a sense bloat problem**: more senses → harder classification → more false positives → larger file sizes. Can't just union the inventories.

### Google Translate

Not tested yet (skipped for speed). Expected to land between Genius (80%) and Spanish-only (69%). The key question is whether Google correctly translates Caribbean slang in sentences — if Google renders "bicho" as "bug" in sentence context, the easy alignment task becomes wrong.

## Proposed direction: Modified Option B — Wiktionary primary, confidence-gated Gemini gap-fill

Based on the eval, this is the most promising direction. The details below are a starting point for implementation, not a finished spec — the open design questions above need resolving during implementation.

### Architecture

**Pass A stays unchanged.** Sentence translation via Genius + Google Translate + Gemini (existing cost-optimization workflow).

**Pass B replaced with cascade:**

1. **Wiktionary lookup** — look up each post-filter word in the raw Wiktionary file. Use existing `lookup_senses()` logic from `build_senses.py` (accent stripping, redirect following, gloss cleaning, dedup, caps). This covers ~82% of words with dictionary-quality senses.

2. **Classifier** — for words with Wiktionary senses, use the existing biencoder or Gemini Flash Lite classifier to assign lyric examples to senses. The classifier uses bilingual input (translated lyric + Spanish lyric) when sentence translations are available, Spanish-only otherwise. Frequency distribution falls out naturally.

3. **Confidence-gated Gemini gap-fill** — for words where (a) no Wiktionary match exists, or (b) classification confidence is low (no sense matches well), make a targeted Gemini call. NOT "translate this word" (generation → safety filter). Instead: "Here are the Wiktionary senses for X. The lyrics use it in these contexts [with translations]. Is one of these correct, or is a slang meaning missing?" This is comprehension, not generation — less likely to trigger safety filters. Results flow into curated_translations.json for reuse.

4. **Curated overrides** — applied first, highest trust, as today.

### What this preserves

- Sentence translations (Pass A) are unchanged and still the highest-quality output
- Example sentences still come from the lyric corpus
- Frequency weighting still computed from example-to-sense assignments
- Curated translations still override everything
- `--no-gemini` runs still work (Wiktionary + biencoder, no API needed)
- Provenance tracking via `source` field on each sense

### What changes

- Pass B no longer asks Gemini to generate word-level translations from scratch
- Senses come from Wiktionary (deterministic, cross-artist consistent) instead of Gemini (variable)
- Gemini generation only fires for ~8% of words (Wiktionary gaps) via gap-fill
- `senses_gemini.json` renamed to `senses.json` with source field: "wiktionary", "gemini", "curated"
- `match_artist_senses.py` becomes the primary classifier (currently fallback-only)
- `build_senses.py` → `lookup_senses()` extracted to shared utility for cross-pipeline use

### Why not Spanish Wiktionary merge

Adding a second sense source (es.wiktionary.org) causes sense bloat. Bicho goes from 5 → 14 senses, making classification harder and file sizes larger. Can't tell a priori which senses to add. Better to keep English Wiktionary as the single source and use confidence-gated Gemini for the gaps.

Spanish Wiktionary is useful as a **human reference** when curating overrides, not as a programmatic data source.

### Cost impact

- Current: ~1,058 Gemini calls per artist (290 Pass A + 768 Pass B)
- Proposed: ~360 calls (290 Pass A + ~70 gap-fill)
- ~65% reduction in API costs with better translation quality

### Sense count is critical

Keep MAX_SENSES_TOTAL = 8. More senses → more false positives. The Wiktionary lookup already caps and deduplicates. Gap-fill adds at most 1-2 new senses per word, not a dump.

## Implementation plan

1. Extract `lookup_senses()` and `load_wiktionary()` from `build_senses.py` into a shared module (e.g., `Artists/scripts/wiktionary_utils.py` or similar)
2. Modify step 6 to do Wiktionary lookup as the primary sense source instead of Gemini generation
3. Upgrade `match_artist_senses.py` from fallback to primary classifier path
4. Add confidence detection for gap-fill triggering
5. Rename sense layer file, add source provenance
6. Test: re-run Bad Bunny pipeline, diff senses, spot-check focus words (bicho, candela, rico, gata)

## Eval script

`Artists/scripts/eval_wiktionary_cascade.py` — standalone eval that tests the cascade hypothesis. Compares biencoder classification accuracy across translation sources (Gemini, Genius, Google, Spanish-only) using Wiktionary senses. Run with:

```
.venv/bin/python3 Artists/scripts/eval_wiktionary_cascade.py --artist-dir "Artists/Bad Bunny"
```
