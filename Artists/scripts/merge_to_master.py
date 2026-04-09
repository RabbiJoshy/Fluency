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

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict

import spacy

from _artist_config import normalize_translation

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ARTISTS_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(ARTISTS_DIR)
MASTER_PATH = os.path.join(ARTISTS_DIR, "vocabulary_master.json")


# ---------------------------------------------------------------------------
# Sense dedup: spaCy morphology for canonical translation selection
# ---------------------------------------------------------------------------

_NLP = None  # type: ignore  # Lazy-loaded spaCy model

PERSON_PRONOUN = {
    ("1", "Sing"): "I",
    ("2", "Sing"): "you",
    ("3", "Sing"): "he/she",
    ("1", "Plur"): "we",
    ("2", "Plur"): "you all",
    ("3", "Plur"): "they",
}


def _get_nlp():
    # type: () -> object
    global _NLP
    if _NLP is None:
        print("Loading spaCy es_core_news_lg...")
        _NLP = spacy.load("es_core_news_lg")
    return _NLP


def choose_canonical_translation(word, translations, lemma=None):
    # type: (str, list, str) -> str
    """Pick the best translation for a merged sense using spaCy morphology.

    For conjugated verbs, builds '{pronoun} {base_verb}' from the
    morphological features.  For infinitives, keeps 'to {verb}'.
    For non-verbs, keeps the longest (most informative) translation.

    Falls back to longest translation when spaCy gives unreliable results
    (detected by comparing spaCy's lemma against our known lemma).
    """
    if not translations:
        return ""
    if len(translations) == 1:
        return translations[0]

    nlp = _get_nlp()
    doc = nlp(word)
    token = doc[0]
    morph = token.morph.to_dict()

    # Validate spaCy's analysis: if the lemma doesn't match what we
    # already know, the morphological features are unreliable.
    spacy_reliable = True
    if lemma and token.lemma_ != lemma:
        spacy_reliable = False

    if spacy_reliable and token.pos_ in ("VERB", "AUX"):
        verbform = morph.get("VerbForm", "")
        person = morph.get("Person")
        number = morph.get("Number")

        if verbform == "Inf":
            # Infinitive — prefer 'to X' form
            for t in translations:
                if t.lower().startswith("to "):
                    return t
            return "to " + normalize_translation(translations[0])

        if verbform == "Fin" and person and number:
            pronoun = PERSON_PRONOUN.get((person, number))
            if pronoun:
                # Build '{pronoun} {base_verb}' from normalized form
                base = normalize_translation(translations[0])
                if base:
                    return "%s %s" % (pronoun, base)

    # Non-verb, unreliable spaCy, or fallback: keep the longest translation
    return max(translations, key=len)


def make_stable_id(word, lemma, used=None):
    # type: (str, str, set) -> str
    """6-char hex ID from md5(word|lemma). On collision, picks next unused ID."""
    h = hashlib.md5((word + "|" + lemma).encode("utf-8")).hexdigest()
    base_id = h[:6]
    if used is None or base_id not in used:
        return base_id
    # Rare collision — just find an unused ID by walking the hash
    for start in range(0, len(h) - 5):
        candidate = h[start:start + 6]
        if candidate not in used:
            return candidate
    # Exhausted the hash — increment and try
    val = int(base_id, 16) + 1
    while True:
        candidate = format(val % 0xFFFFFF, '06x')
        if candidate not in used:
            return candidate
        val += 1


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
        "senses_merged": 0,
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

            # Merge senses by normalized (pos, translation) match
            for meaning in entry.get("meanings", []):
                pos = meaning.get("pos", "X")
                translation = meaning.get("translation", "")
                norm = normalize_translation(translation)
                # Check if a matching sense already exists
                existing_sense = None
                for s in m["senses"]:
                    if s["pos"] == pos and normalize_translation(s["translation"]) == norm:
                        existing_sense = s
                        break
                if existing_sense:
                    # Track candidate translations for later canonical selection
                    existing_sense.setdefault("_candidates", [existing_sense["translation"]])
                    if translation not in existing_sense["_candidates"]:
                        existing_sense["_candidates"].append(translation)
                        stats["senses_merged"] += 1
                        stats.setdefault("merge_details", []).append(
                            (word, new_id, pos, existing_sense["translation"], translation)
                        )
                else:
                    m["senses"].append({"pos": pos, "translation": translation})
                    stats["new_senses_added"] += 1

            # MWE memberships no longer stored in master (handled by build step)

            artist_entries.append({
                "id": new_id,
                "old_id": old_id,
                "entry": entry,
            })

        per_artist_data.append({
            "artist": artist,
            "entries": artist_entries,
        })

    # Resolve canonical translations for merged senses using spaCy
    merged_count = 0
    for wid, m in master.items():
        for sense in m["senses"]:
            candidates = sense.pop("_candidates", None)
            if candidates and len(candidates) > 1:
                old = sense["translation"]
                sense["translation"] = choose_canonical_translation(
                    m["word"], candidates, lemma=m.get("lemma")
                )
                if sense["translation"] != old:
                    merged_count += 1
    if merged_count:
        print("\nCanonical translations updated for %d senses" % merged_count)

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
            # Find matching meaning in artist's entry (normalized match)
            norm_sense = normalize_translation(sense["translation"])
            matching_meaning = None
            for meaning in entry.get("meanings", []):
                if meaning.get("pos") == sense["pos"] and normalize_translation(meaning.get("translation", "")) == norm_sense:
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

        # MWE examples from entry (not master)
        entry_mwes = entry.get("mwe_memberships", [])
        mwe_examples = [mwe.get("examples", []) for mwe in entry_mwes]

        idx_entry = {
            "id": new_id,
            "corpus_count": entry.get("corpus_count", 0),
            "most_frequent_lemma_instance": entry.get("most_frequent_lemma_instance", False),
            "sense_frequencies": sense_freq,
        }
        if entry_mwes:
            idx_entry["mwe_memberships"] = [
                {"expression": mwe["expression"], "translation": mwe.get("translation", "")}
                for mwe in entry_mwes
            ]
        index.append(idx_entry)

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

        # MWE memberships from index entry
        mwe_memberships = idx_entry.get("mwe_memberships", [])
        if ex.get("w"):
            for i, mwe in enumerate(mwe_memberships):
                if i < len(ex["w"]):
                    mwe["examples"] = ex["w"][i]

        mono_entry = {
            "id": new_id,
            "word": m["word"],
            "lemma": m["lemma"],
            "meanings": meanings,
            "most_frequent_lemma_instance": idx_entry["most_frequent_lemma_instance"],
            "is_english": m.get("is_english", False),
            "is_interjection": m.get("is_interjection", False),
            "is_propernoun": m.get("is_propernoun", False),
            "is_transparent_cognate": m.get("is_transparent_cognate", False),
            "corpus_count": idx_entry["corpus_count"],
            "display_form": m.get("display_form"),
        }
        if mwe_memberships:
            mono_entry["mwe_memberships"] = mwe_memberships
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
    print("Senses merged (normalized dedup): %d" % stats.get("senses_merged", 0))
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
    parser = argparse.ArgumentParser(description="Build/rebuild shared master vocabulary")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report sense merges without writing any files")
    args = parser.parse_args()

    print("Discovering artists...")
    artists = discover_artists()
    if not artists:
        print("No artists found in %s" % ARTISTS_DIR)
        sys.exit(1)
    print("Found %d artists: %s" % (len(artists), ", ".join(a["name"] for a in artists)))

    print("\nBuilding master vocabulary...")
    master, per_artist_data, stats = build_master(artists)

    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN — no files written")
        print("=" * 60)
        print("Senses merged: %d" % stats["senses_merged"])
        for word, wid, pos, existing, incoming in stats.get("merge_details", []):
            # Find the canonical translation chosen
            m = master[wid]
            canonical = ""
            for s in m["senses"]:
                if s["pos"] == pos and normalize_translation(s["translation"]) == normalize_translation(existing):
                    canonical = s["translation"]
                    break
            print("  %s [%s] %s: \"%s\" + \"%s\" -> \"%s\"" % (
                word, wid, pos, existing, incoming, canonical))
        validate(master, per_artist_data, stats)
        print("\nDry run complete. Run without --dry-run to write files.")
        return

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
