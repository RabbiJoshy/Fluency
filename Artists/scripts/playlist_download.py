#!/usr/bin/env python3
"""
Proof-of-concept: download lyrics for a hardcoded list of songs (mixed artists).

Demonstrates that the pipeline works with playlist-style input (multiple artists)
instead of single-artist catalog scraping.

Usage:
    .venv/bin/python3 Artists/scripts/playlist_download.py --artist-dir Artists/TestPlaylist
"""

import argparse
import json
import os
from pathlib import Path

from lyricsgenius import Genius
from _artist_config import add_artist_arg, scrape_lyrics_by_id

TOKEN = "wYDvwsp9iGyueotPy1BLIbIMfinPKcoxxJZogRDXQjbn13VDBkBZudwAUA8gJnhq"

# (song_title, artist_name)
PLAYLIST = [
    ("Despacito", "Luis Fonsi"),
    ("Waka Waka", "Shakira"),
    ("Vivir Mi Vida", "Marc Anthony"),
]


def main():
    parser = argparse.ArgumentParser(description="Download lyrics for a playlist of songs")
    add_artist_arg(parser)
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    out_dir = Path(artist_dir) / "data" / "input" / "batches"
    out_dir.mkdir(parents=True, exist_ok=True)

    genius = Genius(TOKEN, timeout=30, retries=3, sleep_time=1.0)
    genius.verbose = False
    genius.remove_section_headers = True

    batch = []
    for title, artist in PLAYLIST:
        print("Searching: %s - %s ..." % (artist, title))
        song = genius.search_song(title, artist)
        if not song:
            print("  MISS: could not find on Genius")
            continue

        print("  Found: %s (ID: %d)" % (song.title, song.id))
        lyrics = scrape_lyrics_by_id(genius, song.id)
        if not lyrics:
            print("  No lyrics scraped")
            continue

        batch.append({
            "id": song.id,
            "title": title,
            "artist": artist,
            "url": song.url,
            "lyrics": lyrics,
        })
        print("  OK (%d chars)" % len(lyrics))

    out_path = out_dir / "batch_001.json"
    out_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2))
    print("\nWrote %d songs -> %s" % (len(batch), out_path))


if __name__ == "__main__":
    main()
