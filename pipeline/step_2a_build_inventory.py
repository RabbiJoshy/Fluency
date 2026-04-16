#!/usr/bin/env python3
"""
step_2a_build_inventory.py — Build word inventory from frequency CSV.

Reads SpanishRawWiki.csv and produces a surface-word-first inventory. Each
surface word gets one entry with the total corpus_count and a list of known
lemmas from the CSV.

Lemma disambiguation is deferred to step 7a (after sense assignment), and
frequency redistribution across lemmas happens at assembly time (step 8a).

Usage:
    python3 pipeline/step_2a_build_inventory.py

Inputs:
    Data/Spanish/SpanishRawWiki.csv

Output:
    Data/Spanish/layers/word_inventory.json
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
from util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

# Bump when the inventory schema changes (e.g. new fields, different counting).
STEP_VERSION = 1
STEP_VERSION_NOTES = {
    1: "surface-first inventory with known_lemmas list, corpus_count from ppm",
}

CSV_SOURCE = PROJECT_ROOT / "Data" / "Spanish" / "SpanishRawWiki.csv"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"


def main():
    print("Loading vocabulary from CSV...")
    by_word = defaultdict(lambda: {"corpus_count": 0, "lemmas": set()})

    with open(CSV_SOURCE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = row["word"]
            lemma = row["lemma"]
            corpus_count = int(float(row["occurrences_ppm"]))
            entry = by_word[word]
            # All rows for the same surface word share the same corpus count;
            # use max to be safe in case of minor discrepancies.
            entry["corpus_count"] = max(entry["corpus_count"], corpus_count)
            entry["lemmas"].add(lemma)

    # Build output: one entry per surface word, sorted by corpus_count descending
    entries = []
    for word, info in by_word.items():
        entries.append({
            "word": word,
            "corpus_count": info["corpus_count"],
            "known_lemmas": sorted(info["lemmas"]),
        })

    entries.sort(key=lambda e: (-e["corpus_count"], e["word"]))

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    write_sidecar(OUTPUT_FILE, make_meta("build_inventory", STEP_VERSION))

    multi_lemma = sum(1 for e in entries if len(e["known_lemmas"]) > 1)
    print(f"\n  {len(entries)} surface words ({multi_lemma} with multiple lemmas)")


if __name__ == "__main__":
    main()
