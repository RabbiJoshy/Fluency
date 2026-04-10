#!/usr/bin/env python3
"""
Step 5: Split vocab_evidence_merged.json into layer files.

Reads the merged evidence from step 3 and produces two layer files that
mirror the normal-mode layer schema:
  - word_inventory.json: word identity + corpus frequency
  - examples_raw.json: raw Spanish example lines (no English yet — step 6A adds that)

Usage (from project root):
    .venv/bin/python3 Artists/scripts/5b_split_evidence.py --artist-dir Artists/BadBunny

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
from _artist_config import add_artist_arg, load_artist_config


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

        # Examples: raw Spanish lines with metadata
        raw_examples = entry.get("examples", [])
        if raw_examples:
            examples_raw[word] = [
                {
                    "id": ex["id"],
                    "spanish": ex["line"],
                    "title": ex.get("title", ""),
                }
                for ex in raw_examples
            ]

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
