#!/usr/bin/env python3
"""
9_fetch_lrc_timestamps.py — Fetch synced lyrics from LRCLIB and match to examples.

For each song in the artist's examples_raw.json, queries the LRCLIB API for
synced (LRC-format) lyrics, then matches each example lyric line to the best
LRC line to extract its playback timestamp.

Output layer: data/layers/lyrics_timestamps.json
Cache dir:    data/lrclib_cache/  (raw API responses)

Usage (from project root):
    .venv/bin/python3 pipeline/artist/step_8a_fetch_lrc_timestamps.py --artist-dir "Artists/Bad Bunny"
    .venv/bin/python3 pipeline/artist/step_8a_fetch_lrc_timestamps.py --artist-dir "Artists/Bad Bunny" --force-refetch
"""

import argparse
import concurrent.futures
import difflib
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.request
import urllib.parse
import urllib.error

from util_1a_artist_config import add_artist_arg, load_artist_config

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pipeline.util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

STEP_VERSION = 1
STEP_VERSION_NOTES = {
    1: "LRCLIB synced lyrics + best-line matching",
}

# Thread-safe throttle for API requests
_fetch_lock = threading.Lock()
_last_fetch_time = 0.0

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
REQUEST_DELAY = 0.15  # seconds between API calls (per-thread)
MAX_WORKERS = 8       # concurrent fetch threads

# Reuse the same adlib regex from 3_count_words.py
_ADLIB_RE = re.compile(r'\[[^\]]*\]|\([^\)]*\)')

# LRC timestamp line: [mm:ss.xx] or [mm:ss.xxx]
_LRC_LINE_RE = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\]\s*(.*)')

# For stripping parenthetical suffixes from song names (e.g. "Track (Remix)")
_PAREN_SUFFIX_RE = re.compile(r'\s*\(.*\)\s*$')

FUZZY_THRESHOLD = 0.80


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_text(text):
    """Normalize text for comparison: strip adlibs, lowercase, remove
    punctuation (keep apostrophes), collapse whitespace, NFC normalize."""
    text = _ADLIB_RE.sub('', text)
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    # Remove punctuation except apostrophes (important for elisions like pa')
    text = re.sub(r"[^\w\s']", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# LRC parsing
# ---------------------------------------------------------------------------

def parse_lrc(synced_lyrics):
    """Parse LRC-format lyrics into a list of (timestamp_ms, raw_text, normalized_text)."""
    lines = []
    for raw_line in synced_lyrics.split("\n"):
        m = _LRC_LINE_RE.match(raw_line.strip())
        if not m:
            continue
        minutes = int(m.group(1))
        seconds = int(m.group(2))
        frac = m.group(3)
        # Handle both 2-digit (centiseconds) and 3-digit (milliseconds) fracs
        if len(frac) == 2:
            ms = int(frac) * 10
        else:
            ms = int(frac)
        timestamp_ms = minutes * 60000 + seconds * 1000 + ms
        text = m.group(4).strip()
        if text:  # skip empty/instrumental lines
            lines.append((timestamp_ms, text, normalize_text(text)))
    return lines


# ---------------------------------------------------------------------------
# LRCLIB API
# ---------------------------------------------------------------------------

def _throttle():
    """Ensure minimum delay between API requests across all threads."""
    global _last_fetch_time
    with _fetch_lock:
        now = time.time()
        elapsed = now - _last_fetch_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        _last_fetch_time = time.time()


def fetch_lrclib(artist_name, track_name):
    """Search LRCLIB for synced lyrics. Returns the raw API response (list)."""
    _throttle()
    params = urllib.parse.urlencode({
        "artist_name": artist_name,
        "track_name": track_name,
    })
    url = "%s?%s" % (LRCLIB_SEARCH_URL, params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Fluency-Vocab-App/1.0 (https://github.com/joshuathomas/fluency)",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print("    WARN: LRCLIB request failed for '%s': %s" % (track_name, e))
        return []


def get_synced_lyrics(api_response):
    """Pick the first result with non-null syncedLyrics."""
    for result in api_response:
        synced = result.get("syncedLyrics")
        if synced:
            return synced
    return None


def load_or_fetch(artist_name, track_name, cache_dir, force_refetch):
    """Load cached LRCLIB response or fetch from API."""
    slug = re.sub(r'[^\w\-]', '_', track_name.lower())
    cache_path = os.path.join(cache_dir, "%s.json" % slug)

    if not force_refetch and os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Try exact name first
    response = fetch_lrclib(artist_name, track_name)
    synced = get_synced_lyrics(response)

    # If no synced lyrics, try stripping parenthetical suffix
    if not synced:
        stripped = _PAREN_SUFFIX_RE.sub('', track_name)
        if stripped != track_name:
            time.sleep(REQUEST_DELAY)
            response2 = fetch_lrclib(artist_name, stripped)
            if get_synced_lyrics(response2):
                response = response2

    # Cache raw response
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(response, f, ensure_ascii=False, indent=2)

    return response


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def match_examples_to_lrc(example_lines, lrc_lines):
    """Match example spanish lines to LRC lines. Returns dict of
    spanish_line -> {ms, confidence}."""
    results = {}
    # Build normalized lookup for LRC
    # lrc_lines is [(ms, raw_text, normalized_text), ...]

    norm_to_lrc = {}
    for ms, raw_text, norm_text in lrc_lines:
        if norm_text not in norm_to_lrc:
            norm_to_lrc[norm_text] = (ms, raw_text)

    unmatched = []
    for spanish in example_lines:
        norm_ex = normalize_text(spanish)
        if not norm_ex:
            continue

        # Tier 1: Exact match after normalization
        if norm_ex in norm_to_lrc:
            ms, _ = norm_to_lrc[norm_ex]
            results[spanish] = {"ms": ms, "confidence": "exact"}
            continue

        unmatched.append((spanish, norm_ex))

    # Tier 2: Fuzzy matching for remaining lines
    if unmatched and lrc_lines:
        lrc_norms = [(ms, raw, norm) for ms, raw, norm in lrc_lines]
        still_unmatched = []

        for spanish, norm_ex in unmatched:
            best_ratio = 0.0
            best_ms = None
            for ms, raw, norm_lrc in lrc_norms:
                ratio = difflib.SequenceMatcher(None, norm_ex, norm_lrc).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_ms = ms
            if best_ratio >= FUZZY_THRESHOLD and best_ms is not None:
                results[spanish] = {"ms": best_ms, "confidence": "fuzzy"}
            else:
                still_unmatched.append((spanish, norm_ex))

        # Tier 3: Substring containment
        for spanish, norm_ex in still_unmatched:
            for ms, raw, norm_lrc in lrc_norms:
                if norm_ex in norm_lrc or norm_lrc in norm_ex:
                    results[spanish] = {"ms": ms, "confidence": "substring"}
                    break

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fetch synced lyrics from LRCLIB and match timestamps to examples."
    )
    add_artist_arg(parser)
    parser.add_argument("--force-refetch", action="store_true",
                        help="Re-fetch from LRCLIB even if cached")
    args = parser.parse_args()

    artist_dir = args.artist_dir
    config = load_artist_config(artist_dir)
    artist_name = config["name"]

    # Load examples_raw.json
    examples_path = os.path.join(artist_dir, "data", "layers", "examples_raw.json")
    if not os.path.exists(examples_path):
        print("ERROR: %s not found. Run steps 3-5b first." % examples_path)
        sys.exit(1)

    with open(examples_path, "r", encoding="utf-8") as f:
        examples_raw = json.load(f)

    # Collect unique songs and their example lines
    songs = {}  # song_name -> set of spanish lines
    for word, word_examples in examples_raw.items():
        for ex in word_examples:
            title = ex.get("title", "")
            spanish = ex.get("spanish", "")
            if title and spanish:
                songs.setdefault(title, set()).add(spanish)

    print("Found %d unique songs with %d example lines" % (
        len(songs),
        sum(len(lines) for lines in songs.values()),
    ))

    # Ensure cache directory exists
    cache_dir = os.path.join(artist_dir, "data", "lrclib_cache")
    os.makedirs(cache_dir, exist_ok=True)

    # Process each song — fetch in parallel, match sequentially
    timestamps = {}  # song_name -> {spanish_line -> {ms, confidence}}
    stats = {"songs_queried": 0, "songs_with_lrc": 0,
             "lines_matched": 0, "lines_total": 0}

    sorted_songs = sorted(songs.keys())

    # Parallel fetch phase
    print("Fetching LRC data (%d workers)..." % MAX_WORKERS)
    responses = {}  # song_name -> API response

    def fetch_song(song_name):
        return song_name, load_or_fetch(artist_name, song_name, cache_dir, args.force_refetch)

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_song, s): s for s in sorted_songs}
        for future in concurrent.futures.as_completed(futures):
            song_name, response = future.result()
            responses[song_name] = response

    # Sequential matching phase
    for i, song_name in enumerate(sorted_songs):
        example_lines = songs[song_name]
        stats["songs_queried"] += 1
        stats["lines_total"] += len(example_lines)

        response = responses[song_name]
        synced = get_synced_lyrics(response)

        if not synced:
            print("  [%d/%d] %-40s  no synced lyrics" % (i + 1, len(sorted_songs), song_name[:40]))
            continue

        stats["songs_with_lrc"] += 1
        lrc_lines = parse_lrc(synced)

        matched = match_examples_to_lrc(list(example_lines), lrc_lines)
        if matched:
            timestamps[song_name] = matched
            stats["lines_matched"] += len(matched)

        print("  [%d/%d] %-40s  %d/%d lines matched" % (
            i + 1, len(sorted_songs), song_name[:40],
            len(matched), len(example_lines),
        ))

    # Write output layer
    output = {
        "_meta": stats,
        "timestamps": timestamps,
    }
    output_path = os.path.join(artist_dir, "data", "layers", "lyrics_timestamps.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    write_sidecar(output_path, make_meta("fetch_lrc_timestamps", STEP_VERSION))

    print("\nDone! %d/%d songs with LRC, %d/%d lines matched" % (
        stats["songs_with_lrc"], stats["songs_queried"],
        stats["lines_matched"], stats["lines_total"],
    ))
    print("Output: %s" % output_path)


if __name__ == "__main__":
    main()
