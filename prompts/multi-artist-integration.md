# Multi-Artist Integration — Implementation Prompt

You have three tasks to complete, in order. Each builds on the previous. Read CLAUDE.md thoroughly before starting — it documents the full architecture, ID systems, pipeline, and front-end module system.

---

## Task 1: Switch Normal Spanish Vocabulary to MD5-Based Hex IDs

### Background

Normal Spanish vocabulary (`Data/Spanish/vocabulary.json`) currently uses rank-based hex IDs: `format(rank, '04x')` — rank 1 = `"0001"`, rank 10 = `"000a"`, etc.

The artist pipeline (`Artists/scripts/6_llm_analyze.py`) uses `md5(word|lemma)[:4]` — deterministic hashing that produces the same ID for the same word+lemma regardless of artist. For example, "que" always gets `ed68`.

These need to be unified so that the same word has the same hex ID in both normal and artist vocabularies. The target scheme is `md5(word|lemma)[:4]` everywhere.

### What to change

**Pipeline/data side:**
- Write a script (or extend an existing one) to re-ID `Data/Spanish/vocabulary.json` using the same `md5(word|lemma)[:4]` hashing as the artist pipeline. The `rank` field stays unchanged — only `id` changes.
- Verify there are no hash collisions within the 11,136-entry Spanish vocabulary. If there are, use a collision resolution strategy (e.g., increment the last hex digit) and document it.
- Do the same for any other language vocabulary files that have entries (`Data/Swedish/`, `Data/Italian/`, `Data/Dutch/`, `Data/Polish/`).

**Front-end side:**
- In `js/vocab.js`, the `getWordId()` function already reads `item.id` from the vocabulary JSON. Since the JSON will now contain md5-based IDs, no change should be needed to `getWordId()` itself. Verify this.
- The fallback path in `getWordId()` that computes `Number(item.rank).toString(16).padStart(4, '0')` is for entries without an `id` field — this can remain as a safety net but should never trigger for Spanish vocab after re-IDing.

**Google Sheets migration:**
- Existing progress data in Google Sheets uses the old rank-based fullIds (e.g., `es00001` for "que" at rank 1). After re-IDing, new progress would be saved as `es0ed68`.
- Write a one-time migration: a script or Apps Script function that reads all rows from the `UserProgress` sheet, maps old wordId to new wordId (using a mapping from the re-ID step), and updates the rows in place.
- Generate and save the old-to-new ID mapping as a JSON file for the migration.
- Also update any `localStorage` progress data — add a migration check in `js/auth.js` that runs once on load, detects old-format IDs, and remaps them. Use a localStorage flag (e.g., `id_migration_v1`) to avoid re-running.

### Verification
- Load the app in normal Spanish mode, confirm vocabulary loads and displays correctly.
- Confirm that `getWordId()` produces IDs matching the new vocabulary JSON.
- Check that existing progress (if any) still shows words as mastered after migration.

---

## Task 2: Generalize Artist Mode (Replace `isBadBunnyMode`)

### Background

The app currently uses a boolean `isBadBunnyMode` (set from `?mode=badbunny` URL param) in ~15 places across 7 JS modules. Everything about Bad Bunny — file paths, colors, album art, sheet name, UI text — is hardcoded. This needs to become data-driven so any artist can be loaded.

### What to change

**Create `artists.json` at project root:**
```json
{
  "bad-bunny": {
    "name": "Bad Bunny",
    "language": "spanish",
    "dataPath": "Artists/Bad Bunny/BadBunnyvocabulary.json",
    "indexPath": "Artists/Bad Bunny/BadBunnyvocabulary.index.json",
    "examplesPath": "Artists/Bad Bunny/BadBunnyvocabulary.examples.json",
    "albumsDictionary": "Artists/Bad Bunny/bad_bunny_albums_dictionary.json",
    "imagesDir": "Artists/Bad Bunny/Images/",
    "albumImageMap": {
      "X 100PRE (2018)": "Artists/Bad Bunny/Images/X100PRE.jpg",
      "OASIS (2019) [with J Balvin]": "Artists/Bad Bunny/Images/OASIS.png",
      ...
    },
    "defaultAlbumArt": "Artists/Bad Bunny/Images/SINGLES.jpg",
    "colorTheme": { "primary": "#ED1C24", "secondary": "#0050A0" },
    "maxLevel": 8500
  },
  "rosalia": {
    "name": "Rosalia",
    "language": "spanish",
    "dataPath": "Artists/Rosalía/rosaliavocabulary.json",
    ...
  }
}
```

Move the hardcoded `albumToImagePath` map from `js/state.js` (lines 79-90) into this config under each artist's `albumImageMap`.

**New state variable in `js/state.js`:**
```js
activeArtist: null   // null = normal mode, object = artist/lyrics mode
```

Keep `isBadBunnyMode` as a computed getter for backward compatibility during transition:
```js
get isBadBunnyMode() { return !!state.activeArtist; }
```

**URL handling in `js/main.js`:**
- `?artist=bad-bunny` → look up in `artists.json`, set `activeArtist`
- `?mode=badbunny` → alias, maps to `?artist=bad-bunny`
- No param → `activeArtist` stays null, normal mode

**Replace all `isBadBunnyMode` checks across the codebase.** These are the files and the nature of each check:

- `js/state.js` — declaration + `albumToImagePath` constant (remove hardcoded map)
- `js/config.js` — config override block (lines 12-29): read paths/colors from `activeArtist` instead of hardcoding Bad Bunny values
- `js/main.js` — URL parsing + UI setup (hide language tabs, force Spanish, show help bar): drive from `activeArtist` presence
- `js/vocab.js` — `getWordId()` mode digit + `buildFilteredVocab()` artist-specific filters: use `activeArtist` truthiness
- `js/ui.js` — tooltip text and step labels: read artist name from `activeArtist.name`
- `js/progress.js` — coverage label ("lyrics coverage" vs "corpus coverage"): check `activeArtist`
- `js/estimation.js` — `maxLevel` bound: read from `activeArtist.maxLevel`
- `js/flashcards.js` — any artist-specific rendering
- `js/auth.js` — Google Sheets tab name: `activeArtist ? 'Lyrics' : 'UserProgress'`
- `js/badbunny.js` — album art loading and background updates: generalize to read from `activeArtist` config

**Rename `js/badbunny.js` → `js/artist-ui.js`:**
- `loadBadBunnyAlbumsDictionary()` → `loadArtistAlbumsDictionary()` — fetches from `activeArtist.albumsDictionary`
- `updateBadBunnyBackground()` → `updateArtistBackground()` — reads image paths from `activeArtist.albumImageMap`
- Update the import in `js/main.js` and any `window` exports

**Google Sheets — rename sheet tab:**
- All 4 occurrences of `'BadBunny'` in `js/auth.js` → `'Lyrics'`
- Update `GoogleAppsScript.js`: in `getOrCreateSheet()`, if `'Lyrics'` sheet doesn't exist but `'BadBunny'` does, rename it. This handles migration for existing users.
- Redeploy the Apps Script (remind Josh to do this manually).

**Service worker (`service-worker.js`):**
- Add `artists.json` to the cache list
- Update `badbunny.js` → `artist-ui.js` in the cache list
- Bump the cache version

### Verification
- `?mode=badbunny` still works identically to before
- `?artist=bad-bunny` works identically
- Normal mode (no params) works identically
- All flashcard features work: album art, progress saving, estimation, filtering

---

## Task 3: Multi-Artist Selection and Client-Side Vocabulary Merge

### Background

With Task 2 done, the app can load any single artist. Now add the ability to select multiple artists and merge their vocabularies client-side.

### What to change

**Settings UI:**
- Add a settings icon/gear to the artist mode UI (near the help bar area)
- Clicking it opens a panel showing all available artists (from `artists.json`) as checkboxes
- The artist from the URL param is pre-selected and checked
- User can toggle additional artists on/off
- Persist selected artist slugs in `localStorage` under key `selected_artists`
- On change, reload vocabulary with merged data

**Client-side vocabulary merge:**
- Load vocabulary JSON for each selected artist
- Build a map keyed by hex `id`
- For words appearing in multiple artists:
  - Union the `meanings[].allExamples` arrays, tagging each example with an `artist` field if not already present
  - Take the max `corpus_count` (or sum — decide based on what makes more sense for ranking)
  - Keep all other fields from whichever artist has the richer entry (more meanings, more examples)
- For words unique to one artist: include as-is
- Sort merged vocabulary by combined corpus count (descending)
- Recompute `displayRank` from the merged+sorted result (this happens in `buildFilteredVocab()` already)

**Album art adaptation:**
- When displaying a lyric example, determine which artist it's from (via the `artist` tag on the example, or by looking up the song in each artist's albums dictionary)
- Load the appropriate artist's album art for that example
- If cycling through examples (`cycleExample`), album art updates per example

**Estimation bounds:**
- `maxLevel` should be the max of all selected artists' `maxLevel` values, or recomputed from the merged vocabulary size

**What NOT to change:**
- Google Sheets integration — no changes needed. Progress is keyed by fullId, which is the same regardless of which artist(s) are selected. A word mastered through Bad Bunny stays mastered when Rosalia is added.
- The `getWordId()` function — same hex hash, same mode digit `1`, same fullId.
- The pipeline — each artist is still processed independently. The merge is purely client-side.

### Verification
- Select only Bad Bunny → identical behavior to before
- Select Bad Bunny + Rosalia → merged vocabulary loads, ranks reflect combined corpus
- Learn a word via Bad Bunny only → add Rosalia → word still shows as mastered
- Album art changes correctly when cycling between examples from different artists
- Settings persist across page reloads (localStorage)
- De-selecting all artists except one returns to single-artist behavior
