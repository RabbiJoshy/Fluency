#!/usr/bin/env python3
"""
Step 3: Filter lyrics by language using lingua.

Reads per-song JSON files from a lyrics/ directory, runs lingua on each song's
lyrics, and moves them into language subdirectories (e.g. lyrics/french/,
lyrics/spanish/, lyrics/english/).

Usage:
    .venv/bin/python3 research/3_filter_language.py \
        --input-dir Artists/french/TestPlaylist/lyrics

    # Then feed a specific language into the pipeline:
    .venv/bin/python3 Artists/scripts/3_count_words.py \
        --artist-dir Artists/french/TestPlaylist \
        --batch_glob "Artists/french/TestPlaylist/lyrics/french/*.json" \
        --out Artists/french/TestPlaylist/vocab_evidence.json
"""

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

try:
    from lingua import Language, LanguageDetectorBuilder
except ImportError:
    sys.exit("lingua not installed: pip install lingua-language-detector")


LANGUAGE_NAMES = {
    Language.SPANISH: "spanish",
    Language.FRENCH: "french",
    Language.ENGLISH: "english",
    Language.PORTUGUESE: "portuguese",
    Language.ITALIAN: "italian",
    Language.GERMAN: "german",
    Language.CATALAN: "catalan",
}


def detect_language(detector, lyrics):
    """Detect the primary language of a lyrics string."""
    lines = []
    for line in lyrics.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("[") or "contributor" in stripped.lower():
            continue
        lines.append(stripped)

    text = "\n".join(lines[:40])
    if len(text) < 20:
        return "unknown", 0.0

    results = detector.compute_language_confidence_values(text)
    if results:
        top = results[0]
        label = LANGUAGE_NAMES.get(top.language, top.language.name.lower())
        return label, top.value
    return "unknown", 0.0


def main():
    parser = argparse.ArgumentParser(description="Filter lyrics by detected language")
    parser.add_argument("--input-dir", required=True, help="Directory of per-song JSON files")
    parser.add_argument("--min-confidence", type=float, default=0.5,
                        help="Minimum confidence to assign a language (default: 0.5)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    files = sorted(p for p in input_dir.glob("*.json") if not p.name.startswith("_"))
    print("Found %d song files in %s" % (len(files), input_dir))

    print("Building lingua detector...")
    detector = LanguageDetectorBuilder.from_all_languages().build()

    counts = defaultdict(int)
    for i, path in enumerate(files, 1):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Files are wrapped in a list for step 3 compat
        song = data[0] if isinstance(data, list) else data
        lyrics = song.get("lyrics", "")

        lang, conf = detect_language(detector, lyrics)
        if conf < args.min_confidence:
            lang = "unknown"

        # Move into language subdirectory
        lang_dir = input_dir / lang
        lang_dir.mkdir(exist_ok=True)
        shutil.move(str(path), str(lang_dir / path.name))
        counts[lang] += 1

        print("[%d/%d] %-35s %-20s -> %s (%.0f%%)" % (
            i, len(files),
            song.get("title", "")[:35],
            song.get("artist", "")[:20],
            lang, conf * 100))

    print("\n--- Summary ---")
    for lang, count in sorted(counts.items(), key=lambda x: -x[1]):
        print("  %-12s %3d songs -> %s/%s/" % (lang, count, input_dir, lang))


if __name__ == "__main__":
    main()
