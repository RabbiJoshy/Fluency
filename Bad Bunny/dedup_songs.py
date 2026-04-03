#!/usr/bin/env python3
"""
Deduplicate songs in the vocabulary evidence.

Identifies duplicate songs (remixes, live versions, mixed versions, reposts)
and removes their inflated counts and example lines from the evidence JSON.

Reads:
  intermediates/2_vocab_evidence.json
  duplicate_songs.json (auto-generated if missing)
  bad_bunny_genius/batch_*.json (for song metadata)

Writes:
  intermediates/2_vocab_evidence.json (updated in-place)
  duplicate_songs.json (if auto-generated)

Usage (from project root):
    .venv/bin/python3 "Bad Bunny/dedup_songs.py"
    .venv/bin/python3 "Bad Bunny/dedup_songs.py" --dry-run
"""

import json
import glob
import os
import re
import argparse
from collections import defaultdict
from typing import Dict, List, Set, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EVIDENCE_PATH = os.path.join(SCRIPT_DIR, "intermediates", "2_vocab_evidence.json")
DUPES_PATH = os.path.join(SCRIPT_DIR, "duplicate_songs.json")
BATCH_GLOB = os.path.join(SCRIPT_DIR, "bad_bunny_genius", "batch_*.json")


def load_songs():
    # type: () -> Tuple[Dict[str, str], Dict[str, int]]
    """Load all song ID -> title and ID -> lyrics_length from Genius batch files."""
    titles = {}
    lyrics_len = {}
    for path in sorted(glob.glob(BATCH_GLOB)):
        with open(path, "r", encoding="utf-8") as f:
            batch = json.load(f)
        for song in batch:
            sid = str(song.get("id", ""))
            titles[sid] = song.get("title", "")
            lyrics_len[sid] = len(song.get("lyrics", "") or "")
    return titles, lyrics_len


def normalize_title(title):
    # type: (str) -> str
    """Normalize title for duplicate detection."""
    t = title.lower()
    # Remove parenthetical/bracketed tags
    t = re.sub(
        r"\s*[\(\[](remix|live|versión?\s*(limpia|extendida|original)|"
        r"headphone\s*mix|mixed|fru\w+\s*remix|debí\s+tirar.*|"
        r"vow\s+renewal|nov\w+\s+\d+|deb[ií]\s+tirar\s+m[aá]s\s+foto.*tour)[\)\]]",
        "", t, flags=re.IGNORECASE
    )
    # Remove trailing tags without parens
    t = re.sub(r"\s*-\s*en vivo\s*$", "", t)
    t = re.sub(r"\s*\*\s*$", "", t)
    t = t.strip()
    return t


def detect_duplicates(songs, lyrics_len):
    # type: (Dict[str, str], Dict[str, int]) -> Dict[str, str]
    """
    Group songs by normalized title. For each group, keep the version with
    the most lyrics (fullest version). Break ties by lowest song ID.
    Return {duplicate_id: keep_id}.
    """
    groups = defaultdict(list)  # type: Dict[str, List[Tuple[str, str]]]
    for sid, title in songs.items():
        norm = normalize_title(title)
        groups[norm].append((sid, title))

    duplicates = {}  # type: Dict[str, str]
    for norm, entries in groups.items():
        if len(entries) <= 1:
            continue
        # Sort: most lyrics first, then lowest ID as tiebreaker
        entries.sort(key=lambda x: (-lyrics_len.get(x[0], 0), int(x[0])))
        keep_id = entries[0][0]
        for sid, title in entries[1:]:
            duplicates[sid] = keep_id

    return duplicates


def load_or_create_dupes(songs, lyrics_len):
    # type: (Dict[str, str], Dict[str, int]) -> Dict[str, str]
    """Load duplicate_songs.json if it exists, otherwise auto-detect and save."""
    if os.path.exists(DUPES_PATH):
        with open(DUPES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        dupes = data.get("duplicates", {})
        print("  Loaded %d duplicates from %s" % (len(dupes), DUPES_PATH))
        return dupes

    dupes = detect_duplicates(songs, lyrics_len)

    # Build readable output
    output = {
        "description": "Duplicate song mappings. Key = duplicate song ID, value = original to keep.",
        "duplicates": {},
    }
    for dup_id, keep_id in sorted(dupes.items(), key=lambda x: int(x[0])):
        output["duplicates"][dup_id] = {
            "keep": keep_id,
            "duplicate_title": songs.get(dup_id, ""),
            "original_title": songs.get(keep_id, ""),
        }

    with open(DUPES_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("  Auto-detected %d duplicates, wrote %s" % (len(dupes), DUPES_PATH))
    print("  Review and edit this file to correct any false positives.")

    # Flatten for internal use
    return {k: v["keep"] for k, v in output["duplicates"].items()}


def dedup_evidence(evidence, duplicate_ids):
    # type: (list, Set[str]) -> Tuple[list, int, int]
    """
    Remove examples from duplicate songs and recount corpus frequencies.

    For each word:
      1. Recount corpus_count by re-tokenizing kept examples only
         (we can't recount from scratch, but we can subtract duplicate lines)
      2. Remove examples whose song ID is in the duplicate set

    Returns (updated_evidence, examples_removed, words_removed).
    """
    # We need to know how many times each word appeared in duplicate songs.
    # Since we don't have per-song token counts, we approximate:
    # remove duplicate examples and reduce corpus_count proportionally
    # based on the fraction of examples removed.
    #
    # Better approach: recount from the example lines we keep.
    # But corpus_count includes ALL occurrences, not just example lines.
    # So we use a ratio: if 3/10 examples were from dupes, reduce count by 30%.

    examples_removed = 0
    words_removed = 0
    updated = []

    for entry in evidence:
        examples = entry.get("examples", [])
        original_count = len(examples)

        # Filter out examples from duplicate songs
        kept = []
        for ex in examples:
            ex_id = ex.get("id", "")
            song_id = ex_id.split(":")[0] if ":" in ex_id else ""
            if song_id not in duplicate_ids:
                kept.append(ex)

        removed = original_count - len(kept)
        examples_removed += removed

        if not kept:
            # All examples were from duplicates — but the word might still
            # exist in non-duplicate songs (just no selected examples).
            # Reduce corpus count proportionally but don't remove entirely
            # unless corpus_count would drop to 0.
            if original_count > 0:
                ratio = 0.0
            else:
                ratio = 1.0
        elif original_count > 0:
            ratio = len(kept) / original_count
        else:
            ratio = 1.0

        new_count = max(1, int(entry.get("corpus_count", 0) * ratio)) if ratio > 0 else 0

        if new_count == 0 and not kept:
            words_removed += 1
            continue

        entry["examples"] = kept
        entry["corpus_count"] = new_count
        updated.append(entry)

    return updated, examples_removed, words_removed


def main():
    parser = argparse.ArgumentParser(description="Deduplicate songs in vocabulary evidence")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without modifying files")
    args = parser.parse_args()

    print("Loading songs from Genius batches...")
    songs, lyrics_len = load_songs()
    print("  %d songs" % len(songs))

    print("\nLoading/detecting duplicates...")
    dupes = load_or_create_dupes(songs, lyrics_len)

    if not dupes:
        print("No duplicates found!")
        return

    duplicate_ids = set(dupes.keys())
    print("  %d duplicate songs to remove" % len(duplicate_ids))

    # Show summary
    print("\n  Sample duplicates:")
    shown = 0
    for dup_id in sorted(duplicate_ids, key=int)[:10]:
        keep = dupes[dup_id]
        print("    %s (%s) -> %s (%s)" %
              (dup_id, songs.get(dup_id, "?")[:40], keep, songs.get(keep, "?")[:40]))
        shown += 1
    if len(duplicate_ids) > shown:
        print("    ... +%d more" % (len(duplicate_ids) - shown))

    print("\nLoading evidence...")
    with open(EVIDENCE_PATH, "r", encoding="utf-8") as f:
        evidence = json.load(f)
    print("  %d words, %d total examples" %
          (len(evidence), sum(len(e.get("examples", [])) for e in evidence)))

    updated, ex_removed, words_removed = dedup_evidence(evidence, duplicate_ids)

    print("\nResults:")
    print("  Examples removed: %d" % ex_removed)
    print("  Words removed (all examples from dupes): %d" % words_removed)
    print("  Words remaining: %d" % len(updated))

    if args.dry_run:
        print("\n[DRY RUN] No files modified.")
    else:
        with open(EVIDENCE_PATH, "w", encoding="utf-8") as f:
            json.dump(updated, f, ensure_ascii=False, indent=2)
        print("\nWrote %s" % EVIDENCE_PATH)
        print("Re-run steps 2d, 3, 4 (with --skip 2c or cached progress) to propagate.")


if __name__ == "__main__":
    main()
