#!/usr/bin/env python3
"""
Migrate vocabulary JSON files from rank-based hex IDs to md5(word|lemma)-based IDs.

This unifies the ID scheme with the artist pipeline (Artists/scripts/6_llm_analyze.py)
so the same word+lemma gets the same hex ID in both normal and artist vocabularies.

Outputs:
  - Updated vocabulary JSON files (only the `id` field changes)
  - Per-language id_migration.json mapping files: {old_id: new_id, ...}

Usage:
    .venv/bin/python3 scripts/migrate_vocab_ids.py
    .venv/bin/python3 scripts/migrate_vocab_ids.py --dry-run   # preview without writing
"""

import hashlib
import json
import os
import sys
from collections import Counter

VOCAB_FILES = [
    ("Spanish",  "Data/Spanish/vocabulary.json"),
    ("Swedish",  "Data/Swedish/vocabulary.json"),
    ("Italian",  "Data/Italian/vocabulary.json"),
    ("Dutch",    "Data/Dutch/vocabulary.json"),
    ("Polish",   "Data/Polish/vocabulary.json"),
]


def make_stable_id(word, lemma):
    """Same logic as Artists/scripts/6_llm_analyze.py — md5(word|lemma)[:4]."""
    h = hashlib.md5((word + "|" + lemma).encode("utf-8")).hexdigest()
    return h[:4]


def assign_unique_ids(entries):
    """Assign md5-based IDs with collision resolution. Matches artist pipeline."""
    used = set()
    for entry in entries:
        lemma = entry.get("lemma") or entry["word"]
        base_id = make_stable_id(entry["word"], lemma)
        final_id = base_id
        suffix = 0
        while final_id in used:
            suffix += 1
            h = hashlib.md5(
                (entry["word"] + "|" + lemma + "|" + str(suffix)).encode("utf-8")
            ).hexdigest()
            final_id = h[:4]
        used.add(final_id)
        entry["_new_id"] = final_id


def find_duplicates(entries):
    """Find duplicate word|lemma pairs for reporting."""
    pairs = [(e["word"], e.get("lemma") or e["word"]) for e in entries]
    counts = Counter(pairs)
    return {k: v for k, v in counts.items() if v > 1}


def migrate_file(language, path, dry_run=False):
    """Migrate a single vocabulary file. Returns (mapping, stats)."""
    print(f"\n{'='*60}")
    print(f"Processing {language}: {path}")
    print(f"{'='*60}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"  Entries: {len(data)}")

    # Check for missing lemma
    no_lemma = sum(1 for e in data if not e.get("lemma"))
    if no_lemma:
        print(f"  WARNING: {no_lemma} entries missing lemma (using word as fallback)")

    # Report duplicates
    dupes = find_duplicates(data)
    if dupes:
        print(f"  WARNING: {len(dupes)} duplicate word|lemma pairs:")
        for (word, lemma), count in sorted(dupes.items()):
            print(f"    {word}|{lemma} x{count}")

    # Assign new IDs
    assign_unique_ids(data)

    # Build mapping and check for changes
    mapping = {}
    changed = 0
    for entry in data:
        old_id = entry["id"]
        new_id = entry["_new_id"]
        if old_id != new_id:
            changed += 1
        mapping[old_id] = new_id

    print(f"  IDs changed: {changed}/{len(data)}")

    # Verify uniqueness
    new_ids = [e["_new_id"] for e in data]
    assert len(set(new_ids)) == len(new_ids), "Collision resolution failed!"
    print(f"  All {len(data)} IDs are unique ✓")

    # Sample mappings
    print(f"  Sample: {data[0]['word']}|{data[0].get('lemma','')} : {data[0]['id']} → {data[0]['_new_id']}")
    if len(data) > 1:
        print(f"  Sample: {data[1]['word']}|{data[1].get('lemma','')} : {data[1]['id']} → {data[1]['_new_id']}")

    if not dry_run:
        # Apply new IDs
        for entry in data:
            entry["id"] = entry.pop("_new_id")
        # Remove temp key from any remaining
        for entry in data:
            entry.pop("_new_id", None)

        # Write updated vocabulary
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  ✓ Written: {path}")

        # Write migration mapping
        migration_dir = os.path.dirname(path)
        migration_path = os.path.join(migration_dir, "id_migration.json")
        with open(migration_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2)
        print(f"  ✓ Written: {migration_path}")
    else:
        # Clean up temp keys
        for entry in data:
            entry.pop("_new_id", None)
        print(f"  (dry run — no files written)")

    return mapping


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("DRY RUN — no files will be modified\n")

    for language, path in VOCAB_FILES:
        if not os.path.exists(path):
            print(f"  Skipping {language}: {path} not found")
            continue
        migrate_file(language, path, dry_run=dry_run)

    print(f"\n{'='*60}")
    if dry_run:
        print("Dry run complete. Run without --dry-run to apply changes.")
    else:
        print("Migration complete! All vocabulary files updated.")
        print("Migration mappings saved as Data/{lang}/id_migration.json")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
