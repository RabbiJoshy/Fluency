#!/usr/bin/env python3
"""
tool_2a_build_french_freq.py — Convert Lexique 3.83 → FrenchRawWiki.csv + french_ranks.json.

One-shot preprocessor that turns the raw Lexique 3.83 TSV download into the
schema step_2a_build_inventory.py expects (one row per (surface, lemma) pair,
grouped by surface, with rank + occurrences_ppm columns).

Frequency column: freqfilms2 (per-million in subtitle corpus). Picked because
the rest of the pipeline is biased toward conversational vocabulary, mirroring
how Spanish was built.

Usage:
    # Default: reads /tmp/Lexique383/Lexique383.tsv
    python3 pipeline/tool_2a_build_french_freq.py

    # Or specify the TSV path:
    python3 pipeline/tool_2a_build_french_freq.py --lexique /path/to/Lexique383.tsv

Outputs:
    Data/French/FrenchRawWiki.csv     — rank,word,lemma,occurrences_ppm
    Data/French/french_ranks.json     — {word: rank, lemma: rank, ...} (single line)
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEXIQUE = Path("/tmp/Lexique383/Lexique383.tsv")
OUTPUT_CSV = PROJECT_ROOT / "Data" / "French" / "FrenchRawWiki.csv"
OUTPUT_RANKS = PROJECT_ROOT / "Data" / "French" / "french_ranks.json"

# Cap depth so the inventory matches Spanish's order of magnitude (~10k surface
# words). Lexique has ~140k rows total but the long tail is single-occurrence
# vocabulary that adds noise without coverage.
TOP_N_SURFACE = 10_000

# Skip orthos that aren't useful as flashcard headwords.
_SKIP_ORTHO_RE = re.compile(r"^[^a-zàâäèéêëîïôöùûüÿœæç]")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lexique",
        type=Path,
        default=DEFAULT_LEXIQUE,
        help=f"Path to Lexique383.tsv (default: {DEFAULT_LEXIQUE})",
    )
    parser.add_argument(
        "--top-n", type=int, default=TOP_N_SURFACE,
        help=f"Cap output at top-N surface words by frequency (default: {TOP_N_SURFACE})",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.lexique.exists():
        print(f"ERROR: Lexique TSV not found at {args.lexique}", file=sys.stderr)
        print("Download with:", file=sys.stderr)
        print("  curl -sSL http://www.lexique.org/databases/Lexique383/Lexique383.zip -o /tmp/Lexique383.zip \\", file=sys.stderr)
        print("    && unzip -o /tmp/Lexique383.zip -d /tmp/Lexique383", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {args.lexique}...")
    # Aggregate (ortho, lemme) -> summed freqfilms2 (across multiple POS rows)
    pair_freq = defaultdict(float)
    n_rows = 0
    n_skipped_zero = 0
    n_skipped_format = 0

    with open(args.lexique, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            n_rows += 1
            ortho = (row.get("ortho") or "").strip().lower()
            lemme = (row.get("lemme") or "").strip().lower()
            if not ortho or not lemme:
                n_skipped_format += 1
                continue
            if _SKIP_ORTHO_RE.match(ortho):
                n_skipped_format += 1
                continue
            try:
                freq = float(row.get("freqfilms2") or 0)
            except ValueError:
                freq = 0.0
            if freq <= 0:
                n_skipped_zero += 1
                continue
            pair_freq[(ortho, lemme)] += freq

    print(f"  {n_rows:,} TSV rows, {len(pair_freq):,} (ortho,lemme) pairs after filtering")
    print(f"    skipped (zero freq):  {n_skipped_zero:,}")
    print(f"    skipped (bad format): {n_skipped_format:,}")

    # Per-surface total freq = sum across that surface's lemma rows
    surface_freq = defaultdict(float)
    surface_lemmas = defaultdict(list)  # ortho -> [(lemma, freq), ...]
    for (ortho, lemme), freq in pair_freq.items():
        surface_freq[ortho] += freq
        surface_lemmas[ortho].append((lemme, freq))

    # Sort surfaces by total freq desc; cap at top_n
    surfaces_ranked = sorted(surface_freq.items(), key=lambda kv: (-kv[1], kv[0]))[:args.top_n]
    print(f"  Top-{len(surfaces_ranked):,} surface words (cap: {args.top_n:,})")

    # Build CSV rows. For each surface, emit one row per lemma (sorted by lemma freq desc),
    # all sharing the same surface-level ppm. Ranks are sequential across all rows.
    out_rows = []
    rank = 0
    ranks_map = {}  # word/lemma -> lowest rank seen
    for ortho, total_ppm in surfaces_ranked:
        # Sort lemmas for this surface by their contribution (most-likely lemma first)
        lemmas = sorted(surface_lemmas[ortho], key=lambda lf: (-lf[1], lf[0]))
        ppm_int_str = f"{round(total_ppm, 1)}"
        for lemme, _lemma_freq in lemmas:
            rank += 1
            out_rows.append({
                "rank": rank,
                "word": ortho,
                "lemma": lemme,
                "occurrences_ppm": ppm_int_str,
            })
            # ranks JSON: lowest rank wins for both surface and lemma keys
            for key in (ortho, lemme):
                if key not in ranks_map or rank < ranks_map[key]:
                    ranks_map[key] = rank

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing {OUTPUT_CSV} ({len(out_rows):,} rows)...")
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "word", "lemma", "occurrences_ppm"])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Writing {OUTPUT_RANKS} ({len(ranks_map):,} entries)...")
    with open(OUTPUT_RANKS, "w", encoding="utf-8") as f:
        # Single-line, no indent — matches spanish_ranks.json shape
        json.dump(ranks_map, f, ensure_ascii=False, separators=(",", ":"))

    # Sample output
    print("\nTop 15 entries:")
    for r in out_rows[:15]:
        print(f"  {r['rank']:>4}  {r['word']:<15}  {r['lemma']:<15}  {r['occurrences_ppm']}")


if __name__ == "__main__":
    main()
