---
title: Shared master vocabulary architecture
status: implemented
created: 2026-03-01
updated: 2026-04-08
---

# Shared Master Vocabulary Architecture

## Decision

`Artists/vocabulary_master.json` is the single source of truth for word identity and senses across all artists.

## Design

- Keyed by 6-char hex IDs: `md5(word|lemma)[:6]`
- Collision resolution: suffix rehash (`md5(word|lemma|1)[:6]`)
- Both pipelines (normal + artist) share the same ID scheme
- Senses accumulate across artists — a new artist's Gemini run can discover new senses
- `merge_to_master.py` handles sense dedup via `normalize_translation()` + spaCy morphology
- Front-end joins master + artist index + artist examples at load time via `joinWithMaster()` in `vocab.js`

## Key files

- `Artists/vocabulary_master.json` — the master
- `pipeline/artist/merge_to_master.py` — rebuild/migration tool
- `pipeline/artist/build_artist_vocabulary.py` — builder that reads master for ID assignment
- `js/vocab.js` → `joinWithMaster()` — front-end join logic
