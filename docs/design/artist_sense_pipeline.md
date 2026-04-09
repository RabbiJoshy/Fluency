---
title: Artist mode sense discovery and assignment
status: research
created: 2026-04-08
updated: 2026-04-08
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

## Open questions

1. How often do artist lyrics use a word in a sense Wiktionary doesn't list? (Needs measurement)
2. Is the MWE system sufficient to cover idiomatic gaps, or do we need single-word sense fallback?
3. Should Gemini still handle lemma/POS/flag detection even if sense discovery moves to Wiktionary?
4. Would Option C's confidence threshold be reliable enough to automate, or would it need manual review?

## Next steps

- [ ] Measure Wiktionary sense coverage for artist vocabularies (how many words have Wiktionary entries, how many examples map cleanly)
- [ ] Prototype: run normal-mode Gemini classifier on artist examples using Wiktionary senses, compare to current assignments
- [ ] Decide approach based on coverage data
