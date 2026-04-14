#!/usr/bin/env python3
"""
Step 5: Split vocab_evidence_merged.json into layer files.

Reads the merged evidence from step 3 and produces two layer files that
mirror the normal-mode layer schema:
  - word_inventory.json: word identity + corpus frequency
  - examples_raw.json: raw Spanish example lines (no English yet — step 6A adds that)

Usage (from project root):
    .venv/bin/python3 pipeline/artist/step_5a_split_evidence.py --artist-dir Artists/BadBunny

Inputs:
    data/elision_merge/vocab_evidence_merged.json

Outputs:
    data/layers/word_inventory.json
    data/layers/examples_raw.json
"""

import json
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util_1a_artist_config import add_artist_arg, load_artist_config


def main():
    parser = argparse.ArgumentParser(description="Step 5: Split evidence into inventory + examples layers")
    add_artist_arg(parser)
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    merged_path = os.path.join(artist_dir, "data", "elision_merge", "vocab_evidence_merged.json")
    layers_dir = os.path.join(artist_dir, "data", "layers")
    os.makedirs(layers_dir, exist_ok=True)

    print(f"Loading {merged_path}...")
    with open(merged_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  {len(data)} entries")

    # Load previous examples to preserve order (keeps sense assignments stable)
    ex_path = os.path.join(layers_dir, "examples_raw.json")
    prev_examples = {}
    if os.path.isfile(ex_path):
        with open(ex_path, "r", encoding="utf-8") as f:
            prev_examples = json.load(f)
        print(f"  Previous examples_raw: {len(prev_examples)} words (preserving order)")

    inventory = []
    examples_raw = {}

    for entry in data:
        word = entry["word"]

        # Inventory entry: word identity + corpus stats
        inv_entry = {
            "word": word,
            "corpus_count": entry.get("corpus_count", 0),
        }
        if entry.get("display_form"):
            inv_entry["display_form"] = entry["display_form"]
        if entry.get("variants"):
            inv_entry["variants"] = entry["variants"]

        inventory.append(inv_entry)

        # Examples: preserve previous order so sense assignment indices stay valid.
        # Keep previous examples that still exist in the corpus, then append new ones.
        raw_examples = entry.get("examples", [])
        if not raw_examples:
            continue

        new_by_id = {ex["id"]: ex for ex in raw_examples}
        prev_word_examples = prev_examples.get(word, [])

        kept = []
        seen_ids = set()
        # First: keep previous examples in order if they still exist
        for prev_ex in prev_word_examples:
            eid = prev_ex.get("id", "")
            if eid in new_by_id:
                kept.append(prev_ex)
                seen_ids.add(eid)

        # Then: append new examples not seen before
        for ex in raw_examples:
            if ex["id"] not in seen_ids:
                kept.append({
                    "id": ex["id"],
                    "spanish": ex["line"],
                    "title": ex.get("title", ""),
                })

        if kept:
            examples_raw[word] = kept

    # Write layers
    inv_path = os.path.join(layers_dir, "word_inventory.json")
    ex_path = os.path.join(layers_dir, "examples_raw.json")

    with open(inv_path, "w", encoding="utf-8") as f:
        json.dump(inventory, f, ensure_ascii=False, indent=2)
    with open(ex_path, "w", encoding="utf-8") as f:
        json.dump(examples_raw, f, ensure_ascii=False)

    words_with_examples = sum(1 for exs in examples_raw.values() if exs)
    total_examples = sum(len(exs) for exs in examples_raw.values())

    print(f"\n  word_inventory: {len(inventory)} entries -> {inv_path}")
    print(f"  examples_raw: {words_with_examples} words, {total_examples} examples -> {ex_path}")


if __name__ == "__main__":
    main()
