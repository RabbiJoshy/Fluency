#!/usr/bin/env python3
"""
9_rerank.py — Re-rank BadBunnyvocabulary.json using meaningful tiebreakers.

Primary sort: corpus_count descending (unchanged between groups).
Within each corpus_count tie group, break ties using:
  1. General Spanish vocabulary rank (lower = more common = better)
     - Match on word first, fall back to lemma
     - Unmatched words sort after all matched ones
  2. Distinct song count (higher = more generalizable = better)
  3. Non-cognate before cognate (harder words first, cognates are "free")
  4. Word length ascending (shorter = more fundamental)

Preserves the old rank as 'original_rank' and assigns new sequential 'rank'.

Input:  BadBunnyvocabulary.json  (output of 8_flag_cognates.py)
        data/Spanish/vocabulary.json  (general Spanish frequency list)
Output: BadBunnyvocabulary.json  (updated with new ranks)
"""

import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BB_VOCAB_PATH = os.path.join(SCRIPT_DIR, "BadBunnyvocabulary.json")
SPANISH_VOCAB_PATH = os.path.join(SCRIPT_DIR, "..", "data", "Spanish", "vocabulary.json")

SENTINEL_RANK = 999_999  # For words not found in Spanish vocabulary


def build_spanish_lookup(spanish_path):
    """Build word -> rank and lemma -> rank lookups from the general Spanish vocabulary."""
    with open(spanish_path, "r", encoding="utf-8") as f:
        spanish_data = json.load(f)

    word_to_rank = {}
    lemma_to_rank = {}

    for entry in spanish_data:
        rank = entry["rank"]
        word = entry.get("word", "").lower().strip()
        lemma = entry.get("lemma", "").lower().strip()

        if word and word not in word_to_rank:
            word_to_rank[word] = rank
        if lemma and lemma not in lemma_to_rank:
            lemma_to_rank[lemma] = rank

    return word_to_rank, lemma_to_rank


def count_distinct_songs(entry):
    """Count distinct song_name values across all meanings' examples."""
    songs = set()
    for meaning in entry.get("meanings", []):
        for example in meaning.get("examples", []):
            song_name = example.get("song_name")
            if song_name:
                songs.add(song_name)
    return len(songs)


def get_spanish_rank(entry, word_to_rank, lemma_to_rank):
    """Get the Spanish vocabulary rank for a word, trying word then lemma."""
    word = entry.get("word", "").lower().strip()
    lemma = entry.get("lemma", "").lower().strip()

    # Try exact word match first
    if word in word_to_rank:
        return word_to_rank[word]

    # Fall back to lemma match
    if lemma and lemma in word_to_rank:
        return word_to_rank[lemma]

    # Try lemma-to-lemma match
    if lemma and lemma in lemma_to_rank:
        return lemma_to_rank[lemma]

    # Try word in lemma lookup
    if word in lemma_to_rank:
        return lemma_to_rank[word]

    return SENTINEL_RANK


def sort_key(entry, word_to_rank, lemma_to_rank):
    """
    Generate sort key for an entry. Python sorts tuples element by element.
    We want:
      1. corpus_count descending (negate)
      2. Spanish rank ascending (lower = more common)
      3. Song count descending (negate)
      4. Cognate status: False (0) before True (1)
      5. Word length ascending
    """
    corpus_count = entry.get("corpus_count") or 0
    spanish_rank = get_spanish_rank(entry, word_to_rank, lemma_to_rank)
    song_count = count_distinct_songs(entry)
    is_cognate = 1 if entry.get("is_transparent_cognate", False) else 0
    word_len = len(entry.get("word", ""))

    return (-corpus_count, spanish_rank, -song_count, is_cognate, word_len)


def main():
    print("Loading Bad Bunny vocabulary...")
    with open(BB_VOCAB_PATH, "r", encoding="utf-8") as f:
        bb_data = json.load(f)
    print(f"  {len(bb_data)} entries")

    print("Loading Spanish vocabulary...")
    word_to_rank, lemma_to_rank = build_spanish_lookup(SPANISH_VOCAB_PATH)
    print(f"  {len(word_to_rank)} word entries, {len(lemma_to_rank)} lemma entries")

    # Sort using tiebreakers — array position becomes the effective rank
    print("Sorting with tiebreakers...")
    bb_data.sort(key=lambda e: sort_key(e, word_to_rank, lemma_to_rank))

    # Strip any leftover rank/original_rank fields from previous pipeline runs
    for entry in bb_data:
        entry.pop("rank", None)
        entry.pop("original_rank", None)

    # Report statistics
    matched = sum(
        1
        for e in bb_data
        if get_spanish_rank(e, word_to_rank, lemma_to_rank) < SENTINEL_RANK
    )
    print(f"\nResults:")
    print(f"  {len(bb_data)} entries sorted (rank = array position + 1)")
    print(f"  {matched} entries matched in Spanish vocab ({matched * 100 / len(bb_data):.1f}%)")

    # Show sample of ordering within a tie group
    cc3 = [e for e in bb_data if e["corpus_count"] == 3]
    print(f"\n  Sample: corpus_count=3 ({len(cc3)} words)")
    print(f"  First 10 (highest priority):")
    for i, e in enumerate(cc3[:10]):
        sp_rank = get_spanish_rank(e, word_to_rank, lemma_to_rank)
        songs = count_distinct_songs(e)
        sp_str = str(sp_rank) if sp_rank < SENTINEL_RANK else "—"
        print(
            f"    pos {bb_data.index(e) + 1:>5}: "
            f"{e['word']:<20} sp_rank={sp_str:<6} songs={songs} "
            f"cognate={e.get('is_transparent_cognate', False)}"
        )

    # Write back
    print(f"\nWriting to {BB_VOCAB_PATH}...")
    with open(BB_VOCAB_PATH, "w", encoding="utf-8") as f:
        json.dump(bb_data, f, ensure_ascii=False, indent=2)
    print("Done!")


if __name__ == "__main__":
    main()
