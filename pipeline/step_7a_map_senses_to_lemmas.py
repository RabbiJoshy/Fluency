#!/usr/bin/env python3
"""
step_7a_map_senses_to_lemmas.py — Normalize sense assignments onto word|lemma keys.

This is a small consolidation step that runs after sense assignment.
It prefers explicit lemma-aware keys when they already exist, but can also
recover them from word_inventory.json when assignments are keyed only by
surface form or legacy hex IDs.

If no reliable lemma is available, it degrades gracefully to word|word.

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/layers/sense_menu.json
    Data/Spanish/layers/sense_assignments.json

Output:
    Data/Spanish/layers/sense_assignments_lemma.json
"""

import json
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"
INVENTORY_FILE = LAYERS / "word_inventory.json"
SENSE_MENU_FILE = LAYERS / "sense_menu.json"
ASSIGNMENTS_FILE = LAYERS / "sense_assignments.json"
OUTPUT_FILE = LAYERS / "sense_assignments_lemma.json"


def make_key(word, lemma):
    return f"{word}|{lemma}"


def choose_target_key(raw_key, inventory_by_id, candidates_by_word, senses_data):
    if "|" in raw_key:
        return raw_key

    if raw_key in inventory_by_id:
        entry = inventory_by_id[raw_key]
        return make_key(entry["word"], entry.get("lemma", entry["word"]))

    word = raw_key
    candidates = candidates_by_word.get(word.lower(), [])
    if not candidates:
        fallback = make_key(word, word)
        return fallback

    exact_surface = [
        c for c in candidates
        if c.get("lemma", c["word"]).lower() == c["word"].lower()
    ]
    if exact_surface:
        candidates = exact_surface

    menu_candidates = [
        c for c in candidates
        if make_key(c["word"], c.get("lemma", c["word"])) in senses_data
    ]
    if menu_candidates:
        candidates = menu_candidates

    preferred = [
        c for c in candidates if c.get("most_frequent_lemma_instance")
    ]
    if preferred:
        candidates = preferred

    best = max(candidates, key=lambda c: c.get("corpus_count", 0))
    return make_key(best["word"], best.get("lemma", best["word"]))


def merge_method_items(items):
    merged = {}
    order = []
    for item in items:
        sense = item.get("sense")
        if not sense:
            continue
        examples = sorted(set(item.get("examples", [])))
        if sense not in merged:
            merged[sense] = {"sense": sense, "examples": examples}
            order.append(sense)
        else:
            merged[sense]["examples"] = sorted(
                set(merged[sense]["examples"]) | set(examples)
            )
    return [merged[sense] for sense in order]


def merge_assignment_values(existing, incoming):
    if isinstance(existing, list) and isinstance(incoming, list):
        return existing + incoming

    if isinstance(existing, dict) and isinstance(incoming, dict):
        out = {method: list(items) for method, items in existing.items()}
        for method, items in incoming.items():
            if method not in out:
                out[method] = list(items)
            else:
                out[method] = merge_method_items(out[method] + list(items))
        return out

    return incoming


def main():
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        inventory = json.load(f)
    with open(SENSE_MENU_FILE, encoding="utf-8") as f:
        senses_data = json.load(f)
    with open(ASSIGNMENTS_FILE, encoding="utf-8") as f:
        assignments = json.load(f)

    inventory_by_id = {}
    candidates_by_word = defaultdict(list)
    for entry in inventory:
        inventory_by_id[entry["id"]] = entry
        candidates_by_word[entry["word"].lower()].append(entry)

    remapped = {}
    changed = 0
    fallback_word_word = 0

    for raw_key, value in assignments.items():
        target_key = choose_target_key(raw_key, inventory_by_id, candidates_by_word, senses_data)
        if target_key != raw_key:
            changed += 1
        word, lemma = target_key.split("|", 1)
        if word.lower() == lemma.lower() and raw_key not in inventory_by_id and "|" not in raw_key:
            fallback_word_word += 1
        if target_key in remapped:
            remapped[target_key] = merge_assignment_values(remapped[target_key], value)
        else:
            remapped[target_key] = value

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(remapped, f, ensure_ascii=False, indent=2)

    print(f"Wrote {OUTPUT_FILE}")
    print(f"  input keys: {len(assignments)}")
    print(f"  output keys: {len(remapped)}")
    print(f"  remapped keys: {changed}")
    if fallback_word_word:
        print(f"  word|word fallbacks: {fallback_word_word}")


if __name__ == "__main__":
    main()
