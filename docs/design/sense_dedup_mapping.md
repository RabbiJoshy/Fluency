---
title: Sense deduplication and mapping
status: implemented
created: 2026-03-15
updated: 2026-04-08
---

# Sense Deduplication and Mapping

## Decision

Merged 271 duplicate senses via normalization + spaCy morphology in `merge_to_master.py`.

## How it works

`choose_canonical_translation()` in `merge_to_master.py` normalizes translations before comparing:
- Strips articles, parentheticals, "to" prefix for verbs
- spaCy morphology catches singular/plural and tense variants
- Within same POS: identical normalized translations merge

## Remaining polish

English 3rd-person conjugation: generated translations say "he/she go" instead of "he/she goes". Would need English conjugation logic in `choose_canonical_translation()`. Tracked as [idea] in TODO.md.

## Key files

- `Artists/scripts/merge_to_master.py` — merge logic
- `Artists/vocabulary_master.json` — output
