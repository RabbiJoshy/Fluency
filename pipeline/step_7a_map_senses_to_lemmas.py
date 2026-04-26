#!/usr/bin/env python3
"""
step_7a_map_senses_to_lemmas.py — Split surface-word assignments onto word|lemma keys.

Unified for normal mode and artist mode. Auto-discovers all available sense
sources by scanning sense_assignments/. For each source:

  1. Splits assignments into word|lemma keys using the sense IDs present in
     the sense menu. Writes `sense_assignments_lemma/{source}.json`.
  2. Routes every unassigned raw example to one `word|lemma` key based on
     its spaCy POS tag. Writes `unassigned_routing/{source}.json`.

If `--artist-dir PATH` is given, operates against that artist's layers
instead of normal mode's `Data/Spanish/layers`.

Inputs:
    {layers}/sense_menu/{source}.json
    {layers}/sense_assignments/{source}.json
    {layers}/examples_raw.json               (optional — if missing, routing
                                               output is empty)
    {layers}/example_pos.json                (optional — if missing, every
                                               unassigned example routes to
                                               the primary analysis)

Outputs:
    {layers}/sense_assignments_lemma/{source}.json
    {layers}/unassigned_routing/{source}.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

from util_7a_lemma_split import split_word_assignments, merge_method_maps
from util_5c_sense_menu_format import normalize_artist_sense_menu
from util_5c_sense_paths import (sense_menu_path, sense_assignments_path,
                                  sense_assignments_lemma_path, discover_sources)
from util_6a_assignment_format import load_assignments, dump_assignments
from util_pipeline_meta import make_meta, write_sidecar

STEP_VERSION = 3
STEP_VERSION_NOTES = {
    1: "split surface-word assignments onto word|lemma keys, multi-source merge",
    2: "route phrasebook self-analyses into inventory known_lemmas[0]",
    3: "unified normal/artist mode with POS-routed unassigned bucket",
}


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NORMAL_LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"

# spaCy POS tags we trust enough to route by. Everything else (PRON, CCONJ,
# DET, PHRASE, etc.) falls into the "untrusted" bucket that gets routed to
# the primary analysis.
_TRUSTED_ROUTING_POS = {"VERB", "NOUN", "ADJ", "ADV", "INTJ"}


def _load_known_lemmas_map(layers_dir: Path):
    """Return {surface_word_lower: known_lemmas list} from word_inventory.json.

    Missing or old-format inventories return {} — callers then fall back to
    SpanishDict's headword as the lemma (the original behaviour).
    """
    inv_path = layers_dir / "word_inventory.json"
    if not inv_path.exists():
        return {}
    with open(inv_path, encoding="utf-8") as f:
        inventory = json.load(f)
    out = {}
    for entry in inventory:
        if not isinstance(entry, dict):
            continue
        word = entry.get("word")
        lemmas = entry.get("known_lemmas")
        if isinstance(word, str) and isinstance(lemmas, list) and lemmas:
            out[word.lower()] = lemmas
    return out


def _route_unassigned_for_word(word, analyses, word_assignments, raw_examples, word_pos_data):
    """Return a dict of ``{lemma_key: [ex_idx, ...]}`` for examples that weren't
    claimed by any sense assignment, routed to whichever analysis best matches
    each example's spaCy POS tag. Analyses without a matching POS and examples
    with untrusted / missing tags fall back to the primary analysis (most
    assignments, tiebreak first)."""
    if not raw_examples:
        return {}

    assigned_indices = set()
    if isinstance(word_assignments, dict):
        for method_items in word_assignments.values():
            for item in method_items or []:
                assigned_indices.update(item.get("examples", []))
    elif isinstance(word_assignments, list):
        for item in word_assignments:
            assigned_indices.update(item.get("examples", []))

    # Build analysis metadata: lemma_key, pos -> sense count, assignment count
    analysis_meta = []
    for a in analyses or []:
        headword = (a.get("headword") or "").strip() or word
        lemma_key = "%s|%s" % (word, headword)
        senses = a.get("senses") or {}
        if isinstance(senses, dict):
            sense_list = list(senses.values())
        else:
            sense_list = senses
        pos_counts = {}
        for s in sense_list:
            p = (s.get("pos") or "").strip()
            if p:
                pos_counts[p] = pos_counts.get(p, 0) + 1
        analysis_meta.append({
            "lemma_key": lemma_key,
            "pos_counts": pos_counts,
        })

    if not analysis_meta:
        return {}

    # Assignment counts per lemma_key from word_assignments structure
    lemma_assignment_counts = {}
    if isinstance(word_assignments, dict):
        for method_items in word_assignments.values():
            for item in method_items or []:
                sense_id = item.get("sense")
                n_ex = len(item.get("examples", []))
                for a in analyses or []:
                    senses = a.get("senses") or {}
                    sense_ids = set(senses.keys()) if isinstance(senses, dict) else set()
                    if sense_id in sense_ids:
                        headword = (a.get("headword") or "").strip() or word
                        lemma_key = "%s|%s" % (word, headword)
                        lemma_assignment_counts[lemma_key] = (
                            lemma_assignment_counts.get(lemma_key, 0) + n_ex
                        )
                        break

    def _assignments(meta):
        return lemma_assignment_counts.get(meta["lemma_key"], 0)

    primary_meta = max(analysis_meta, key=_assignments) if analysis_meta else None

    routing = {}
    for ex_idx in range(len(raw_examples)):
        if ex_idx in assigned_indices:
            continue
        ex_pos = word_pos_data.get(str(ex_idx)) if isinstance(word_pos_data, dict) else None
        chosen = None
        if ex_pos and ex_pos in _TRUSTED_ROUTING_POS:
            candidates = [m for m in analysis_meta if m["pos_counts"].get(ex_pos)]
            if candidates:
                candidates.sort(
                    key=lambda m: (-m["pos_counts"].get(ex_pos, 0), -_assignments(m))
                )
                chosen = candidates[0]
        if chosen is None:
            chosen = primary_meta
        if chosen is not None:
            routing.setdefault(chosen["lemma_key"], []).append(ex_idx)
    return routing


def process_source(source, layers_dir: Path, known_lemmas_by_word, examples_raw, example_pos):
    """Process one sense source: split + unassigned routing."""
    menu_file = sense_menu_path(layers_dir, source)
    assignments_file = sense_assignments_path(layers_dir, source)
    output_file = sense_assignments_lemma_path(layers_dir, source)
    routing_file = layers_dir / "unassigned_routing" / ("%s.json" % source)

    if not menu_file.exists():
        print(f"  WARNING: sense menu not found for {source}: {menu_file}")
        return
    if not assignments_file.exists():
        print(f"  WARNING: assignments not found for {source}: {assignments_file}")
        return

    with open(menu_file, encoding="utf-8") as f:
        menu = normalize_artist_sense_menu(json.load(f))
    assignments = load_assignments(assignments_file)

    remapped = {}
    routing = {}
    changed = 0
    fallbacks = 0
    routed_words = 0

    for word, raw_value in assignments.items():
        analyses = menu.get(word, [])
        known = known_lemmas_by_word.get(word.lower())
        split = split_word_assignments(word, analyses, raw_value, known_lemmas=known)

        if len(split) != 1 or next(iter(split.keys())) != "%s|%s" % (word, word):
            changed += 1
        elif analyses and any(
            (a.get("headword") or "").strip() and a.get("headword") != word
            for a in analyses
        ):
            fallbacks += 1

        for target_key, value in split.items():
            if target_key in remapped:
                remapped[target_key] = merge_method_maps(remapped[target_key], value)
            else:
                remapped[target_key] = value

        # Route unassigned examples to the best-matching analysis.
        raw_exs = examples_raw.get(word, [])
        word_pos = example_pos.get(word, {})
        word_routing = _route_unassigned_for_word(
            word, analyses, raw_value, raw_exs, word_pos,
        )
        if word_routing:
            routed_words += 1
            for lemma_key, indices in word_routing.items():
                routing.setdefault(lemma_key, []).extend(indices)

    # Deduplicate routing indices per lemma (sorted for stability).
    routing = {k: sorted(set(v)) for k, v in routing.items() if v}

    output_file.parent.mkdir(parents=True, exist_ok=True)
    dump_assignments(remapped, output_file)
    write_sidecar(output_file, make_meta("map_senses_to_lemmas", STEP_VERSION, extra={"source": source}))

    routing_file.parent.mkdir(parents=True, exist_ok=True)
    with open(routing_file, "w", encoding="utf-8") as f:
        json.dump(routing, f, ensure_ascii=False, indent=2)
    write_sidecar(routing_file, make_meta("map_senses_to_lemmas", STEP_VERSION,
                                          extra={"source": source, "output": "unassigned_routing"}))

    print(f"  [{source}] {assignments_file.name} -> {output_file}")
    print(f"    input keys: {len(assignments)}, output keys: {len(remapped)}, "
          f"remapped: {changed}", end="")
    if fallbacks:
        print(f", fallbacks: {fallbacks}", end="")
    print(f", routed_words: {routed_words}")


def main():
    parser = argparse.ArgumentParser(description="Step 7a: map sense assignments to word|lemma keys")
    parser.add_argument("--artist-dir", type=str, default=None,
                        help="If set, operate against this artist's layers instead of normal mode.")
    parser.add_argument("--language", choices=["spanish", "french"], default="spanish",
                        help="Target language for normal-mode paths (default: spanish). "
                             "Ignored when --artist-dir is set.")
    args = parser.parse_args()

    if args.artist_dir:
        layers_dir = Path(os.path.abspath(args.artist_dir)) / "data" / "layers"
        print(f"Artist mode: {args.artist_dir}")
    else:
        layers_dir = PROJECT_ROOT / "Data" / args.language.capitalize() / "layers"
        print(f"Normal mode ({args.language})")

    sources = discover_sources(layers_dir, "sense_assignments")
    if not sources:
        print("No sense assignment sources found in %s" % (layers_dir / "sense_assignments"))
        sys.exit(1)

    known_lemmas_by_word = _load_known_lemmas_map(layers_dir)
    if known_lemmas_by_word:
        print(f"Loaded known_lemmas for {len(known_lemmas_by_word)} surface words")

    # Load raw examples + POS tags (optional — if missing, routing degrades).
    examples_raw = {}
    example_pos = {}
    examples_path = layers_dir / "examples_raw.json"
    pos_path = layers_dir / "example_pos.json"
    if examples_path.exists():
        with open(examples_path, encoding="utf-8") as f:
            examples_raw = json.load(f)
        print(f"examples_raw: {len(examples_raw)} words")
    else:
        print(f"examples_raw.json not found — unassigned_routing will be empty")
    if pos_path.exists():
        with open(pos_path, encoding="utf-8") as f:
            example_pos = json.load(f)
        example_pos.pop("_example_ids", None)
        print(f"example_pos: {len(example_pos)} words")
    else:
        print(f"example_pos.json not found — unassigned examples route to primary analysis")

    print(f"Consolidating {len(sources)} source(s): {', '.join(sources)}")
    for source in sources:
        process_source(source, layers_dir, known_lemmas_by_word, examples_raw, example_pos)


if __name__ == "__main__":
    main()
