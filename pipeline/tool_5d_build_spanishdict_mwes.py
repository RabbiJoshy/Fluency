#!/usr/bin/env python3
"""
tool_5d_build_spanishdict_mwes.py — Build MWE layer from SpanishDict phrases cache.

Reads the SpanishDict phrases cache and the normal-mode word inventory,
producing Data/Spanish/layers/mwe_phrases.json in the same format as
step_5d_build_mwes.py (Wiktionary source).

Usage:
    .venv/bin/python3 pipeline/tool_5d_build_spanishdict_mwes.py
"""

import json
from collections import defaultdict
from pathlib import Path

from util_5c_spanishdict import SPANISHDICT_PHRASES_CACHE, load_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "mwe_phrases.json"

MAX_MWES_PER_WORD = 10
MAX_TRANSLATION_LEN = 100


def main():
    print("SpanishDict MWE builder")

    # Load word inventory for word -> ID mapping
    inventory = load_json(INVENTORY_FILE, [])
    word_to_id = {}
    for entry in inventory:
        word = (entry.get("word") or "").strip().lower()
        if word and entry.get("id"):
            word_to_id[word] = entry["id"]
    print("  Inventory: %d words" % len(word_to_id))

    # Load phrases cache
    phrases_cache = load_json(SPANISHDICT_PHRASES_CACHE, {})
    print("  Phrases cache: %d words" % len(phrases_cache))

    # Build MWE layer keyed by word ID
    mwe_by_id = defaultdict(list)
    matched_words = 0

    for word, wid in word_to_id.items():
        phrases = phrases_cache.get(word, [])
        if not phrases:
            continue
        matched_words += 1
        seen_exprs = set()
        for phrase in phrases:
            if len(mwe_by_id[wid]) >= MAX_MWES_PER_WORD:
                break
            expr = phrase.get("expression", "")
            if not expr or expr.lower() in seen_exprs:
                continue
            seen_exprs.add(expr.lower())

            trans = phrase.get("translation", "")
            if len(trans) > MAX_TRANSLATION_LEN:
                parts = trans.split(", ")
                result = parts[0]
                for part in parts[1:]:
                    candidate = result + ", " + part
                    if len(candidate) > MAX_TRANSLATION_LEN:
                        break
                    result = candidate
                trans = result

            mwe_by_id[wid].append({
                "expression": expr,
                "translation": trans,
                "source": "spanishdict",
            })

    total_mwes = sum(len(v) for v in mwe_by_id.values())

    # Write output
    print("\nWriting %s..." % OUTPUT_FILE)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(mwe_by_id), f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 55)
    print("SPANISHDICT MWE RESULTS")
    print("=" * 55)
    print("Words with phrases in cache:  %6d" % matched_words)
    print("Words with MWEs in output:    %6d" % len(mwe_by_id))
    print("Total MWE memberships:        %6d" % total_mwes)

    # Sample output
    sample_words = {"dar", "hacer", "tener", "mano", "por"}
    print("\nSample entries:")
    for word in sorted(sample_words):
        wid = word_to_id.get(word)
        if wid and wid in mwe_by_id:
            mwes = mwe_by_id[wid]
            print("\n  %s (%d MWEs):" % (word, len(mwes)))
            for m in mwes[:5]:
                print("    %-30s  %s" % (m["expression"], m.get("translation", "")))
            if len(mwes) > 5:
                print("    ... and %d more" % (len(mwes) - 5))


if __name__ == "__main__":
    main()
