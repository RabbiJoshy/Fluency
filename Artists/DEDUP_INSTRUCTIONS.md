# Deduplication & Song Exclusion — Instructions for Claude

This document describes how to maintain `duplicate_songs.json`. **Only run this when Josh explicitly asks for a dedup pass or foreign song removal** — do not run it automatically as part of the pipeline or after downloading new songs.

## What `duplicate_songs.json` controls

The file has four sections:

- **`duplicates`** — maps a duplicate song ID to the canonical version to keep. The duplicate's lyrics are excluded from word counting; the canonical version's lyrics are kept.
- **`placeholders`** — song IDs with no real lyrics (stubs, "yet to be transcribed", instrumentals, <50 chars of content).
- **`non_spanish`** — songs to exclude because they aren't in Spanish. Portuguese covers, German tracks, English-only content, translation pages, SNL skits, etc.
- **`stats`** — summary counts (update after every pass).

## Step-by-step process

### 1. Scan for duplicates

Load all songs from `data/input/batches/batch_*.json`. Group songs whose titles match after normalization:

**Title normalization rules** — strip these parenthetical/bracketed tags (case-insensitive):
- `(Remix)`, `(Spanish Remix)`, `(Mega Remix)`, `(FRUTi Remix)`, etc. — any remix variant
- `(Live)`, `[Live]`
- `(Mixed)`, `[Mixed]`, `(Mixed) [date]`
- `(Extended Version)`, `(Versión Original)`, `(Primera Versión)`
- `(Clean Version)`, `(Versión Limpia)`
- `(Radio Edit)`, `(Radio Version)`
- `(Instrumental)`
- `(Headphone Mix)`, `(Dolby Atmos Version)`
- `(Concert Version)`
- `(VISION: DJ C2)`, `(Fitness: Run, ...)`, `[NYE 2024]`, etc. — Apple Music/Spotify playlist tags
- `(Nico de Andrea Remix)`, `(Marshmello Remix)`, `(KLAP Remix)`, etc. — named remixes
- `(XNYWOLF Remix)`, `(Cornetto Remix)`, `(Wuayio Remix)`, etc.
- Trailing `*` (Genius incomplete marker)

After stripping, normalize case and whitespace. Songs with identical normalized titles are candidates for grouping.

**Which version to keep:**
- Prefer the version with the most lyrics content (longest non-boilerplate text)
- If roughly equal, prefer the one attributed to Bad Bunny in the URL (contains `bad-bunny`)
- If still tied, prefer the lowest song ID (oldest on Genius)

**Sequels are NOT duplicates:**
- "Me Llueven", "Me Llueven 2", "Me Llueven 3.0" are distinct songs — the number suffix makes them different titles after normalization
- Same for "Soy Peor" vs "Ahora Soy Peor", "Coronamos" vs "Coronamos (Remix 2)" (different base songs)

### 2. Scan for placeholders

Flag songs where the lyrics are:
- Fewer than 50 characters total
- Contain "yet to be transcribed", "instrumental", "letra completa no está disponible" with no other substantial content

### 3. Scan for non-Spanish songs

Check every song's lyrics for language. Flag songs that are:
- **Portuguese** — look for Portuguese markers: "você", "não", "tô", "beijo", "Ao Vivo", "nossas", "saudade", "fazendo"
- **German** — look for: "ich", "und", "nicht", "schwör", "weh", umlauts (ä, ö, ü) in non-Spanish contexts
- **English-only** — songs where the lyrics are overwhelmingly English with no meaningful Spanish content. A few Spanish words in an otherwise English song still counts as English-only. Bad Bunny features where he contributes Spanish verses on an otherwise English track should generally be KEPT (the English line filter in step 3 handles removing the English lines).
- **Translation pages** — Genius sometimes has English translation pages filed under the song. These have titles like "Bad Bunny - La Romana ft. El Alfa (English Translation)" or contain only English text that's clearly a translation.
- **SNL skits** — comedy sketches, spoken word, not actual songs

**Edge cases to KEEP (not exclude):**
- Songs by other artists where Bad Bunny has a feature with Spanish verses (Solita, Dura Remix, Te Boté, etc.) — these are valid corpus material
- Spanglish songs where Bad Bunny's parts are in Spanish — the English line filter handles the English portions
- Songs like DRUNK that mix English and Spanish — keep the canonical version, the line filter handles language separation

### 4. Check for overlaps

A song ID should only appear in ONE section. If a song is both a duplicate and non-Spanish, put it in duplicates (it'll be excluded either way, but duplicates maps it to a canonical version which is cleaner).

### 5. Update stats

```json
"stats": {
  "total_songs": <count of all songs in batch files>,
  "duplicates": <count of entries in duplicates>,
  "placeholders": <count of entries in placeholders>,
  "non_spanish": <count of entries in non_spanish.songs>,
  "unique_songs": <total - unique excluded IDs across all sections>
}
```

Note: some placeholder IDs also appear in duplicates (overlap). `unique_songs` should be `total_songs - |union of all excluded IDs|`.

## JSON schema

```json
{
  "description": "...",
  "duplicates": {
    "<duplicate_id>": {
      "keep": "<canonical_id>",
      "duplicate_title": "<title on Genius>",
      "original_title": "<canonical version's title>"
    }
  },
  "placeholders": ["<song_id>", ...],
  "non_spanish": {
    "description": "...",
    "songs": {
      "<song_id>": {
        "title": "<title on Genius>",
        "language": "portuguese|german|english|...",
        "reason": "<brief explanation>"
      }
    }
  },
  "stats": { ... }
}
```

## How to verify

After updating, validate with:

```python
python3 -c "
import json
with open('Bad Bunny/data/input/duplicate_songs.json') as f:
    data = json.load(f)
dup_ids = set(data['duplicates'].keys())
ph_ids = set(data['placeholders'])
ns_ids = set(data['non_spanish']['songs'].keys())
all_excluded = dup_ids | ph_ids | ns_ids
print(f'Duplicates: {len(dup_ids)}')
print(f'Placeholders: {len(ph_ids)}')
print(f'Non-Spanish: {len(ns_ids)}')
print(f'Total excluded (unique): {len(all_excluded)}')
print(f'Unique songs: {data[\"stats\"][\"total_songs\"]} - {len(all_excluded)} = {data[\"stats\"][\"total_songs\"] - len(all_excluded)}')
assert data['stats']['unique_songs'] == data['stats']['total_songs'] - len(all_excluded), 'Stats mismatch!'
print('Stats OK')
"
```
