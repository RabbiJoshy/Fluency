#!/usr/bin/env python3
"""
Scrape community-contributed English translations from Genius.

For each song in the artist's batches, queries the geniURL API to check if
an English translation exists on Genius.  If found, scrapes the translation
lyrics using lyricsgenius (same technique as step 1).

Output: <artist-dir>/data/input/translations/translations.json
Progress: <artist-dir>/data/input/translations/done_song_ids.json

Usage (from project root):
    .venv/bin/python3 Artists/scripts/3b_scrape_translations.py --artist-dir "Artists/Bad Bunny"
    .venv/bin/python3 Artists/scripts/3b_scrape_translations.py --artist-dir "Artists/Bad Bunny" --workers 8
"""

TOKEN = "wYDvwsp9iGyueotPy1BLIbIMfinPKcoxxJZogRDXQjbn13VDBkBZudwAUA8gJnhq"

GENIURL_BASE = "https://api.sv443.net/geniurl/translations"

# geniURL: 25 requests per 30 seconds = ~0.83 per request minimum.
# We use a semaphore to enforce this across parallel workers.
GENIURL_MIN_INTERVAL = 1.2        # seconds between geniURL requests (global)
GENIUS_SCRAPE_DELAY = 0.1         # lyricsgenius sleep_time (per-client)

import argparse
import json
import os
import glob
import time
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from lyricsgenius import Genius
from requests.exceptions import Timeout, HTTPError

# -- artist config helper --------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _artist_config import add_artist_arg, load_artist_config, scrape_lyrics_by_id, load_done_ids, save_done_ids


# ---------------------------------------------------------------------------
# ETA helper
# ---------------------------------------------------------------------------

def format_eta(seconds):
    """Format seconds into a human-readable string."""
    if seconds < 60:
        return "%ds" % seconds
    elif seconds < 3600:
        return "%dm%02ds" % (seconds // 60, seconds % 60)
    else:
        return "%dh%02dm" % (seconds // 3600, (seconds % 3600) // 60)


class ETATracker(object):
    """Track progress and estimate time remaining."""

    def __init__(self, total):
        self.total = total
        self.done = 0
        self.start_time = time.time()
        self.lock = threading.Lock()

    def tick(self):
        with self.lock:
            self.done += 1
            return self.done

    def eta_str(self):
        with self.lock:
            done = self.done
        if done == 0:
            return "estimating..."
        elapsed = time.time() - self.start_time
        rate = done / elapsed
        remaining = self.total - done
        eta_secs = remaining / rate
        return "%s left" % format_eta(int(eta_secs))

    def progress_str(self):
        with self.lock:
            done = self.done
        pct = 100.0 * done / self.total if self.total else 0
        return "[%d/%d %.0f%%]" % (done, self.total, pct)


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
# Rate-limited geniURL requests
# ---------------------------------------------------------------------------

_geniurl_lock = threading.Lock()
_geniurl_last_request = 0.0


def _geniurl_throttle():
    """Enforce minimum interval between geniURL requests across all threads."""
    global _geniurl_last_request
    with _geniurl_lock:
        now = time.time()
        wait = GENIURL_MIN_INTERVAL - (now - _geniurl_last_request)
        if wait > 0:
            time.sleep(wait)
        _geniurl_last_request = time.time()


def find_english_translation(song_id):
    """Query geniURL for an English translation of song_id.

    Returns (translation_genius_id, title, url) or None.
    Thread-safe: uses global rate limiter.
    """
    _geniurl_throttle()
    url = "%s/%s" % (GENIURL_BASE, song_id)
    try:
        resp = requests.get(url, timeout=15)

        # Rate-limited — honour Retry-After header
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            print("  Rate-limited by geniURL, waiting %ds..." % retry_after)
            time.sleep(retry_after)
            resp = requests.get(url, timeout=15)

        if resp.status_code >= 400:
            return None

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


def make_genius_client():
    """Create a Genius client instance (one per thread for thread safety)."""
    g = Genius(TOKEN, timeout=30, retries=3, sleep_time=GENIUS_SCRAPE_DELAY)
    g.verbose = False
    g.remove_section_headers = False
    return g


# ---------------------------------------------------------------------------
# Worker functions for thread pool
# ---------------------------------------------------------------------------

def scrape_one_translation(item):
    """Scrape a single translation.  Called from thread pool.

    item: (song_id_str, translation_dict)
    Returns: (song_id_str, lyrics_or_None)
    """
    sid, t = item
    genius = make_genius_client()
    lyrics = scrape_lyrics_by_id(genius, t["translation_id"])
    return (sid, lyrics)


def check_and_scrape_one(song, dry_run):
    """Full pipeline for one song: geniURL check + Genius scrape.

    Returns: (song_id, title, result_dict_or_None)
    """
    song_id = song["id"]
    title = song.get("title", "???")

    result = find_english_translation(song_id)
    if result is None:
        return (song_id, title, None)

    trans_id, trans_title, trans_url = result

    entry = {
        "song_title": title,
        "translation_id": trans_id,
        "translation_title": trans_title,
        "translation_url": trans_url,
        "lyrics": None,
    }

    if dry_run:
        return (song_id, title, entry)

    # Scrape immediately in the same worker
    genius = make_genius_client()
    lyrics = scrape_lyrics_by_id(genius, trans_id)
    entry["lyrics"] = lyrics
    return (song_id, title, entry)


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
    parser.add_argument(
        "--scrape-missing", action="store_true",
        help="Scrape lyrics for translations already found but with null lyrics "
             "(e.g. after a --dry-run)."
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="Number of parallel workers (default: 8)."
    )
    parser.add_argument(
        "--align", action="store_true",
        help="Align Spanish lyrics with English translations line by line. "
             "Outputs aligned_translations.json for inspection and use by step 6."
    )
    args = parser.parse_args()

    artist_dir = args.artist_dir
    config = load_artist_config(artist_dir)
    artist_name = config["name"]
    num_workers = args.workers

    # --align: just run alignment on existing translations and exit
    if args.align:
        run_alignment(artist_dir)
        return

    trans_dir = os.path.join(artist_dir, "data", "input", "translations")
    ensure_dir(trans_dir)

    # Load state
    songs = load_all_song_ids(artist_dir)
    done_ids_path = os.path.join(trans_dir, "done_song_ids.json")
    done_ids = load_done_ids(done_ids_path)
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
    print("Workers: %d" % num_workers)
    print()

    # --scrape-missing: scrape lyrics for entries that have translation metadata
    # but null lyrics (e.g. after a --dry-run).
    if args.scrape_missing:
        missing = {sid: t for sid, t in translations.items()
                   if t.get("translation_id") and not t.get("lyrics")}
        if not missing:
            print("No translations with missing lyrics found.")
            print_summary(translations, total)
            return

        items = list(missing.items())
        eta = ETATracker(len(items))
        print("Scraping lyrics for %d translations (%d workers)...\n" % (
            len(items), num_workers))

        scraped = 0
        failed = 0
        save_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = {pool.submit(scrape_one_translation, item): item
                       for item in items}
            for future in as_completed(futures):
                sid, lyrics = future.result()
                n = eta.tick()
                title = translations[sid]["song_title"]
                if lyrics:
                    with save_lock:
                        translations[sid]["lyrics"] = lyrics
                        scraped += 1
                    print("%s %s — %d chars  (%s)" % (
                        eta.progress_str(), title, len(lyrics), eta.eta_str()))
                else:
                    failed += 1
                    print("%s %s — FAILED  (%s)" % (
                        eta.progress_str(), title, eta.eta_str()))

                # Save periodically
                if n % 10 == 0 or n == len(items):
                    with save_lock:
                        save_translations(translations, trans_dir)

        print("\n--- Scrape missing complete ---")
        print("Scraped: %d  Failed: %d" % (scraped, failed))
        print()
        print_summary(translations, total)
        return

    if not remaining:
        print("All songs already checked.")
        print_summary(translations, total)
        return

    # --- Main single-pass flow ---
    # Parallel workers handle geniURL check + Genius scrape together.
    # The geniURL rate limiter (_geniurl_throttle) serialises API calls
    # across threads, but Genius scrapes run fully in parallel.

    eta = ETATracker(len(remaining))
    found_count = 0
    no_translation_count = 0
    error_count = 0
    save_lock = threading.Lock()

    print("Starting %s check%s + scrape (%d workers)...\n" % (
        len(remaining), "" if len(remaining) == 1 else "s", num_workers))

    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = {
            pool.submit(check_and_scrape_one, song, args.dry_run): song
            for song in remaining
        }

        for future in as_completed(futures):
            song_id, title, entry = future.result()
            n = eta.tick()

            with save_lock:
                done_ids.add(song_id)

                if entry is None:
                    no_translation_count += 1
                    print("%s %s — no translation  (%s)" % (
                        eta.progress_str(), title, eta.eta_str()))
                else:
                    translations[str(song_id)] = entry
                    has_lyrics = entry.get("lyrics") is not None
                    if has_lyrics:
                        found_count += 1
                        print("%s %s — %d chars  (%s)" % (
                            eta.progress_str(), title,
                            len(entry["lyrics"]), eta.eta_str()))
                    elif args.dry_run:
                        found_count += 1
                        print("%s %s — found  (%s)" % (
                            eta.progress_str(), title, eta.eta_str()))
                    else:
                        error_count += 1
                        print("%s %s — scrape failed  (%s)" % (
                            eta.progress_str(), title, eta.eta_str()))

                # Save periodically
                if n % 20 == 0 or n == len(remaining):
                    save_done_ids(done_ids_path, done_ids)
                    save_translations(translations, trans_dir)

    # Final save
    save_done_ids(done_ids_path, done_ids)
    save_translations(translations, trans_dir)

    elapsed = time.time() - eta.start_time
    print()
    print("--- Session complete in %s ---" % format_eta(int(elapsed)))
    print("Checked: %d" % len(remaining))
    print("Found translations: %d" % found_count)
    print("No translation: %d" % no_translation_count)
    print("Scrape errors: %d" % error_count)
    print()
    print_summary(translations, total)


# ---------------------------------------------------------------------------
# Alignment: match Spanish lyrics to English translations line by line
# ---------------------------------------------------------------------------

import re as _re

_SECTION_HEADER_RE = _re.compile(r'^\[.+\]$')


def _clean_lyrics_keep_blanks(raw_text):
    """Clean raw Genius lyrics, keeping empty lines as section boundaries.

    Drops the metadata first line and section headers like [Chorus].
    Empty lines are preserved as '' for section splitting.
    """
    lines = raw_text.split("\n")
    lines = lines[1:]  # drop Genius metadata
    result = []
    for line in lines:
        stripped = line.strip()
        if _SECTION_HEADER_RE.match(stripped):
            continue
        result.append(stripped)
    return result


def clean_lyrics_lines(raw_text):
    """Clean raw Genius lyrics text into a list of content lines.

    Drops the metadata first line (Genius contributor/description text),
    section headers like [Chorus], and empty lines.
    """
    return [l for l in _clean_lyrics_keep_blanks(raw_text) if l]


def _split_sections(lines):
    """Split lines at empty-line boundaries into sections."""
    sections = []
    current = []
    for line in lines:
        if not line:
            if current:
                sections.append(current)
                current = []
        else:
            current.append(line)
    if current:
        sections.append(current)
    return sections


def build_aligned_translations(artist_dir, max_diff_pct=0.10):
    """Align Spanish lyrics with English Genius translations line by line.

    For exact-match songs (same line count): zips all lines 1:1.
    For close-match songs (within max_diff_pct): splits at empty lines into
    sections and only uses sections where line counts match exactly. This
    avoids cascading misalignment from a single split/merged line.

    Returns a dict with:
      "songs": {song_id: {title, match_quality, sp_lines, en_lines, lines: [{spanish, english}]}}
      "index": {spanish_line: english_line}  (flat lookup for step 6)
      "stats": {exact, close, skipped, lines_indexed}
    """
    trans_dir = os.path.join(artist_dir, "data", "input", "translations")
    trans_path = os.path.join(trans_dir, "translations.json")
    if not os.path.exists(trans_path):
        print("No translations.json found — nothing to align.")
        return {"songs": {}, "index": {}, "stats": {"exact": 0, "close": 0, "skipped": 0, "lines_indexed": 0}}

    with open(trans_path, "r", encoding="utf-8") as f:
        translations = json.load(f)

    # Load Spanish lyrics from batch files
    all_songs = {}
    batch_dir = os.path.join(artist_dir, "data", "input", "batches")
    for path in sorted(glob.glob(os.path.join(batch_dir, "batch_*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            for song in json.load(f):
                all_songs[str(song["id"])] = song

    songs_out = {}
    index = {}
    stats = {"exact": 0, "close": 0, "skipped": 0, "lines_indexed": 0}

    for song_id, tdata in sorted(translations.items()):
        if song_id not in all_songs:
            continue
        if not tdata.get("lyrics"):
            continue

        sp_raw = _clean_lyrics_keep_blanks(all_songs[song_id]["lyrics"])
        en_raw = _clean_lyrics_keep_blanks(tdata["lyrics"])
        sp_content = [l for l in sp_raw if l]
        en_content = [l for l in en_raw if l]

        if not sp_content or not en_content:
            stats["skipped"] += 1
            continue

        diff_pct = abs(len(sp_content) - len(en_content)) / max(len(sp_content), len(en_content))

        if diff_pct > max_diff_pct:
            stats["skipped"] += 1
            songs_out[song_id] = {
                "title": tdata.get("song_title", ""),
                "match_quality": "skipped",
                "sp_lines": len(sp_content),
                "en_lines": len(en_content),
                "lines": [],
            }
            continue

        aligned = []

        if len(sp_content) == len(en_content):
            # Exact match — zip all lines
            quality = "exact"
            stats["exact"] += 1
            for sp_line, en_line in zip(sp_content, en_content):
                aligned.append({"spanish": sp_line, "english": en_line})
                if sp_line not in index:
                    index[sp_line] = en_line
                    stats["lines_indexed"] += 1
        else:
            # Close match — section-aware alignment
            quality = "close"
            stats["close"] += 1
            sp_sections = _split_sections(sp_raw)
            en_sections = _split_sections(en_raw)
            for i in range(min(len(sp_sections), len(en_sections))):
                sp_sec = sp_sections[i]
                en_sec = en_sections[i]
                if len(sp_sec) == len(en_sec):
                    for sp_line, en_line in zip(sp_sec, en_sec):
                        aligned.append({"spanish": sp_line, "english": en_line})
                        if sp_line not in index:
                            index[sp_line] = en_line
                            stats["lines_indexed"] += 1
                # Mismatched sections are skipped — no cascading errors

        songs_out[song_id] = {
            "title": tdata.get("song_title", ""),
            "match_quality": quality,
            "sp_lines": len(sp_content),
            "en_lines": len(en_content),
            "lines": aligned,
        }

    return {"songs": songs_out, "index": index, "stats": stats}


def run_alignment(artist_dir):
    """Build and save aligned_translations.json."""
    result = build_aligned_translations(artist_dir)
    stats = result["stats"]

    print("=== Alignment Results ===")
    print("Exact match songs: %d" % stats["exact"])
    print("Close match songs: %d" % stats["close"])
    print("Skipped (>10%% diff): %d" % stats["skipped"])
    print("Total lines indexed: %d" % stats["lines_indexed"])

    out_path = os.path.join(artist_dir, "data", "input", "translations", "aligned_translations.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("Wrote %s" % out_path)


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
