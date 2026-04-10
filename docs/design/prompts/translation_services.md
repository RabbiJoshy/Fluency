---
title: Translation service for Spanish lyrics
status: research
created: 2026-04-08
updated: 2026-04-08
---

# Translation Services for Spanish Lyrics → English

## The question

What's the best way to translate ~10k Spanish lyric lines per artist to English, cheaper than Gemini?

## Context

- Input is reggaeton/Latin pop lyrics — colloquial, slang-heavy, code-switching (Spanglish)
- Full sentence translation, not single words
- Quality needs to be "good enough for language learners" — doesn't need to be literary
- Currently using Gemini for this in step 6 (`pipeline/artist/6_llm_analyze.py`), which is expensive at scale
- Young Miko has 0% English translation coverage — Genius community translations barely exist for her
- Python 3.9, sentence-transformers already installed, `.venv/bin/python3`
- Willing to pay a little but prefer free/cheap

## What to investigate

### 1. Local models (free, unlimited)

- Helsinki-NLP/opus-mt-es-en (MarianMT) — small, CPU-friendly
- facebook/nllb-200-distilled-600M — Meta's multilingual model
- Any other huggingface translation models worth trying for es→en
- Can any of these handle Spanglish/code-switching?

### 2. Free API tiers

- DeepL Free API (500k chars/month)
- Google Cloud Translation free tier
- Microsoft Azure Translator free tier
- LibreTranslate (self-hosted, open source)
- Lingva Translate (free, no key needed)
- Any others?

### 3. Cheap paid APIs

- DeepL Pro pricing vs Gemini for this use case
- Amazon Translate pricing
- Any batch/bulk translation services

## Benchmark approach

Take 20 diverse lyric lines from `Artists/Young Miko/data/layers/examples_raw.json` — mix of clean Spanish, slang, and Spanglish. Run each candidate and compare quality. Time the local models. Calculate cost per 10k lines.

## Output expected

A comparison table: quality rating, speed, cost per 10k lines, Spanglish handling. Recommend the best option for the pipeline. Show raw translations so Josh can judge quality.

Don't build anything permanent — just research and benchmark.

---

# Research Findings (2026-04-08)

## Benchmark setup

20 diverse lyric lines from Young Miko's `examples_raw.json`. Mix of clean Spanish, Puerto Rican slang, apocope (to'a, vamo', cerra'o), and Spanglish code-switching. Young Miko has ~10,105 total example lines.

Environment: Python 3.9, `transformers` 4.57.6, `torch` 2.8.0, `deep-translator` 1.11.4 (all pre-installed). CPU-only (no GPU).

## Comparison table

| Service | Quality | Speed | Cost / 10k lines | Spanglish | Notes |
|---------|---------|-------|-------------------|-----------|-------|
| **Google Translate** (deep-translator) | **Good** | 535ms/line (~90 min for 10k) | **$0 (free)** | Good — handles code-switching, gets "jevo", resolves apocope | Unofficial API, no key needed |
| MarianMT (opus-mt-es-en) | Decent | 100ms/line (~17 min for 10k) | $0 (local) | Weak — "bandolera" → "crossbody", literal on slang | 300MB download, CPU-friendly |
| NLLB-200-distilled-600M | **Poor** | 4,594ms/line (~12.7 hrs for 10k) | $0 (local) | Terrible — leaves Spanish untranslated, hallucinates | 600MB, unusably slow on CPU |
| DeepL Free API | (not tested) | — | $0 (500k chars/mo) | Likely good | Requires API key signup; 500k chars ≈ 1 artist |
| DeepL Pro API | (not tested) | — | ~$18 per artist | Likely best | $5.49/mo base + $25/M chars |
| Google Cloud Translation | (not tested) | — | $10 per artist (or free for first 500k chars/mo) | Good | Official API, requires GCP project |
| Amazon Translate | (not tested) | — | $7.50 per artist | Good | 2M chars free for 12 months |
| Gemini 2.5 Flash Lite (current) | Best | ~fast (batched) | ~$0.07-0.30 per artist | Best — understands context, slang, intent | Already in pipeline, sentence batch of 40 |

**Cost assumptions:** ~10k lines x ~50 chars avg = ~500k characters per artist.

## Raw translations — side by side

### Lines where Google Translate clearly wins vs MarianMT

| # | Spanish | Google Translate | MarianMT |
|---|---------|-----------------|----------|
| 2 | "...bandolera vuelve ya, 'tás en mi mente..." | "shoulder bag come back now, you are on my mind" | "'tis in my mind" (lost half the line) |
| 5 | "Tu jevo no cabe sorry..." | "Your boy doesn't fit, sorry..." | "Your jevo doesn't fit sorry" (left "jevo" untranslated) |
| 7 | "Si tú te pegas, yo te guayo..." | "If you hit me, I'll help you" | "If you hit yourself, I'll cool you off" |
| 8 | "En casita comiéndote to'a" | "At home eating everything" | "In little house eating you to'a" |
| 12 | "Mas que un caballo 'e paso fino" | "More than a Paso Fino horse" | "More than a horse's fine step" |
| 16 | "Jura'o tengo la llave de tu corazón cerra'o" | "I swear I have the key to your closed heart" | "I swear I have the key to your heart closed" |
| 17 | "Pa' los Mickey Mouse traje la blicky" | "For Mickey Mouse I brought the blicky" | "Pa' the Mickey Mouse brought the blicky" |

### Lines where both do well

| # | Spanish | Google Translate | MarianMT |
|---|---------|-----------------|----------|
| 1 | "Pa' vivir el sueño hay que estar despierto" | "To live the dream you have to be awake" | "To live the dream you have to be awake" |
| 10 | "...que sientan la presión, shit, I like that" | "Well, let them feel the pressure, shit, I like that" | "Well, let them feel the pressure, shit, I like that" |
| 20 | "Esto es temporero" | "This is temporary" | "This is temporary" |

### Neither handles well (would need Gemini/LLM)

| # | Spanish | Google Translate | MarianMT | Issue |
|---|---------|-----------------|----------|-------|
| 7 | "yo te guayo" | "I'll help you" | "I'll cool you off" | Both miss the reggaeton meaning (grinding) |
| 8 | "comiéndote to'a" | "eating everything" | "eating you to'a" | Google misses the sexual connotation |
| 14 | "enchula'o" | left untranslated | "on the hook" | Slang — MarianMT actually closer here |

## Key observations

1. **Google Translate via deep-translator is the clear value winner.** Free, no API key, good quality on ~80% of lines. Handles apocope, code-switching, and common slang reasonably well.

2. **MarianMT is fast but mediocre.** 100ms/line is great, but it stumbles on apocope (to'a, pa'), leaves Caribbean slang untranslated (jevo), and produces awkward word order. Not worth it when Google Translate is also free and better.

3. **NLLB-200 is unusable.** Hallucinated, left Spanish untranslated, and took 4.6s/line on CPU. Eliminated.

4. **Gemini is still the quality king** for this domain — it understands reggaeton context, sexual innuendo, slang intent. But for "good enough for language learners," Google Translate covers most cases.

5. **Rate limiting concern:** `deep-translator` uses the unofficial Google Translate web API. For 10k lines sequentially at 535ms each, it takes ~90 minutes. No known hard rate limit, but could get throttled. Worth testing at full 10k scale.

6. **Hybrid approach possible:** Use Google Translate for the bulk (free), flag lines with untranslated words or low confidence for Gemini review. Could cut Gemini costs by 80-90%.

## Recommendation

**Google Translate via `deep-translator`** as the primary sentence translator. It's free, already installed, quality is good enough for language learners, and handles Spanglish/apocope better than local models.

**Open questions before deciding:**
- Does Google Translate hold up at 10k line scale without throttling?
- Is the quality gap vs Gemini acceptable for the pipeline's purpose?
- Worth building a hybrid (Google Translate + Gemini fallback for flagged lines)?
