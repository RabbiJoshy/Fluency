---
title: Normal mode translation quality
status: implemented
created: 2026-03-20
updated: 2026-04-08
---

# Normal Mode Translation Quality

## Problem

Wiktionary-sourced translations had quality issues for common words: wrong sense prioritized, verbose definitions, missing prepositions.

## Fixes applied in `build_senses.py`

- **Sense merge bug:** stop-word-only translations no longer incorrectly merged
- **Alt-of extraction:** rescued `al`, `muy` and similar entries
- **Letter-name deprioritization:** `de` → "of" ranks above "letter D"
- **Verbose translation cleaning:** colon/semicolon pattern extraction (`lo` → "the, that which is", `tu` → "you", `me` → "me")
- **Pronoun form-of extraction:** `nos` → "us", `les` → "them"

## Remaining issue

`a|a` (preposition) has no usable Wiktionary entry — needs a curated override in the senses layer or a different source. Tracked as [soon] in TODO.md.

## Key files

- `pipeline/build_senses.py` — all fixes here
