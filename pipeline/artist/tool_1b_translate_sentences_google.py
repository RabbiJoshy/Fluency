#!/usr/bin/env python3
"""Translate example sentences via Google Translate (free, via deep-translator).

Reads examples_raw.json, merges existing Genius translations, translates the
rest via Google Translate, and writes sentence_translations.json in the same
format that 6_llm_analyze.py expects.

Usage (from project root):
    .venv/bin/python3 pipeline/artist/tool_1b_translate_sentences_google.py --artist-dir "Artists/spanish/Young Miko"
    .venv/bin/python3 pipeline/artist/tool_1b_translate_sentences_google.py --artist-dir "Artists/spanish/Rosalía"
    .venv/bin/python3 pipeline/artist/tool_1b_translate_sentences_google.py --artist-dir "Artists/spanish/Young Miko" --dry-run
"""

import argparse
import json
import os
import sys
import time

from deep_translator import GoogleTranslator


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def collect_unique_lines(examples_raw):
    """Extract deduplicated Spanish lines from examples_raw.json."""
    seen = set()
    lines = []
    for word_examples in examples_raw.values():
        for ex in word_examples:
            line = ex.get("spanish", "")
            if line and line not in seen:
                seen.add(line)
                lines.append(line)
    return lines


def main():
    # -- locate artist directory ----------------------------------------
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from util_1a_artist_config import add_artist_arg, load_artist_config

    parser = argparse.ArgumentParser(description="Translate sentences via Google Translate")
    add_artist_arg(parser)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show counts but don't translate")
    parser.add_argument("--batch-save", type=int, default=50,
                        help="Save progress every N translations (default: 50)")
    args = parser.parse_args()

    artist_dir = args.artist_dir
    config = load_artist_config(artist_dir)
    artist_name = config["name"]

    examples_path = os.path.join(artist_dir, "data", "layers", "examples_raw.json")
    genius_path = os.path.join(artist_dir, "data", "input", "translations", "aligned_translations.json")
    cache_path = os.path.join(artist_dir, "data", "llm_analysis", "sentence_translations.json")

    # -- load data ------------------------------------------------------
    examples_raw = load_json(examples_path)
    if not examples_raw:
        print("ERROR: No examples_raw.json found at %s" % examples_path)
        sys.exit(1)

    all_lines = collect_unique_lines(examples_raw)
    print("[%s] %d unique lines in examples_raw.json" % (artist_name, len(all_lines)))

    # Load existing cache (resume support)
    cache = load_json(cache_path)
    cached_count = sum(1 for k, v in cache.items() if not k.startswith("_") and v)
    if cached_count:
        print("  %d lines already cached in sentence_translations.json" % cached_count)

    # Merge Genius translations
    genius = load_json(genius_path)
    genius_added = 0
    for line in all_lines:
        if line not in cache and line in genius and genius[line]:
            cache[line] = genius[line]
            genius_added += 1
    if genius_added:
        print("  +%d lines from Genius translations" % genius_added)

    # Find what still needs translating
    untranslated = [l for l in all_lines if l not in cache or not cache[l]]
    print("  %d lines need Google Translate" % len(untranslated))

    if args.dry_run:
        est_minutes = len(untranslated) * 0.535 / 60
        print("  Estimated time: %.0f minutes" % est_minutes)
        print("  (dry run — exiting)")
        return

    if not untranslated:
        print("  Nothing to translate!")
        # Still write the output layer
        write_output_layer(artist_dir, cache, genius)
        return

    # -- translate -------------------------------------------------------
    translator = GoogleTranslator(source="es", target="en")
    translated = 0
    errors = 0
    t0 = time.time()

    for i, line in enumerate(untranslated):
        try:
            result = translator.translate(line)
            if result:
                cache[line] = result
                translated += 1
            else:
                cache[line] = ""
                errors += 1
        except Exception as e:
            cache[line] = ""
            errors += 1
            if errors <= 5:
                print("  [WARN] Translation failed for: %s — %s" % (line[:60], e))
            if errors == 5:
                print("  (suppressing further error messages)")

        # Progress + periodic save
        if (i + 1) % args.batch_save == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            remaining = (len(untranslated) - i - 1) / rate
            print("  %d/%d translated (%.1f lines/sec, ~%.0f min remaining)"
                  % (i + 1, len(untranslated), rate, remaining / 60))
            save_json(cache_path, cache)

    elapsed = time.time() - t0
    save_json(cache_path, cache)
    print("\nDone: %d translated, %d errors in %.1f minutes (%.1f lines/sec)"
          % (translated, errors, elapsed / 60, translated / elapsed if elapsed else 0))

    # -- write output layer ----------------------------------------------
    write_output_layer(artist_dir, cache, genius)


def write_output_layer(artist_dir, cache, genius):
    """Write example_translations.json, preserving existing entries."""
    output_path = os.path.join(artist_dir, "data", "layers", "example_translations.json")

    # Load existing layer (preserves Genius translations etc.)
    output = load_json(output_path)
    existing_count = len(output)

    added = 0
    for line, translation in cache.items():
        if line.startswith("_") or not translation:
            continue
        if line in output:
            continue  # don't overwrite existing translations
        source = "genius" if line in genius and genius[line] else "google"
        output[line] = {"english": translation, "source": source}
        added += 1

    save_json(output_path, output)
    print("example_translations.json: %d existing + %d new = %d total"
          % (existing_count, added, len(output)))


if __name__ == "__main__":
    main()
