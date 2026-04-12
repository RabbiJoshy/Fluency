#!/usr/bin/env python3
"""Scan for duplicate/overlapping songs by finding shared verse blocks.

Compares all unexcluded songs pairwise, finding consecutive runs of shared
lyrics. A run of 4+ consecutive matching lines indicates a copied verse.
This catches remixes that reuse an artist's verse even when the rest of the
song is completely different.

Output: a report sorted by overlap severity, showing exactly which lines match
and where. Human decides what to exclude.

Usage (from project root):
    .venv/bin/python3 Artists/tools/scan_duplicates.py --artist "Bad Bunny"
    .venv/bin/python3 Artists/tools/scan_duplicates.py --artist "Rosalía" --min-run 3
    .venv/bin/python3 Artists/tools/scan_duplicates.py --artist "Young Miko" --show-lines
"""

import argparse
import glob
import json
import os
import re
import sys
import unicodedata

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline", "artist"))


# ---------------------------------------------------------------------------
# Text normalization (reuses logic from 2_count_words.py)
# ---------------------------------------------------------------------------

_HOMOGLYPHS = {
    "\u0435": "e", "\u0430": "a", "\u043E": "o",
    "\u0440": "r", "\u0441": "c", "\u0445": "x", "\u0456": "i",
}
_HOMOGLYPH_TABLE = str.maketrans(_HOMOGLYPHS)

_SECTION_TAG = re.compile(r"^\[.*?\]$")
_PAREN_CONTENT = re.compile(r"\(.*?\)")
_BRACKET_CONTENT = re.compile(r"\[.*?\]")
_PUNCT = re.compile(r"[^\w\s']")


def normalize_text(s):
    if not s:
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\u2018", "'").replace("\u2019", "'").replace("`", "'")
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    s = s.translate(_HOMOGLYPH_TABLE)
    return s


def clean_genius_boilerplate(raw):
    """Strip Genius boilerplate to get just lyrics."""
    if not raw:
        return ""
    text = normalize_text(raw)
    idx = text.find("Lyrics")
    if idx != -1:
        text = text[idx + len("Lyrics"):]
        text = text.lstrip(" \n\t-\u2013\u2014:")
    rm_match = re.search(r"(?:\u2026|\.\.\.?)?\s*Read More[\xa0\s]*\n", text)
    if rm_match:
        text = text[rm_match.end():]
    for marker in ("Embed", "You might also like", "See "):
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx]
    return text.strip()


def normalize_line(line):
    """Normalize a lyric line for comparison. Strips ad-libs, punctuation, lowercases."""
    line = _BRACKET_CONTENT.sub("", line)
    line = _PAREN_CONTENT.sub("", line)
    line = _PUNCT.sub("", line)
    line = line.lower().strip()
    line = re.sub(r"\s+", " ", line)
    return line


def extract_lines(raw_lyrics):
    """Extract normalized non-empty lyric lines from raw Genius text."""
    text = clean_genius_boilerplate(raw_lyrics)
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if _SECTION_TAG.match(line):
            continue
        norm = normalize_line(line)
        if len(norm) < 3:
            continue
        lines.append(norm)
    return lines


# ---------------------------------------------------------------------------
# Artist attribution from section tags
# ---------------------------------------------------------------------------

_SECTION_ARTIST_RE = re.compile(
    r"^\[(?:Verso|Verse|Chorus|Estribillo|Intro|Outro|Pre-Estribillo|"
    r"Pre-Chorus|Bridge|Puente|Hook|Refrán|Letra|Post-Chorus|Interludio|"
    r"Interlude|Part|Parte)(?:\s*\d*)?\s*:\s*(.+?)\]$",
    re.IGNORECASE
)


def _clean_artist_name(raw):
    """Normalize artist name from section tag: strip *, markdown, &-split."""
    raw = raw.replace("*", "").strip()
    # Split on & or , to get individual artists
    artists = re.split(r"\s*[&,]\s*", raw)
    return [a.strip().lower() for a in artists if a.strip()]


def extract_artist_lines(raw_lyrics, target_artist):
    """Count lines attributed to the target artist vs others via section tags.

    Returns (target_lines, other_lines, total_lines, has_tags).
    Lines in unattributed sections (no artist in tag) count as target.
    """
    text = clean_genius_boilerplate(raw_lyrics)
    target_lower = target_artist.lower()
    # Also match without accents
    target_ascii = target_lower.replace("í", "i").replace("á", "a").replace(
        "é", "e").replace("ó", "o").replace("ú", "u").replace("ñ", "n")

    current_is_target = True  # default: unattributed = target artist
    target_count = 0
    other_count = 0
    total_count = 0
    has_tags = False

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Check if this is a section tag
        m = _SECTION_ARTIST_RE.match(line)
        if m:
            has_tags = True
            artists = _clean_artist_name(m.group(1))
            current_is_target = any(
                target_lower in a or target_ascii in a
                for a in artists
            )
            continue

        if _SECTION_TAG.match(line):
            # Section tag without artist attribution (e.g. [Instrumental])
            # Keep current attribution
            continue

        norm = normalize_line(line)
        if len(norm) < 3:
            continue

        total_count += 1
        if current_is_target:
            target_count += 1
        else:
            other_count += 1

    return target_count, other_count, total_count, has_tags


# ---------------------------------------------------------------------------
# Similarity detection
# ---------------------------------------------------------------------------

def find_consecutive_runs(shared_indices_a, shared_indices_b):
    """Find consecutive runs of shared lines.

    Given parallel arrays of indices in song A and song B where lines match,
    find maximal runs where BOTH indices are consecutive.
    Returns list of (start_a, start_b, length) tuples.
    """
    if not shared_indices_a:
        return []

    # Sort by position in song A
    pairs = sorted(zip(shared_indices_a, shared_indices_b))
    runs = []
    run_start_a, run_start_b = pairs[0]
    run_len = 1

    for i in range(1, len(pairs)):
        a, b = pairs[i]
        prev_a, prev_b = pairs[i - 1]
        if a == prev_a + 1 and b == prev_b + 1:
            run_len += 1
        else:
            runs.append((run_start_a, run_start_b, run_len))
            run_start_a, run_start_b = a, b
            run_len = 1
    runs.append((run_start_a, run_start_b, run_len))
    return runs


def compare_songs(lines_a, lines_b):
    """Compare two songs. Returns (shared_count, longest_run, runs, shared_pct).

    Uses exact normalized line matching. Finds shared lines, then computes
    consecutive runs to detect copied verses.
    """
    if not lines_a or not lines_b:
        return 0, 0, [], 0.0

    # Build index of line → positions in song B
    b_index = {}
    for i, line in enumerate(lines_b):
        b_index.setdefault(line, []).append(i)

    # Find all shared line pairs
    shared_a = []
    shared_b = []
    for i, line in enumerate(lines_a):
        if line in b_index:
            # Match with the closest unmatched position in B
            for j in b_index[line]:
                shared_a.append(i)
                shared_b.append(j)

    if not shared_a:
        return 0, 0, [], 0.0

    # Deduplicate: for each line in A, keep best (most consecutive) match in B
    # Simple approach: try all combinations, find best runs
    runs = find_consecutive_runs(shared_a, shared_b)
    longest = max((r[2] for r in runs), default=0)
    total_shared = len(set(shared_a))  # unique lines in A that have a match in B
    shorter = min(len(lines_a), len(lines_b))
    shared_pct = total_shared / shorter if shorter > 0 else 0.0

    return total_shared, longest, runs, shared_pct


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scan for duplicate/overlapping songs by shared verse blocks")
    parser.add_argument("--artist", required=True,
                        help="Artist name (directory under Artists/)")
    parser.add_argument("--min-run", type=int, default=4,
                        help="Minimum consecutive matching lines to report (default: 4)")
    parser.add_argument("--min-shared-pct", type=float, default=0.30,
                        help="Minimum shared line percentage to report (default: 0.30)")
    parser.add_argument("--show-lines", action="store_true",
                        help="Show the actual matching lines in the report")
    parser.add_argument("--include-excluded", action="store_true",
                        help="Also compare against songs already in duplicates (to find missed mappings)")
    parser.add_argument("--artist-name", type=str, default=None,
                        help="Artist name for section tag attribution (default: from artist.json)")
    args = parser.parse_args()

    artist_dir = os.path.join(PROJECT_ROOT, "Artists", args.artist)
    if not os.path.isdir(artist_dir):
        print("ERROR: Artist directory not found: %s" % artist_dir)
        sys.exit(1)

    # Load exclusions
    dedup_path = os.path.join(artist_dir, "data", "input", "duplicate_songs.json")
    excluded_ids = set()
    dup_keep_targets = {}  # excluded_id -> keep_id
    if os.path.isfile(dedup_path):
        with open(dedup_path) as f:
            dedup = json.load(f)
        for k, v in dedup.get("duplicates", {}).items():
            excluded_ids.add(int(k))
            dup_keep_targets[int(k)] = int(v["keep"])
        for k in dedup.get("placeholders", []):
            excluded_ids.add(int(k))
        for k in dedup.get("non_spanish", {}).get("songs", {}):
            excluded_ids.add(int(k))
        for k in dedup.get("non_songs", {}).get("songs", {}):
            excluded_ids.add(int(k))
    print("Loaded %d excluded song IDs" % len(excluded_ids))

    # Resolve target artist name for section tag attribution
    target_artist = args.artist_name
    if not target_artist:
        artist_json = os.path.join(artist_dir, "artist.json")
        if os.path.isfile(artist_json):
            with open(artist_json) as f:
                target_artist = json.load(f).get("name", args.artist)
        else:
            target_artist = args.artist
    print("Target artist for attribution: %s" % target_artist)

    # Load all songs from batches
    batch_dir = os.path.join(artist_dir, "data", "input", "batches")
    songs = {}  # id -> {title, lines, raw_lines, ...}
    for f in sorted(glob.glob(os.path.join(batch_dir, "batch_*.json"))):
        with open(f) as fh:
            batch = json.load(fh)
        for s in batch:
            sid = s["id"]
            if sid in excluded_ids and not args.include_excluded:
                continue
            raw = s.get("lyrics", "")
            lines = extract_lines(raw)
            if len(lines) < 3:
                continue
            # Keep raw lines for display
            text = clean_genius_boilerplate(raw)
            raw_lines = [l.strip() for l in text.split("\n")
                         if l.strip() and not _SECTION_TAG.match(l.strip())]
            # Artist attribution from section tags
            artist_lines, other_lines, _, has_tags = extract_artist_lines(
                raw, target_artist)
            songs[sid] = {
                "title": s["title"],
                "lines": lines,
                "raw_lines": raw_lines,
                "excluded": sid in excluded_ids,
                "artist_lines": artist_lines,
                "other_lines": other_lines,
                "has_tags": has_tags,
            }

    print("Loaded %d songs (%d excluded, %d active)" % (
        len(songs),
        sum(1 for s in songs.values() if s["excluded"]),
        sum(1 for s in songs.values() if not s["excluded"])))

    # Build global line index: which lines appear in which songs
    # Used to compute per-song uniqueness
    line_to_songs = {}  # normalized_line -> set of song IDs
    for sid, s in songs.items():
        for line in s["lines"]:
            line_to_songs.setdefault(line, set()).add(sid)

    # Compute per-song unique lines (lines that appear in NO other song)
    for sid, s in songs.items():
        unique = [line for line in s["lines"]
                  if len(line_to_songs.get(line, set())) == 1]
        s["unique_lines"] = len(unique)
        s["unique_pct"] = len(unique) / len(s["lines"]) if s["lines"] else 0

    # Pairwise comparison
    song_ids = sorted(songs.keys())
    results = []

    for i in range(len(song_ids)):
        for j in range(i + 1, len(song_ids)):
            id_a, id_b = song_ids[i], song_ids[j]
            sa, sb = songs[id_a], songs[id_b]

            shared, longest_run, runs, shared_pct = compare_songs(
                sa["lines"], sb["lines"])

            if longest_run >= args.min_run or shared_pct >= args.min_shared_pct:
                results.append({
                    "id_a": id_a, "title_a": sa["title"],
                    "id_b": id_b, "title_b": sb["title"],
                    "lines_a": len(sa["lines"]), "lines_b": len(sb["lines"]),
                    "unique_a": sa["unique_lines"], "unique_b": sb["unique_lines"],
                    "artist_lines_a": sa["artist_lines"], "other_lines_a": sa["other_lines"],
                    "artist_lines_b": sb["artist_lines"], "other_lines_b": sb["other_lines"],
                    "has_tags_a": sa["has_tags"], "has_tags_b": sb["has_tags"],
                    "shared": shared, "longest_run": longest_run,
                    "shared_pct": shared_pct,
                    "runs": runs,
                    "excluded_a": sa["excluded"],
                    "excluded_b": sb["excluded"],
                    "raw_lines_a": sa["raw_lines"],
                    "raw_lines_b": sb["raw_lines"],
                    "norm_lines_a": sa["lines"],
                    "norm_lines_b": sb["lines"],
                })

    # Sort by longest run (primary), then shared percentage (secondary)
    results.sort(key=lambda r: (r["longest_run"], r["shared_pct"]), reverse=True)

    print("\n" + "=" * 70)
    print("OVERLAP REPORT: %s (%d pairs flagged)" % (args.artist, len(results)))
    print("=" * 70)

    if not results:
        print("\nNo overlapping song pairs found.")
        return

    for r in results:
        excl_a = " [EXCLUDED]" if r["excluded_a"] else ""
        excl_b = " [EXCLUDED]" if r["excluded_b"] else ""

        print("\n%d \"%s\"%s  vs  %d \"%s\"%s" % (
            r["id_a"], r["title_a"], excl_a,
            r["id_b"], r["title_b"], excl_b))
        # Show artist attribution if tags available
        for side, sfx in [("A", "_a"), ("B", "_b")]:
            total = r["lines" + sfx]
            unique = r["unique" + sfx]
            artist = r["artist_lines" + sfx]
            other = r["other_lines" + sfx]
            has = r["has_tags" + sfx]
            if has:
                print("  Song %s: %d lines (%d %s, %d other artists, %d unique)" % (
                    side, total, artist, target_artist, other, unique))
            else:
                print("  Song %s: %d lines (%d unique, no section tags)" % (
                    side, total, unique))
        print("  Shared: %d lines, longest consecutive run: %d" % (
            r["shared"], r["longest_run"]))

        # Show runs
        sig_runs = [run for run in r["runs"] if run[2] >= args.min_run]
        if sig_runs:
            for start_a, start_b, length in sig_runs:
                print("  Run: lines %d-%d (song A) = lines %d-%d (song B)" % (
                    start_a + 1, start_a + length,
                    start_b + 1, start_b + length))
                if args.show_lines:
                    for k in range(length):
                        idx_a = start_a + k
                        if idx_a < len(r["raw_lines_a"]):
                            print("    | %s" % r["raw_lines_a"][idx_a][:80])

        # Decide: is each song worth keeping despite the overlap?
        # Key rule: if the target artist's ONLY contribution is a verse
        # that exists in another song, the song adds no new vocabulary.
        for side, sfx in [("A", "_a"), ("B", "_b")]:
            total = r["lines" + sfx]
            unique = r["unique" + sfx]
            artist = r["artist_lines" + sfx]
            other = r["other_lines" + sfx]
            has = r["has_tags" + sfx]
            if total == 0:
                continue

            if has and artist > 0 and other > artist:
                # More lines from other artists than target — it's a feature
                unique_artist = max(0, artist - r["shared"])
                if unique_artist <= 2 and r["longest_run"] >= args.min_run:
                    print("  ** Song %s (%d \"%s\"): %s has %d lines, %d are shared"
                          " with the other song, only %d unique — copied verse, consider excluding" % (
                              side, r["id" + sfx], r["title" + sfx],
                              target_artist, artist, min(artist, r["shared"]),
                              unique_artist))
                elif artist < 10 and r["longest_run"] >= args.min_run:
                    print("  ** Song %s (%d \"%s\"): %s has only %d/%d lines"
                          " (minor feature)" % (
                              side, r["id" + sfx], r["title" + sfx],
                              target_artist, artist, total))
            elif not has:
                unique_ratio = unique / total
                if unique_ratio < 0.20 and r["longest_run"] >= args.min_run:
                    print("  ** Song %s (%d \"%s\"): only %d/%d lines (%.0f%%) are unique"
                          " — consider excluding" % (
                              side, r["id" + sfx], r["title" + sfx],
                              unique, total, unique_ratio * 100))

        # General label
        if r["shared_pct"] >= 0.80:
            print("  --> HIGH OVERLAP: likely same song or near-duplicate")
        elif r["longest_run"] >= 6:
            print("  --> SHARED VERSE: one song reuses a verse from the other")
        elif r["longest_run"] >= args.min_run:
            print("  --> SHARED BLOCK: possibly shared chorus or verse fragment")

    # Summary
    print("\n" + "-" * 70)
    print("SUMMARY")
    print("  Pairs with longest_run >= %d: %d" % (
        args.min_run, sum(1 for r in results if r["longest_run"] >= args.min_run)))
    print("  Pairs with shared >= %.0f%%: %d" % (
        args.min_shared_pct * 100,
        sum(1 for r in results if r["shared_pct"] >= args.min_shared_pct)))
    high = [r for r in results if r["shared_pct"] >= 0.80]
    if high:
        print("\n  HIGH OVERLAP (>80%% shared) — likely duplicates:")
        for r in high:
            print("    %d \"%s\" vs %d \"%s\" (%.0f%%)" % (
                r["id_a"], r["title_a"], r["id_b"], r["title_b"],
                r["shared_pct"] * 100))


if __name__ == "__main__":
    main()
