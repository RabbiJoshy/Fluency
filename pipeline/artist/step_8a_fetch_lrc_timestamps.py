#!/usr/bin/env python3
"""
9_fetch_lrc_timestamps.py — Fetch synced lyrics from LRCLIB and match to examples.

For each song in the artist's examples_raw.json, queries the LRCLIB API for
synced (LRC-format) lyrics, then matches each example lyric line to the best
LRC line to extract its playback timestamp.

Output layer: data/layers/lyrics_timestamps.json
Cache dir:    data/lrclib_cache/  (raw API responses)

Usage (from project root):
    .venv/bin/python3 pipeline/artist/step_8a_fetch_lrc_timestamps.py --artist-dir "Artists/spanish/Bad Bunny"
    .venv/bin/python3 pipeline/artist/step_8a_fetch_lrc_timestamps.py --artist-dir "Artists/spanish/Bad Bunny" --force-refetch
"""

import argparse
import concurrent.futures
import difflib
import glob as glob_module
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

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from util_1a_artist_config import add_artist_arg, load_artist_config

_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pipeline.util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

STEP_VERSION = 3
STEP_VERSION_NOTES = {
    1: "LRCLIB synced lyrics + best-line matching",
    2: "+ infer end_ms from the next raw LRC boundary (including empty rows) "
       "or track duration for the final line",
    3: "+ use each lyric file's artist for LRCLIB playlist-track searches",
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

def parse_lrc(synced_lyrics, duration_ms=None):
    """Parse text lines with their strict next-timestamp boundary.

    Empty LRC rows are retained as boundaries even though they cannot match an
    example. The last text line uses the LRCLIB track duration when available.
    """
    timed_rows = []
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
        timed_rows.append((timestamp_ms, text))

    lines = []
    for index, (timestamp_ms, text) in enumerate(timed_rows):
        if not text:
            continue
        end_ms = None
        for next_ms, _next_text in timed_rows[index + 1:]:
            if next_ms > timestamp_ms:
                end_ms = next_ms
                break
        if end_ms is None and duration_ms and duration_ms > timestamp_ms:
            end_ms = int(duration_ms)
        lines.append((timestamp_ms, end_ms, text, normalize_text(text)))
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


def get_synced_result(api_response):
    """Pick the first result with non-null syncedLyrics and retain duration."""
    for result in api_response:
        if result.get("syncedLyrics"):
            return result
    return None


def get_synced_lyrics(api_response):
    """Compatibility wrapper returning only the selected synced lyric text."""
    result = get_synced_result(api_response)
    return result.get("syncedLyrics") if result else None


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


def load_song_artists(artist_dir):
    """Return lyric-file artist metadata keyed by title.

    A conventional artist deck can continue to use ``artist.json``'s ``name``
    for every LRCLIB query. Playlist decks, however, contain one lyric JSON per
    track and each record identifies its actual performer. Read that metadata
    here rather than inferring it from a filename, then let callers fall back
    to the configured name when no usable per-song artist is available.
    """
    song_artists = {}
    # Playlists declare their lyric-file layout in artist.json. The default
    # retains compatibility with artist decks that predate batch_glob_rel.
    try:
        config = load_artist_config(artist_dir)
    except (OSError, ValueError):
        config = {}
    lyrics_pattern = os.path.join(
        artist_dir, config.get("batch_glob_rel", os.path.join("lyrics", "*", "*.json"))
    )
    for path in sorted(glob_module.glob(lyrics_pattern)):
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError) as exc:
            print("    WARN: could not read lyric metadata '%s': %s" % (path, exc))
            continue

        records = payload if isinstance(payload, list) else [payload]
        for record in records:
            if not isinstance(record, dict):
                continue
            title = record.get("title")
            artist = record.get("artist")
            if title and artist:
                song_artists[title] = artist
    return song_artists


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def match_examples_to_lrc(example_lines, lrc_lines):
    """Match example spanish lines to LRC lines. Returns dict of
    spanish_line -> {ms, end_ms?, confidence}."""
    results = {}
    # Build normalized lookup for LRC
    # lrc_lines is [(ms, end_ms, raw_text, normalized_text), ...]

    norm_to_lrc = {}
    for ms, end_ms, raw_text, norm_text in lrc_lines:
        if norm_text not in norm_to_lrc:
            norm_to_lrc[norm_text] = (ms, end_ms, raw_text)

    unmatched = []
    for spanish in example_lines:
        norm_ex = normalize_text(spanish)
        if not norm_ex:
            continue

        # Tier 1: Exact match after normalization
        if norm_ex in norm_to_lrc:
            ms, end_ms, _ = norm_to_lrc[norm_ex]
            results[spanish] = {"ms": ms, "confidence": "exact"}
            if end_ms is not None:
                results[spanish]["end_ms"] = end_ms
            continue

        unmatched.append((spanish, norm_ex))

    # Tier 2: Fuzzy matching for remaining lines
    if unmatched and lrc_lines:
        lrc_norms = [(ms, end_ms, raw, norm) for ms, end_ms, raw, norm in lrc_lines]
        still_unmatched = []

        for spanish, norm_ex in unmatched:
            best_ratio = 0.0
            best_match = None
            for ms, end_ms, raw, norm_lrc in lrc_norms:
                ratio = difflib.SequenceMatcher(None, norm_ex, norm_lrc).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = (ms, end_ms)
            if best_ratio >= FUZZY_THRESHOLD and best_match is not None:
                best_ms, best_end_ms = best_match
                results[spanish] = {"ms": best_ms, "confidence": "fuzzy"}
                if best_end_ms is not None:
                    results[spanish]["end_ms"] = best_end_ms
            else:
                still_unmatched.append((spanish, norm_ex))

        # Tier 3: Substring containment
        for spanish, norm_ex in still_unmatched:
            for ms, end_ms, raw, norm_lrc in lrc_norms:
                if norm_ex in norm_lrc or norm_lrc in norm_ex:
                    results[spanish] = {"ms": ms, "confidence": "substring"}
                    if end_ms is not None:
                        results[spanish]["end_ms"] = end_ms
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
    parser.add_argument("--force", action="store_true",
                        help="Re-run even if lyrics_timestamps.json is up to date")
    args = parser.parse_args()

    artist_dir = args.artist_dir
    config = load_artist_config(artist_dir)
    artist_name = config["name"]

    # Load examples_raw.json
    examples_path = os.path.join(artist_dir, "data", "layers", "examples_raw.json")
    if not os.path.exists(examples_path):
        print("ERROR: %s not found. Run steps 3-5b first." % examples_path)
        sys.exit(1)

    # Freshness skip: if the output is newer than the input, nothing to do.
    output_path = os.path.join(artist_dir, "data", "layers", "lyrics_timestamps.json")
    if (not args.force and not args.force_refetch
            and os.path.exists(output_path)
            and os.path.getmtime(output_path) >= os.path.getmtime(examples_path)):
        print("lyrics_timestamps.json is up to date — skipping. Use --force to re-run.")
        return

    with open(examples_path, "r", encoding="utf-8") as f:
        examples_raw = json.load(f)

    song_artists = load_song_artists(artist_dir)

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
    if config.get("source_type", "").endswith("_playlist"):
        missing_artists = sorted(set(songs) - set(song_artists))
        if missing_artists:
            print("WARN: playlist tracks without lyric-file artist metadata "
                  "will use the deck name: %s" % ", ".join(missing_artists))
        else:
            print("Playlist metadata supplies an artist for every song.")

    # Ensure cache directory exists
    cache_dir = os.path.join(artist_dir, "data", "lrclib_cache")
    os.makedirs(cache_dir, exist_ok=True)

    # Process each song — fetch in parallel, match sequentially
    timestamps = {}  # song_name -> {spanish_line -> {ms, end_ms?, confidence}}
    stats = {"songs_queried": 0, "songs_with_lrc": 0,
             "lines_matched": 0, "lines_with_end": 0, "lines_total": 0}

    sorted_songs = sorted(songs.keys())

    # Parallel fetch phase
    print("Fetching LRC data (%d workers)..." % MAX_WORKERS)
    responses = {}  # song_name -> API response

    def fetch_song(song_name):
        query_artist = song_artists.get(song_name, artist_name)
        return song_name, load_or_fetch(query_artist, song_name, cache_dir, args.force_refetch)

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
        synced_result = get_synced_result(response)
        synced = synced_result.get("syncedLyrics") if synced_result else None

        if not synced:
            print("  [%d/%d] %-40s  no synced lyrics" % (i + 1, len(sorted_songs), song_name[:40]))
            continue

        stats["songs_with_lrc"] += 1
        duration = synced_result.get("duration")
        try:
            duration_ms = int(float(duration) * 1000) if duration else None
        except (TypeError, ValueError):
            duration_ms = None
        lrc_lines = parse_lrc(synced, duration_ms=duration_ms)

        matched = match_examples_to_lrc(list(example_lines), lrc_lines)
        if matched:
            timestamps[song_name] = matched
            stats["lines_matched"] += len(matched)
            stats["lines_with_end"] += sum(1 for value in matched.values() if value.get("end_ms"))

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
