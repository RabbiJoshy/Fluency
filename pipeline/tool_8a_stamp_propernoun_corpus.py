#!/usr/bin/env python3
"""Stamp `is_propernoun_corpus` on vocabulary entries from corpus capitalization.

End-of-pipeline post-processor. For each surface word, aggregates how often
it appears capitalized vs. lowercase across every artist's
`examples_raw.json` (excluding sentence-initial positions, where capitalization
is forced by punctuation). If the cap-rate is at or above the threshold
(default 0.80) and there are at least `--min-obs` non-sentence-initial
observations, stamps:

    is_propernoun_corpus: true
    propernoun_cap_rate: 0.95   # rounded to 2 dp

Both fields are written onto the per-language MASTER vocabulary
(`Artists/<lang>/vocabulary_master.json`) so that `joinWithMaster()` in
`js/vocab.js` picks them up. The per-artist monolith files are NOT
stamped — they're rebuilt from the master via `tool_8c_merge_to_master`.

Why this is safe:
  - No pipeline reruns required
  - Idempotent — re-running with the same inputs produces the same output
  - Reversible — re-run with `--clear` to drop both fields

Tradeoff:
  - tool_8c_merge_to_master rebuilds the master from per-artist monoliths,
    which currently DROPS unknown fields. So if you re-run tool_8c after
    stamping, you'll need to re-run this stamper. A future improvement
    would be to teach tool_8c to copy-through unknown corpus-stamped
    flags, OR to invoke this stamper as the final step of the assembly
    chain.

Usage:
    .venv/bin/python3 pipeline/tool_8a_stamp_propernoun_corpus.py --dry-run
    .venv/bin/python3 pipeline/tool_8a_stamp_propernoun_corpus.py --language Spanish
    .venv/bin/python3 pipeline/tool_8a_stamp_propernoun_corpus.py --threshold 0.85
    .venv/bin/python3 pipeline/tool_8a_stamp_propernoun_corpus.py --clear
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)

_LANG_TO_ARTIST_DIR = {
    "Spanish": "spanish",
    "French": "french",
}

# Sentence-ending punctuation. Spanish opens questions/exclamations with
# inverted marks, so include them as sentence-starters as well.
_SENTENCE_PUNCT = set(".!?¡¿\n")


def _collect_cap_stats_for_artist(examples_raw_path, max_per_word=50):
    """Aggregate per-surface (cap_ni, lc_ni) from one artist's examples.

    Returns {surface_lower: {"cap_ni": int, "lc_ni": int}}.
    Counts at most `max_per_word` examples per surface to keep runtime
    bounded on artists with many occurrences.
    """
    with open(examples_raw_path, "r", encoding="utf-8") as f:
        examples_raw = json.load(f)

    out = defaultdict(lambda: {"cap_ni": 0, "lc_ni": 0})
    for surface_lower, occurrences in examples_raw.items():
        pattern = re.compile(r"\b" + re.escape(surface_lower) + r"\b",
                             re.IGNORECASE)
        for occ in occurrences[:max_per_word]:
            line = occ.get("spanish", "") or ""
            if not line:
                continue
            match = pattern.search(line)
            if not match:
                continue
            tok = match.group(0)
            pos = match.start()
            preceding = line[:pos].rstrip(" \"'(¿¡")
            is_sentence_initial = (not preceding) or preceding[-1] in _SENTENCE_PUNCT
            if is_sentence_initial:
                continue
            if tok[0].isupper():
                out[surface_lower]["cap_ni"] += 1
            else:
                out[surface_lower]["lc_ni"] += 1
    return out


def _discover_artists(language):
    """Yield (name, artist_dir) for every artist directory under Artists/<lang>/."""
    artist_dir = _LANG_TO_ARTIST_DIR.get(language, language.lower())
    artists_root = os.path.join(_PROJECT_ROOT, "Artists", artist_dir)
    if not os.path.isdir(artists_root):
        return
    for name in sorted(os.listdir(artists_root)):
        sub = os.path.join(artists_root, name)
        if not os.path.isdir(sub):
            continue
        if not os.path.isfile(os.path.join(sub, "data", "layers",
                                           "examples_raw.json")):
            continue
        yield name, sub


def _master_path(language):
    artist_dir = _LANG_TO_ARTIST_DIR.get(language, language.lower())
    return os.path.join(_PROJECT_ROOT, "Artists", artist_dir,
                        "vocabulary_master.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--language", default="Spanish",
                        help="Language whose master vocabulary to stamp")
    parser.add_argument("--threshold", type=float, default=0.80,
                        help="Cap-rate threshold (default 0.80)")
    parser.add_argument("--min-obs", type=int, default=3,
                        help="Minimum non-sentence-initial observations "
                             "required to compute a rate (default 3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    parser.add_argument("--clear", action="store_true",
                        help="Remove is_propernoun_corpus + propernoun_cap_rate "
                             "from every master entry and exit")
    parser.add_argument("--sample-limit", type=int, default=30,
                        help="How many sample entries to print")
    args = parser.parse_args()

    master_path = _master_path(args.language)
    if not os.path.isfile(master_path):
        print(f"ERROR: master not found at {master_path}")
        sys.exit(1)
    with open(master_path, "r", encoding="utf-8") as f:
        master = json.load(f)
    print(f"Loaded {len(master)} master entries from {master_path}")

    if args.clear:
        cleared = 0
        for entry in master.values():
            if entry.pop("is_propernoun_corpus", None) is not None:
                cleared += 1
            entry.pop("propernoun_cap_rate", None)
        print(f"Clearing {cleared} flagged entries" +
              (" [dry-run]" if args.dry_run else ""))
        if not args.dry_run and cleared:
            with open(master_path, "w", encoding="utf-8") as f:
                json.dump(master, f, ensure_ascii=False, indent=None)
        return

    # Aggregate cap stats across every artist's corpus
    aggregated = defaultdict(lambda: {"cap_ni": 0, "lc_ni": 0})
    artists_seen = 0
    for name, artist_dir in _discover_artists(args.language):
        ex_path = os.path.join(artist_dir, "data", "layers", "examples_raw.json")
        per_artist = _collect_cap_stats_for_artist(ex_path)
        for surface, counts in per_artist.items():
            aggregated[surface]["cap_ni"] += counts["cap_ni"]
            aggregated[surface]["lc_ni"] += counts["lc_ni"]
        artists_seen += 1
        print(f"  {name}: {len(per_artist)} surfaces with cap data")
    print(f"Aggregated across {artists_seen} artist(s); "
          f"{len(aggregated)} unique surfaces with observations")

    # Identify newly-flagged surfaces and compute rates
    surface_to_rate = {}
    for surface, counts in aggregated.items():
        total = counts["cap_ni"] + counts["lc_ni"]
        if total < args.min_obs:
            continue
        rate = counts["cap_ni"] / total
        if rate >= args.threshold:
            surface_to_rate[surface] = round(rate, 2)

    # Apply to master
    newly_flagged = []
    rate_updated = []
    unflagged = []
    for wid, entry in master.items():
        word_lower = (entry.get("word") or "").lower()
        new_rate = surface_to_rate.get(word_lower)
        old_rate = entry.get("propernoun_cap_rate")
        was_flagged = bool(entry.get("is_propernoun_corpus"))
        should_flag = new_rate is not None

        if should_flag and not was_flagged:
            newly_flagged.append((entry, new_rate))
            if not args.dry_run:
                entry["is_propernoun_corpus"] = True
                entry["propernoun_cap_rate"] = new_rate
        elif should_flag and was_flagged and old_rate != new_rate:
            rate_updated.append((entry, old_rate, new_rate))
            if not args.dry_run:
                entry["propernoun_cap_rate"] = new_rate
        elif not should_flag and was_flagged:
            unflagged.append(entry)
            if not args.dry_run:
                entry.pop("is_propernoun_corpus", None)
                entry.pop("propernoun_cap_rate", None)

    print()
    print(f"Newly flagged:    {len(newly_flagged)}")
    print(f"Rate updated:     {len(rate_updated)}")
    print(f"Unflagged:        {len(unflagged)} (no longer meet threshold)")

    if newly_flagged:
        sample = sorted(newly_flagged,
                        key=lambda t: -(t[0].get("word", "") and
                                        sum(aggregated[t[0]["word"].lower()].values())))
        print(f"\nSample of {min(len(sample), args.sample_limit)} newly flagged "
              f"(sorted by observation count desc):")
        for entry, rate in sample[:args.sample_limit]:
            w = entry.get("word")
            counts = aggregated[w.lower()]
            print(f"  {w!r:18s}  rate={rate:.2f}  "
                  f"({counts['cap_ni']} cap / {counts['lc_ni']} lc)")

    if not args.dry_run and (newly_flagged or rate_updated or unflagged):
        with open(master_path, "w", encoding="utf-8") as f:
            json.dump(master, f, ensure_ascii=False, indent=None)
        print(f"\nWrote {master_path}")
    elif args.dry_run:
        print("\nDRY RUN — no files modified.")


if __name__ == "__main__":
    main()
