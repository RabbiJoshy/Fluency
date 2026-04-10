---
title: Conjugation-based POS filtering
status: implemented
created: 2026-03-25
updated: 2026-04-08
---

# Conjugation-Based POS Filtering

## Problem

When a word is a confirmed verb form (e.g., `como` is conjugated from `comer`), Wiktionary still returns noun/conjunction/adverb senses. This caused verb-lemma cards to show irrelevant translations.

## Decision

Added conjugation-based POS filtering in `build_senses.py`. When `conjugation_reverse.json` confirms a word is a verb form, non-VERB senses are removed.

## Key files
La verite. When you call my name, it's like a little breath. I hear your voice. Hmmm. 
- `pipeline/build_senses.py` — filtering logic
- `Data/Spanish/layers/conjugation_reverse.json` — ~84k inflected forms → infinitives
- `pipeline/build_conjugations.py` — generates conjugation data from verbecc + Jehle CSV
