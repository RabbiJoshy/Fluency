#!/usr/bin/env python3
"""
Step 4: Fetch English translations from Genius via geniURL.

Reads per-song JSON files from a language subdirectory, queries geniURL for
English translations, scrapes the translation lyrics from Genius, and updates
each song file with an english_translation field.

geniURL rate limit: ~25 requests per 30s, so we throttle to 1.2s between calls.

Usage:
    .venv/bin/python3 research/4_fetch_translations.py \
        --input-dir Artists/french/TestPlaylist/lyrics/french
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests as req_lib
from requests.exceptions import Timeout, HTTPError

from lyricsgenius import Genius

GENIUS_TOKEN = "wYDvwsp9iGyueotPy1BLIbIMfinPKcoxxJZogRDXQjbn13VDBkBZudwAUA8gJnhq"
GENIURL_BASE = "https://api.sv443.net/geniurl/translations"
GENIURL_MIN_INTERVAL = 1.2  # seconds between requests


_last_geniurl_request = 0.0


def _throttle():
    """Enforce minimum interval between geniURL requests."""
    global _last_geniurl_request
    now = time.time()
    wait = GENIURL_MIN_INTERVAL - (now - _last_geniurl_request)
    if wait > 0:
        time.sleep(wait)
    _last_geniurl_request = time.time()


def find_english_translation(song_id):
    """Query geniURL for an English translation of song_id.

    Returns (translation_genius_id, title, url) or None.
    """
    _throttle()
    url = "%s/%s" % (GENIURL_BASE, song_id)
    try:
        resp = req_lib.get(url, timeout=15)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            time.sleep(retry_after)
            resp = req_lib.get(url, timeout=15)

        if resp.status_code >= 400:
            return None

        data = resp.json()
        if data.get("error") or not data.get("translations"):
            return None

        for t in data["translations"]:
            if t.get("language") == "en":
                return (t["id"], t.get("title", ""), t.get("url", ""))
        return None

    except Exception:
        return None


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


def main():
    parser = argparse.ArgumentParser(description="Fetch English translations from Genius via geniURL")
    parser.add_argument("--input-dir", required=True,
                        help="Directory of per-song JSON files (e.g. lyrics/french/)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    files = sorted(p for p in input_dir.glob("*.json") if not p.name.startswith("_"))
    print("Found %d song files in %s" % (len(files), input_dir))

    genius = Genius(GENIUS_TOKEN, timeout=30, retries=3, sleep_time=0.5)
    genius.verbose = False
    genius.remove_section_headers = True

    found = 0
    skipped = 0
    no_translation = 0

    for i, path in enumerate(files, 1):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        song = data[0] if isinstance(data, list) else data

        # Skip if already has a translation
        if song.get("english_translation"):
            skipped += 1
            continue

        song_id = song.get("id")
        title = song.get("title", "")
        artist = song.get("artist", "")

        print("[%d/%d] %s - %s ..." % (i, len(files), artist, title), end=" ", flush=True)

        result = find_english_translation(song_id)
        if result is None:
            print("no translation")
            no_translation += 1
            continue

        trans_id, trans_title, trans_url = result
        print("found -> %s" % trans_title, end=" ", flush=True)

        trans_lyrics = scrape_lyrics(genius, trans_id)
        if not trans_lyrics:
            print("(scrape failed)")
            no_translation += 1
            continue

        song["english_translation"] = {
            "id": trans_id,
            "title": trans_title,
            "url": trans_url,
            "lyrics": trans_lyrics,
        }
        found += 1
        print("OK (%d chars)" % len(trans_lyrics))

        # Write back
        out = [song] if isinstance(data, list) else song
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print("\nDone: %d translations found, %d not available, %d already had translations" % (
        found, no_translation, skipped))


if __name__ == "__main__":
    main()
