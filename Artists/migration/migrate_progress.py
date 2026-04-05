#!/usr/bin/env python3
"""
Migrate Google Sheets progress data to new hex ID format.

Reads progress_input.txt (tab-separated, exported from Google Sheets) and
produces progress_migrated.csv with updated WordId values.

Handles two input formats:
  - Rank-based IDs: WordRank column contains a number (e.g., "120")
    Maps rank -> word|lemma via the pre-migration Bad Bunny vocab in git.
  - Hex-based IDs: WordId column contains "es1XXXX" (old 4-char hex)
    Maps old hex -> word|lemma via pre-migration vocab files in git.

Both are then mapped to the new 6-char master hex IDs.

When the same word appears multiple times (from different eras), progress
is merged: correct/wrong counts are summed, latest timestamps are kept.

Usage (from project root):
    .venv/bin/python3 Artists/migration/migrate_progress.py

Inputs:
    Artists/migration/progress_input.txt  (tab-separated, from Google Sheets)
Outputs:
    Artists/migration/progress_migrated.csv
    Artists/migration/progress_migrated.txt (tab-separated)

To adapt for a future ID format change:
    1. Update OLD_VOCAB_GIT_REF to the last commit before the ID change
    2. Update the ID parsing logic in map_to_new_id() if the format changed
    3. Run the script
"""

import csv
import json
import os
import subprocess
import sys
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ARTISTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(ARTISTS_DIR)

INPUT_PATH = os.path.join(SCRIPT_DIR, "progress_input.txt")
OUTPUT_TSV = os.path.join(SCRIPT_DIR, "progress_migrated.txt")
OUTPUT_CSV = os.path.join(SCRIPT_DIR, "progress_migrated.csv")
MASTER_PATH = os.path.join(ARTISTS_DIR, "vocabulary_master.json")

# Git ref for the pre-migration vocabulary files (last commit before ID change).
# Update this if you do another ID migration in the future.
OLD_VOCAB_GIT_REF = "e80e680"


def load_master():
    """Load master vocabulary and build lookup dicts."""
    with open(MASTER_PATH, "r", encoding="utf-8") as f:
        master = json.load(f)

    word_to_new_id = {}
    wl_to_new_id = {}
    for mid, m in master.items():
        wl_to_new_id[(m["word"], m["lemma"])] = mid
        if m["word"] not in word_to_new_id:
            word_to_new_id[m["word"]] = mid

    return master, word_to_new_id, wl_to_new_id


def load_old_vocabs():
    """Load pre-migration vocab files from git to map old IDs to word|lemma."""
    old_hex_to_wl = {}
    rank_to_wl = {}

    for artist_path in [
        "Artists/Bad Bunny/BadBunnyvocabulary.json",
        "Artists/Rosalía/Rosaliavocabulary.json",
    ]:
        try:
            raw = subprocess.check_output(
                ["git", "show", "%s:%s" % (OLD_VOCAB_GIT_REF, artist_path)],
                cwd=PROJECT_ROOT,
            )
            vocab = json.loads(raw)
        except subprocess.CalledProcessError:
            print("  Warning: could not load %s from git ref %s" % (artist_path, OLD_VOCAB_GIT_REF))
            continue

        for i, entry in enumerate(vocab):
            old_id = entry.get("id", "")
            wl = (entry["word"], entry["lemma"])
            if old_id:
                old_hex_to_wl[old_id] = wl
            # Rank mapping only for first artist (Bad Bunny was the original)
            if "Bad Bunny" in artist_path:
                rank_to_wl[i + 1] = wl

    return old_hex_to_wl, rank_to_wl


def merge_entry(existing, new_parts):
    """Merge two progress entries for the same word: sum counts, keep latest timestamps."""
    old_correct = int(existing[4]) if existing[4] else 0
    old_wrong = int(existing[5]) if existing[5] else 0
    new_correct = int(new_parts[4]) if new_parts[4] else 0
    new_wrong = int(new_parts[5]) if new_parts[5] else 0

    last_correct = max(
        existing[6] if len(existing) > 6 else "",
        new_parts[6] if len(new_parts) > 6 else "",
    )
    last_wrong = max(
        existing[7] if len(existing) > 7 else "",
        new_parts[7] if len(new_parts) > 7 else "",
    )

    return [
        existing[0], existing[1], existing[2], existing[3],
        str(old_correct + new_correct),
        str(old_wrong + new_wrong),
        last_correct, last_wrong,
    ]


def main():
    if not os.path.exists(INPUT_PATH):
        print("Error: %s not found" % INPUT_PATH)
        print("Export your Google Sheets progress tab as TSV and save it there.")
        sys.exit(1)

    print("Loading master vocabulary...")
    master, word_to_new_id, wl_to_new_id = load_master()
    print("  %d entries" % len(master))

    print("Loading pre-migration vocabularies from git ref %s..." % OLD_VOCAB_GIT_REF)
    old_hex_to_wl, rank_to_wl = load_old_vocabs()
    print("  %d hex mappings, %d rank mappings" % (len(old_hex_to_wl), len(rank_to_wl)))

    print("Reading %s..." % INPUT_PATH)
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    entries = {}  # new_word_id -> [User, Word, WordId, Language, Correct, Wrong, LastCorrect, LastWrong]
    mapped = 0
    unmapped = 0
    unmapped_words = []

    for line in lines[1:]:  # skip header
        line = line.rstrip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue

        word = parts[1]
        old_id_str = parts[2]
        new_id = None

        # Try hex-style ID (es1XXXX)
        if old_id_str.startswith("es"):
            old_hex = old_id_str[3:]
            wl = old_hex_to_wl.get(old_hex)
            if wl:
                new_id = wl_to_new_id.get(wl)

        # Try rank number
        if not new_id and old_id_str.isdigit():
            rank = int(old_id_str)
            wl = rank_to_wl.get(rank)
            if wl:
                new_id = wl_to_new_id.get(wl)

        # Fallback: match by word name
        if not new_id:
            new_id = word_to_new_id.get(word)

        if not new_id:
            unmapped += 1
            unmapped_words.append(word)
            continue

        mapped += 1
        new_word_id = "es1" + new_id
        new_parts = [
            "JST", word, new_word_id, "spanish",
            parts[4], parts[5],
            parts[6] if len(parts) > 6 else "",
            parts[7] if len(parts) > 7 else "",
        ]

        if new_word_id in entries:
            entries[new_word_id] = merge_entry(entries[new_word_id], new_parts)
        else:
            entries[new_word_id] = new_parts

    # Write TSV
    header = "User\tWord\tWordId\tLanguage\tCorrect\tWrong\tLastCorrect\tLastWrong"
    with open(OUTPUT_TSV, "w", encoding="utf-8") as f:
        f.write(header + "\n")
        for parts in entries.values():
            f.write("\t".join(parts) + "\n")

    # Write CSV
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header.split("\t"))
        for parts in entries.values():
            writer.writerow(parts)

    print("\nResults:")
    print("  Mapped: %d" % mapped)
    print("  Unmapped: %d" % unmapped)
    if unmapped_words:
        print("  Unmapped words: %s" % ", ".join(unmapped_words[:20]))
    print("  Output entries: %d (after merging duplicates)" % len(entries))
    print("\nOutput files:")
    print("  %s" % OUTPUT_TSV)
    print("  %s" % OUTPUT_CSV)


if __name__ == "__main__":
    main()
