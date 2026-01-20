#!/usr/bin/env python3
"""
Merge newly generated vocabulary entries into vocabulary_correct_ranks.json.
This script replaces minimal {rank, word} entries with full vocabulary data.
"""

import json
from pathlib import Path


def main():
    # File paths for PyCharm console in Data/Swedish/ directory
    base_dir = Path("Data/Swedish")

    correct_ranks_path = base_dir / "vocabulary.json"
    generated_entries_path = base_dir / "swedish_vocab_new_entries.json"
    output_path = base_dir / "vocabulary_updated.json"

    print("Loading vocabulary_correct_ranks.json...")
    with open(correct_ranks_path, 'r', encoding='utf-8') as f:
        correct_ranks = json.load(f)

    print("Loading generated_entries.json...")
    with open(generated_entries_path, 'r', encoding='utf-8') as f:
        generated_entries = json.load(f)

    # Create a mapping of rank -> generated entry for quick lookup
    generated_by_rank = {}
    for entry in generated_entries:
        rank = entry['rank']
        generated_by_rank[rank] = entry

    print(f"\nMerging {len(generated_entries)} generated entries...")

    # Track statistics
    updated_count = 0
    skipped_count = 0

    # Update the correct_ranks array
    for i, entry in enumerate(correct_ranks):
        rank = entry['rank']

        # Check if this rank has a generated entry
        if rank in generated_by_rank:
            # Check if current entry is minimal (needs updating)
            if 'meanings' not in entry:
                # Replace with generated entry
                correct_ranks[i] = generated_by_rank[rank]
                updated_count += 1
            else:
                # Already has full data, skip
                skipped_count += 1
                print(f"  Rank {rank} already has full data, skipping")

    print(f"\n📊 RESULTS")
    print(f"{'=' * 70}")
    print(f"Entries updated: {updated_count}")
    print(f"Entries skipped (already had full data): {skipped_count}")
    print(f"Generated entries not used: {len(generated_entries) - updated_count - skipped_count}")

    # Save the updated file
    print(f"\nSaving updated vocabulary to: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(correct_ranks, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Done!")
    print(f"\nOriginal file: {correct_ranks_path}")
    print(f"Updated file: {output_path}")
    print(f"\nReview the updated file, then rename it to replace the original if satisfied.")

    # Show some examples of what was updated
    print(f"\n📋 SAMPLE OF UPDATED ENTRIES:")
    print(f"{'=' * 70}")
    count = 0
    for rank in sorted(generated_by_rank.keys())[:10]:
        if rank in generated_by_rank:
            entry = generated_by_rank[rank]
            if 'meanings' in entry:
                print(f"Rank {rank}: {entry['word']} (lemma: {entry['lemma']}, {len(entry['meanings'])} meaning(s))")
                count += 1
                if count >= 10:
                    break


if __name__ == '__main__':
    main()