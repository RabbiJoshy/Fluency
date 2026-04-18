#!/usr/bin/env python3
"""
Step 2: Download lyrics from Genius for a tracks.json file.

Reads the track list produced by 1_fetch_playlist.py, searches Genius for each,
and writes one JSON file per song into a lyrics/ directory. Filenames are
sanitized from the song title (e.g. "Despacito - Luis Fonsi.json").

Resumable: skips songs that already have a file.
Parallel: uses a thread pool (default 5 workers) for speed.

Usage:
    .venv/bin/python3 research/2_download_lyrics.py \
        --tracks Artists/french/TestPlaylist/tracks.json \
        --out-dir Artists/french/TestPlaylist/lyrics

    # Adjust parallelism:
    .venv/bin/python3 research/2_download_lyrics.py \
        --tracks Artists/french/TestPlaylist/tracks.json \
        --out-dir Artists/french/TestPlaylist/lyrics \
        --workers 8
"""

import argparse
import json
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from requests.exceptions import Timeout, HTTPError

from lyricsgenius import Genius

GENIUS_TOKEN = "wYDvwsp9iGyueotPy1BLIbIMfinPKcoxxJZogRDXQjbn13VDBkBZudwAUA8gJnhq"

# Thread-local storage so each worker gets its own Genius client
_local = threading.local()


def _get_genius():
    """Return a per-thread Genius client."""
    if not hasattr(_local, "genius"):
        _local.genius = Genius(GENIUS_TOKEN, timeout=30, retries=3, sleep_time=0.2)
        _local.genius.verbose = False
        _local.genius.remove_section_headers = True
    return _local.genius


def scrape_lyrics(genius_client, song_id, max_tries=5):
    """Scrape lyrics from Genius by song ID with exponential backoff."""
    delay = 2
    for attempt in range(1, max_tries + 1):
        try:
            return genius_client.lyrics(song_id=song_id)
        except (Timeout, HTTPError) as e:
            if attempt == max_tries:
                return None
            time.sleep(delay)
            delay *= 2
        except Exception:
            return None


def safe_filename(title, artist):
    """Turn 'Song Title' + 'Artist Name' into a safe filename."""
    name = "%s - %s" % (title, artist)
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 200:
        name = name[:200]
    return name + ".json"


def download_one(track, out_dir):
    """Download lyrics for a single track. Returns (title, artist, status)."""
    title = track["title"]
    artist = track["artist"]
    filename = safe_filename(title, artist)

    genius = _get_genius()
    song = genius.search_song(title, artist)
    if not song:
        return (title, artist, "MISS")

    lyrics = scrape_lyrics(genius, song.id)
    if not lyrics:
        return (title, artist, "NO_LYRICS")

    song_data = {
        "id": song.id,
        "title": title,
        "artist": artist,
        "url": song.url,
        "lyrics": lyrics,
    }
    # Wrap in a list so step 3's batch glob can read it directly
    (out_dir / filename).write_text(json.dumps([song_data], ensure_ascii=False, indent=2))
    return (title, artist, "OK:%d" % len(lyrics))


def main():
    parser = argparse.ArgumentParser(description="Download lyrics from Genius for a track list")
    parser.add_argument("--tracks", required=True, help="Path to tracks.json from 1_fetch_playlist.py")
    parser.add_argument("--out-dir", required=True, help="Output directory for per-song JSON files")
    parser.add_argument("--workers", type=int, default=5, help="Number of parallel workers (default: 5)")
    args = parser.parse_args()

    with open(args.tracks, "r", encoding="utf-8") as f:
        data = json.load(f)
    track_list = data.get("tracks", [])
    print("Loaded %d tracks from %s" % (len(track_list), args.tracks))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Filter out already-downloaded tracks
    existing = set(p.name for p in out_dir.glob("*.json") if not p.name.startswith("_"))
    todo = []
    for track in track_list:
        filename = safe_filename(track["title"], track["artist"])
        if filename not in existing:
            todo.append(track)

    print("Skipping %d already downloaded, %d to fetch (%d workers)" % (
        len(track_list) - len(todo), len(todo), args.workers))

    if not todo:
        print("Nothing to do!")
        return

    missed = []
    ok_count = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download_one, track, out_dir): track for track in todo}
        for i, future in enumerate(as_completed(futures), 1):
            title, artist, status = future.result()
            if status.startswith("OK"):
                ok_count += 1
                print("[%d/%d] OK  %s - %s (%s chars)" % (
                    i, len(todo), artist, title, status.split(":")[1]))
            else:
                missed.append(futures[future])
                print("[%d/%d] %-4s %s - %s" % (i, len(todo), status, artist, title))

    elapsed = time.time() - start
    print("\nDone in %.0fs: %d downloaded, %d missed (%.1f songs/sec)" % (
        elapsed, ok_count, len(missed), ok_count / elapsed if elapsed > 0 else 0))

    if missed:
        print("Missed: %s" % ", ".join(
            "%s - %s" % (t["artist"], t["title"]) for t in missed[:10]))
        (out_dir / "_missed.json").write_text(json.dumps(missed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
