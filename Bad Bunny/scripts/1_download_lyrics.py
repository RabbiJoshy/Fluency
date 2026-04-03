#!/usr/bin/env python3
"""
Download Bad Bunny lyrics from Genius API.

Fetches all songs for an artist in batches, using the Genius API for metadata
and direct song-ID scraping for lyrics (more reliable than title-based search).

Supports:
  --include-remixes    Also fetch songs with Remix/Live/etc. in the title
  --retry-nulls        Re-attempt songs that previously got null lyrics
  --start-page N       Resume from a specific page

Output: data/input/batch_NNN_page_N.json

Usage (from project root):
    .venv/bin/python3 "Bad Bunny/scripts/1_download_lyrics.py"
    .venv/bin/python3 "Bad Bunny/scripts/1_download_lyrics.py" --include-remixes
    .venv/bin/python3 "Bad Bunny/scripts/1_download_lyrics.py" --retry-nulls
"""

TOKEN = "wYDvwsp9iGyueotPy1BLIbIMfinPKcoxxJZogRDXQjbn13VDBkBZudwAUA8gJnhq"

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any, Set, List

from requests.exceptions import Timeout, HTTPError
from lyricsgenius import Genius

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------

ARTIST_QUERY = "Bad Bunny"
BATCH_SIZE = 25

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.dirname(SCRIPT_DIR)  # scripts/ -> Bad Bunny/
OUT_DIR = os.path.join(PIPELINE_DIR, "data", "input")

# Terms that indicate a variant (remix, live, etc.)
VARIANT_TERMS = [
    "(Remix)", "(Live)", "(Concert)", "(Version)", "(Acoustic)",
    "Tracklist", "Credits", "Romanized", "Translation",
]

# Non-song markers to always exclude
ALWAYS_EXCLUDED = [
    "Tracklist", "Credits", "Romanized", "Translation",
]

# ---------------------------------------------------------------------
# GENIUS CLIENT
# ---------------------------------------------------------------------

def make_genius(excluded_terms):
    """Create a Genius client with the specified excluded terms."""
    g = Genius(
        TOKEN,
        timeout=30,
        retries=3,
        sleep_time=1.0,
    )
    g.verbose = True
    g.remove_section_headers = True
    g.skip_non_songs = True
    g.excluded_terms = excluded_terms
    return g


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------

def load_done_ids(progress_path):
    # type: (Path) -> Set[int]
    if progress_path.exists():
        return set(json.loads(progress_path.read_text()))
    return set()


def save_done_ids(progress_path, done_ids):
    # type: (Path, Set[int]) -> None
    progress_path.write_text(json.dumps(sorted(done_ids), indent=2))


def fetch_batch_song_metas(genius_client, artist_id, page, per_page=25):
    """Returns (songs, next_page) using Genius API's artist_songs endpoint."""
    res = genius_client.artist_songs(artist_id, per_page=per_page, page=page, sort="popularity")
    return res.get("songs", []), res.get("next_page")


def scrape_lyrics_by_id(genius_client, song_id, max_tries=5):
    """
    Scrape lyrics using the song ID directly.
    More reliable than search_song() which re-searches by title and can
    return the wrong song.
    """
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


def song_meta_to_record(meta, lyrics):
    # type: (Dict, Optional[str]) -> Dict[str, Any]
    """Build a JSON-serializable record from song metadata + scraped lyrics."""
    return {
        "id": meta["id"],
        "title": meta.get("title", ""),
        "artist": meta.get("primary_artist", {}).get("name", ARTIST_QUERY),
        "url": meta.get("url", ""),
        "lyrics": lyrics,
    }


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------

def download_artist_lyrics(artist_query, batch_size=25, start_page=1,
                           include_remixes=False, retry_nulls=False):
    """Download all lyrics for an artist."""

    # Set up excluded terms based on flags
    if include_remixes:
        excluded = ALWAYS_EXCLUDED
        print("Including remixes/variants (only excluding: %s)" % ", ".join(ALWAYS_EXCLUDED))
    else:
        excluded = VARIANT_TERMS
        print("Excluding variants: %s" % ", ".join(VARIANT_TERMS))

    genius_client = make_genius(excluded)

    # Resolve artist
    artist_stub = genius_client.search_artist(artist_query, max_songs=1)
    if not artist_stub:
        raise RuntimeError("Could not resolve artist: %s" % artist_query)

    artist_id = artist_stub.id
    artist_name = artist_stub.name
    print("Artist: %s (ID: %d)" % (artist_name, artist_id))

    out_dir = Path(OUT_DIR)
    out_dir.mkdir(exist_ok=True)

    progress_path = out_dir / "done_song_ids.json"
    done_ids = load_done_ids(progress_path)
    print("Already scraped: %d songs" % len(done_ids))

    # If retry_nulls, load existing batches to find null-lyrics songs
    null_retry_ids = set()  # type: Set[int]
    if retry_nulls:
        null_retry_ids = find_null_lyrics_songs(out_dir)
        # Remove these from done_ids so they get re-fetched
        overlap = done_ids & null_retry_ids
        if overlap:
            done_ids -= overlap
            save_done_ids(progress_path, done_ids)
            print("Re-queued %d songs with null lyrics for retry" % len(overlap))
        else:
            print("No null-lyrics songs found to retry")

    page = start_page
    batch_num = 1
    total_new = 0

    while page:
        metas, next_page = fetch_batch_song_metas(genius_client, artist_id,
                                                   page=page, per_page=batch_size)

        # Filter out already-done songs
        metas = [m for m in metas if m.get("id") not in done_ids]

        if not metas:
            page = next_page
            continue

        batch = []
        for m in metas:
            song_id = m["id"]
            title = m.get("title", "")

            print("  Scraping: %s (ID: %d)..." % (title, song_id))
            lyrics = scrape_lyrics_by_id(genius_client, song_id)

            rec = song_meta_to_record(m, lyrics)
            batch.append(rec)
            total_new += 1

            done_ids.add(song_id)
            save_done_ids(progress_path, done_ids)

        batch_file = out_dir / ("batch_%03d_page_%d.json" % (batch_num, page))
        batch_file.write_text(json.dumps(batch, ensure_ascii=False, indent=2))
        print("Saved %d songs -> %s" % (len(batch), batch_file))

        batch_num += 1
        page = next_page

    print("\nDone! Scraped %d new songs." % total_new)


def find_null_lyrics_songs(out_dir):
    # type: (Path) -> Set[int]
    """Find song IDs with null/empty lyrics in existing batch files."""
    import glob
    null_ids = set()
    for path in sorted(glob.glob(str(out_dir / "batch_*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            batch = json.load(f)
        for song in batch:
            if not song.get("lyrics"):
                null_ids.add(song["id"])
    return null_ids


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download artist lyrics from Genius")
    parser.add_argument("--include-remixes", action="store_true",
                        help="Also fetch remixes, live versions, etc.")
    parser.add_argument("--retry-nulls", action="store_true",
                        help="Re-attempt songs that previously got null lyrics")
    parser.add_argument("--start-page", type=int, default=1,
                        help="Start from this page (default: 1)")
    args = parser.parse_args()

    download_artist_lyrics(
        ARTIST_QUERY,
        batch_size=BATCH_SIZE,
        start_page=args.start_page,
        include_remixes=args.include_remixes,
        retry_nulls=args.retry_nulls,
    )
