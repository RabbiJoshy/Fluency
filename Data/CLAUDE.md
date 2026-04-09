# Data Directory — AI Reference

Static vocabulary JSON files consumed by the front-end. No backend.

## Vocabulary Files

| Language | File | Entries |
|----------|------|---------|
| Spanish | `Spanish/vocabulary.json` | ~11,136 |
| Swedish | `Swedish/vocabulary.json` | ~2,001 |
| Italian | `Italian/vocabulary.json` | ~600 |
| Dutch | `Dutch/vocabulary.json` | ~100 |
| Polish | `Polish/vocabulary.json` | ~300 |

## Vocabulary Entry Schema

```json
{
  "word": "hacer",
  "lemma": "hacer",
  "id": "a1b2c3",
  "rank": 42,
  "meanings": [
    {
      "pos": "VERB",
      "translation": "to do / to make",
      "example_spanish": "Voy a hacer la tarea",
      "example_english": "I'm going to do the homework"
    }
  ],
  "is_transparent_cognate": false
}
```

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
