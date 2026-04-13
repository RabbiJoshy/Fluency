#!/usr/bin/env python3
"""
refine_pos.py — Post-process sense assignments using spaCy POS tagging.

Corrects cross-POS misassignments: if the bi-encoder assigned an example to a
VERB sense but spaCy says the word is a NOUN in that sentence, move the example
to the most-assigned NOUN sense instead.

Works on both normal-mode and artist-mode assignments. Reads/writes the same
sense_assignments file — it's a refinement layer, not a competing method.

For words where POS fully disambiguates (every sense has a unique POS), this
can assign examples with no classifier at all.

Usage:
    python3 pipeline/refine_pos.py                          # normal mode
    python3 pipeline/refine_pos.py --artist-dir Artists/Bad\ Bunny  # artist mode
    python3 pipeline/refine_pos.py --dry-run                # report only
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from method_priority import assign_sense_ids
from artist.sense_menu_format import normalize_artist_sense_menu, resolve_analysis_for_assignments

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# spaCy POS → our POS scheme
_SPACY_POS_MAP = {
    "NOUN": "NOUN", "VERB": "VERB", "ADJ": "ADJ", "ADV": "ADV",
    "ADP": "ADP", "DET": "DET", "PRON": "PRON", "CCONJ": "CCONJ",
    "SCONJ": "CCONJ", "INTJ": "INTJ", "NUM": "NUM", "PART": "PART",
    "AUX": "VERB",  # auxiliary verbs are verbs
}


def load_spacy():
    """Load spaCy with Spanish model."""
    import spacy
    for model in ["es_core_news_sm", "es_core_news_md", "es_core_news_lg"]:
        try:
            return spacy.load(model, disable=["ner"])
        except OSError:
            continue
    print("ERROR: No Spanish spaCy model found. Install with:")
    print("  .venv/bin/python3 -m spacy download es_core_news_sm")
    sys.exit(1)


def tag_examples(nlp, word, lemma, examples, example_indices):
    """Tag each example sentence and return POS for the target word.

    Returns dict {example_index: our_pos} for examples where the word was found.
    """
    results = {}
    word_lower = word.lower()
    lemma_lower = lemma.lower()

    # Batch process for efficiency
    texts = []
    idx_map = []
    for ei in example_indices:
        if ei < len(examples):
            text = examples[ei].get("target", examples[ei].get("spanish", ""))
            if text:
                texts.append(text)
                idx_map.append(ei)

    if not texts:
        return results

    for doc, ei in zip(nlp.pipe(texts, batch_size=64), idx_map):
        for token in doc:
            tok_lower = token.text.lower()
            lem_lower = token.lemma_.lower()
            if tok_lower == word_lower or lem_lower == lemma_lower or lem_lower == word_lower:
                mapped = _SPACY_POS_MAP.get(token.pos_)
                if mapped:
                    results[ei] = mapped
                break

    return results


def refine_assignments(nlp, senses_data, assignments, examples_data, inventory,
                       artist_mode=False, dry_run=False):
    """Refine sense assignments using POS tagging.

    Produces a SEPARATE corrections dict (not in-place). Only includes words
    where POS tagging changed at least one example's assignment.

    Returns (corrections_dict, corrected_count, skipped_count,
             fully_disambiguated_count, words_touched).
    """
    corrections = {}  # key -> {method: [{sense, examples}]}
    corrected = 0
    fully_disambiguated = 0
    skipped = 0
    words_touched = 0

    # Build inventory lookup
    if artist_mode:
        senses_data = normalize_artist_sense_menu(senses_data)
        # Artist mode: bare word keys, no hex IDs
        inv_words = {entry["word"].lower() for entry in inventory}
    else:
        # Normal mode: word_id -> (word, lemma)
        id_to_info = {}
        for entry in inventory:
            wid = entry["id"]
            id_to_info[wid] = (entry["word"], entry.get("lemma", entry["word"]))

    for key, methods in assignments.items():
        if not isinstance(methods, dict):
            continue

        # Resolve senses: artist uses bare word key, normal uses word|lemma
        word, lemma = key.split("|", 1) if "|" in key else (key, key)

        # Try multiple sense key formats
        senses = None
        if artist_mode:
            analysis = resolve_analysis_for_assignments(senses_data, word, methods)
            s = analysis.get("senses", {})
            if isinstance(s, dict):
                senses = list(s.values())
        else:
            for skey in [key, "%s|%s" % (word, lemma)]:
                s = senses_data.get(skey)
                if isinstance(s, list) and len(s) >= 2:
                    senses = s
                    break
                elif isinstance(s, dict):
                    senses = list(s.values())
                    if len(senses) >= 2:
                        break
                    senses = None

        if not senses:
            continue

        # Check if senses span multiple POS
        sense_poses = [s["pos"] for s in senses]
        unique_pos = set(sense_poses)
        if len(unique_pos) < 2:
            continue  # all same POS, nothing to refine

        # Build sense ID → pos mapping
        id_map = assign_sense_ids(senses)
        id_list = list(id_map.keys())
        sid_to_pos = {}
        for sid, sense in id_map.items():
            sid_to_pos[sid] = sense["pos"]

        # Get examples
        if artist_mode:
            # Artist: examples keyed by bare word
            examples = examples_data.get(word, [])
        else:
            # Normal: examples keyed by hex ID
            word_id = None
            for wid, (w, l) in id_to_info.items():
                if w.lower() == word.lower() and l.lower() == lemma.lower():
                    word_id = wid
                    break
            if word_id is None:
                skipped += 1
                continue
            examples = examples_data.get(word_id, [])

        if not examples:
            skipped += 1
            continue

        # Collect all example indices across all methods
        all_example_indices = set()
        for method_assigns in methods.values():
            for a in method_assigns:
                all_example_indices.update(a.get("examples", []))

        # Tag examples with spaCy
        pos_tags = tag_examples(nlp, word, lemma, examples, sorted(all_example_indices))
        if not pos_tags:
            skipped += 1
            continue

        # Find the best method (we'll refine its assignments)
        from method_priority import METHOD_PRIORITY
        best_method = max(methods.keys(),
                          key=lambda m: METHOD_PRIORITY.get(m, -1))
        best_assigns = methods[best_method]

        # Count examples per sense (for "most common" fallback)
        sense_example_counts = Counter()
        for a in best_assigns:
            sense_example_counts[a.get("sense", "")] += len(a.get("examples", []))

        # Build POS → most-assigned-sense mapping
        pos_to_best_sense = {}
        for pos in unique_pos:
            # Find senses with this POS, pick the one with most examples
            candidates = [(sid, sense_example_counts.get(sid, 0))
                          for sid, p in sid_to_pos.items() if p == pos]
            if candidates:
                best_sid = max(candidates, key=lambda x: x[1])[0]
                pos_to_best_sense[pos] = best_sid

        # Now check each example: is it assigned to the right POS?
        word_corrected = 0
        new_sense_examples = defaultdict(list)

        for a in best_assigns:
            sid = a.get("sense", "")
            assigned_pos = sid_to_pos.get(sid, "")
            for ei in a.get("examples", []):
                tagged_pos = pos_tags.get(ei)
                if tagged_pos and tagged_pos != assigned_pos:
                    # POS mismatch — reassign to best sense with correct POS
                    correct_sid = pos_to_best_sense.get(tagged_pos)
                    if correct_sid and correct_sid != sid:
                        new_sense_examples[correct_sid].append(ei)
                        word_corrected += 1
                        continue
                # Keep original assignment
                new_sense_examples[sid].append(ei)

        if word_corrected > 0:
            corrected += word_corrected
            words_touched += 1

            if len(unique_pos) == len(senses):
                fully_disambiguated += 1

            # Build corrected entry for the output layer
            new_assigns = []
            for sid in id_list:
                exs = new_sense_examples.get(sid, [])
                if exs:
                    new_assigns.append({"sense": sid, "examples": sorted(exs)})
            corrections[key] = {"pos-" + best_method: new_assigns}

    return corrections, corrected, skipped, fully_disambiguated, words_touched


def main():
    parser = argparse.ArgumentParser(
        description="Refine sense assignments using spaCy POS tagging")
    parser.add_argument("--artist-dir", type=str, default=None,
                        help="Artist directory (e.g. Artists/Bad Bunny)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report corrections without writing")
    args = parser.parse_args()

    print("Loading spaCy...")
    nlp = load_spacy()
    print("  Model: %s" % nlp.meta["name"])

    if args.artist_dir:
        # Artist mode
        layers_dir = os.path.join(args.artist_dir, "data", "layers")
        assign_path = os.path.join(layers_dir, "sense_assignments_wiktionary.json")
        if not os.path.exists(assign_path):
            assign_path = os.path.join(layers_dir, "sense_assignments.json")
        examples_path = os.path.join(layers_dir, "examples_raw.json")
        # Artist senses from shared + artist layers
        senses_path = os.path.join(layers_dir, "sense_menu.json")
        shared_senses_path = os.path.join(PROJECT_ROOT, "Data", "Spanish",
                                           "layers", "sense_menu.json")
        inv_path = os.path.join(layers_dir, "word_inventory.json")
    else:
        # Normal mode
        layers = PROJECT_ROOT / "Data" / "Spanish" / "layers"
        assign_path = str(layers / "sense_assignments.json")
        examples_path = str(layers / "examples_raw.json")
        senses_path = str(layers / "sense_menu.json")
        shared_senses_path = None
        inv_path = str(layers / "word_inventory.json")

    print("Loading data...")
    with open(assign_path, encoding="utf-8") as f:
        assignments = json.load(f)
    print("  Assignments: %d entries" % len(assignments))

    with open(examples_path, encoding="utf-8") as f:
        examples_data = json.load(f)
    print("  Examples: %d entries" % len(examples_data))

    with open(senses_path, encoding="utf-8") as f:
        senses_data = json.load(f)
    # Merge shared senses for artist mode
    if shared_senses_path and os.path.exists(shared_senses_path):
        with open(shared_senses_path, encoding="utf-8") as f:
            shared = json.load(f)
        for k, v in shared.items():
            if k not in senses_data:
                senses_data[k] = v
    print("  Senses: %d entries" % len(senses_data))

    with open(inv_path, encoding="utf-8") as f:
        inventory = json.load(f)
    print("  Inventory: %d entries" % len(inventory))

    # Filter to multi-POS words
    multi_pos = sum(1 for k, s in senses_data.items()
                    if isinstance(s, list) and len(s) >= 2
                    and len(set(x["pos"] for x in s)) >= 2)
    print("  Multi-POS words in senses: %d" % multi_pos)

    print("\nRefining with POS tagging%s..." % (" (dry run)" if args.dry_run else ""))
    corrections, corrected, skipped, fully_disambiguated, words_touched = refine_assignments(
        nlp, senses_data, assignments, examples_data, inventory,
        artist_mode=bool(args.artist_dir), dry_run=args.dry_run)

    print("\n%s" % ("=" * 55))
    print("POS REFINEMENT RESULTS")
    print("=" * 55)
    print("Words checked:              %6d" % (words_touched + skipped))
    print("Words with corrections:     %6d" % words_touched)
    print("Examples reassigned:        %6d" % corrected)
    print("Fully POS-disambiguated:    %6d" % fully_disambiguated)
    print("Skipped (no examples/match):%6d" % skipped)

    # Write corrections to a separate layer file
    output_path = os.path.join(os.path.dirname(assign_path),
                               "sense_assignments_pos.json")

    if not args.dry_run and corrections:
        print("\nWriting %s (%d entries)..." % (output_path, len(corrections)))
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(corrections, f, ensure_ascii=False, indent=2)
        print("  Original assignments untouched at %s" % os.path.basename(assign_path))
        print("  Done.")
    elif args.dry_run and corrected > 0:
        print("\nDry run — no changes written. Remove --dry-run to apply.")
        print("  Would write to: %s" % output_path)


if __name__ == "__main__":
    main()
