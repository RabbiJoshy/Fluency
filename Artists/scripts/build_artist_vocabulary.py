#!/usr/bin/env python3
"""
build_artist_vocabulary.py — Assemble final artist vocabulary output from monolith.

Reads the artist monolith vocabulary and produces the split files for the front end:
  - {Name}vocabulary.index.json  (compact: id, corpus_count, sense_frequencies)
  - {Name}vocabulary.examples.json (examples keyed by ID)

When a shared master vocabulary exists, the index is aligned to master senses
(sense_frequencies parallel the master's senses array). Without a master, falls
back to a legacy split that preserves full meanings in the index.

This is the builder step in the layered architecture. Currently it reads the
monolith produced by steps 6-8, but will eventually read layer files directly.

Usage (from project root):
    .venv/bin/python3 Artists/scripts/build_artist_vocabulary.py --artist-dir Artists/BadBunny
"""

import json
import os
import sys
import argparse

from _artist_config import add_artist_arg, load_artist_config


def build_master_split(entries, master, vocab_path, master_path):
    """Build per-artist index and examples aligned to the master vocabulary.

    Also updates the master with any new MWE memberships from this artist.
    """
    base = vocab_path.rsplit(".", 1)[0]
    index_path = base + ".index.json"
    examples_path = base + ".examples.json"

    # Update master with any MWE changes
    for entry in entries:
        fid = entry.get("id")
        if not fid or fid not in master:
            continue
        m = master[fid]
        for mwe in entry.get("mwe_memberships", []):
            expr = mwe.get("expression", "")
            trans = mwe.get("translation", "")
            exists = any(
                e["expression"] == expr and e["translation"] == trans
                for e in m.get("mwe_memberships", [])
            )
            if not exists:
                if "mwe_memberships" not in m:
                    m["mwe_memberships"] = []
                m["mwe_memberships"].append({"expression": expr, "translation": trans})

    # Write updated master
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False)
    print(f"  Master updated: {len(master)} entries -> {master_path}")

    # Build index and examples parallel to master senses
    index = []
    examples = {}

    for entry in entries:
        fid = entry.get("id")
        if not fid:
            continue
        m = master.get(fid)
        if not m:
            continue

        sense_freq = []
        sense_examples = []
        total_ex = 0

        for sense in m.get("senses", []):
            matching = None
            for meaning in entry.get("meanings", []):
                if meaning.get("pos") == sense["pos"] and meaning.get("translation") == sense["translation"]:
                    matching = meaning
                    break
            exs = matching.get("examples", []) if matching else []
            sense_examples.append(exs)
            total_ex += len(exs)

        for exs in sense_examples:
            sense_freq.append(round(len(exs) / total_ex, 2) if total_ex > 0 else 0)

        mwe_examples = []
        for master_mwe in m.get("mwe_memberships", []):
            matched = []
            for entry_mwe in entry.get("mwe_memberships", []):
                if (entry_mwe.get("expression") == master_mwe["expression"]
                        and entry_mwe.get("translation") == master_mwe["translation"]):
                    matched = entry_mwe.get("examples", [])
                    break
            mwe_examples.append(matched)

        index.append({
            "id": fid,
            "corpus_count": entry.get("corpus_count", 0),
            "most_frequent_lemma_instance": entry.get("most_frequent_lemma_instance", False),
            "sense_frequencies": sense_freq,
        })

        ex_entry = {"m": sense_examples}
        if any(mwe_examples):
            ex_entry["w"] = mwe_examples
        examples[fid] = ex_entry

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False)

    idx_size = os.path.getsize(index_path)
    ex_size = os.path.getsize(examples_path)
    print(f"  Split files written:")
    print(f"    {index_path}: {idx_size:,} bytes")
    print(f"    {examples_path}: {ex_size:,} bytes")


def build_legacy_split(entries, vocab_path):
    """Fallback split when no master vocabulary exists.

    Index contains full meanings (without examples). Examples keyed by ID.
    """
    base = vocab_path.rsplit(".", 1)[0]
    index_path = base + ".index.json"
    examples_path = base + ".examples.json"

    index = []
    examples = {}

    for entry in entries:
        idx_entry = {}
        for k, v in entry.items():
            if k in ("meanings", "mwe_memberships"):
                continue
            idx_entry[k] = v

        idx_entry["meanings"] = [
            {k: v for k, v in m.items() if k != "examples"}
            for m in entry.get("meanings", [])
        ]
        if entry.get("mwe_memberships"):
            idx_entry["mwe_memberships"] = [
                {k: v for k, v in mwe.items() if k != "examples"}
                for mwe in entry["mwe_memberships"]
            ]
        index.append(idx_entry)

        m_examples = [m.get("examples", []) for m in entry.get("meanings", [])]
        ex_entry = {"m": m_examples}
        if entry.get("mwe_memberships"):
            w_examples = [mwe.get("examples", []) for mwe in entry["mwe_memberships"]]
            if any(w_examples):
                ex_entry["w"] = w_examples
        examples[entry["id"]] = ex_entry

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False)

    idx_size = os.path.getsize(index_path)
    ex_size = os.path.getsize(examples_path)
    print(f"  Split files written:")
    print(f"    {index_path}: {idx_size:,} bytes")
    print(f"    {examples_path}: {ex_size:,} bytes")


def main():
    parser = argparse.ArgumentParser(description="Build artist vocabulary split files")
    add_artist_arg(parser)
    parser.add_argument("--master-path", type=str, default=None,
                        help="Path to shared master vocabulary (default: Artists/vocabulary_master.json)")
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    config = load_artist_config(artist_dir)
    vocab_path = os.path.join(artist_dir, config["vocabulary_file"])

    artists_dir = os.path.dirname(artist_dir)
    master_path = args.master_path or os.path.join(artists_dir, "vocabulary_master.json")

    if not os.path.isfile(vocab_path):
        print(f"ERROR: Vocabulary file not found: {vocab_path}")
        sys.exit(1)

    print(f"Loading {vocab_path}...")
    with open(vocab_path, "r", encoding="utf-8") as f:
        entries = json.load(f)
    print(f"  {len(entries)} entries")

    if os.path.isfile(master_path):
        print(f"Loading master vocabulary from {master_path}...")
        with open(master_path, "r", encoding="utf-8") as f:
            master = json.load(f)
        print(f"  {len(master)} master entries")
        build_master_split(entries, master, vocab_path, master_path)
    else:
        print(f"No master vocabulary at {master_path} — using legacy split format")
        build_legacy_split(entries, vocab_path)

    print("Done!")


if __name__ == "__main__":
    main()
