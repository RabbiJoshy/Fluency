# Refactor: Move elision resolution before tokenization

## Problem

Elision merging currently happens in step 5 (`5_merge_elisions.py`), after step 3 has already tokenized and counted words. By that point, examples are capped at 10 per word. For ambiguous elisions like `ve'` (which can be "vez" or "ves"), we only have 10 examples to disambiguate from, then estimate the full count proportionally.

## Proposed architecture

Resolve elisions in a preprocessing pass on the raw lyric text **before** step 3 tokenizes and counts. Step 3 would never see elided forms — it just tokenizes normal Spanish words.

### Flow

1. **New step (2c or pre-3)**: Load elision mapping. For each lyric line, replace elided tokens with canonical forms. Preserve original text for display.
   - `ere'` → `eres`, `to'` → `todo`, `pa'` → `para`, `olvida'o` → `olvidado`, `toy` → `estoy`
   - For ambiguous elisions (`ve'`): use preceding-word heuristic or spaCy transformer to decide `vez` vs `ves` — full sentence context is available for every occurrence
   - Attach provenance metadata: `{original_form: "ere'", resolved_to: "eres"}`
2. **Step 3**: Tokenizes the normalized text. Counts are already correct per canonical form. No elision awareness needed.
3. **Step 5**: Eliminated entirely (or reduced to a no-op).

### Benefits

- Every occurrence gets disambiguated (not just 10 examples)
- Counts are exact, not estimated
- Step 3 stays simple (tokenize + count)
- Step 5 goes away — one fewer pipeline step
- D-elisions and s-elisions handled uniformly
- Same treatment as normal text normalization (lowercasing, etc.)

### Key detail: variant tracking

Currently cards show "ere' | eres" with per-variant frequency. If we normalize before counting, we lose variant counts unless we track them during normalization. The preprocessing step should output a side table:

```json
{
  "eres": {"ere'": 145, "eres": 89},
  "estoy": {"toy": 47, "estoy": 312}
}
```

This gets carried through to the front-end for variant display.

### Key detail: original lyrics preserved

Example sentences must show the original elided text (what the artist actually sang). Only the tokenization/counting input gets normalized. The `examples_raw.json` layer keeps the original `line` field untouched.

### Disambiguation methods (for ambiguous elisions like ve')

Two methods available, switchable via config:

1. **`preceding_word`** (default, 10/10 accuracy on test data): Check word before `ve'` — determiners/adjectives (`una`, `otra`, `cada`, `tal`, etc.) signal "vez"; pronouns (`tú`, `me`, `te`, `se`) signal "ves"
2. **`spacy_trf`** (7/10 accuracy): POS-tag with `es_dep_news_trf` transformer model. Less accurate because the non-standard apostrophe token confuses the tagger. Available as an alternative if the preceding-word list proves incomplete.

### What's already done

- `elision_mapping.json`: `toy` entry fixed to `elision_pair` → `estoy` (committed)
- `5_merge_elisions.py`: Ambiguous elision disambiguation with both methods + proportional count splitting (committed, but will be superseded by this refactor)
- `flashcards.js`: Duplicate ELISION_MAP entry removed (committed)

### Files to modify

- New preprocessing script (step 2c or integrated into step 3's batch loading)
- `3_count_words.py` — remove any elision awareness, consume normalized input
- `5_merge_elisions.py` — deprecate or remove
- `run_pipeline.py` — update step ordering
- `Artists/CLAUDE.md` — update pipeline table
