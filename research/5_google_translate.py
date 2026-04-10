#!/usr/bin/env python3
"""
Step 5: Google Translate lyrics for songs without a Genius translation.

Reads per-song JSON files, translates lyrics via deep_translator (free Google
Translate), and writes the translation into the song's english_translation field.

Skips songs that already have an english_translation (from step 4 / geniURL).
Uses threading for parallelism and batches lines per song to minimize API calls.

Usage:
    .venv/bin/python3 research/5_google_translate.py \
        --input-dir research/TestPlaylist/lyrics/french

    # Adjust parallelism:
    .venv/bin/python3 research/5_google_translate.py \
        --input-dir research/TestPlaylist/lyrics/french \
        --workers 8
"""

import argparse
import json
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from deep_translator import GoogleTranslator

# Separator unlikely to appear in lyrics — used to batch lines into one API call
_SEP = "\n§§§\n"

# Language directory name -> Google Translate language code
LANG_CODES = {
    "french": "fr",
    "spanish": "es",
    "portuguese": "pt",
    "italian": "it",
    "german": "de",
    "dutch": "nl",
    "catalan": "ca",
    "korean": "ko",
    "hungarian": "hu",
    "ukrainian": "uk",
}


def translate_lyrics(lyrics, source="auto"):
    """Translate lyrics in bulk — one API call per ~5000 char chunk."""
    lines = lyrics.split("\n")
    content_indices = []
    content_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("["):
            content_indices.append(i)
            content_lines.append(stripped)

    if not content_lines:
        return lyrics

    # Batch into chunks under 5000 chars
    translator = GoogleTranslator(source=source, target="en")
    translated_map = {}
    chunk = []
    chunk_indices = []
    chunk_len = 0

    for idx, line in zip(content_indices, content_lines):
        line_cost = len(line) + len(_SEP)
        if chunk_len + line_cost > 4500 and chunk:
            # Translate this chunk
            joined = _SEP.join(chunk)
            try:
                result = translator.translate(joined)
                parts = result.split("§§§") if result else [""] * len(chunk)
                for ci, part in zip(chunk_indices, parts):
                    translated_map[ci] = part.strip()
            except Exception:
                for ci, orig in zip(chunk_indices, chunk):
                    translated_map[ci] = orig
            chunk = []
            chunk_indices = []
            chunk_len = 0

        chunk.append(line)
        chunk_indices.append(idx)
        chunk_len += line_cost

    # Final chunk
    if chunk:
        joined = _SEP.join(chunk)
        try:
            result = translator.translate(joined)
            parts = result.split("§§§") if result else [""] * len(chunk)
            for ci, part in zip(chunk_indices, parts):
                translated_map[ci] = part.strip()
        except Exception:
            for ci, orig in zip(chunk_indices, chunk):
                translated_map[ci] = orig

    # Reassemble with original structure
    result_lines = []
    for i, line in enumerate(lines):
        if i in translated_map:
            result_lines.append(translated_map[i])
        else:
            result_lines.append(line)
    return "\n".join(result_lines)


def translate_one(path, source):
    """Translate a single song file. Returns (title, artist, status)."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    song = data[0] if isinstance(data, list) else data

    title = song.get("title", "")
    artist = song.get("artist", "")

    if song.get("english_translation"):
        return (title, artist, "SKIP")

    lyrics = song.get("lyrics", "")
    if not lyrics:
        return (title, artist, "NO_LYRICS")

    try:
        english_lyrics = translate_lyrics(lyrics, source=source)
        song["english_translation"] = {
            "id": None,
            "title": "%s (Google Translate)" % title,
            "url": "",
            "lyrics": english_lyrics,
            "source": "google",
        }
        out = [song] if isinstance(data, list) else song
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        return (title, artist, "OK:%d" % len(english_lyrics))
    except Exception as e:
        return (title, artist, "ERROR:%s" % e)


def main():
    parser = argparse.ArgumentParser(description="Google Translate lyrics without Genius translations")
    parser.add_argument("--input-dir", required=True,
                        help="Directory of per-song JSON files (e.g. lyrics/french/)")
    parser.add_argument("--source", default=None,
                        help="Source language code (default: infer from directory name)")
    parser.add_argument("--workers", type=int, default=5,
                        help="Number of parallel workers (default: 5)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    files = sorted(p for p in input_dir.glob("*.json") if not p.name.startswith("_"))
    print("Found %d song files in %s" % (len(files), input_dir))

    source = args.source
    if not source:
        dir_name = input_dir.name.lower()
        source = LANG_CODES.get(dir_name, "auto")
    print("Source language: %s, workers: %d" % (source, args.workers))

    translated = 0
    skipped = 0
    errors = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(translate_one, path, source): path for path in files}
        for i, future in enumerate(as_completed(futures), 1):
            title, artist, status = future.result()
            if status == "SKIP":
                skipped += 1
            elif status.startswith("OK"):
                translated += 1
                print("[%d/%d] OK  %s - %s (%s chars)" % (
                    i, len(files), artist, title, status.split(":")[1]))
            else:
                errors += 1
                print("[%d/%d] %-4s %s - %s" % (i, len(files), status[:4], artist, title))

    elapsed = time.time() - t0
    print("\nDone in %.0fs: %d translated, %d already had translations, %d errors" % (
        elapsed, translated, skipped, errors))


if __name__ == "__main__":
    main()
