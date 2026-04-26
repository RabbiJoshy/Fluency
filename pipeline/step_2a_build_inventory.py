#!/usr/bin/env python3
"""
step_2a_build_inventory.py — Build word inventory from frequency CSV.

Reads {Language}RawWiki.csv and produces a surface-word-first inventory. Each
surface word gets one entry with the total corpus_count and a list of known
lemmas from the CSV.

Lemma disambiguation is deferred to step 7a (after sense assignment), and
frequency redistribution across lemmas happens at assembly time (step 8a).

Usage:
    python3 pipeline/step_2a_build_inventory.py [--language {spanish,french}]

Inputs:
    Data/{Language}/{Language}RawWiki.csv

Output:
    Data/{Language}/layers/word_inventory.json
"""

import argparse
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--language",
        default="spanish",
        choices=["spanish", "french"],
        help="Language to build inventory for (default: spanish)",
    )
    args = parser.parse_args()

    lang_dir = args.language.capitalize()
    csv_source = PROJECT_ROOT / "Data" / lang_dir / f"{lang_dir}RawWiki.csv"
    output_file = PROJECT_ROOT / "Data" / lang_dir / "layers" / "word_inventory.json"
    # Optional per-lemma frequency sidecar (e.g. french_lemma_counts.json from
    # tool_2a_build_french_freq.py). When present, step_8a uses these as
    # pre-split corpus_count weights instead of proportional-by-example fallback,
    # which fixes verb-form homographs like est (être) vs est (NOM "east").
    lemma_counts_file = (
        PROJECT_ROOT / "Data" / lang_dir / f"{args.language}_lemma_counts.json"
    )

    print(f"Loading vocabulary from {csv_source}...")
    by_word = defaultdict(lambda: {"corpus_count": 0, "lemmas": set()})

    with open(csv_source, encoding="utf-8") as f:
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

    # Optional: load per-lemma counts sidecar
    lemma_counts_map = {}
    if lemma_counts_file.exists():
        print(f"Loading per-lemma counts from {lemma_counts_file.name}...")
        with open(lemma_counts_file, encoding="utf-8") as f:
            raw = json.load(f)
        # Convert ppm-floats to ints to match corpus_count style
        for word, lemma_to_ppm in raw.items():
            lemma_counts_map[word] = {
                lem: int(round(float(ppm))) for lem, ppm in lemma_to_ppm.items()
            }
        print(f"  {len(lemma_counts_map)} surfaces with per-lemma splits")

    # Build output: one entry per surface word, sorted by corpus_count descending
    entries = []
    for word, info in by_word.items():
        entry = {
            "word": word,
            "corpus_count": info["corpus_count"],
            "known_lemmas": sorted(info["lemmas"]),
        }
        if word in lemma_counts_map:
            # Only include lemmas we know about in this inventory entry's known_lemmas
            entry["lemma_counts"] = {
                lem: count
                for lem, count in lemma_counts_map[word].items()
                if lem in info["lemmas"]
            }
        entries.append(entry)

    entries.sort(key=lambda e: (-e["corpus_count"], e["word"]))

    output_file.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing {output_file}...")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    write_sidecar(output_file, make_meta("build_inventory", STEP_VERSION))

    multi_lemma = sum(1 for e in entries if len(e["known_lemmas"]) > 1)
    print(f"\n  {len(entries)} surface words ({multi_lemma} with multiple lemmas)")


if __name__ == "__main__":
    main()
