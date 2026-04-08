---
title: Translation service for Spanish lyrics
status: prompt
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
- Currently using Gemini for this in step 6 (`Artists/scripts/6_llm_analyze.py`), which is expensive at scale
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
