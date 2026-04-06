#!/usr/bin/env python3
"""
migrate_to_6char.py — Migrate all normal-mode vocabulary IDs from 4-char to 6-char hex.

Uses md5(word|lemma)[:6], same algorithm as artist-mode master vocabulary.
Cross-checks Spanish against Artists/vocabulary_master.json to ensure
overlapping word|lemma pairs get the same ID.

Outputs:
  - Updated Data/{Language}/vocabulary.json with 6-char IDs
  - Updated Data/{Language}/id_migration.json with chained mappings
    (rank-based → 6-char in one hop, plus 4-char → 6-char entries)

Usage:
    python3 Data/Spanish/Scripts/migrate_to_6char.py

Run from project root (Fluency/).
"""

import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

LANGUAGES = {
    "Spanish": PROJECT_ROOT / "Data" / "Spanish" / "vocabulary.json",
    "Swedish": PROJECT_ROOT / "Data" / "Swedish" / "vocabulary.json",
    "Italian": PROJECT_ROOT / "Data" / "Italian" / "vocabulary.json",
    "Dutch": PROJECT_ROOT / "Data" / "Dutch" / "vocabulary.json",
    "Polish": PROJECT_ROOT / "Data" / "Polish" / "vocabulary.json",
}

# Spanish has its migration file in archive/ (moved earlier), others at top level
MIGRATION_INPUTS = {
    "Spanish": PROJECT_ROOT / "Data" / "Spanish" / "archive" / "id_migration.json",
    "Swedish": PROJECT_ROOT / "Data" / "Swedish" / "id_migration.json",
    "Italian": PROJECT_ROOT / "Data" / "Italian" / "id_migration.json",
    "Dutch": PROJECT_ROOT / "Data" / "Dutch" / "id_migration.json",
    "Polish": PROJECT_ROOT / "Data" / "Polish" / "id_migration.json",
}

MASTER_VOCAB = PROJECT_ROOT / "Artists" / "vocabulary_master.json"


def make_stable_id(word, lemma, used):
    """
    6-char hex ID from md5(word|lemma). On collision, slide the hash window.
    Mirrors Artists/scripts/merge_to_master.py.
    """
    h = hashlib.md5((word + "|" + lemma).encode("utf-8")).hexdigest()
    base_id = h[:6]

    if base_id not in used:
        return base_id

    # Slide the hash window
    for start in range(1, len(h) - 5):
        candidate = h[start:start + 6]
        if candidate not in used:
            return candidate

    # Exhausted hash — increment
    val = int(base_id, 16) + 1
    while True:
        candidate = format(val % 0xFFFFFF, "06x")
        if candidate not in used:
            return candidate
        val += 1


def load_master_lookup():
    """Load artist master vocab and build word|lemma → 6-char ID lookup."""
    if not MASTER_VOCAB.exists():
        print("  (No artist master vocab found, skipping cross-check)")
        return {}

    with open(MASTER_VOCAB, encoding="utf-8") as f:
        master = json.load(f)

    lookup = {}
    for hex_id, entry in master.items():
        key = entry["word"].lower() + "|" + entry["lemma"].lower()
        lookup[key] = hex_id
    return lookup


def migrate_language(lang, vocab_path, old_migration_path, master_lookup, dry_run=False):
    """Migrate one language's vocabulary and migration file."""
    print(f"\n{'='*50}")
    print(f"  {lang}")
    print(f"{'='*50}")

    if not vocab_path.exists():
        print(f"  SKIP — {vocab_path} not found")
        return

    with open(vocab_path, encoding="utf-8") as f:
        vocab = json.load(f)
    print(f"  {len(vocab)} entries")

    # Load old migration mapping (rank-based → 4-char)
    old_migration = {}
    if old_migration_path.exists():
        with open(old_migration_path, encoding="utf-8") as f:
            old_migration = json.load(f)
        print(f"  Old migration: {len(old_migration)} rank→4char mappings")

    # Build new 6-char IDs
    used_ids = set()
    four_to_six = {}  # 4-char → 6-char mapping
    collisions = 0
    master_matches = 0
    master_mismatches = 0

    for entry in vocab:
        word = entry["word"]
        lemma = entry.get("lemma", word)  # fall back to word if no lemma
        old_id = entry.get("id", "")
        wl_key = word.lower() + "|" + lemma.lower()

        # Check if artist master already has this word|lemma
        if lang == "Spanish" and wl_key in master_lookup:
            new_id = master_lookup[wl_key]
            # Verify it's what md5 would give us
            expected = hashlib.md5((word + "|" + lemma).encode("utf-8")).hexdigest()[:6]
            if new_id == expected:
                master_matches += 1
            else:
                # Master has a collision-resolved ID; use it for consistency
                master_mismatches += 1
                print(f"    NOTE: {word}|{lemma} master={new_id} vs expected={expected}")
        else:
            new_id = make_stable_id(word, lemma, used_ids)

        # Check for collision
        base = hashlib.md5((word + "|" + lemma).encode("utf-8")).hexdigest()[:6]
        if new_id != base:
            collisions += 1

        used_ids.add(new_id)

        if old_id and old_id != new_id:
            four_to_six[old_id] = new_id

        entry["id"] = new_id

    # Build chained migration: rank-based → 6-char (one hop) + 4-char → 6-char
    new_migration = {}

    # Chain: rank → 4char → 6char
    for rank_id, four_id in old_migration.items():
        six_id = four_to_six.get(four_id, four_id)  # if unchanged, keep
        new_migration[rank_id] = six_id

    # Also include 4char → 6char directly (for users on ERA 2)
    for four_id, six_id in four_to_six.items():
        new_migration[four_id] = six_id

    # Report
    print(f"  IDs migrated: {len(four_to_six)}")
    print(f"  Collisions resolved: {collisions}")
    if lang == "Spanish":
        print(f"  Master matches: {master_matches}")
        if master_mismatches:
            print(f"  Master mismatches (collision-resolved): {master_mismatches}")
    print(f"  Migration entries: {len(new_migration)} (rank→6char + 4char→6char)")

    if not dry_run:
        # Write updated vocabulary
        with open(vocab_path, "w", encoding="utf-8") as f:
            json.dump(vocab, f, ensure_ascii=False, indent=2)
        print(f"  Written: {vocab_path}")

        # Write migration file (always to language top-level, not archive)
        migration_output = vocab_path.parent / "id_migration.json"
        with open(migration_output, "w", encoding="utf-8") as f:
            json.dump(new_migration, f, ensure_ascii=False, indent=2)
        print(f"  Written: {migration_output}")

    return four_to_six


def main():
    print("Loading artist master vocabulary for cross-check...")
    master_lookup = load_master_lookup()
    print(f"  {len(master_lookup)} word|lemma entries in master")

    all_mappings = {}
    for lang, vocab_path in LANGUAGES.items():
        mapping = migrate_language(
            lang, vocab_path, MIGRATION_INPUTS[lang], master_lookup
        )
        if mapping:
            all_mappings[lang] = mapping

    # Summary
    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    total = sum(len(m) for m in all_mappings.values())
    print(f"Total IDs migrated across all languages: {total}")
    for lang, m in all_mappings.items():
        print(f"  {lang}: {len(m)}")


if __name__ == "__main__":
    main()
