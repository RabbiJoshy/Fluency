---
name: onboard-artist
description: Onboard a new artist into Fluency — creates directory structure, config files, downloads lyrics, builds albums dictionary with cover art, and runs dedup scan
user-invocable: true
---

# Onboard New Artist

Takes an artist name as the argument (e.g., `/onboard-artist Anuel AA`).

## What to do

### 1. Create directory structure

```
Artists/{lang}/{Name}/
  artist.json
  Images/
  data/input/batches/
  data/input/translations/
  data/layers/
  data/word_counts/
  data/elision_merge/
  data/known_vocab/
  data/llm_analysis/
  data/proper_nouns/
```

### 2. Create `artist.json`

Use the artist name to derive file paths. Strip spaces for file prefixes (e.g., "Bad Bunny" -> "BadBunny").

```json
{
  "name": "{Artist Name}",
  "genius_query": "{Artist Name}",
  "vocabulary_file": "{Prefix}vocabulary.json",
  "index_file": "{Prefix}vocabulary.index.json",
  "examples_file": "{Prefix}vocabulary.examples.json"
}
```

### 3. Add entry to `config/artists.json`

Derive a slug from the name (lowercase, spaces to hyphens, strip accents). Use existing entries as templates. Include:

- `name`, `language` ("spanish"), `masterPath` ("Artists/vocabulary_master.json")
- `dataPath`, `indexPath`, `examplesPath` pointing to `Artists/{lang}/{Name}/` files
- `albumsDictionary` path (will be created in step 6)
- `albumImageMap` (will be populated in step 7)
- `defaultAlbumArt` pointing to `Artists/{lang}/{Name}/Images/SINGLES.jpg`
- `colorTheme` — pick two colors that match the artist's brand/aesthetic. Use web search to check the artist's visual branding.
- `maxLevel` — set to 5000 as a placeholder (will be updated after pipeline runs)

### 4. Download lyrics (Step 1)

Print the command for Josh to run — it's long-running:

```
.venv/bin/python3 pipeline/artist/1_download_lyrics.py --artist "{Name}"
```

Wait for Josh to confirm it's done before proceeding.

### 5. Run dedup scan

Follow the process in `Artists/DEDUP_INSTRUCTIONS.md`:

1. Load all batch files from `Artists/{lang}/{Name}/data/input/batches/`
2. Generate a throwaway Python script that scans for duplicates, placeholders, non-Spanish songs, and non-songs
3. Run the script and review the output
4. Create `Artists/{lang}/{Name}/data/input/duplicate_songs.json` with the findings
5. Delete the throwaway script

### 6. Build albums dictionary

After lyrics are downloaded, build `{slug}_albums_dictionary.json`:

1. Use the Genius API (via `lyricsgenius`) or web search to find the artist's discography — album names and release years
2. Map each song from the batch files to its album using the Genius song URL or title matching
3. Songs not matching any album go under "Singles & Features" (or "Singles & Other Tracks")
4. Format: `{"Album Name (Year)": ["Song Title 1", "Song Title 2", ...], ...}`
5. Write to `Artists/{lang}/{Name}/{slug}_albums_dictionary.json`

### 7. Download album cover images

For each album in the albums dictionary:

1. Search Wikipedia for the album page (e.g., "{Album Name} {Artist Name} album")
2. Try to download the album cover image from the Wikipedia article
3. Save as `Artists/{lang}/{Name}/Images/{ALBUM_NAME_NORMALIZED}.jpg` (uppercase, spaces to underscores, strip accents/special chars)
4. If no image found for an album, skip it — Josh will add it manually
5. For "Singles & Features" / "Singles & Other Tracks", skip (Josh provides this one)

After downloading, update the `albumImageMap` in `config/artists.json` with the actual file paths and extensions.

### 8. Report what's left

Tell Josh:
- How many songs downloaded, how many excluded by dedup
- Which albums have cover art and which need manual images
- The SINGLES.jpg needs to be added manually
- Next step: run the full pipeline (`--no-gemini` first, then `--words-only`)

## Important notes

- All scripts run from the **project root** (`Fluency/`), not from `Artists/`
- Python 3.9 — use `Optional[str]` not `str | None`
- Long-running commands (step 1 download): print for Josh to run, don't run inline
- Never delete `curated_translations.json` if it exists
- The `genius_query` field in `artist.json` may need adjustment if the artist has accented characters or goes by a different name on Genius
