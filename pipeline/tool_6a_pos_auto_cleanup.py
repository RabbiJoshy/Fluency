#!/usr/bin/env python3
"""Surgical `pos-auto` cleanup for already-built sense_assignments files.

Moves examples to their POS-compatible sense **without** re-running any
classifier (Gemini, biencoder, keyword) when per-example POS would have
narrowed the menu to a single sense — i.e. exactly the cases the new
step_6c / step_6b pos-auto short-circuit catches on fresh runs.

Use this after landing the pos-auto change on an artist whose
assignments were built pre-change and you don't want to pay the Gemini
re-run cost. Safe: only touches examples where a TRUSTED POS tag
(VERB / NOUN / ADJ / ADV / INTJ) uniquely picks one sense. Multi-
candidate examples (e.g. `pasar` with 5 verb senses) are left alone.

Usage:
    # Normal mode
    .venv/bin/python3 pipeline/tool_6a_pos_auto_cleanup.py \\
        --sense-source spanishdict

    # Artist mode
    .venv/bin/python3 pipeline/tool_6a_pos_auto_cleanup.py \\
        --artist-dir "Artists/spanish/Bad Bunny" \\
        --sense-source spanishdict

    # Preview without writing
    .venv/bin/python3 pipeline/tool_6a_pos_auto_cleanup.py \\
        --artist-dir "Artists/spanish/Bad Bunny" \\
        --sense-source spanishdict \\
        --dry-run

After a real (non-dry) run, re-run step_7a + step_8b to propagate the
updated assignments to the artist vocab / normal vocab files:

    .venv/bin/python3 pipeline/artist/run_artist_pipeline.py \\
        --artist "Bad Bunny" --from-step 7a
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from util_6a_assignment_format import load_assignments, dump_assignments  # noqa: E402
from util_6a_pos_menu_filter import (  # noqa: E402
    sense_compatible_with_example_pos, TRUSTED_FILTER_POS,
)
from util_6a_method_priority import METHOD_PRIORITY  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]

POS_AUTO_METHOD = "pos-auto"


def _resolve_layers_dir(args):
    if args.artist_dir:
        p = Path(args.artist_dir).resolve() / "data" / "layers"
    else:
        # Normal mode defaults. Spanish is the only fully-built language today;
        # future languages can override via --layers-dir.
        p = PROJECT_ROOT / "Data" / "Spanish" / "layers"
    if args.layers_dir:
        p = Path(args.layers_dir).resolve()
    return p


def _flatten_menu_senses(menu_entry):
    """Return ``{sense_id: sense_dict}`` across all analyses of one word.

    sense_menu.json stores a list of analyses per word (for homographs:
    `como` has one analysis for `como|como` and one for `como|comer`).
    We flatten because classifiers assign by sense-ID; which analysis the
    sense came from is already encoded in the ID.
    """
    out = {}
    if isinstance(menu_entry, list):
        analyses = menu_entry
    elif isinstance(menu_entry, dict) and "senses" in menu_entry:
        analyses = [menu_entry]
    else:
        return out
    for a in analyses:
        senses = a.get("senses") if isinstance(a, dict) else None
        if isinstance(senses, dict):
            for sid, s in senses.items():
                if isinstance(s, dict) and "pos" in s:
                    out[sid] = s
    return out


def _pos_candidates(senses_by_id, ex_pos):
    """Return the list of sense IDs compatible with ``ex_pos``.

    Mirrors step_6b/6c pos-auto logic: trusted `ex_pos` narrows to exact
    POS matches (plus orthogonal POSes like PHRASE / CONTRACTION);
    untrusted `ex_pos` only drops trusted mismatches. We deliberately
    only treat TRUSTED pos tags as decisive — untrusted tags never
    produce a single-candidate narrow here, even by coincidence,
    because that was the implicit contract of the live pos-auto path.
    """
    if ex_pos not in TRUSTED_FILTER_POS:
        return []
    candidates = []
    for sid, s in senses_by_id.items():
        if sense_compatible_with_example_pos(s.get("pos"), ex_pos):
            candidates.append(sid)
    return candidates


def _ex_int(ex_val):
    """Coerce an assignments example entry to int index or None."""
    try:
        return int(ex_val)
    except (TypeError, ValueError):
        return None


def cleanup_assignments(assignments, sense_menu, example_pos, dry_run=False):
    """Move single-POS-candidate examples to pos-auto on the correct sense.

    ``assignments``: in-memory legacy form, ``{word: {method: [items]}}``.
    ``sense_menu``:  ``{word: [analyses]}`` as read from sense_menu/<source>.json.
    ``example_pos``: ``{word: {idx_str: "VERB"|"NOUN"|...}}``.

    Returns ``(moves, stats)``.

    ``moves`` is a flat list of ``(word, ex_idx, old_method, old_sense,
    correct_sense)`` tuples for the report.

    Mutates ``assignments`` in place unless ``dry_run`` is True (in
    which case nothing is written back).
    """
    moves = []
    stats = defaultdict(int)
    stats["words_scanned"] = 0
    stats["words_touched"] = 0
    stats["examples_moved"] = 0
    stats["examples_added"] = 0  # assigned where previously unassigned
    stats["examples_already_correct"] = 0

    for word, word_data in assignments.items():
        stats["words_scanned"] += 1
        if not isinstance(word_data, dict):
            continue
        menu_entry = sense_menu.get(word)
        if not menu_entry:
            continue
        senses_by_id = _flatten_menu_senses(menu_entry)
        if len(senses_by_id) < 2:
            # Single-sense or sense-less words are either already pos-auto
            # territory (trivially correct) or out of scope here.
            continue

        pos_map = example_pos.get(word) or {}
        if not pos_map:
            continue

        # Gather every example-idx that appears in any existing claim, plus
        # their current (method, sense) pairs. An example can be claimed by
        # multiple methods; we track them all so we can remove ALL wrong
        # claims when we move it.
        current_claims = defaultdict(list)  # ex_idx -> [(method, sense_id)]
        for method, items in word_data.items():
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                sid = item.get("sense")
                if not sid:
                    continue
                for e in item.get("examples", []) or []:
                    ei = _ex_int(e)
                    if ei is None:
                        continue
                    current_claims[ei].append((method, sid))

        word_touched = False
        # Walk only the examples whose POS tag exists. Untagged examples
        # can't be pos-auto decided, so we skip them.
        for idx_str, ex_pos in pos_map.items():
            ei = _ex_int(idx_str)
            if ei is None:
                continue
            cands = _pos_candidates(senses_by_id, ex_pos)
            if len(cands) != 1:
                continue
            correct_sid = cands[0]
            existing = current_claims.get(ei, [])
            # If an existing claim already points at the correct sense AND
            # it's either pos-auto or a higher-priority method that agrees,
            # we leave it alone.
            already_correct = any(sid == correct_sid for _, sid in existing)

            # Remove every incorrect claim for this example.
            removed_any = False
            for method, sid in list(existing):
                if sid == correct_sid:
                    continue
                # Prune this (method, sid, example_idx)
                items = word_data.get(method, [])
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("sense") != sid:
                        continue
                    exs = item.get("examples") or []
                    filtered = [e for e in exs if _ex_int(e) != ei]
                    if len(filtered) != len(exs):
                        item["examples"] = filtered
                        removed_any = True
                moves.append((word, ei, method, sid, correct_sid))
            # Drop now-empty items and now-empty method buckets.
            if removed_any:
                for method in list(word_data.keys()):
                    items = word_data[method]
                    cleaned = [it for it in items
                               if isinstance(it, dict) and (it.get("examples") or [])]
                    if cleaned:
                        word_data[method] = cleaned
                    else:
                        del word_data[method]
                word_touched = True
                stats["examples_moved"] += 1

            # Ensure the pos-auto claim exists and covers this example.
            if not already_correct:
                pos_auto_items = word_data.setdefault(POS_AUTO_METHOD, [])
                target_item = None
                for it in pos_auto_items:
                    if isinstance(it, dict) and it.get("sense") == correct_sid:
                        target_item = it
                        break
                if target_item is None:
                    target_item = {"sense": correct_sid, "examples": []}
                    pos_auto_items.append(target_item)
                exs = target_item.setdefault("examples", [])
                if ei not in exs:
                    exs.append(ei)
                    exs.sort()
                    if not removed_any:
                        stats["examples_added"] += 1
                    word_touched = True
            else:
                stats["examples_already_correct"] += 1

        if word_touched:
            stats["words_touched"] += 1

    return moves, stats


def main():
    parser = argparse.ArgumentParser(
        description="Move existing sense assignments onto pos-auto where "
                    "per-example POS narrows the menu to a single sense. "
                    "No classifier re-runs. Same semantics as the live "
                    "step_6b/6c pos-auto short-circuit."
    )
    parser.add_argument("--artist-dir",
                        help="Artist dir (omit for normal mode).")
    parser.add_argument("--layers-dir",
                        help="Override layers dir (default: derived from --artist-dir).")
    parser.add_argument("--sense-source", choices=("spanishdict", "wiktionary"),
                        required=True,
                        help="Which sense_assignments/<source>.json to clean.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change, don't write.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print every individual move.")
    args = parser.parse_args()

    layers_dir = _resolve_layers_dir(args)
    assignments_path = layers_dir / "sense_assignments" / f"{args.sense_source}.json"
    menu_path = layers_dir / "sense_menu" / f"{args.sense_source}.json"
    pos_path = layers_dir / "example_pos.json"

    for p, label in [(assignments_path, "sense_assignments"),
                     (menu_path, "sense_menu"),
                     (pos_path, "example_pos")]:
        if not p.exists():
            print(f"ERROR: {label} not found at {p}")
            sys.exit(1)

    print(f"Loading layers from {layers_dir} ...")
    assignments = load_assignments(assignments_path)
    with open(menu_path, encoding="utf-8") as f:
        sense_menu = json.load(f)
    with open(pos_path, encoding="utf-8") as f:
        example_pos = json.load(f)
    example_pos.pop("_example_ids", None)

    print(f"  sense_assignments: {len(assignments)} words")
    print(f"  sense_menu:        {len(sense_menu)} words")
    print(f"  example_pos:       {len(example_pos)} words")
    print()

    moves, stats = cleanup_assignments(
        assignments, sense_menu, example_pos, dry_run=args.dry_run,
    )

    print("=" * 55)
    print(f"Words scanned:            {stats['words_scanned']:>6}")
    print(f"Words touched:            {stats['words_touched']:>6}")
    print(f"Examples moved:           {stats['examples_moved']:>6}")
    print(f"Examples newly assigned:  {stats['examples_added']:>6}")
    print(f"Examples already correct: {stats['examples_already_correct']:>6}")
    print("=" * 55)

    if args.verbose and moves:
        print("\nIndividual moves (word, ex_idx, old_method → correct_sense):")
        # Group by word for readability
        by_word = defaultdict(list)
        for word, ei, old_method, old_sid, new_sid in moves:
            by_word[word].append((ei, old_method, old_sid, new_sid))
        for word in sorted(by_word):
            for ei, om, osid, nsid in by_word[word]:
                print(f"  {word:20s}  ex={ei:3d}  [{om}:{osid}] -> [pos-auto:{nsid}]")

    if args.dry_run:
        print("\n--dry-run: no files written.")
        return

    dump_assignments(assignments, assignments_path)
    print(f"\nWrote {assignments_path}")
    print("Next: re-run step_7a + step_8b to propagate into the vocab files.")


if __name__ == "__main__":
    main()
