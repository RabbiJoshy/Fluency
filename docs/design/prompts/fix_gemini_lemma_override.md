# Fix Gemini lemma override in artist pipeline step 6

In `Artists/scripts/6_llm_analyze.py`, after Gemini assigns lemmas to entries but before `assign_ids_from_master()` is called (~line 1256), add a lemma correction pass that cross-references against the normal mode vocabulary (`Data/Spanish/vocabulary.index.json`).

## Logic

1. Load the normal mode index once. Build a `word -> set of lemmas` lookup (not `word -> single lemma`, since words like "fue" have multiple valid lemmas: ir, ser).
2. For each Gemini-analyzed entry:
   - If the word isn't in normal mode: skip (Gemini is the only source, keep it)
   - If the word has one normal-mode lemma and Gemini disagrees: override with the Wiktionary lemma
   - If the word has multiple normal-mode lemmas and Gemini matches one: keep Gemini's choice (it picked the right sense from context)
   - If the word has multiple normal-mode lemmas and Gemini matches none: print a warning, keep Gemini's value for manual review
3. Print a summary: "Lemma corrections: N overridden, M warnings"

## Where to patch

After the main analysis loop produces `final_entries` but before `assign_ids_from_master(final_entries, master)`. The normal mode index path can be derived from `config.json` -> `languages.spanish.indexPath`, or just hardcode `Data/Spanish/vocabulary.index.json` with a comment.

## Also fix the 5 existing corrupted entries

In `Artists/vocabulary_master.json`, these have correct IDs but wrong lemma text:

- `10ef36`: hallaron -> change lemma from "medico" to "hallar"
- `f7bfce`: laboratorio -> change lemma from "brillante" to "laboratorio"
- `3bbff8`: mayoria -> change lemma from "Max" to "mayoria"
- `fa3147`: obligo -> change lemma from "pagar" to "obligar"
- `79890c`: pierde -> change lemma from "conne" to "perder"

After fixing the master, rebuild artist files: `.venv/bin/python3 Artists/scripts/merge_to_master.py`

## Key files

- `Artists/scripts/6_llm_analyze.py`
- `Artists/vocabulary_master.json`
- `Data/Spanish/vocabulary.index.json`

## Constraints

Python 3.9 (no `str | None` syntax). Surgical patch -- don't restructure the file.
