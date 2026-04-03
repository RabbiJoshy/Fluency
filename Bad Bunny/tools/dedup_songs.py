#!/usr/bin/env python3
"""
Deduplicate songs in the vocabulary evidence.

Identifies duplicate songs via three methods:
  1. Title normalization (remixes, live versions, mixed versions, reposts)
  2. Exact lyrics match (same text under different Genius IDs)
  3. Placeholder/stub lyrics ("yet to be transcribed", instrumentals)

For each duplicate group, keeps the version with the most lyrics content.
Removes duplicate examples and adjusts corpus counts in the evidence JSON.

Reads:
  intermediates/2_vocab_evidence.json
  duplicate_songs.json (auto-generated if missing, or --regenerate)
  bad_bunny_genius/batch_*.json (for song metadata)

Writes:
  intermediates/2_vocab_evidence.json (updated in-place)
  duplicate_songs.json (if auto-generated or --regenerate)

Usage (from project root):
    .venv/bin/python3 "Bad Bunny/dedup_songs.py"
    .venv/bin/python3 "Bad Bunny/dedup_songs.py" --dry-run
    .venv/bin/python3 "Bad Bunny/dedup_songs.py" --regenerate
    .venv/bin/python3 "Bad Bunny/dedup_songs.py" --regenerate --dry-run
"""

import json
import glob
import os
import re
import argparse
import hashlib
from collections import defaultdict
from typing import Dict, List, Set, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EVIDENCE_PATH = os.path.join(SCRIPT_DIR, "intermediates", "2_vocab_evidence.json")
DUPES_PATH = os.path.join(SCRIPT_DIR, "duplicate_songs.json")
BATCH_GLOB = os.path.join(SCRIPT_DIR, "bad_bunny_genius", "batch_*.json")

# Placeholder patterns — songs with no real lyrics
PLACEHOLDER_RE = re.compile(
    r"yet to be transcribed|yet to be released|"
    r"This song is an instrumental",
    re.IGNORECASE,
)


def load_songs():
    # type: () -> Tuple[Dict[str, str], Dict[str, int], Dict[str, str]]
    """Load all song ID -> title, ID -> lyrics_length, ID -> lyrics from batch files."""
    titles = {}
    lyrics_len = {}
    lyrics_text = {}
    for path in sorted(glob.glob(BATCH_GLOB)):
        with open(path, "r", encoding="utf-8") as f:
            batch = json.load(f)
        for song in batch:
            sid = str(song.get("id", ""))
            raw = song.get("lyrics", "") or ""
            titles[sid] = song.get("title", "")
            lyrics_len[sid] = len(raw)
            lyrics_text[sid] = raw
    return titles, lyrics_len, lyrics_text


def normalize_title(title):
    # type: (str) -> str
    """Normalize title for duplicate detection."""
    t = title.lower()
    # Remove parenthetical/bracketed tags — covers remixes, versions, mixes, etc.
    t = re.sub(
        r"\s*[\(\[](remix|live|versión?\s*\w*|version\s*\w*|"
        r"headphone\s*mix|mixed|clean\s*version|radio\s*version|"
        r"dolby\s*atmos\s*version|concert\s*version|"
        r"primera\s*versión?|original\s*version|"
        r"instrumental|acoustic|"
        r"\w+\s+remix|"  # Named remixes like "Dillon Francis Remix"
        r"\w+\s+edit|"   # Named edits like "Loud Luxury Edit"
        r"fitness[^)\]]*|vision[^)\]]*|nye\s*\d*|"  # Gym/DJ mixes
        r"[a-z]+\s+\d{4}|"  # Month+year like "April 2023"
        r"\d{4})[\)\]]",
        "", t, flags=re.IGNORECASE,
    )
    # Remove trailing tags without parens
    t = re.sub(r"\s*-\s*en vivo\s*$", "", t)
    t = re.sub(r"\s*\*\s*$", "", t)
    # Remove year suffixes like "(2023)"
    t = re.sub(r"\s*\(\d{4}\)\s*$", "", t)
    t = t.strip()
    return t


def lyrics_hash(text):
    # type: (str) -> str
    """Hash lyrics text for exact-match duplicate detection."""
    # Normalize whitespace before hashing
    normalized = " ".join(text.split()).strip().lower()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]


def is_placeholder(lyrics):
    # type: (str) -> bool
    """Check if lyrics are a Genius placeholder (not real content)."""
    if not lyrics or len(lyrics.strip()) < 50:
        return True
    # Check for common placeholder patterns
    if PLACEHOLDER_RE.search(lyrics[:200]):
        return True
    return False


def detect_duplicates(songs, lyrics_len, lyrics_text):
    # type: (Dict[str, str], Dict[str, int], Dict[str, str]) -> Tuple[Dict[str, str], Set[str]]
    """
    Detect duplicates via three methods:
      1. Title normalization (remixes, live versions, etc.)
      2. Exact lyrics match (same text, different IDs)
      3. Placeholder lyrics (no real content)

    Returns (duplicates, placeholders):
      duplicates: {duplicate_id: keep_id}
      placeholders: set of song IDs with placeholder lyrics
    """
    # --- Method 1: Title-based grouping ---
    title_groups = defaultdict(list)  # type: Dict[str, List[Tuple[str, str]]]
    for sid, title in songs.items():
        norm = normalize_title(title)
        title_groups[norm].append((sid, title))

    duplicates = {}  # type: Dict[str, str]
    for norm, entries in title_groups.items():
        if len(entries) <= 1:
            continue
        # Prefer the oldest version (lowest ID) — that's usually the original.
        # Remix verses are from featured artists, not the primary artist.
        # Fall back to most lyrics only if the oldest has no real content.
        entries.sort(key=lambda x: int(x[0]))
        # If oldest has no lyrics, pick the one with most lyrics instead
        if lyrics_len.get(entries[0][0], 0) < 100:
            entries.sort(key=lambda x: (-lyrics_len.get(x[0], 0), int(x[0])))
        keep_id = entries[0][0]
        for sid, title in entries[1:]:
            if sid not in duplicates:  # don't overwrite if already marked
                duplicates[sid] = keep_id

    # --- Method 2: Exact lyrics match ---
    # Only for songs with real lyrics (>200 chars)
    hash_groups = defaultdict(list)  # type: Dict[str, List[str]]
    for sid, text in lyrics_text.items():
        if len(text) > 200 and sid not in duplicates:
            h = lyrics_hash(text)
            hash_groups[h].append(sid)

    for h, sids in hash_groups.items():
        if len(sids) <= 1:
            continue
        # Keep the one with lowest ID (original)
        sids.sort(key=int)
        keep_id = sids[0]
        for sid in sids[1:]:
            if sid not in duplicates:
                duplicates[sid] = keep_id

    # --- Method 3: Placeholder detection ---
    placeholders = set()  # type: Set[str]
    for sid, text in lyrics_text.items():
        if is_placeholder(text):
            placeholders.add(sid)

    return duplicates, placeholders


def load_or_create_dupes(songs, lyrics_len, lyrics_text, regenerate=False):
    # type: (Dict[str, str], Dict[str, int], Dict[str, str], bool) -> Tuple[Dict[str, str], Set[str]]
    """Load duplicate_songs.json if it exists, otherwise auto-detect and save."""
    if os.path.exists(DUPES_PATH) and not regenerate:
        with open(DUPES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        dupes = {}
        for k, v in data.get("duplicates", {}).items():
            if isinstance(v, dict):
                dupes[k] = v["keep"]
            else:
                dupes[k] = v
        placeholders = set(data.get("placeholders", []))
        print("  Loaded %d duplicates + %d placeholders from %s" %
              (len(dupes), len(placeholders), DUPES_PATH))
        return dupes, placeholders

    dupes, placeholders = detect_duplicates(songs, lyrics_len, lyrics_text)

    # Build readable output
    output = {
        "description": "Duplicate song mappings and placeholder songs to exclude.",
        "duplicates": {},
        "placeholders": sorted(placeholders),
        "stats": {
            "total_songs": len(songs),
            "duplicates": len(dupes),
            "placeholders": len(placeholders),
            "unique_songs": len(songs) - len(dupes) - len(placeholders - set(dupes.keys())),
        },
    }  # type: Dict

    for dup_id, keep_id in sorted(dupes.items(), key=lambda x: int(x[0])):
        output["duplicates"][dup_id] = {
            "keep": keep_id,
            "duplicate_title": songs.get(dup_id, ""),
            "original_title": songs.get(keep_id, ""),
        }

    with open(DUPES_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("  Auto-detected %d duplicates + %d placeholders, wrote %s" %
          (len(dupes), len(placeholders), DUPES_PATH))
    print("  Review and edit this file to correct any false positives.")

    return dupes, placeholders


def dedup_evidence(evidence, exclude_ids):
    # type: (list, Set[str]) -> Tuple[list, int, int]
    """
    Remove examples from excluded songs and recount corpus frequencies.
    Returns (updated_evidence, examples_removed, words_removed).
    """
    examples_removed = 0
    words_removed = 0
    updated = []

    for entry in evidence:
        examples = entry.get("examples", [])
        original_count = len(examples)

        # Filter out examples from excluded songs
        kept = []
        for ex in examples:
            ex_id = ex.get("id", "")
            song_id = ex_id.split(":")[0] if ":" in ex_id else ""
            if song_id not in exclude_ids:
                kept.append(ex)

        removed = original_count - len(kept)
        examples_removed += removed

        if not kept:
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
    parser.add_argument("--regenerate", action="store_true",
                        help="Regenerate duplicate_songs.json (ignore existing)")
    args = parser.parse_args()

    print("Loading songs from Genius batches...")
    songs, lyrics_len, lyrics_text = load_songs()
    print("  %d songs" % len(songs))

    print("\nDetecting duplicates...")
    dupes, placeholders = load_or_create_dupes(
        songs, lyrics_len, lyrics_text, regenerate=args.regenerate)

    if not dupes and not placeholders:
        print("No duplicates or placeholders found!")
        return

    # Combine all IDs to exclude
    exclude_ids = set(dupes.keys()) | placeholders
    print("  %d duplicate songs + %d placeholders = %d total to exclude" %
          (len(dupes), len(placeholders), len(exclude_ids)))

    # Show summary by category
    print("\n  Title-based duplicates (sample):")
    shown = 0
    for dup_id in sorted(dupes.keys(), key=int)[:8]:
        keep = dupes[dup_id]
        print("    %s (%s) -> %s (%s)" %
              (dup_id, songs.get(dup_id, "?")[:40], keep, songs.get(keep, "?")[:40]))
        shown += 1
    if len(dupes) > shown:
        print("    ... +%d more" % (len(dupes) - shown))

    if placeholders:
        print("\n  Placeholders (sample):")
        for sid in sorted(placeholders, key=int)[:8]:
            print("    %s (%s)" % (sid, songs.get(sid, "?")[:50]))
        if len(placeholders) > 8:
            print("    ... +%d more" % (len(placeholders) - 8))

    if not os.path.exists(EVIDENCE_PATH):
        print("\n  Evidence file not found (%s) — skipping evidence dedup." % EVIDENCE_PATH)
        print("  Run step 2 first, then re-run this script.")
        return

    print("\nLoading evidence...")
    with open(EVIDENCE_PATH, "r", encoding="utf-8") as f:
        evidence = json.load(f)
    print("  %d words, %d total examples" %
          (len(evidence), sum(len(e.get("examples", [])) for e in evidence)))

    updated, ex_removed, words_removed = dedup_evidence(evidence, exclude_ids)

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
        print("Re-run steps 2d, 3, 4 to propagate changes.")


if __name__ == "__main__":
    main()
