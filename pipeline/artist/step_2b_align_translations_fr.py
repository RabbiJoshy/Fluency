#!/usr/bin/env python3
"""
Step 2b (French): Align English translations to French lyric lines.

Reads each lyrics/french/*.json file (produced by research/2-5_*.py), splits
the French and English lyrics into non-empty lines, and writes the artist
layer file that step_6b keyword mode + step_8b builder both consume.

Input:   {artist}/lyrics/french/*.json              (from research scripts)
Output:  {artist}/data/layers/example_translations.json
             {french_line: {"english": english_line, "source": "google"|"genius"|...}}

Alignment strategy:
  1. Exact line-count match → zip by index (52/64 songs in TestPlaylist).
  2. Fuzzy match → difflib.SequenceMatcher over a local window; skip low-
     confidence pairs. (handles 5–10/64 songs where stanza breaks differ.)
  3. Wildly different line counts → skip the song entirely.

Usage (from project root):
    .venv/bin/python3 pipeline/artist/step_2b_align_translations_fr.py \
        --artist-dir "Artists/french/TestPlaylist"
"""

import argparse
import difflib
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util_1a_artist_config import add_artist_arg

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pipeline.util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

STEP_VERSION = 1
STEP_VERSION_NOTES = {
    1: "initial French translation aligner from research-script lyrics JSON",
}

# SequenceMatcher cut-off for fuzzy pairing. Cross-lingual ratios are
# usually low (different alphabets + morphology); this is a sanity floor
# to reject random-pair matches, not a confidence guarantee.
MIN_ALIGN_RATIO = 0.15
# Local window for fuzzy alignment (in line indices).
FUZZY_WINDOW = 3


def nonempty_lines(text):
    return [line.strip() for line in (text or "").split("\n") if line.strip()]


def align_exact(fr_lines, en_lines):
    """Line counts match — zip and go."""
    return list(zip(fr_lines, en_lines))


def align_fuzzy(fr_lines, en_lines):
    """Counts differ — for each French line, pick the best English line in a
    window around its proportional expected position."""
    pairs = []
    n_fr, n_en = len(fr_lines), len(en_lines)
    for i, fr in enumerate(fr_lines):
        j_expected = int(i * n_en / max(n_fr, 1))
        lo = max(0, j_expected - FUZZY_WINDOW)
        hi = min(n_en, j_expected + FUZZY_WINDOW + 1)
        best_ratio = 0.0
        best_en = None
        for j in range(lo, hi):
            r = difflib.SequenceMatcher(None, fr.lower(), en_lines[j].lower()).ratio()
            if r > best_ratio:
                best_ratio = r
                best_en = en_lines[j]
        if best_en and best_ratio >= MIN_ALIGN_RATIO:
            pairs.append((fr, best_en))
    return pairs


def align_song(fr_lines, en_lines, skip_ratio=0.5):
    """Return [(fr_line, en_line)] pairs for one song. Returns [] if the
    line-count ratio is worse than `skip_ratio` either direction."""
    if not fr_lines or not en_lines:
        return []
    if len(fr_lines) == len(en_lines):
        return align_exact(fr_lines, en_lines)
    ratio = min(len(fr_lines), len(en_lines)) / max(len(fr_lines), len(en_lines))
    if ratio < skip_ratio:
        return []
    return align_fuzzy(fr_lines, en_lines)


def main():
    parser = argparse.ArgumentParser(
        description="Step 2b (French): align English translations to French lyric lines."
    )
    add_artist_arg(parser)
    parser.add_argument(
        "--lyrics-glob", default=None,
        help="Override glob for lyrics JSON files. "
             "Default: {artist-dir}/lyrics/french/*.json",
    )
    args = parser.parse_args()

    artist_dir = Path(os.path.abspath(args.artist_dir))
    lyrics_glob = args.lyrics_glob or str(artist_dir / "lyrics" / "french" / "*.json")
    out_path = artist_dir / "data" / "layers" / "example_translations.json"

    paths = sorted(glob.glob(lyrics_glob))
    if not paths:
        print(f"ERROR: no lyrics JSON files match {lyrics_glob}")
        sys.exit(1)

    translations = {}
    stats = {
        "songs": 0, "exact": 0, "fuzzy": 0,
        "skipped_mismatch": 0, "no_translation": 0,
        "pairs": 0,
    }
    source_counts = {}

    for path in paths:
        stats["songs"] += 1
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        song = data[0] if isinstance(data, list) else data
        et = song.get("english_translation") or {}
        source = et.get("source", "unknown")
        fr = nonempty_lines(song.get("lyrics"))
        en = nonempty_lines(et.get("lyrics"))

        if not en:
            stats["no_translation"] += 1
            continue

        pairs = align_song(fr, en)
        if not pairs:
            stats["skipped_mismatch"] += 1
            continue

        if len(fr) == len(en):
            stats["exact"] += 1
        else:
            stats["fuzzy"] += 1

        for fr_line, en_line in pairs:
            # First-writer-wins across songs; identical French lines should
            # translate identically anyway.
            if fr_line not in translations:
                translations[fr_line] = {"english": en_line, "source": source}
                stats["pairs"] += 1
                source_counts[source] = source_counts.get(source, 0) + 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(translations, f, ensure_ascii=False, indent=2)
    write_sidecar(out_path, make_meta(
        "align_translations_fr", STEP_VERSION,
        extra={"songs": stats["songs"], "pairs": stats["pairs"]},
    ))

    print(f"Songs processed:     {stats['songs']:>6}")
    print(f"  exact-aligned:     {stats['exact']:>6}")
    print(f"  fuzzy-aligned:     {stats['fuzzy']:>6}")
    print(f"  skipped (>2x):     {stats['skipped_mismatch']:>6}")
    print(f"  no translation:    {stats['no_translation']:>6}")
    print(f"Unique French keys:  {len(translations):>6}")
    print(f"Source breakdown:    {source_counts}")
    print(f"→ {out_path}")


if __name__ == "__main__":
    main()
