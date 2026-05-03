# Data Directory — AI Reference

> **Don't bulk-read** vocabulary or examples JSON files — they're 1–10 MB. Grep them by hex ID or word.

Static vocabulary JSON files consumed by the front-end. No backend.

Pipeline layers (intermediate files produced by each build step) are in `Spanish/layers/` — see `layers/CLAUDE.md` for schemas and provenance design. The normal-mode pipeline orchestrator is `pipeline/run_pipeline.py`.

## Vocabulary Files

| Language | File | Entries |
|----------|------|---------|
| Spanish | `Spanish/vocabulary.json` | ~11,136 |
| Swedish | `Swedish/vocabulary.json` | ~2,001 |
| Italian | `Italian/vocabulary.json` | ~600 |
| Dutch | `Dutch/vocabulary.json` | ~100 |
| Polish | `Polish/vocabulary.json` | ~300 |

## Vocabulary File Formats

Spanish uses a **split format** for efficiency:

- `vocabulary.index.json` — compact index (no examples), loaded first
- `vocabulary.examples.json` — examples keyed by hex ID, lazy-loaded
- `vocabulary.json` — full monolith (debug/legacy, contains everything)

### Artist Index Entry Schema

Artist vocabulary index files live at `Artists/{lang}/` (not in `Data/`). Sense definitions live in `Artists/{lang}/vocabulary_master.json`; the per-artist index only carries per-artist statistics. `joinWithMaster()` in `vocab.js` reconstructs full entries at load time.

```json
{
  "id": "a1b2c3",
  "corpus_count": 142,
  "most_frequent_lemma_instance": true,
  "sense_frequencies": [0.8, 0.2],
  "sense_methods": ["spanishdict-keyword", null],
  "unassigned": true,
  "cognate_score": 0.5,
  "sense_cycles": [
    {
      "pos": "SENSE_CYCLE",
      "cycle_pos": "NOUN",
      "translation": "debt",
      "allSenses": [{"pos": "NOUN", "translation": "debt"}, {"pos": "NOUN", "translation": "drug"}]
    }
  ]
}
```

- `sense_frequencies[i]` — fraction of examples assigned to master sense i
- `sense_methods[i]` — assignment method for sense i (`"spanishdict-keyword"`, `"flash-lite-wiktionary"`, etc.), or `null` for strong/auto assignments and unassigned senses
- `unassigned: true` — present if any sense has no real assignment (random bucket); controls border display in flashcards
- `sense_cycles` — SENSE_CYCLE groups for unassigned senses; `allSenses` includes keyword-assigned senses of the same POS so the remainder cycler shows all interpretations

In `joinWithMaster()`: if `sense_methods[i]` is non-null, the meaning gets `assignment_method` set (informational, no rendering effect). If `sense_methods[i]` is null and `idx.unassigned` is true, the meaning gets `unassigned: true` (no border). Strong/auto-assigned senses get neither flag (border shown).

The normal-mode pipeline uses a simpler legacy index with `word`, `lemma`, `rank`, and `meanings` inline — not master-aligned.

### Examples Entry Schema (`vocabulary.examples.json`)

```json
{
  "a1b2c3": {
    "m": [
      [{ "target": "Voy a hacer la tarea", "english": "I'm going to do the homework" }]
    ],
    "w": []
  }
}
```

`m[i]` = examples for meaning at index i, `w[i]` = examples for MWE at index i.

## Word IDs

6-char **hex** string: `md5(word|lemma)[:6]`. Consistent across all files.

- Collision resolution: append suffix before rehashing (`md5(word|lemma|1)[:6]`)
- Same word = same ID across artists and normal vocab (enables merge)
- Migration from rank-based IDs: `{lang}/id_migration.json`

## Composite fullId (built at runtime by front-end)

```
fullId = {2-char lang code}{0=normal|1=lyrics}{6-char hex id}
```

Examples: `es0a1b2c3` (Spanish normal), `es1a1b2c3` (Spanish lyrics), `sv06b7f8a` (Swedish normal).

Lang codes: spanish->es, swedish->sv, italian->it, dutch->nl, polish->pl, french->fr, russian->ru.

## Word Inventory (intermediate layer)

`Spanish/layers/word_inventory.json` — foundation layer produced by step 1 (`build_inventory.py`).

```json
{
  "word": "como",
  "lemma": "como",
  "id": "227610",
  "corpus_count": 1598,
  "most_frequent_lemma_instance": true,
  "homograph_ratio": 0.85
}
```

- `corpus_count`: raw frequency from wiki corpus, adjusted by `homograph_ratio` when the word is a homograph
- `most_frequent_lemma_instance`: true if this entry has the highest corpus_count among all entries sharing its lemma
- `homograph_ratio`: (homographs only) the estimated proportion of this surface form's usage attributable to this lemma. Computed by spaCy over Tatoeba, with manual overrides from `layers/homograph_overrides.json`. See `docs/design/homograph_disambiguation.md`.

## PPM Data (optional per language)

CSV files like `Spanish/SpanishRawWiki.csv` with columns: `rank,occurrences_ppm`. Used for % coverage mode. `totalPpm` = sum of all ppm values.

## progressData Schema (runtime, not stored here)

```js
progressData[fullId] = {
  correct: 3, wrong: 1,
  lastCorrect: "ISO timestamp", lastWrong: "ISO timestamp",
  lastSeen: "ISO timestamp", word: "hacer", language: "spanish"
}
```

Mastered: `correct > 0` for the selected language. Mastered words filtered out of sets.

## Google Sheets Integration

Sheets: `UserProgress` (normal) and `Lyrics` (artist mode). Columns: User | Word | WordId | Language | Correct | Wrong | LastCorrect | LastWrong.

`secrets.json` (not in git): `{ "googleScriptUrl": "..." }`. If missing, sync silently disabled.

`GoogleAppsScript.js` is the Apps Script source — must be copy-pasted and redeployed manually.
