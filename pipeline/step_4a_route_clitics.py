#!/usr/bin/env python3
"""
step_4a_route_clitics.py — Detect and classify verb+clitic forms.

Three-tier classification matching artist mode:
  Tier 1+2 (clitic_merge): non-reflexive clitics, or reflexive where base has
           no reflexive senses → merge into base verb at assembly
  Tier 3 (clitic_keep): reflexive where base HAS reflexive senses → keep as
           separate entry with reflexive-only senses

Also catches gerund+clitic forms programmatically (dándote→dar).

Reads Wiktionary JSONL and the conjugation reverse lookup. Writes
word_routing.json with clitic_merge and clitic_keep sections.

Shared logic lives in `pipeline/util_4a_routing.py`.

Usage:
    python3 pipeline/step_4a_route_clitics.py

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/Senses/wiktionary/kaikki-spanish.jsonl.gz
    Data/Spanish/layers/conjugation_reverse.json  (optional)

Output:
    Data/Spanish/layers/word_routing.json
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
from util_pipeline_meta import make_meta  # noqa: E402
from util_4a_routing import (  # noqa: E402
    classify_clitics,
    load_spanishdict_parents,
    load_wiktionary_clitic_data,
)

# Bump when routing categories, clitic detection, or output schema change.
STEP_VERSION = 3
STEP_VERSION_NOTES = {
    1: "clitic_merge + clitic_keep + exclude categories + gerund decomposition",
    2: "infinitive+enclitic decomposition (alejarte → alejar) alongside gerunds",
    3: "SpanishDict headwords own the parent inventory (replaces the literal-`se` "
       "reflexive test); Wiktionary keeps routing + pronoun roles, emitted as clitic_roles",
}

INVENTORY_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"
WIKT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "Senses" / "wiktionary" / "kaikki-spanish.jsonl.gz"
CONJ_REVERSE_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "conjugation_reverse.json"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_routing.json"


def main():
    print("Loading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        inventory = json.load(f)
    inv_words = {e["word"].lower() for e in inventory}
    print(f"  {len(inv_words)} surface words")

    conj_forms = set()
    if CONJ_REVERSE_FILE.exists():
        with open(CONJ_REVERSE_FILE, encoding="utf-8") as f:
            conj_reverse = json.load(f)
        conj_forms = set(conj_reverse.keys())
        print(f"  {len(conj_forms)} conjugated forms loaded")

    print("\nScanning Wiktionary for clitic data...")
    wikt_words, _wikt_propn, clitic_map, verbs_with_refl = load_wiktionary_clitic_data(WIKT_FILE)
    print(f"  Wiktionary: {len(wikt_words)} words, {len(clitic_map)} clitic forms, "
          f"{len(verbs_with_refl)} verbs with reflexive senses")

    sd_parents = load_spanishdict_parents()
    print(f"  SpanishDict parents: {len(sd_parents)} headwords "
          f"({sum(1 for h in sd_parents if h.endswith('se'))} pronominal)")

    known_for_gerund = inv_words | conj_forms | wikt_words
    clitic_merge, clitic_orphans, clitic_keep, gerund_added, clitic_info = classify_clitics(
        inv_words, clitic_map, verbs_with_refl, known_for_gerund,
        sd_parents=sd_parents,
    )

    print("\n--- Clitic Routing ---")
    print(f"  Tier 1+2 (merge): {len(clitic_merge)} "
          f"({len(clitic_merge) - len(clitic_orphans)} to conjugated form, "
          f"{len(clitic_orphans)} orphans to infinitive)")
    print(f"  Tier 3 (keep separate): {len(clitic_keep)}")
    if gerund_added:
        print(f"  Gerund+clitic (programmatic): {gerund_added}")

    output = {
        "clitic_merge": dict(sorted(clitic_merge.items())),
        "clitic_orphans": sorted(clitic_orphans),
        "clitic_keep": sorted(clitic_keep),
        # Pronoun + role annotation for every detected form. Wiktionary's tags
        # where it has an entry, positional otherwise. Downstream consumers and
        # the front end's describeCliticForm() rely on this surviving.
        "clitic_roles": {w: clitic_info[w] for w in sorted(clitic_info)},
        "stats": {
            "inventory_words": len(inv_words),
            "wikt_clitic_forms": len(clitic_map),
            "clitic_merge": len(clitic_merge),
            "clitic_keep": len(clitic_keep),
            "clitic_reflexive_parents": sum(
                1 for v in clitic_info.values() if v["reflexive"]),
            "gerund_programmatic": gerund_added,
        },
    }

    output["_meta"] = make_meta("route_clitics", STEP_VERSION)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
