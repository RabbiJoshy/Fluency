#!/usr/bin/env python3
"""
Step 5: Merge s-elision pairs in vocab_evidence.json before LLM analysis.

Elided words like ere' (= eres) get merged into their full form:
- word key becomes the full form (eres)
- display_form preserves the elided spelling (ere')
- corpus_count is summed
- examples are pooled (deduplicated by song, capped at --max_examples)

Non-s-elision words (pa'=para, English -in' words, etc.) are left as-is.

Input:  data/word_counts/vocab_evidence.json
Output: data/elision_merge/vocab_evidence_merged.json

Usage:
  python "Bad Bunny/scripts/5_merge_elisions.py"
"""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

import argparse
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _artist_config import SHARED_DIR

PIPELINE_DIR = None  # Set from --artist-dir in main()
IN_PATH = None
OUT_PATH = None
MAPPING_PATH = None
MAX_EXAMPLES = 10

# ---------------------------------------------------------------------------
# D-elision patterns: Caribbean Spanish drops -d- from past participles
#   -ado → -a'o  (olvidado → olvida'o)
#   -ído → -í'o  (jodido → jodí'o)
# These are detected by regex and merged into canonical forms.
# ---------------------------------------------------------------------------
D_ELISION_RE = re.compile(r"^(.+)a'o$")      # captures stem before a'o
D_ELISION_I_RE = re.compile(r"^(.+)í'o$")    # captures stem before í'o

# Words ending in -a'o/-í'o that are NOT d-elisions (keep as-is)
D_ELISION_EXCEPTIONS = frozenset()


def d_elision_canonical(word):
    """If word is a d-elision, return (canonical_form, display_form). Else None."""
    if word in D_ELISION_EXCEPTIONS:
        return None
    m = D_ELISION_RE.match(word)
    if m:
        return (m.group(1) + "ado", word)
    m = D_ELISION_I_RE.match(word)
    if m:
        return (m.group(1) + "ido", word)
    return None


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
    groups = defaultdict(lambda: {"count": 0, "examples": [], "display_form": None,
                                  "variants": {}})

    for entry in data:
        word = entry["word"]
        count = entry.get("corpus_count", 0)
        examples = entry.get("examples", [])

        if word in targets:
            t = targets[word]
            key = t["target_word"]
            groups[key]["display_form"] = t["display_form"]
        else:
            # Check for d-elision pattern (e.g. olvida'o → olvidado)
            d_result = d_elision_canonical(word)
            if d_result:
                canonical, display = d_result
                key = canonical
                # Only set display_form if the elided form is first seen
                if groups[key]["display_form"] is None:
                    groups[key]["display_form"] = display
            else:
                key = word
                if groups[key]["display_form"] is None:
                    groups[key]["display_form"] = word

        groups[key]["count"] += count
        groups[key]["examples"].extend(examples)
        # Track per-variant counts for merged forms
        groups[key]["variants"][word] = groups[key]["variants"].get(word, 0) + count

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
            "corpus_count": g["count"],
            "examples": deduped[:MAX_EXAMPLES],
        }
        if g["display_form"] and g["display_form"] != word:
            entry["display_form"] = g["display_form"]
        if len(g["variants"]) >= 2:
            entry["variants"] = g["variants"]

        out.append(entry)

    # Sort by PPM descending
    out.sort(key=lambda e: -e["corpus_count"])
    return out


def main():
    global PIPELINE_DIR, IN_PATH, OUT_PATH, MAPPING_PATH

    parser = argparse.ArgumentParser(description="Step 5: Merge s-elision pairs")
    parser.add_argument("--artist-dir", required=True, help="Path to artist data directory")
    args = parser.parse_args()

    PIPELINE_DIR = os.path.abspath(args.artist_dir)
    IN_PATH = Path(os.path.join(PIPELINE_DIR, "data", "word_counts", "vocab_evidence.json"))
    OUT_PATH = Path(os.path.join(PIPELINE_DIR, "data", "elision_merge", "vocab_evidence_merged.json"))
    MAPPING_PATH = Path(os.path.join(SHARED_DIR, "elision_mapping.json"))

    print(f"Loading {IN_PATH} ...")
    with open(IN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  {len(data)} entries")

    print(f"Loading merge mapping from {MAPPING_PATH} ...")
    targets = load_merge_targets(MAPPING_PATH)
    print(f"  {len(targets)} words have merge targets")

    # Count d-elisions for reporting
    d_elision_count = 0
    for entry in data:
        w = entry["word"]
        if w not in targets and d_elision_canonical(w) is not None:
            d_elision_count += 1

    merged = merge_evidence(data, targets)

    os.makedirs(os.path.dirname(str(OUT_PATH)), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(merged)} entries -> {OUT_PATH}")
    print(f"  Reduced by {len(data) - len(merged)} entries")
    print(f"  D-elisions merged: {d_elision_count} (-a'o/-í'o forms)")

    # Show top merged entries
    print("\n=== Top 20 merged entries ===")
    for e in merged[:20]:
        df = e.get("display_form", "")
        display = f" (display: {df})" if df else ""
        print(f"  {e['word']}{display} — {e['corpus_count']} occurrences, {len(e['examples'])} examples")


if __name__ == "__main__":
    main()
