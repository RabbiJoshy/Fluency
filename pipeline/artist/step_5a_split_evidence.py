#!/usr/bin/env python3
"""
Step 5: Split vocab_evidence_merged.json into layer files.

Reads the merged evidence from step 3 and produces two layer files that
mirror the normal-mode layer schema:
  - word_inventory.json: word identity + corpus frequency
  - examples_raw.json: raw Spanish example lines (no English yet — step 6A adds that)

Usage (from project root):
    .venv/bin/python3 pipeline/artist/step_5a_split_evidence.py --artist-dir Artists/BadBunny

Inputs:
    data/elision_merge/vocab_evidence_merged.json

Outputs:
    data/layers/word_inventory.json
    data/layers/examples_raw.json
"""

import json
import os
import re
import sys
import argparse
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util_1a_artist_config import add_artist_arg, load_artist_config

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pipeline.util_pipeline_meta import (  # noqa: E402
    dependency_metadata,
    make_meta,
    write_sidecar,
)

# Bump when split-evidence logic or output schema changes.
STEP_VERSION = 6
STEP_VERSION_NOTES = {
    1: "split merged evidence into word_inventory + examples_raw, clitic orphan handling",
    2: "+ carry full-corpus distinct song_count into word_inventory",
    3: "+ retain vocalist provenance and stamp Spotify/variant example priority metadata",
    4: "+ retain per-track Spotify IDs and artists from playlist tracks.json",
    5: "+ carry stable segment/occurrence ledger references into legacy examples",
    6: "+ propagate ledger and corpus-profile dependency fingerprints",
}

_VARIANT_TITLE_RE = re.compile(
    r"\b(?:remix|remaster(?:ed)?|live|version|edit|acoustic|karaoke|sped\s+up|slowed)\b",
    re.IGNORECASE,
)
_EXAMPLE_META_KEYS = (
    "surface", "segment_id", "occurrence_ids",
    "vocalists", "sung_by_primary_artist",
    "artist", "spotify_track_id", "spotify_available", "is_variant",
)


def _track_key(value):
    """Normalize a Spotify/Genius title for playlist matching."""
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def load_playlist_track_metadata(artist_dir):
    """Read ``tracks.json`` as normalized title -> artist/Spotify-ID data.

    This source comes directly from Spotify before lyric scraping.  If a
    playlist contains the same title by different artists, omit that ambiguous
    title rather than attaching a wrong track to an example.
    """
    tracks_path = os.path.join(artist_dir, "tracks.json")
    if not os.path.isfile(tracks_path):
        return {}
    with open(tracks_path, "r", encoding="utf-8") as f:
        tracks = json.load(f).get("tracks", [])

    by_title = {}
    ambiguous_titles = set()
    for track in tracks:
        title_key = _track_key(track.get("title"))
        track_id = track.get("spotify_id")
        if not title_key or not track_id:
            continue
        metadata = {
            "artist": track.get("artist", ""),
            "spotify_track_id": track_id,
        }
        existing = by_title.get(title_key)
        if existing and existing != metadata:
            ambiguous_titles.add(title_key)
        else:
            by_title[title_key] = metadata
    for title_key in ambiguous_titles:
        by_title.pop(title_key, None)
    return by_title


def main():
    parser = argparse.ArgumentParser(description="Step 5: Split evidence into inventory + examples layers")
    add_artist_arg(parser)
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    merged_path = os.path.join(artist_dir, "data", "elision_merge", "vocab_evidence_merged.json")
    layers_dir = os.path.join(artist_dir, "data", "layers")
    os.makedirs(layers_dir, exist_ok=True)

    spotify_tracks = {}
    spotify_path = os.path.join(artist_dir, "data", "spotify_tracks.json")
    if os.path.isfile(spotify_path):
        with open(spotify_path, "r", encoding="utf-8") as f:
            spotify_tracks = json.load(f)
    playlist_track_metadata = load_playlist_track_metadata(artist_dir)

    print(f"Loading {merged_path}...")
    with open(merged_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  {len(data)} entries")

    # Load previous examples to preserve order (keeps sense assignments stable)
    ex_path = os.path.join(layers_dir, "examples_raw.json")
    prev_examples = {}
    if os.path.isfile(ex_path):
        with open(ex_path, "r", encoding="utf-8") as f:
            prev_examples = json.load(f)
        print(f"  Previous examples_raw: {len(prev_examples)} words (preserving order)")

    inventory = []
    examples_raw = {}

    for entry in data:
        word = entry["word"]

        # Inventory entry: word identity + corpus stats
        inv_entry = {
            "word": word,
            "corpus_count": entry.get("corpus_count", 0),
            "song_count": entry.get("song_count", len(entry.get("song_ids", []))),
        }
        if entry.get("display_form"):
            inv_entry["display_form"] = entry["display_form"]
        if entry.get("variants"):
            inv_entry["variants"] = entry["variants"]

        inventory.append(inv_entry)

        # Examples: preserve previous order so sense assignment indices stay valid.
        # Keep previous examples that still exist in the corpus, then append new ones.
        raw_examples = entry.get("examples", [])
        if not raw_examples:
            continue

        for example in raw_examples:
            title = example.get("title", "")
            playlist_track = playlist_track_metadata.get(_track_key(title))
            if playlist_track:
                example["artist"] = playlist_track["artist"]
                example["spotify_track_id"] = playlist_track["spotify_track_id"]
            else:
                example.pop("spotify_track_id", None)
            example["spotify_available"] = bool(
                example.get("spotify_track_id") or spotify_tracks.get(title))
            example["is_variant"] = bool(_VARIANT_TITLE_RE.search(title))

        new_by_id = {ex["id"]: ex for ex in raw_examples}
        prev_word_examples = prev_examples.get(word, [])

        kept = []
        seen_ids = set()
        # First: keep previous examples in order if they still exist
        for prev_ex in prev_word_examples:
            eid = prev_ex.get("id", "")
            if eid in new_by_id:
                # Preserve index/order for sense assignments while refreshing
                # non-semantic example metadata from the rebuilt corpus.
                fresh = new_by_id[eid]
                for key in _EXAMPLE_META_KEYS:
                    if key in fresh:
                        prev_ex[key] = fresh[key]
                    else:
                        prev_ex.pop(key, None)
                kept.append(prev_ex)
                seen_ids.add(eid)

        # Then: append new examples not seen before
        for ex in raw_examples:
            if ex["id"] not in seen_ids:
                entry_dict = {
                    "id": ex["id"],
                    "spanish": ex["line"],
                    "title": ex.get("title", ""),
                }
                for key in _EXAMPLE_META_KEYS:
                    if key in ex:
                        entry_dict[key] = ex[key]
                kept.append(entry_dict)

        if kept:
            examples_raw[word] = kept

    # Orphan clitics: create synthetic entries for infinitives whose conjugated
    # form isn't in the inventory. Transfers clitic examples as the infinitive's
    # own examples so downstream steps (5c, 6) treat them as normal words.
    # Orphan = base verb doesn't appear standalone in this artist's corpus.
    # (step_4a used to write clitic_orphans explicitly; now detected inline.)
    routing_path = os.path.join(artist_dir, "data", "known_vocab", "word_routing.json")
    if os.path.isfile(routing_path):
        with open(routing_path, "r", encoding="utf-8") as f:
            routing = json.load(f)
        clitic_merge = routing.get("clitic_merge", {})
        original_inv_words = {e["word"].lower() for e in inventory}
        inv_words = set(original_inv_words)
        orphan_count = 0
        for clitic_word, base_verb in clitic_merge.items():
            if base_verb in original_inv_words:
                continue  # non-orphan — step_8b merges via clitic_data
            if base_verb in inv_words:
                # Another orphan already created this entry — just stack examples
                examples_raw.setdefault(base_verb, []).extend(
                    examples_raw.get(clitic_word, []))
            else:
                clitic_count = 0
                for entry in data:
                    if entry["word"].lower() == clitic_word:
                        clitic_count = entry.get("corpus_count", 0)
                        break
                inventory.append({
                    "word": base_verb,
                    "corpus_count": clitic_count,
                    "song_count": next((
                        entry.get("song_count", len(entry.get("song_ids", [])))
                        for entry in data if entry["word"].lower() == clitic_word
                    ), 0),
                })
                inv_words.add(base_verb)
                examples_raw[base_verb] = list(examples_raw.get(clitic_word, []))
            orphan_count += 1
        if orphan_count:
            print(f"  Orphan clitics: {orphan_count} → synthetic infinitive entries")

    # Write layers
    inv_path = os.path.join(layers_dir, "word_inventory.json")
    ex_path = os.path.join(layers_dir, "examples_raw.json")

    with open(inv_path, "w", encoding="utf-8") as f:
        json.dump(inventory, f, ensure_ascii=False, indent=2)
    with open(ex_path, "w", encoding="utf-8") as f:
        json.dump(examples_raw, f, ensure_ascii=False)
    upstream = dependency_metadata(merged_path)
    write_sidecar(inv_path, make_meta(
        "split_evidence", STEP_VERSION, extra=upstream))
    write_sidecar(ex_path, make_meta(
        "split_evidence", STEP_VERSION, extra=upstream))

    words_with_examples = sum(1 for exs in examples_raw.values() if exs)
    total_examples = sum(len(exs) for exs in examples_raw.values())

    print(f"\n  word_inventory: {len(inventory)} entries -> {inv_path}")
    print(f"  examples_raw: {words_with_examples} words, {total_examples} examples -> {ex_path}")


if __name__ == "__main__":
    main()
