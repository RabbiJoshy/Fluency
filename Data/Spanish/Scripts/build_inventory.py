#!/usr/bin/env python3
"""
build_inventory.py — Step 1: Build word inventory from frequency CSV.

Reads SpanishRawWiki.csv and produces the base word inventory with stable
6-char hex IDs. This is the foundation layer that all other steps reference.

Stores corpus_count (raw frequency from corpus) rather than rank — the builder
computes sort position from corpus_count.

Usage:
    python3 Data/Spanish/Scripts/build_inventory.py

Inputs:
    Data/Spanish/SpanishRawWiki.csv

Output:
    Data/Spanish/layers/word_inventory.json
"""

import csv
import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CSV_SOURCE = PROJECT_ROOT / "Data" / "Spanish" / "SpanishRawWiki.csv"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"


def make_stable_id(word, lemma, used):
    """6-char hex ID from md5(word|lemma). On collision, slide the hash window."""
    h = hashlib.md5((word + "|" + lemma).encode("utf-8")).hexdigest()
    base_id = h[:6]

    if base_id not in used:
        return base_id

    for start in range(1, len(h) - 5):
        candidate = h[start:start + 6]
        if candidate not in used:
            return candidate

    val = int(base_id, 16) + 1
    while True:
        candidate = format(val % 0xFFFFFF, "06x")
        if candidate not in used:
            return candidate
        val += 1


def main():
    print("Loading vocabulary from CSV...")
    entries = []
    used_ids = set()

    with open(CSV_SOURCE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = row["word"]
            lemma = row["lemma"]
            corpus_count = int(float(row["occurrences_ppm"]))
            word_id = make_stable_id(word, lemma, used_ids)
            used_ids.add(word_id)

            entries.append({
                "word": word,
                "lemma": lemma,
                "id": word_id,
                "corpus_count": corpus_count,
            })

    # Compute most_frequent_lemma_instance:
    # For each lemma, the entry with the highest corpus_count gets True
    seen_lemmas = {}
    for entry in entries:
        lemma = entry["lemma"].lower()
        if lemma not in seen_lemmas or entry["corpus_count"] > seen_lemmas[lemma]["corpus_count"]:
            seen_lemmas[lemma] = entry
    for entry in entries:
        entry["most_frequent_lemma_instance"] = (
            entry is seen_lemmas[entry["lemma"].lower()]
        )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    lemma_reps = sum(1 for e in entries if e["most_frequent_lemma_instance"])
    print(f"\n  {len(entries)} entries, {lemma_reps} unique lemma representatives")


if __name__ == "__main__":
    main()
