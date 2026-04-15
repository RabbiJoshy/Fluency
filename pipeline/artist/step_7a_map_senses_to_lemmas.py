#!/usr/bin/env python3
"""Consolidate artist sense assignments onto word|lemma keys.

This runs after step 6 and before later assembly/reranking steps.
It keeps the existing method structure, but splits a surface-form assignment
into per-analysis keys using the sense IDs present in the artist sense menu.

If an analysis has no explicit ``headword``, the step degrades gracefully to
``word|word``.
"""

import argparse
import json
import os
import sys

from util_1a_artist_config import (
    add_artist_arg,
    artist_sense_assignments_lemma_path,
    artist_sense_assignments_path,
    artist_sense_menu_path,
)
from util_5c_sense_menu_format import normalize_artist_sense_menu
from util_7a_lemma_split import (
    split_word_assignments, merge_method_maps,
)


def main():
    parser = argparse.ArgumentParser(description="Step 7a: map artist sense assignments to word|lemma keys")
    add_artist_arg(parser)
    parser.add_argument(
        "--sense-source",
        choices=("wiktionary", "spanishdict"),
        default="wiktionary",
        help="Which sense menu/assignments source to consolidate",
    )
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    layers_dir = os.path.join(artist_dir, "data", "layers")

    menu_path = artist_sense_menu_path(layers_dir, args.sense_source, prefer_new=False)
    assignments_path = artist_sense_assignments_path(layers_dir, args.sense_source, prefer_new=False)
    output_path = artist_sense_assignments_lemma_path(layers_dir, args.sense_source)

    if not os.path.isfile(menu_path):
        print("ERROR: sense menu not found: %s" % menu_path)
        sys.exit(1)
    if not os.path.isfile(assignments_path):
        print("ERROR: sense assignments not found: %s" % assignments_path)
        sys.exit(1)

    with open(menu_path, "r", encoding="utf-8") as f:
        menu = normalize_artist_sense_menu(json.load(f))
    with open(assignments_path, "r", encoding="utf-8") as f:
        assignments = json.load(f)

    remapped = {}
    changed = 0
    fallbacks = 0

    for word, raw_value in assignments.items():
        analyses = menu.get(word, [])
        split = split_word_assignments(word, analyses, raw_value)
        if len(split) != 1 or next(iter(split.keys())) != "%s|%s" % (word, word):
            changed += 1
        elif analyses and any((a.get("headword") or "").strip() and a.get("headword") != word for a in analyses):
            fallbacks += 1

        for target_key, value in split.items():
            if target_key in remapped:
                remapped[target_key] = merge_method_maps(remapped[target_key], value)
            else:
                remapped[target_key] = value

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(remapped, f, ensure_ascii=False, indent=2)

    print("Wrote %s" % output_path)
    print("  input keys: %d" % len(assignments))
    print("  output keys: %d" % len(remapped))
    print("  remapped words: %d" % changed)
    if fallbacks:
        print("  word|word fallbacks: %d" % fallbacks)


if __name__ == "__main__":
    main()
