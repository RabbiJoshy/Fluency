#!/usr/bin/env python3
"""
step_7a_map_senses_to_lemmas.py — Split surface-word assignments onto word|lemma keys.

Auto-discovers all available sense sources by scanning sense_assignments/.
For each source, loads the matching sense_menu/{source}.json, splits assignments
into word|lemma keyed entries, and writes to sense_assignments_lemma/{source}.json.

Inputs:
    Data/Spanish/layers/sense_menu/{source}.json
    Data/Spanish/layers/sense_assignments/{source}.json

Outputs:
    Data/Spanish/layers/sense_assignments_lemma/{source}.json
"""

import json
import os
import sys
from pathlib import Path

# Import shared split logic
from util_7a_lemma_split import split_word_assignments, merge_method_maps

# Import sense menu format helper
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "artist"))
from util_5c_sense_menu_format import normalize_artist_sense_menu

from util_5c_sense_paths import (sense_menu_path, sense_assignments_path,
                                  sense_assignments_lemma_path, discover_sources)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"


def process_source(source):
    """Process one sense source: split surface-word assignments into word|lemma keys."""
    menu_file = sense_menu_path(LAYERS, source)
    assignments_file = sense_assignments_path(LAYERS, source)
    output_file = sense_assignments_lemma_path(LAYERS, source)

    if not menu_file.exists():
        print(f"  WARNING: sense menu not found for {source}: {menu_file}")
        return
    if not assignments_file.exists():
        print(f"  WARNING: assignments not found for {source}: {assignments_file}")
        return

    with open(menu_file, encoding="utf-8") as f:
        menu = normalize_artist_sense_menu(json.load(f))
    with open(assignments_file, encoding="utf-8") as f:
        assignments = json.load(f)

    remapped = {}
    changed = 0
    fallbacks = 0

    for word, raw_value in assignments.items():
        analyses = menu.get(word, [])
        split = split_word_assignments(word, analyses, raw_value)

        if len(split) != 1 or next(iter(split.keys())) != "%s|%s" % (word, word):
            changed += 1
        elif analyses and any(
            (a.get("headword") or "").strip() and a.get("headword") != word
            for a in analyses
        ):
            fallbacks += 1

        for target_key, value in split.items():
            if target_key in remapped:
                remapped[target_key] = merge_method_maps(remapped[target_key], value)
            else:
                remapped[target_key] = value

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(remapped, f, ensure_ascii=False, indent=2)

    print(f"  [{source}] {assignments_file.name} -> {output_file}")
    print(f"    input keys: {len(assignments)}, output keys: {len(remapped)}, "
          f"remapped: {changed}", end="")
    if fallbacks:
        print(f", fallbacks: {fallbacks}")
    else:
        print()


def main():
    sources = discover_sources(LAYERS, "sense_assignments")
    if not sources:
        print("No sense assignment sources found in %s" % (LAYERS / "sense_assignments"))
        sys.exit(1)

    print(f"Consolidating {len(sources)} source(s): {', '.join(sources)}")
    for source in sources:
        process_source(source)


if __name__ == "__main__":
    main()
