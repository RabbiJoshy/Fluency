#!/usr/bin/env python3
"""
Merge s-elision pairs in 2_vocab_evidence.json before spaCy processing.

Elided words like ere' (= eres) get merged into their full form:
- word key becomes the full form (eres)
- display_form preserves the elided spelling (ere')
- PPM is summed
- examples are pooled (deduplicated by song, capped at --max_examples)

Non-s-elision words (pa'=para, English -in' words, etc.) are left as-is.

Input:  intermediates/2_vocab_evidence.json
Output: intermediates/3_vocab_evidence_merged.json

Usage:
  python "Bad Bunny/2b_merge_elisions.py"
"""

import json
import re
from collections import defaultdict
from pathlib import Path

IN_PATH = Path("Bad Bunny/intermediates/2_vocab_evidence.json")
OUT_PATH = Path("Bad Bunny/intermediates/3_vocab_evidence_merged.json")
MAPPING_PATH = Path("Bad Bunny/intermediates/3_elision_mapping.json")
MAX_EXAMPLES = 10


def load_merge_targets(mapping_path: Path) -> dict:
    """
    Build a lookup from the mapping file:
      elided_word -> { target_word, display_form }
      full_word   -> { target_word, display_form }

    Only for action=merge entries of type elision_pair or elided_only.
    """
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    targets = {}
    for r in mapping:
        if r["action"] != "merge":
            continue
        if r["merge_type"] == "elision_pair":
            # Both elided and full form merge into target_word
            targets[r["elided_word"]] = {
                "target_word": r["target_word"],
                "display_form": r["display_form"],
            }
            targets[r["full_word"]] = {
                "target_word": r["target_word"],
                "display_form": r["display_form"],
            }
        elif r["merge_type"] == "elided_only":
            targets[r["elided_word"]] = {
                "target_word": r["target_word"],
                "display_form": r["display_form"],
            }
    return targets


def merge_evidence(data: list, targets: dict) -> list:
    """
    Merge entries according to the targets lookup.
    Returns a new list of evidence entries.
    """
    # Group entries by their merge target (or keep as-is if no target)
    groups = defaultdict(lambda: {"ppm": 0.0, "examples": [], "display_form": None})

    for entry in data:
        word = entry["word"]
        ppm = entry.get("occurrences_ppm", 0)
        examples = entry.get("examples", [])

        if word in targets:
            t = targets[word]
            key = t["target_word"]
            groups[key]["display_form"] = t["display_form"]
        else:
            key = word
            # No merge target — keep display_form = word
            if groups[key]["display_form"] is None:
                groups[key]["display_form"] = word

        groups[key]["ppm"] += ppm
        groups[key]["examples"].extend(examples)

    # Build output, deduplicating examples by song
    out = []
    for word, g in groups.items():
        # Deduplicate examples by song_id (first part of id before ':')
        seen_songs = set()
        deduped = []
        for ex in g["examples"]:
            song_id = ex["id"].split(":")[0] if "id" in ex else None
            if song_id and song_id in seen_songs:
                continue
            if song_id:
                seen_songs.add(song_id)
            deduped.append(ex)

        entry = {
            "word": word,
            "occurrences_ppm": g["ppm"],
            "examples": deduped[:MAX_EXAMPLES],
        }
        if g["display_form"] and g["display_form"] != word:
            entry["display_form"] = g["display_form"]

        out.append(entry)

    # Sort by PPM descending
    out.sort(key=lambda e: -e["occurrences_ppm"])
    return out


def main():
    print(f"Loading {IN_PATH} ...")
    with open(IN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  {len(data)} entries")

    print(f"Loading merge mapping from {MAPPING_PATH} ...")
    targets = load_merge_targets(MAPPING_PATH)
    print(f"  {len(targets)} words have merge targets")

    merged = merge_evidence(data, targets)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(merged)} entries -> {OUT_PATH}")
    print(f"  Reduced by {len(data) - len(merged)} entries")

    # Show top merged entries
    print("\n=== Top 20 merged entries ===")
    for e in merged[:20]:
        df = e.get("display_form", "")
        display = f" (display: {df})" if df else ""
        print(f"  {e['word']}{display} — {e['occurrences_ppm']:.0f} ppm, {len(e['examples'])} examples")


if __name__ == "__main__":
    main()
