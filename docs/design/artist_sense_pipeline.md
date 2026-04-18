---
title: Artist mode sense discovery and assignment
status: implemented
created: 2026-04-08
updated: 2026-04-11
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

Ran `pipeline/artist/eval_wiktionary_cascade.py` against Bad Bunny. Key findings:

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

## Classifier benchmark results (2026-04-10)

Tested 14 problem words (vez, real, entera, nombre, pone, paso, etc.) across classifiers:

| Classifier | vez | real | entera | nombre | Speed | Cost |
|------------|-----|------|--------|--------|-------|------|
| Biencoder (multilingual-mpnet) | 60% turn ✗ | 70% NOUN ✗ | 80% find out ✗ | 80% name | ~10min | free |
| Biencoder (E5-large) | 60% turn ✗ | 60% NOUN ✗ | 60% find out ✗ | 80% name | ~10min | free |
| NLI (bart-large-mnli) | 60% turn ✗ | 90% NOUN ✗ | 50% inform ✗ | 100% name | ~87min | free |
| NLI (distilbart) | 90% place ✗ | 60% ADJ ✓ | 40% find out ✗ | 90% name | ~55min | free |
| **Gemini 2.5 Flash Lite** | **100% time ✓** | **90% ADJ ✓** | **80% whole ✓** | **100% name** | **~13s** | **~$0.05** |

**Decision: Gemini Flash Lite as classifier.** Biencoder architecture (even large models) fundamentally can't handle this task — it embeds example and sense separately, never seeing them as a pair. NLI/cross-encoder approaches are better but still fail on near-synonym disambiguation and take 55-87 minutes. Gemini gets near-100% accuracy in seconds for negligible cost.

The biencoder remains available as `--no-gemini` fallback (free, 80% accuracy on easy cases, fails on hard cases).

## Gap-fill benchmark results (2026-04-10)

Tested 28 words (20 slang candidates + 8 normal words). Gemini proposes missing senses when Wiktionary doesn't cover the contextual meaning.

**Results:**
- 22/28 correctly said "all senses sufficient" (zero false positives on normal words)
- 6/28 proposed new senses: gata, loca, pone, rico, vivo, nuevo
- Genuinely useful: loca → "crazy, wild, excited" (10/10 examples needed it), pone → "to become" (ponerse reflexive), pone → "to wear"
- Borderline: nuevo → "again" (really an MWE "de nuevo"), rico → "deliciously" (adverb)
- gata → only 1/10 proposed "girlfriend" (prompt too conservative — needs learner-perspective framing)

**Prompt refinement needed:** Ask "would a learner understand from the dictionary definition alone?" rather than "is the existing sense close enough?" — catches figurative/slang usage like gata = "hot girl" where "cat" is technically present but useless for comprehension.

## Spanish Wiktionary (eswiktionary) as regional supplement (2026-04-11)

The Spanish edition of Wiktionary (`kaikki-eswiktionary-raw.jsonl.gz`, 98.7MB) has excellent dialect/region tagging per sense. Tags include `Puerto-Rico`, `Caribbean`, `Cuba`, `Dominican-Republic`, `Mexico`, `Venezuela`, etc.

**Coverage overlap with Bad Bunny (PR + Caribbean + Cuba):**
- 1,113 words with dialect-tagged senses in the full corpus
- 236 overlap with Bad Bunny's vocabulary
- Key wins: bicho → "Pene" (PR/Cuba), prender → "turn on a device" (Caribbean), candela → "Fuego" (PR/Cuba), rico → "physically attractive" (Cuba), corillo → "group of young people who party" (PR), mami → "attractive woman" (PR/Cuba)
- Still missing: gata → "attractive woman" (not in either Wiktionary)

**Architecture decision:** Use eswiktionary as a supplement, not a replacement. Per-artist `dialect` config drives which regional tags to include. English Wiktionary senses go first on the menu; dialect senses are appended. No dedup — Gemini classifier prefers English senses when both cover the same meaning.

**Translation of Spanish glosses:** When Gemini picks a Spanish-only sense, it translates it in the same response. Translations cached in `.eswikt_translation_cache.json` so the same gloss gets the same English translation across artists and runs. Already working: rico → "Dicho de una persona, que tiene gran atractivo físico" → "physically attractive" cached on first run.

**Data file:** `Data/Spanish/corpora/wiktionary/kaikki-eswiktionary-raw.jsonl.gz` (raw wiktextract format, `lang_code: "es"` entries, senses have `tags` array with region names).

## Gap-fill prompt v3 results (2026-04-11)

Tested 5 prompt variations with the combined English + Spanish Wiktionary menu on 28 words. The core challenge: balancing false positives (proposing senses when existing ones are fine) vs false negatives (saying "covered" when the dictionary definition would mislead).

**Best results so far (substitution test prompt, 21/28 correct):**
- Fixed from original: prende, perreo, carajo, candela, corazón, real now correctly "covered"
- Genuine proposals: meto → "to have sex with", nuevo → "again" (MWE), pone → "makes feel"
- Remaining false positives: fuego ("fire" covers "passion"), duro ("tough" covers "intensely")
- **Persistent failure: gata** — Flash Lite cannot distinguish "cat→girlfriend" (genuinely misleading) from "fire→passion" (figurative extension). It sees "cat" and says covered every time, even with explicit substitution test instructions. Pro gets it right.

**Prompt evolution:**
1. Original two-step prompt → 6/28 proposals (too many FPs: prende, perreo, carajo)
2. "Err strongly on covered" → 1/28 proposals (too conservative: gata says covered)
3. "Learner substitution test" → 7/28 proposals (gata still covered, fuego/duro still FP)
4. "Show your substitution work" (chain-of-thought) → 19/28 correct, **gata finally works** (7/10, proposes "woman, girlfriend"). Substitution output: "I don't know if you have a cat or you have a boyfriend" — clearly wrong. But more FPs return: candela, fuego, duro, rico (ignored its own Spanish Wiktionary "physically attractive" sense)

**Key insight:** Flash Lite correctly identifies `actual_meaning: "girlfriend, woman"` for gata — it KNOWS the meaning. Without chain-of-thought it fails the coverage judgment, treating "cat→girlfriend" as a metaphorical extension. With chain-of-thought (forced to write out the substitution) it catches the error, but the literal substitution test is too strict for figurative extensions — "The streets are on fire, light" sounds awkward when you jam in the full dictionary text.

**Trade-off:** Conservative prompt (v2) → 27/28 correct but misses gata. Chain-of-thought (v4) → catches gata but 9/28 proposals (too many FPs). Need to find a middle ground — possibly substituting just the core word, or a two-pass approach.

**Next steps:**
1. Refine chain-of-thought substitution — substitute just the first word/phrase, not the full dictionary text
2. Or accept v2 prompt + curated override for the small number of gata-type words
3. Or use Pro for gap-fill only (handles nuance correctly, negligible cost on small word counts)

## Decided architecture

1. **English Wiktionary senses** — primary sense source via `lookup_senses()` + `clean_translation()` + `merge_similar_senses()`. Covers 82% of vocabulary with clean, cross-artist-consistent senses. Pickle cache for fast reloads.
2. **Spanish Wiktionary dialect supplement** — regional senses filtered by artist's `dialect` config (e.g., `["Puerto-Rico", "Caribbean", "Cuba"]` for Bad Bunny). Appended after English senses. Spanish glosses translated by Gemini on first use, cached for reuse.
3. **Gemini Flash Lite classifier** — picks from combined menu. ~$0.05 per artist, 13s for 140 examples. Near-100% accuracy.
4. **Gap-fill** — for words where classifier finds no good match, Gemini proposes 1-2 additional senses (learner-perspective prompt). Low false positive rate. Results persist in master for future artists.
5. **Curated overrides** — highest trust, applied first, never deleted.
6. **Biencoder fallback** — for `--no-gemini` runs (free, lower accuracy).

### Scaling: gap-fill senses in the master

Gap-fill senses accumulate in the shared master vocabulary (`source: "gap-fill"`). Cap at MAX_SENSES_TOTAL=8 prevents bloat even with many artists. Irrelevant gap-fill senses (from other artists' idiolects) naturally get 0% frequency and are filtered out — the classifier ignores them without explicit genre/region scoping.

## Gap-fill divergence detection experiments (2026-04-11)

Tested three architectural approaches to automated gap-fill detection on the 28-word test set. All use Flash Lite. The core problem: Flash Lite KNOWS gata means "girlfriend" (it says so every time) but won't FLAG the mismatch with the "cat" sense.

### Approach 1: Combined classifier + meaning extraction (anchored)

Single call: classify examples to senses AND state `actual_meaning`. Problem: showing the sense menu **anchors** Flash Lite — it said `actual_meaning: "female cat or girl"` for gata, echoing the dictionary. The word "cat" in `actual_meaning` causes the word-overlap divergence check to say "covered."

Result: 73% accuracy. Catches pone, loca. Misses gata (hedges), meto (self-censors to "put in or insert"). False positives on ojos (stemmer bug), candela (cross-language), real/rico (synonym blindness).

### Approach 2: Blind meaning extraction + embedding similarity

Two calls: (1) extract meaning WITHOUT showing sense menu (prevents anchoring), (2) classify with sense menu. Compare blind meaning against sense via cosine similarity (`all-MiniLM-L6-v2`).

Blind extraction results (no anchoring): gata → "girlfriend or cat" (STILL hedges — model knows gata=cat from training, not from the prompt), meto → "hit it or go hard" (works! no self-censoring without "to put" as safe landing), loca → "crazy or wild", pone → "makes, becomes, puts."

Embedding similarities: clean separation for most words, but gata (0.667) sits right next to fuego (0.664) and corillo (0.666). No threshold separates them. Best accuracy: **88% at threshold 0.50** (catches meto/loca/pone, misses gata/vivo).

Key finding: **gata hedging is NOT caused by the sense menu**. Flash Lite includes "cat" in its meaning extraction even blind, because it knows the word's literal meaning from training data.

### Approach 3: Self-checking classifier

Single call: classify + check whether English translations match the assigned sense. The model sees "Mi gata salvaje | My wild girl" assigned to sense "cat" and is asked to notice the mismatch.

Result: **77% accuracy**. The model DID notice both words — it reported `translation_uses: "cat, girlfriend"`. But it still said "covered" because "cat" appears in enough translations (~44%). Even with the prompt literally saying "only flag when translations use a genuinely different word (cat→girlfriend)" — using gata's exact case as the example — Flash Lite didn't flag it.

Catches pone. Misses gata, meto, loca, vivo. False positives on rico, tiempo.

### Key insight across all approaches

Flash Lite consistently **understands** that gata means "girlfriend" in these lyrics. Every approach confirms this — it correctly extracts the meaning. The failure is always in the **flagging/judgment** step: the model sees evidence for both "cat" and "girlfriend" in the data (because some translations genuinely say "cat" in simile contexts) and defaults to "covered."

The translations for gata are genuinely mixed: ~44% say "cat" (similes like "loose like a sassy cat"), ~56% say "girl/girlfriend." This mixed evidence is what makes gata uniquely hard — unlike meto (translations unanimously avoid "put") or loca (translations unanimously say "crazy" not "madwoman").

### Approach 4: Per-example translation word extraction (model extracts, code counts)

Single call: classify + extract the 1-3 English words each translation uses for the target word. Code counts whether majority diverge from the assigned sense. Problem: **Flash Lite extracts from its own knowledge, not from the translation text.** For gata, model extracted "cat" for 8/10 examples even though translations say "girl" — same world-knowledge bias as every other approach.

Result: 65% accuracy. Catches loca, meto, pone. Misses gata, vivo. 7 false positives (candela from Spanish gloss, bicho/cabrones/ojos from stemmer inconsistencies, bellaca/carajo/rico from synonym blindness).

### Approach 5: Programmatic keyword check (no model, spacy lemmatization)

Zero extra API calls. For each example, check if any lemmatized content word from the assigned sense definition appears in the English translation sentence. Uses spacy `en_core_web_sm` for lemmatization. Fixes stemmer issues (eyes→eye, motherfuckers→motherfucker). Piggybacks on self-checking classifier's sense assignments.

Result: **69% accuracy.** Catches loca, meto, pone. Misses gata, vivo. 6 false positives (bellaca, perreo, carajo, bicho, cabrones, rico — synonym blindness: "dick"≠"penis", "freak"≠"horny", etc.).

### Approach 6: Bilingual word alignment (SimAlign)

Attempted to use SimAlign (XLM-R / mBERT based) to align Spanish tokens to English translation tokens. Would find gata→girl directly. Problem: **alignment model has same world-knowledge bias.** SimAlign aligned gata→wild (positional) instead of gata→girl because its cross-lingual embeddings encode gata≈cat. Works for easy cases (fuego→fire, loca→crazy) but fails exactly where needed.

### Root cause: gata translations literally say "cat"

Examined the actual English translations for gata: **8 out of 10 say "cat"** because translators preserved the Spanish metaphor ("My wild cat", "Wild cat, come here"). Only 2 use "girl/girlfriend." The earlier "56% girl" figure came from the model's semantic understanding, not the translation text. No translation-based approach — keyword, extraction, or alignment — can detect gata's slang meaning because the translations themselves use the literal word.

### Conclusion: gap-fill detection deprioritized

The v2 gap-fill prompt (27/28, 96%) is the most accurate approach. It catches all detectable cases. Gata-class words (sense exists but translations preserve the literal metaphor) require manual curation — estimated 30-50 words per artist annually.

## New direction: dedicated WSD models on Spanish text (2026-04-11)

### The cross-lingual problem

All approaches above operate on English translations, which creates two problems:
1. **Translation quality** — translators preserve Spanish metaphors literally ("my wild cat" instead of "my wild girl")
2. **Cross-lingual bridge** — the target word (Spanish) doesn't appear in the classification context (English translation), so standard WSD models don't apply

### Spanish-native WSD

If we disambiguate the **Spanish word in the Spanish sentence** against **Spanish sense definitions**, both problems vanish:
- The target word IS in the sentence ("Mi **gata** salvaje") — standard monolingual WSD
- No dependency on translation quality
- "Mi gata salvaje" in reggaeton context has pragmatic cues (possessive + romantic context) that suggest a person, not an animal

### Candidate models

| Model | Spanish? | Arbitrary glosses? | Size | Notes |
|-------|----------|-------------------|------|-------|
| ConSeC (SapienzaNLP 2021) | Yes, tested | Yes, gloss-based | BERT-scale | Open source, cross-lingual CLEF benchmarks |
| AMuSE-WSD (Babelscape 2021) | Yes, RAE dictionary | Yes | BERT-scale | Requires API key |
| LLM-wsd-FT-ALL (2024) | Yes | Yes, flexible | 8B (Llama) | HuggingFace, needs GPU |
| GlossBERT (2019) | English only | Yes | BERT-scale | Architecture is right, needs multilingual version |

### Sense inventory flexibility

Not committed to Wiktionary. If WSD models work best with WordNet synset IDs or BabelNet, use those. The inventory format matters less than classification accuracy. BabelNet unifies WordNet + Wiktionary + Wikipedia — may be the best of all worlds.

### Key architectural insight: gap-fill accumulates across artists

If WSD classification is accurate, the sense inventory becomes the simpler problem. Gap-fill senses (like gata→"girlfriend") discovered for one artist accumulate in the master vocabulary and are available for all future artists. Each new artist only contributes genuinely new slang. The sense inventory grows organically.

### Cost model

WSD model runs locally — free, instant. Only gap-fill (proposing new senses for uncovered words) needs Gemini. Per-artist cost approaches zero as the sense inventory matures.

## WSD model benchmark results (2026-04-11)

### Setup

Benchmarked 28 test words (20 slang + 8 normal) from Bad Bunny corpus, 259 total example sentences. Ground truth: Gemini Flash Lite classifications (100% accuracy on prior benchmarks). Script: `pipeline/artist/bench/bench_wsd.py`.

### ConSeC assessment

ConSeC (SapienzaNLP/consec) **does accept arbitrary glosses** — its `predict.py` is purely gloss-based with no WordNet lookup at inference time. However:
- Requires `transformers==4.3.3`, `pytorch-lightning==1.1.7`, Java, Debian `apt-get` — incompatible with our env (transformers 4.57.6, macOS)
- Released checkpoint uses English DeBERTa — would tokenize Spanish input poorly
- Cross-lingual scores in the paper (68-77% on Spanish) likely used translated glosses or an unreleased multilingual variant
- **Not viable** without significant rework

### BabelNet assessment

BabelNet unifies WordNet + Wiktionary + Wikipedia senses. Could provide richer sense inventories, but:
- Free tier: 1000 API calls/day (insufficient for pipeline)
- Offline: 45GB download, research-only license
- **Not practical** — Wiktionary + gap-fill accumulation is more sustainable

### Benchmark results: all local models

| Model | Accuracy | Speed | Cost |
|-------|----------|-------|------|
| **Gemini Flash Lite (ref)** | **100%** | **71s** | **$0.05** |
| mDeBERTa NLI (en glosses) | 42.5% | 45s | free |
| mDeBERTa NLI (es glosses) | 42.1% | 44s | free |
| Bi-encoder (en glosses) | 47.9% | 9s | free |
| Bi-encoder (es glosses) | 47.9% | 7s | free |

**Spanish vs English glosses make no difference** — NLI: 42.5% vs 42.1%, bi-encoder: 47.9% vs 47.9%. The language of the sense definition doesn't help when the model fundamentally can't do fine-grained WSD.

### Per-word breakdown

Easy words (1-2 senses, unambiguous): gata 100%, flow 100%, perreo 100%, gente 100%, ojos 90-100%.

Hard words (many similar senses): meto 10-30%, pone 10-50%, vivo 22-33%, duro 0-33%, real 0-10%, sola 0-11%, bellaca 0-22%, bicho 0%.

### Failure analysis

The models fail on **fine-grained sense distinctions**:
- "vivo" has 8 senses (live/reside/experience/alive/vivid/intense). "Vivo en PR como si fuera Dubái" → NLI picks "vivid, lively" (wrong), should be "to live in, reside". The NLI model doesn't understand that "vivo en" is the verb "vivir" with a locative complement.
- "pone" has 5 senses. "Se pone bellaca" → NLI picks "to put" (wrong), should be "to make" (reflexive ponerse = to become). The model has no knowledge of Spanish reflexive constructions.
- "meto" examples — NLI assigns 0.985+ confidence to wrong senses because the entailment framework doesn't capture word-in-context disambiguation.

### Conclusion: local WSD models are not viable

Off-the-shelf encoder models (NLI cross-encoder, bi-encoder) plateau at ~45% accuracy on this task. The gap to Gemini (100%) is fundamental, not addressable by template tuning or gloss language. The models lack:
1. Fine-grained sense disambiguation capability (they match sentences to glosses by surface similarity, not meaning)
2. Spanish grammar understanding (reflexive constructions, syntactic cues)
3. Register/context awareness (reggaeton slang, figurative usage)

**Gemini Flash Lite remains the right classifier** — $0.05/artist for 100% accuracy. The cost is negligible. The bi-encoder fallback (48%) is only useful as a `--no-gemini` degraded mode.

### Remaining option: LLM-wsd-FT-ALL (8B Llama)

The 2024 Llama-8B model fine-tuned on WSD might close the gap, but requires GPU and significant memory. Worth investigating if the $0.05/artist cost ever becomes a concern at scale. Not a priority given current economics.

## Shipped: unified sense layer format (2026-04-11)

### New layer format

One senses file + one assignments file per artist, with stable content-hash IDs and multi-method evidence.

**`senses_wiktionary.json`** — senses keyed by stable content-hash IDs:
```json
{
  "bicho|bicho": {
    "34c": {"pos": "NOUN", "translation": "bug", "source": "en-wikt"},
    "88b": {"pos": "NOUN", "translation": "penis", "source": "en-wikt"},
    "22c": {"pos": "NOUN", "translation": "Pene.", "source": "es-wikt"}
  }
}
```

**`sense_assignments_wiktionary.json`** — multi-method assignments per word:
```json
{
  "bicho": {
    "biencoder": [{"sense": "88b", "examples": [1, 3, 5]}],
    "flash-lite-wiktionary": [{"sense": "88b", "examples": [0, 1, 2, 3]}]
  }
}
```

Sense IDs: `md5(pos + "|" + translation)[:3]`, extended on collision. Senses are append-only. Methods coexist — adding a new classification method doesn't touch existing ones. Orphaned sense IDs (from removed senses) are skipped by the builder.

### Architecture for new artists

| Words | Method | Cost |
|-------|--------|------|
| In normal mode (~4K/artist) | Bi-encoder against normal-mode Wiktionary senses + eswiktionary dialect senses | Free |
| Normal-mode with eswikt slang (~170/artist) | Gemini Flash Lite with expanded menu | ~$0.02 |
| New words not in normal mode (~300/artist) | Gemini Flash Lite with Wiktionary + gap-fill | ~$0.05 |
| English/propn/intj/short/single-use | Skip | Free |

Per new artist total: ~$0.07. Bi-encoder runs first (free), Gemini only for words that need it.

### Scripts

- `pipeline/artist/match_artist_senses.py --normal-only` — bi-encoder on normal-mode words, includes eswiktionary dialect senses, writes new format
- `pipeline/artist/build_wiktionary_senses.py` — Gemini Flash Lite on Wiktionary menu, with substitution test prompt, `--normal-slang-only` for dialect words, `--new-only` for non-normal words
- `pipeline/artist/build_artist_vocabulary.py --sense-source wiktionary` — builds from new layers (default), `--sense-source gemini` for old layers
- Builder handles both old (list) and new (dict-of-IDs) format automatically

### Shipped: word filters + song exclusions + method priority (2026-04-11)

**Word filters** (`4_filter_known_vocab.py`): Added English 50k wordlist filter (catches loanwords lingua misses), interjection regex patterns, proper noun capitalization ratio + spaCy NER. Output categories in `skip_words.json` consumed by `build_wiktionary_senses.py --new-only` as whitelist.

**Song exclusions**: `scan_duplicates.py` tool finds copied verses via consecutive line matching + artist attribution from Genius section tags (rescrape with `--rescrape-headers`). Reports BB line count vs other artists per song. Used to exclude ~15 additional songs (copied verses, 0% artist lines, mashups).

**Method priority** (`_artist_config.py`): `METHOD_PRIORITY` dict defines quality ordering (flash-lite-wiktionary=50, biencoder=30, keyword=10, wiktionary-auto=0). Both `match_artist_senses.py` and `build_wiktionary_senses.py` check existing assignments and skip words with equal or higher priority. Methods coexist additively per word.

**`--new-only` flag**: Reads step 4's remaining list as whitelist. Single source of truth for which words need Gemini.

**`match_artist_senses.py`**: Always writes to `sense_assignments_wiktionary.json` (new format). Always merges additively. No longer needs `--normal-only` to write new format.

### Remaining work

1. **Curate gata-class edge cases** — words where the sense exists but translations preserve the literal metaphor
2. **Find better English frequency list** — current OpenSubtitles-derived list has foreign word artifacts

### Utilities added

`pipeline/build_senses.py` now has `stem_en()`, `stemmed_content_words()`, and `content_word_overlap()` for programmatic divergence checking.

`pipeline/artist/_artist_config.py` now has `make_sense_id()` and `assign_sense_ids()` for stable content-hash sense IDs.

`pipeline/artist/5_split_evidence.py` preserves example order across re-runs (keeps sense assignments stable when songs are removed).

## Test scripts

- `pipeline/artist/test_wiktionary_cascade.py` — full cascade test, writes browsable `_cascade_{method}.json`
- `pipeline/artist/bench/bench_nli.py` — quick classifier comparison (biencoder, NLI, Gemini) on 14 problem words
- `pipeline/artist/bench/bench_gapfill.py` — gap-fill proposal test on 28 words, now with Spanish Wiktionary supplement
- `pipeline/artist/bench/bench_divergence.py` — divergence detection bench (6 approaches tested)
- `pipeline/artist/bench/bench_wsd.py` — local WSD model benchmark (ConSeC, NLI, bi-encoder)
- `pipeline/artist/bench/bench_wsd.py` — WSD model benchmark (NLI, bi-encoder, ConSeC) on 28 words, Gemini ground truth
- `pipeline/artist/bench/eval_wiktionary_cascade.py` — original eval (translation source comparison)

Run cascade test: `.venv/bin/python3 pipeline/artist/bench/bench_test_wiktionary_cascade.py --artist-dir "Artists/spanish/Bad Bunny"`
Run classifier bench: `.venv/bin/python3 pipeline/artist/bench/bench_nli.py --gemini`
Run gap-fill bench: `.venv/bin/python3 pipeline/artist/bench/bench_gapfill.py`
Run divergence bench: `.venv/bin/python3 pipeline/artist/bench/bench_divergence.py`
Run WSD bench: `.venv/bin/python3 pipeline/artist/bench/bench_wsd.py --model all`

## Data files

- `Data/Spanish/corpora/wiktionary/kaikki-spanish.jsonl.gz` — English Wiktionary (primary), 118K lookup keys
- `Data/Spanish/corpora/wiktionary/kaikki-eswiktionary-raw.jsonl.gz` — Spanish Wiktionary (dialect supplement), raw wiktextract format, 850K entries, 1,113 words with Caribbean/PR/Cuba tags
- `pipeline/artist/bench/.eswikt_translation_cache.json` — cached Spanish→English gloss translations from gap-fill runs
