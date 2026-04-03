#!/usr/bin/env python3
"""
Targeted rescrape of songs with null/empty lyrics.

Reads existing batch files, identifies songs with missing lyrics,
re-scrapes them using genius.lyrics(song_id), and updates the batch
files in-place.

Also supports scraping specific song IDs that aren't in any batch file
(e.g. remixes that were previously excluded).

Usage (from project root):
    # Re-scrape all null-lyrics songs
    .venv/bin/python3 "Bad Bunny/scripts/2_rescrape_nulls.py"

    # Dry run — show what would be re-scraped
    .venv/bin/python3 "Bad Bunny/scripts/2_rescrape_nulls.py" --dry-run

    # Only re-scrape non-variant songs (skip remixes/live)
    .venv/bin/python3 "Bad Bunny/scripts/2_rescrape_nulls.py" --skip-variants

    # Also scrape specific song IDs (adds to a new batch file)
    .venv/bin/python3 "Bad Bunny/scripts/2_rescrape_nulls.py" --add-ids 12345 67890
"""

TOKEN = "wYDvwsp9iGyueotPy1BLIbIMfinPKcoxxJZogRDXQjbn13VDBkBZudwAUA8gJnhq"

import argparse
import glob
import json
import os
import re
import time
from typing import Dict, List, Optional, Set, Tuple

from requests.exceptions import Timeout, HTTPError
from lyricsgenius import Genius

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.dirname(SCRIPT_DIR)  # scripts/ -> Bad Bunny/
BATCH_GLOB = os.path.join(PIPELINE_DIR, "data", "input", "batch_*.json")
OUT_DIR = os.path.join(PIPELINE_DIR, "data", "input")

VARIANT_RE = re.compile(
    r"(remix|live|concert|acoustic|versión|version|mixed|headphone|en vivo|primera)",
    re.IGNORECASE,
)


def make_genius():
    """Create a Genius client for lyrics scraping."""
    g = Genius(
        TOKEN,
        timeout=30,
        retries=3,
        sleep_time=1.0,
    )
    g.verbose = False
    g.remove_section_headers = True
    return g


def scrape_lyrics_by_id(genius_client, song_id, max_tries=5):
    """Scrape lyrics using song ID directly (more reliable than title search)."""
    delay = 2
    for attempt in range(1, max_tries + 1):
        try:
            lyrics = genius_client.lyrics(song_id=song_id)
            return lyrics
        except (Timeout, HTTPError) as e:
            if attempt == max_tries:
                print("    Failed after %d attempts: %s" % (max_tries, e))
                return None
            time.sleep(delay)
            delay *= 2
        except Exception as e:
            print("    Unexpected error scraping %d: %s" % (song_id, e))
            return None


def load_all_batches():
    # type: () -> List[Tuple[str, List[Dict]]]
    """Load all batch files. Returns [(path, songs), ...]."""
    batches = []
    for path in sorted(glob.glob(BATCH_GLOB)):
        with open(path, "r", encoding="utf-8") as f:
            songs = json.load(f)
        batches.append((path, songs))
    return batches


def find_null_lyrics(batches, skip_variants=False):
    # type: (List[Tuple[str, List[Dict]]], bool) -> List[Tuple[str, int, Dict]]
    """Find songs with null/empty lyrics. Returns [(batch_path, index, song), ...]."""
    results = []
    for path, songs in batches:
        for i, song in enumerate(songs):
            if song.get("lyrics"):
                continue
            if skip_variants and VARIANT_RE.search(song.get("title", "")):
                continue
            results.append((path, i, song))
    return results


def fetch_song_metadata(genius_client, song_id):
    """Fetch song metadata from Genius API."""
    try:
        data = genius_client.song(song_id)
        if data and "song" in data:
            s = data["song"]
            return {
                "id": s.get("id", song_id),
                "title": s.get("title", ""),
                "artist": s.get("primary_artist", {}).get("name", "Bad Bunny"),
                "url": s.get("url", ""),
            }
    except Exception as e:
        print("    Could not fetch metadata for %d: %s" % (song_id, e))
    return None


def main():
    parser = argparse.ArgumentParser(description="Re-scrape songs with null lyrics")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be re-scraped without doing it")
    parser.add_argument("--skip-variants", action="store_true",
                        help="Skip songs with remix/live/etc. in the title")
    parser.add_argument("--add-ids", type=int, nargs="*", default=[],
                        help="Additional song IDs to scrape (not in any batch)")
    args = parser.parse_args()

    print("Loading batch files...")
    batches = load_all_batches()
    total_songs = sum(len(songs) for _, songs in batches)
    print("  %d batch files, %d total songs" % (len(batches), total_songs))

    # Find null-lyrics songs
    nulls = find_null_lyrics(batches, skip_variants=args.skip_variants)
    print("  %d songs with null lyrics%s" % (
        len(nulls),
        " (excluding variants)" if args.skip_variants else "",
    ))

    if not nulls and not args.add_ids:
        print("Nothing to re-scrape!")
        return

    # Show what we'll scrape
    print("\n=== Songs to re-scrape ===")
    for path, idx, song in nulls:
        batch_name = os.path.basename(path)
        is_variant = "  [variant]" if VARIANT_RE.search(song.get("title", "")) else ""
        print("  %8d  %-50s  %s%s" % (
            song["id"], song.get("title", "?")[:50], batch_name, is_variant,
        ))

    if args.add_ids:
        # Check which IDs are already in batches
        existing_ids = set()
        for _, songs in batches:
            for s in songs:
                existing_ids.add(s["id"])
        new_ids = [sid for sid in args.add_ids if sid not in existing_ids]
        already = [sid for sid in args.add_ids if sid in existing_ids]
        if already:
            print("\n  %d IDs already in batches (skipping): %s" % (
                len(already), ", ".join(str(x) for x in already)))
        if new_ids:
            print("\n  %d new IDs to add: %s" % (
                len(new_ids), ", ".join(str(x) for x in new_ids)))

    if args.dry_run:
        print("\n[DRY RUN] No changes made.")
        return

    # Scrape!
    genius_client = make_genius()
    success = 0
    failed = 0
    modified_files = set()  # type: Set[str]

    print("\nScraping lyrics...")
    for path, idx, song in nulls:
        song_id = song["id"]
        title = song.get("title", "?")
        print("  %d: %s..." % (song_id, title[:50]))

        lyrics = scrape_lyrics_by_id(genius_client, song_id)
        if lyrics and len(lyrics.strip()) > 10:
            # Update in-place
            with open(path, "r", encoding="utf-8") as f:
                batch_data = json.load(f)
            batch_data[idx]["lyrics"] = lyrics
            with open(path, "w", encoding="utf-8") as f:
                json.dump(batch_data, f, ensure_ascii=False, indent=2)
            modified_files.add(path)
            success += 1
            print("    OK (%d chars)" % len(lyrics))
        else:
            failed += 1
            print("    No lyrics found")

    # Handle --add-ids (new songs not in any batch)
    if args.add_ids:
        existing_ids = set()
        for _, songs in batches:
            for s in songs:
                existing_ids.add(s["id"])

        new_ids = [sid for sid in args.add_ids if sid not in existing_ids]
        if new_ids:
            print("\nFetching metadata and lyrics for %d new songs..." % len(new_ids))
            new_songs = []
            for song_id in new_ids:
                print("  %d..." % song_id)
                meta = fetch_song_metadata(genius_client, song_id)
                if not meta:
                    print("    Could not fetch metadata, skipping")
                    failed += 1
                    continue

                lyrics = scrape_lyrics_by_id(genius_client, song_id)
                meta["lyrics"] = lyrics
                new_songs.append(meta)

                if lyrics and len(lyrics.strip()) > 10:
                    success += 1
                    print("    OK: %s (%d chars)" % (meta["title"], len(lyrics)))
                else:
                    failed += 1
                    print("    %s — no lyrics found" % meta["title"])

            if new_songs:
                # Find the next batch number
                existing_batches = sorted(glob.glob(BATCH_GLOB))
                next_num = len(existing_batches) + 1
                new_batch_path = os.path.join(OUT_DIR, "batch_%03d_rescrape.json" % next_num)
                with open(new_batch_path, "w", encoding="utf-8") as f:
                    json.dump(new_songs, f, ensure_ascii=False, indent=2)
                print("  Wrote %d songs to %s" % (len(new_songs), new_batch_path))

    # Summary
    print("\n=== Summary ===")
    print("  Lyrics found: %d" % success)
    print("  Still missing: %d" % failed)
    if modified_files:
        print("  Modified files: %d" % len(modified_files))
        for f in sorted(modified_files):
            print("    %s" % os.path.basename(f))


if __name__ == "__main__":
    main()
