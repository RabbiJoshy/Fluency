# Research: Playlist Pipeline

Proof-of-concept for running the vocabulary pipeline on a Spotify playlist (mixed artists) instead of a single artist. Everything here is self-contained and does not touch the main artist pipeline.

## Pipeline Steps

```bash
# 1. Fetch playlist track list from Spotify (needs browser OAuth)
.venv/bin/python3 research/1_fetch_playlist.py \
  --playlist "https://open.spotify.com/playlist/..." \
  --out research/TestPlaylist/tracks.json

# 2. Download lyrics from Genius (parallel, ~1.2 songs/sec, resumable)
.venv/bin/python3 research/2_download_lyrics.py \
  --tracks research/TestPlaylist/tracks.json \
  --out-dir research/TestPlaylist/lyrics

# 3. Filter by language using lingua (instant, moves files into subdirs)
.venv/bin/python3 research/3_filter_language.py \
  --input-dir research/TestPlaylist/lyrics

# 4. Fetch Genius community English translations via geniURL (~1.2s/song)
.venv/bin/python3 research/4_fetch_translations.py \
  --input-dir research/TestPlaylist/lyrics/french

# 5. Google Translate remaining songs without Genius translations (parallel)
.venv/bin/python3 research/5_google_translate.py \
  --input-dir research/TestPlaylist/lyrics/french

# 6. Feed into main pipeline step 3+ (not yet run)
.venv/bin/python3 pipeline/artist/3_count_words.py \
  --artist-dir research/TestPlaylist \
  --batch_glob "research/TestPlaylist/lyrics/french/*.json" \
  --out research/TestPlaylist/vocab_evidence.json
```

## Current State (TestPlaylist)

Playlist: "An Evening at 870 JVG" (215 tracks, Josh's personal playlist)

- **tracks.json**: 215 tracks fetched from Spotify
- **lyrics/**: 185 songs downloaded from Genius (30 missed — mostly instrumentals/remixes)
- **Language split**: 79 English, 64 French, 22 Spanish, 5 Hungarian, 4 Dutch, misc others
- **Translations**: All 64 French songs had Genius community translations (unusually high hit rate)
- **Next**: Run step 3 (word counting) on French songs, then continue pipeline

## Data Format

Each song is a single JSON file: `lyrics/{language}/{Title - Artist}.json`

```json
[{
  "id": 12345,
  "title": "Song Title",
  "artist": "Artist Name",
  "url": "https://genius.com/...",
  "lyrics": "Full lyrics text...",
  "english_translation": {
    "id": 67890,
    "title": "Song Title (English Translation)",
    "url": "https://genius.com/...",
    "lyrics": "English translation text...",
    "source": "genius"
  }
}]
```

Wrapped in a list for compatibility with `3_count_words.py --batch_glob`.

## Known Limitations

- **Spotify API (Feb 2026)**: Dev mode apps must use `/items` not `/tracks`, and need user OAuth (PKCE) — client credentials can't read playlist tracks anymore
- **Corpus size**: French songs average ~200 words each (vs ~350 for Bad Bunny). 64 songs may not be enough for a rich vocabulary deck. Consider adding a dedicated French artist or bigger playlist.
- **No dedup**: No `duplicate_songs.json` equivalent yet. Playlists shouldn't need it since songs are hand-picked, but remixes could slip through.

## Dependencies

All already installed in .venv:
- `lyricsgenius` — Genius API
- `lingua-language-detector` — language classification
- `deep_translator` — Google Translate (free tier)
- `requests` — HTTP (used by geniURL + deep_translator)
