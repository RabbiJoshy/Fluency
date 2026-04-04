#!/usr/bin/env python3
"""
Scrape community-contributed English translations from Genius.

For each song in the artist's batches, queries the geniURL API to check if
an English translation exists on Genius.  If found, scrapes the translation
lyrics using lyricsgenius (same technique as step 1).

Output: <artist-dir>/data/input/translations/translations.json
Progress: <artist-dir>/data/input/translations/done_song_ids.json

Usage (from project root):
    .venv/bin/python3 Artists/scripts/1b_scrape_translations.py --artist-dir "Artists/Bad Bunny"
"""

TOKEN = "wYDvwsp9iGyueotPy1BLIbIMfinPKcoxxJZogRDXQjbn13VDBkBZudwAUA8gJnhq"

GENIURL_BASE = "https://api.sv443.net/geniurl/translations"

# geniURL allows 25 requests per 30 seconds.  We stay comfortably under.
GENIURL_RATE_DELAY = 1.3          # seconds between geniURL requests
GENIUS_SCRAPE_DELAY = 1.0         # seconds between Genius lyric scrapes

import argparse
import json
import os
import glob
import time
import sys

import requests
from lyricsgenius import Genius
from requests.exceptions import Timeout, HTTPError

# -- artist config helper --------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _artist_config import add_artist_arg, load_artist_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_all_song_ids(artist_dir):
    """Load every song record from batch_*.json files.  Returns list of dicts."""
    batch_dir = os.path.join(artist_dir, "data", "input", "batches")
    songs = []
    for path in sorted(glob.glob(os.path.join(batch_dir, "batch_*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            songs.extend(json.load(f))
    return songs


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def load_done_ids(trans_dir):
    path = os.path.join(trans_dir, "done_song_ids.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_done_ids(done_ids, trans_dir):
    path = os.path.join(trans_dir, "done_song_ids.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(done_ids), f, indent=2)


def load_translations(trans_dir):
    path = os.path.join(trans_dir, "translations.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_translations(translations, trans_dir):
    path = os.path.join(trans_dir, "translations.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(translations, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# geniURL: find English translation ID
# ---------------------------------------------------------------------------

def find_english_translation(song_id):
    """Query geniURL for an English translation of song_id.

    Returns (translation_genius_id, title, url) or None.
    """
    url = "%s/%s" % (GENIURL_BASE, song_id)
    try:
        resp = requests.get(url, timeout=15)

        # Rate-limited — honour Retry-After header
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            print("  Rate-limited by geniURL, waiting %ds..." % retry_after)
            time.sleep(retry_after)
            resp = requests.get(url, timeout=15)

        data = resp.json()
        if data.get("error") or not data.get("translations"):
            return None

        for t in data["translations"]:
            if t.get("language") == "en":
                return (t["id"], t.get("title", ""), t.get("url", ""))
        return None

    except Exception as e:
        print("  geniURL error for song %s: %s" % (song_id, e))
        return None


# ---------------------------------------------------------------------------
# Genius: scrape translation lyrics by ID
# ---------------------------------------------------------------------------

def scrape_lyrics_by_id(genius_client, song_id, max_tries=5):
    """Scrape lyrics from Genius by song ID with exponential backoff."""
    delay = 2
    for attempt in range(1, max_tries + 1):
        try:
            lyrics = genius_client.lyrics(song_id=song_id)
            return lyrics
        except (Timeout, HTTPError) as e:
            if attempt == max_tries:
                print("    Scrape failed after %d attempts: %s" % (max_tries, e))
                return None
            time.sleep(delay)
            delay *= 2
        except Exception as e:
            print("    Unexpected scrape error for %d: %s" % (song_id, e))
            return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape English translations from Genius for an artist's songs."
    )
    add_artist_arg(parser)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only query geniURL for translation availability, don't scrape lyrics."
    )
    args = parser.parse_args()

    artist_dir = args.artist_dir
    config = load_artist_config(artist_dir)
    artist_name = config["name"]

    trans_dir = os.path.join(artist_dir, "data", "input", "translations")
    ensure_dir(trans_dir)

    # Load state
    songs = load_all_song_ids(artist_dir)
    done_ids = load_done_ids(trans_dir)
    translations = load_translations(trans_dir)

    # Deduplicate song IDs (same song can appear in multiple batches)
    seen_ids = set()
    unique_songs = []
    for s in songs:
        sid = s["id"]
        if sid not in seen_ids:
            seen_ids.add(sid)
            unique_songs.append(s)

    total = len(unique_songs)
    remaining = [s for s in unique_songs if s["id"] not in done_ids]

    print("Artist: %s" % artist_name)
    print("Total unique songs: %d" % total)
    print("Already checked: %d" % (total - len(remaining)))
    print("Remaining to check: %d" % len(remaining))
    print("Translations found so far: %d" % len(translations))
    print()

    if not remaining:
        print("All songs already checked.")
        print_summary(translations, total)
        return

    # Set up Genius client for lyric scraping
    genius = Genius(TOKEN, timeout=30, retries=3, sleep_time=GENIUS_SCRAPE_DELAY)
    genius.verbose = False
    genius.remove_section_headers = False

    found_count = 0
    no_translation_count = 0
    error_count = 0

    for i, song in enumerate(remaining):
        song_id = song["id"]
        title = song.get("title", "???")

        print("[%d/%d] Checking: %s (id=%d)" % (
            i + 1, len(remaining), title, song_id
        ))

        # Step 1: query geniURL
        result = find_english_translation(song_id)
        time.sleep(GENIURL_RATE_DELAY)

        if result is None:
            no_translation_count += 1
            done_ids.add(song_id)
            save_done_ids(done_ids, trans_dir)
            continue

        trans_id, trans_title, trans_url = result
        print("  Found English translation: %s (id=%d)" % (trans_title, trans_id))

        if args.dry_run:
            # In dry-run mode, record the translation metadata but skip scraping
            translations[str(song_id)] = {
                "song_title": title,
                "translation_id": trans_id,
                "translation_title": trans_title,
                "translation_url": trans_url,
                "lyrics": None,
            }
            found_count += 1
            done_ids.add(song_id)
            save_done_ids(done_ids, trans_dir)
            save_translations(translations, trans_dir)
            continue

        # Step 2: scrape translation lyrics from Genius
        lyrics = scrape_lyrics_by_id(genius, trans_id)

        if lyrics:
            translations[str(song_id)] = {
                "song_title": title,
                "translation_id": trans_id,
                "translation_title": trans_title,
                "translation_url": trans_url,
                "lyrics": lyrics,
            }
            found_count += 1
            print("  Scraped %d chars of translation" % len(lyrics))
        else:
            # Translation page exists but scrape failed — record without lyrics
            translations[str(song_id)] = {
                "song_title": title,
                "translation_id": trans_id,
                "translation_title": trans_title,
                "translation_url": trans_url,
                "lyrics": None,
            }
            error_count += 1
            print("  WARNING: translation exists but scrape failed")

        done_ids.add(song_id)
        save_done_ids(done_ids, trans_dir)
        save_translations(translations, trans_dir)

    print()
    print("--- Session complete ---")
    print("Checked: %d" % len(remaining))
    print("Found translations: %d" % found_count)
    print("No translation: %d" % no_translation_count)
    print("Scrape errors: %d" % error_count)
    print()
    print_summary(translations, total)


def print_summary(translations, total_songs):
    """Print overall summary of translation coverage."""
    with_lyrics = sum(1 for t in translations.values() if t.get("lyrics"))
    without_lyrics = sum(1 for t in translations.values() if not t.get("lyrics"))
    print("=== Translation Coverage ===")
    print("Total songs: %d" % total_songs)
    print("Songs with English translation: %d (%.1f%%)" % (
        len(translations),
        100.0 * len(translations) / total_songs if total_songs else 0,
    ))
    print("  With scraped lyrics: %d" % with_lyrics)
    print("  Missing lyrics (scrape failed): %d" % without_lyrics)


if __name__ == "__main__":
    main()
