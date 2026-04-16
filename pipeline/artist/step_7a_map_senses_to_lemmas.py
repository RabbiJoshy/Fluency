#!/usr/bin/env python3
"""Consolidate artist sense assignments onto word|lemma keys.

This runs after step 6 and before later assembly/reranking steps.
It keeps the existing method structure, but splits a surface-form assignment
into per-analysis keys using the sense IDs present in the artist sense menu.

If an analysis has no explicit ``headword``, the step degrades gracefully to
``word|word``.
"""

import argparse
import json
import os
import sys

from util_1a_artist_config import (
    add_artist_arg,
    artist_sense_assignments_lemma_path,
    artist_sense_assignments_path,
    artist_sense_menu_path,
    artist_unassigned_routing_path,
)
from util_5c_sense_menu_format import normalize_artist_sense_menu
from util_7a_lemma_split import (
    split_word_assignments, merge_method_maps,
)


# spaCy POS tags we trust enough to route by. Everything else (PRON, CCONJ,
# DET, PHRASE, etc.) falls into the "untrusted" bucket that gets routed to
# the primary analysis.
_TRUSTED_ROUTING_POS = {"VERB", "NOUN", "ADJ", "ADV", "INTJ"}


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
        ex_pos = word_pos_data.get(str(ex_idx))
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


def main():
    parser = argparse.ArgumentParser(description="Step 7a: map artist sense assignments to word|lemma keys")
    add_artist_arg(parser)
    parser.add_argument(
        "--sense-source",
        choices=("wiktionary", "spanishdict"),
        default="wiktionary",
        help="Which sense menu/assignments source to consolidate",
    )
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    layers_dir = os.path.join(artist_dir, "data", "layers")

    menu_path = artist_sense_menu_path(layers_dir, args.sense_source, prefer_new=False)
    assignments_path = artist_sense_assignments_path(layers_dir, args.sense_source, prefer_new=False)
    output_path = artist_sense_assignments_lemma_path(layers_dir, args.sense_source)
    routing_path = artist_unassigned_routing_path(layers_dir, args.sense_source)
    examples_path = os.path.join(layers_dir, "examples_raw.json")
    pos_path = os.path.join(layers_dir, "example_pos.json")

    if not os.path.isfile(menu_path):
        print("ERROR: sense menu not found: %s" % menu_path)
        sys.exit(1)
    if not os.path.isfile(assignments_path):
        print("ERROR: sense assignments not found: %s" % assignments_path)
        sys.exit(1)

    with open(menu_path, "r", encoding="utf-8") as f:
        menu = normalize_artist_sense_menu(json.load(f))
    with open(assignments_path, "r", encoding="utf-8") as f:
        assignments = json.load(f)

    # Load raw examples + POS tags for unassigned routing (optional — if
    # missing, routing is skipped and every unassigned example lands on the
    # primary analysis via step 8b's fallback).
    examples_raw = {}
    example_pos = {}
    if os.path.isfile(examples_path):
        with open(examples_path, "r", encoding="utf-8") as f:
            examples_raw = json.load(f)
    else:
        print("  Note: %s not found — unassigned routing will be empty." % examples_path)
    if os.path.isfile(pos_path):
        with open(pos_path, "r", encoding="utf-8") as f:
            example_pos = json.load(f)
    else:
        print("  Note: %s not found — all unassigned examples will route to the primary analysis." % pos_path)

    remapped = {}
    routing = {}
    changed = 0
    fallbacks = 0
    routed_words = 0

    for word, raw_value in assignments.items():
        analyses = menu.get(word, [])
        split = split_word_assignments(word, analyses, raw_value)
        if len(split) != 1 or next(iter(split.keys())) != "%s|%s" % (word, word):
            changed += 1
        elif analyses and any((a.get("headword") or "").strip() and a.get("headword") != word for a in analyses):
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

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(remapped, f, ensure_ascii=False, indent=2)
    with open(routing_path, "w", encoding="utf-8") as f:
        json.dump(routing, f, ensure_ascii=False, indent=2)

    print("Wrote %s" % output_path)
    print("Wrote %s" % routing_path)
    print("  input keys: %d" % len(assignments))
    print("  output keys: %d" % len(remapped))
    print("  remapped words: %d" % changed)
    if fallbacks:
        print("  word|word fallbacks: %d" % fallbacks)
    print("  unassigned-routing entries: %d lemmas, %d words contributed" %
          (len(routing), routed_words))


if __name__ == "__main__":
    main()
