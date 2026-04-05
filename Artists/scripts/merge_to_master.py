#!/usr/bin/env python3
"""
merge_to_master.py — Build/rebuild the shared master vocabulary from artist monoliths.

Usage (from project root):
    .venv/bin/python3 Artists/scripts/merge_to_master.py

Reads every artist's monolith vocabulary file, computes 6-char hex IDs, merges
senses by exact (pos, translation) match, and writes:
  - Artists/vocabulary_master.json           (shared master)
  - Per-artist .index.json and .examples.json (new split format)
  - Per-artist monolith .json                 (denormalized, for debugging)

Also validates that no two distinct word|lemma pairs collide on the same 6-char ID.
"""

import hashlib
import json
import os
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ARTISTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(ARTISTS_DIR)
MASTER_PATH = os.path.join(ARTISTS_DIR, "vocabulary_master.json")


def make_stable_id(word, lemma, used=None):
    # type: (str, str, set) -> str
    """6-char hex ID from md5(word|lemma). Falls back to suffix rehash on collision."""
    h = hashlib.md5((word + "|" + lemma).encode("utf-8")).hexdigest()
    base_id = h[:6]
    if used is None or base_id not in used:
        return base_id
    # Rare collision — rehash with suffix (same approach as old assign_unique_ids)
    suffix = 0
    final_id = base_id
    while final_id in used:
        suffix += 1
        final_id = hashlib.md5(
            (word + "|" + lemma + "|" + str(suffix)).encode("utf-8")
        ).hexdigest()[:6]
    return final_id


def discover_artists():
    # type: () -> list
    """Find all artist directories that have an artist.json and a monolith vocab file."""
    artists = []
    for name in sorted(os.listdir(ARTISTS_DIR)):
        artist_dir = os.path.join(ARTISTS_DIR, name)
        config_path = os.path.join(artist_dir, "artist.json")
        if not os.path.isfile(config_path):
            continue
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        vocab_file = config.get("vocabulary_file")
        if not vocab_file:
            continue
        vocab_path = os.path.join(artist_dir, vocab_file)
        if not os.path.isfile(vocab_path):
            print("  SKIP %s — vocabulary file not found: %s" % (name, vocab_path))
            continue
        artists.append({
            "name": config.get("name", name),
            "dir": artist_dir,
            "config": config,
            "vocab_path": vocab_path,
        })
    return artists


def assign_all_ids(artists):
    # type: (list) -> tuple
    """First pass: collect all unique word|lemma pairs across all artists,
    sort them deterministically, and assign 6-char hex IDs.

    Returns (word_lemma_to_id, artist_vocabs) where artist_vocabs is a list
    of (artist_info, vocab_list) tuples with loaded data.
    """
    all_pairs = set()  # type: set
    artist_vocabs = []

    for artist in artists:
        with open(artist["vocab_path"], "r", encoding="utf-8") as f:
            vocab = json.load(f)
        artist_vocabs.append((artist, vocab))
        for entry in vocab:
            all_pairs.add((entry["word"], entry["lemma"]))

    # Sort deterministically so collision reassignment is stable
    sorted_pairs = sorted(all_pairs)
    word_lemma_to_id = {}  # type: dict
    used_ids = set()  # type: set
    reassignments = 0

    for word, lemma in sorted_pairs:
        new_id = make_stable_id(word, lemma, used_ids)
        if new_id != hashlib.md5((word + "|" + lemma).encode("utf-8")).hexdigest()[:6]:
            reassignments += 1
            print("  Collision reassigned: %s|%s -> %s" % (word, lemma, new_id))
        used_ids.add(new_id)
        word_lemma_to_id[(word, lemma)] = new_id

    print("  %d unique word|lemma pairs, %d collision reassignments" % (
        len(word_lemma_to_id), reassignments))
    return word_lemma_to_id, artist_vocabs, reassignments


def build_master(artists):
    # type: (list) -> tuple
    """Build master vocabulary from artist monoliths.

    Returns (master_dict, per_artist_data, stats).
    master_dict: {id: {word, lemma, senses, flags, mwe_memberships}}
    per_artist_data: [{artist_info, entries: [{id, old_id, entry}]}]
    """
    print("\nAssigning IDs (deterministic, sorted)...")
    word_lemma_to_id, artist_vocabs, reassignment_count = assign_all_ids(artists)

    master = {}  # type: dict  # id -> master entry
    per_artist_data = []
    stats = {
        "total_entries": 0,
        "unique_words": 0,
        "new_senses_added": 0,
        "collision_reassignments": reassignment_count,
        "old_id_changes": 0,
    }

    for artist, vocab in artist_vocabs:
        print("\nProcessing %s..." % artist["name"])
        print("  %d entries" % len(vocab))
        stats["total_entries"] += len(vocab)

        artist_entries = []

        for entry in vocab:
            word = entry["word"]
            lemma = entry["lemma"]
            old_id = entry.get("id", "")
            new_id = word_lemma_to_id[(word, lemma)]

            if old_id != new_id:
                stats["old_id_changes"] += 1

            # Merge into master
            if new_id not in master:
                master[new_id] = {
                    "word": word,
                    "lemma": lemma,
                    "senses": [],
                    "is_english": entry.get("is_english", False),
                    "is_interjection": entry.get("is_interjection", False),
                    "is_propernoun": entry.get("is_propernoun", False),
                    "is_transparent_cognate": entry.get("is_transparent_cognate", False),
                    "display_form": entry.get("display_form"),
                    "mwe_memberships": [],
                }
                stats["unique_words"] += 1

            m = master[new_id]

            # Union flags (if any artist says true, keep true)
            for flag in ("is_english", "is_interjection", "is_propernoun", "is_transparent_cognate"):
                if entry.get(flag, False):
                    m[flag] = True

            # Prefer non-null display_form
            if entry.get("display_form") and not m.get("display_form"):
                m["display_form"] = entry["display_form"]

            # Merge senses by exact (pos, translation) match
            for meaning in entry.get("meanings", []):
                pos = meaning.get("pos", "X")
                translation = meaning.get("translation", "")
                # Check if this exact sense already exists
                existing_sense = None
                for s in m["senses"]:
                    if s["pos"] == pos and s["translation"] == translation:
                        existing_sense = s
                        break
                if not existing_sense:
                    m["senses"].append({"pos": pos, "translation": translation})
                    stats["new_senses_added"] += 1

            # Merge MWE memberships by exact (expression, translation) match
            for mwe in entry.get("mwe_memberships", []):
                expr = mwe.get("expression", "")
                trans = mwe.get("translation", "")
                exists = any(
                    existing["expression"] == expr and existing["translation"] == trans
                    for existing in m["mwe_memberships"]
                )
                if not exists:
                    m["mwe_memberships"].append({
                        "expression": expr,
                        "translation": trans,
                    })

            artist_entries.append({
                "id": new_id,
                "old_id": old_id,
                "entry": entry,
            })

        per_artist_data.append({
            "artist": artist,
            "entries": artist_entries,
        })

    return master, per_artist_data, stats


def write_artist_files(master, artist_data):
    # type: (dict, dict) -> None
    """Write per-artist index, examples, and monolith files in the new format."""
    artist = artist_data["artist"]
    entries = artist_data["entries"]
    vocab_path = artist["vocab_path"]

    # Build artist index and examples
    index = []
    examples = {}

    for ae in entries:
        new_id = ae["id"]
        entry = ae["entry"]
        m = master[new_id]

        # Compute sense_frequencies: for each master sense, what fraction of
        # this artist's examples map to it?
        sense_freq = []
        sense_examples = []
        total_examples = 0

        for sense in m["senses"]:
            # Find matching meaning in artist's entry
            matching_meaning = None
            for meaning in entry.get("meanings", []):
                if meaning.get("pos") == sense["pos"] and meaning.get("translation") == sense["translation"]:
                    matching_meaning = meaning
                    break
            if matching_meaning and matching_meaning.get("examples"):
                exs = matching_meaning["examples"]
                sense_examples.append(exs)
                total_examples += len(exs)
            else:
                sense_examples.append([])

        for exs in sense_examples:
            if total_examples > 0:
                sense_freq.append(round(len(exs) / total_examples, 2))
            else:
                sense_freq.append(0)

        # Build MWE examples parallel to master mwe_memberships
        mwe_examples = []
        for master_mwe in m["mwe_memberships"]:
            matched_mwe_ex = []
            for entry_mwe in entry.get("mwe_memberships", []):
                if (entry_mwe.get("expression") == master_mwe["expression"]
                        and entry_mwe.get("translation") == master_mwe["translation"]):
                    matched_mwe_ex = entry_mwe.get("examples", [])
                    break
            mwe_examples.append(matched_mwe_ex)

        index.append({
            "id": new_id,
            "corpus_count": entry.get("corpus_count", 0),
            "most_frequent_lemma_instance": entry.get("most_frequent_lemma_instance", False),
            "sense_frequencies": sense_freq,
        })

        ex_entry = {"m": sense_examples}
        if any(mwe_examples):
            ex_entry["w"] = mwe_examples
        examples[new_id] = ex_entry

    # Sort index by corpus_count descending (position = rank)
    index.sort(key=lambda e: -(e.get("corpus_count") or 0))

    # Write index
    base = vocab_path.rsplit(".", 1)[0]
    index_path = base + ".index.json"
    examples_path = base + ".examples.json"

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    print("  Index: %s (%d entries, %s bytes)" % (
        index_path, len(index), "{:,}".format(os.path.getsize(index_path))))

    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False)
    print("  Examples: %s (%s bytes)" % (
        examples_path, "{:,}".format(os.path.getsize(examples_path))))

    # Write denormalized monolith (master + artist data combined)
    monolith = []
    for idx_entry in index:
        new_id = idx_entry["id"]
        m = master[new_id]
        ex = examples.get(new_id, {"m": []})

        # Denormalize: rebuild the old-style entry
        meanings = []
        for i, sense in enumerate(m["senses"]):
            meaning = {
                "pos": sense["pos"],
                "translation": sense["translation"],
                "frequency": "%.2f" % idx_entry["sense_frequencies"][i] if i < len(idx_entry["sense_frequencies"]) else "0.00",
                "examples": ex["m"][i] if i < len(ex["m"]) else [],
            }
            meanings.append(meaning)

        mwe_memberships = []
        for i, master_mwe in enumerate(m["mwe_memberships"]):
            mwe = {
                "expression": master_mwe["expression"],
                "translation": master_mwe["translation"],
            }
            if ex.get("w") and i < len(ex["w"]):
                mwe["examples"] = ex["w"][i]
            mwe_memberships.append(mwe)

        mono_entry = {
            "id": new_id,
            "word": m["word"],
            "lemma": m["lemma"],
            "meanings": meanings,
            "most_frequent_lemma_instance": idx_entry["most_frequent_lemma_instance"],
            "is_english": m["is_english"],
            "is_interjection": m["is_interjection"],
            "is_propernoun": m["is_propernoun"],
            "is_transparent_cognate": m["is_transparent_cognate"],
            "corpus_count": idx_entry["corpus_count"],
            "display_form": m["display_form"],
            "mwe_memberships": mwe_memberships,
        }
        monolith.append(mono_entry)

    with open(vocab_path, "w", encoding="utf-8") as f:
        json.dump(monolith, f, ensure_ascii=False)
    print("  Monolith: %s (%d entries, %s bytes)" % (
        vocab_path, len(monolith), "{:,}".format(os.path.getsize(vocab_path))))


def validate(master, per_artist_data, stats):
    # type: (dict, list, dict) -> None
    """Print validation summary."""
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    print("Total entries across all artists: %d" % stats["total_entries"])
    print("Unique word|lemma pairs in master: %d" % stats["unique_words"])
    print("Total senses in master: %d" % sum(len(m["senses"]) for m in master.values()))
    print("IDs that changed (old 4-char -> new 6-char): %d" % stats["old_id_changes"])
    if stats["collision_reassignments"] > 0:
        print("Collision reassignments (different word|lemma -> same base hash, suffix used): %d" % stats["collision_reassignments"])
    else:
        print("Zero 6-char ID collisions — all clear!")

    # Cross-artist overlap analysis
    if len(per_artist_data) >= 2:
        print("\nCross-artist overlap:")
        all_sets = []
        for ad in per_artist_data:
            ids = set(ae["id"] for ae in ad["entries"])
            all_sets.append((ad["artist"]["name"], ids))
        for i in range(len(all_sets)):
            for j in range(i + 1, len(all_sets)):
                name_a, set_a = all_sets[i]
                name_b, set_b = all_sets[j]
                overlap = set_a & set_b
                print("  %s ∩ %s: %d shared words (of %d + %d)" % (
                    name_a, name_b, len(overlap), len(set_a), len(set_b)))

    # Check for words that had different old IDs but now share a new ID
    # (these were the "same word, different ID" bugs)
    print("\nOld-ID divergence check (same word|lemma, different old IDs across artists):")
    word_lemma_to_old_ids = defaultdict(set)
    for ad in per_artist_data:
        for ae in ad["entries"]:
            wl = (master[ae["id"]]["word"], master[ae["id"]]["lemma"])
            word_lemma_to_old_ids[wl].add(ae["old_id"])
    divergent = {wl: ids for wl, ids in word_lemma_to_old_ids.items() if len(ids) > 1}
    if divergent:
        print("  %d word|lemma pairs had different old IDs across artists (now unified)" % len(divergent))
        # Show a few examples
        for wl, ids in list(divergent.items())[:5]:
            print("    %s|%s: old IDs %s -> new ID %s" % (
                wl[0], wl[1], sorted(ids), make_stable_id(wl[0], wl[1])))
    else:
        print("  None found")


def main():
    print("Discovering artists...")
    artists = discover_artists()
    if not artists:
        print("No artists found in %s" % ARTISTS_DIR)
        sys.exit(1)
    print("Found %d artists: %s" % (len(artists), ", ".join(a["name"] for a in artists)))

    print("\nBuilding master vocabulary...")
    master, per_artist_data, stats = build_master(artists)

    # Write master
    print("\nWriting master vocabulary to %s..." % MASTER_PATH)
    with open(MASTER_PATH, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=None)
    master_size = os.path.getsize(MASTER_PATH)
    print("  %d entries, %s bytes" % (len(master), "{:,}".format(master_size)))

    # Write per-artist files
    for ad in per_artist_data:
        print("\nWriting files for %s..." % ad["artist"]["name"])
        write_artist_files(master, ad)

    # Validate
    validate(master, per_artist_data, stats)

    print("\nDone!")


if __name__ == "__main__":
    main()
