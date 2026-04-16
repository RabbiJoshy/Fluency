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

Usage:
    python3 pipeline/step_4a_route_clitics.py

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/Senses/wiktionary/kaikki-spanish.jsonl.gz
    Data/Spanish/layers/conjugation_reverse.json  (optional)

Output:
    Data/Spanish/layers/word_routing.json
"""

import gzip
import json
import os
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
from util_pipeline_meta import make_meta  # noqa: E402

# Bump when routing categories, clitic detection, or output schema change.
STEP_VERSION = 1
STEP_VERSION_NOTES = {
    1: "clitic_merge + clitic_keep + exclude categories + gerund decomposition",
}

INVENTORY_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"
WIKT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "Senses" / "wiktionary" / "kaikki-spanish.jsonl.gz"
CONJ_REVERSE_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "conjugation_reverse.json"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_routing.json"

# Clitic pronouns (longest first to avoid partial matches)
_CLITIC_PRONOUNS = ("nos", "les", "los", "las", "me", "te", "se", "lo", "la", "le")


def _strip_acute(s):
    """Strip acute accents only (á→a), preserving ñ and ü."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if c != "\u0301")


def strip_clitic_pronouns(word, clitic_list=None):
    """Strip clitic pronouns from end of word and return accentless base form."""
    remaining = word.lower()
    if clitic_list:
        for cl in reversed(clitic_list):
            if remaining.endswith(cl) and len(remaining) > len(cl):
                remaining = remaining[:-len(cl)]
    else:
        for _ in range(2):
            for cl in _CLITIC_PRONOUNS:
                if remaining.endswith(cl) and len(remaining) > len(cl):
                    remaining = remaining[:-len(cl)]
                    break
    return _strip_acute(remaining)


def decompose_gerund_clitic(word, known_words):
    """Decompose a gerund+clitic form into base infinitive.

    Returns (base_infinitive, is_reflexive) if decomposable, else None.
    E.g., 'dándote' → ('dar', False), 'ahogándome' → ('ahogar', False)
    """
    wl = word.lower()
    remaining = wl
    clitics = []
    for _ in range(2):
        matched = False
        for pron in _CLITIC_PRONOUNS:
            if remaining.endswith(pron) and len(remaining) > len(pron) + 4:
                remaining = remaining[:-len(pron)]
                clitics.insert(0, pron)
                matched = True
                break
        if not matched:
            break

    if not clitics:
        return None

    clean = _strip_acute(remaining)
    if clean.endswith("ando"):
        infinitive = clean[:-4] + "ar"
    elif clean.endswith("iendo"):
        infinitive = clean[:-5] + "ir"
    elif clean.endswith("endo"):
        infinitive = clean[:-4] + "er"
    else:
        return None

    if infinitive in known_words:
        return (infinitive, "se" in clitics)
    return None


def load_wiktionary_clitic_data(path):
    """Load clitic map and reflexive verb set from Wiktionary JSONL.

    Returns (wikt_words, clitic_map, verbs_with_refl_senses).
    """
    clitic_map = {}
    verbs_with_refl = set()
    wikt_words = set()
    if not path.exists():
        print(f"  WARNING: Wiktionary file not found: {path}")
        return wikt_words, clitic_map, verbs_with_refl

    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            w = entry.get("word", "")
            if not w:
                continue
            wl = w.lower()
            wikt_words.add(wl)
            raw_pos = entry.get("pos", "")
            for s in entry.get("senses", []):
                tags = set(s.get("tags", []))
                if raw_pos == "verb" and "form-of" not in tags:
                    if "reflexive" in tags or "pronominal" in tags:
                        verbs_with_refl.add(wl)
                if "form-of" in tags:
                    gloss = (s.get("glosses") or [""])[0]
                    if "combined with" in gloss:
                        links = s.get("links", [])
                        if links and isinstance(links[0], list):
                            base = links[0][0].lower()
                            clitics = [l[0].lower() for l in links[1:]
                                       if isinstance(l, list)]
                            is_refl = "reflexive" in tags or "se" in clitics
                            if base and base != wl:
                                clitic_map[wl] = (base, clitics, is_refl)

    return wikt_words, clitic_map, verbs_with_refl


def main():
    print("Loading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        inventory = json.load(f)
    inv_words = {e["word"].lower() for e in inventory}
    print(f"  {len(inv_words)} surface words")

    # Load conjugation forms (for gerund+clitic detection)
    conj_forms = set()
    if CONJ_REVERSE_FILE.exists():
        with open(CONJ_REVERSE_FILE, encoding="utf-8") as f:
            conj_reverse = json.load(f)
        conj_forms = set(conj_reverse.keys())
        print(f"  {len(conj_forms)} conjugated forms loaded")

    print(f"\nScanning Wiktionary for clitic data...")
    wikt_words, clitic_map, verbs_with_refl = load_wiktionary_clitic_data(WIKT_FILE)
    print(f"  Wiktionary: {len(wikt_words)} words, {len(clitic_map)} clitic forms, "
          f"{len(verbs_with_refl)} verbs with reflexive senses")

    # Three-tier classification
    clitic_merge = {}   # word -> base_form (tier 1+2)
    clitic_orphans = []
    clitic_keep = set() # tier 3

    # Known words for gerund decomposition
    all_known = inv_words | conj_forms | wikt_words

    for w in inv_words:
        if w not in clitic_map:
            continue
        base_inf, clitics, is_refl = clitic_map[w]
        if is_refl and base_inf in verbs_with_refl:
            clitic_keep.add(w)  # tier 3
            continue
        # Prefer conjugated form in inventory, fall back to infinitive
        stripped = strip_clitic_pronouns(w, clitics)
        if stripped in inv_words:
            clitic_merge[w] = stripped
        else:
            clitic_merge[w] = base_inf
            clitic_orphans.append(w)

    # Programmatic gerund+clitic detection
    gerund_added = 0
    for w in inv_words:
        if w in clitic_merge or w in clitic_keep:
            continue
        result = decompose_gerund_clitic(w, all_known)
        if result:
            base_inf, is_refl = result
            if is_refl and base_inf in verbs_with_refl:
                clitic_keep.add(w)
            else:
                stripped = strip_clitic_pronouns(w)
                if stripped in inv_words:
                    clitic_merge[w] = stripped
                else:
                    clitic_merge[w] = base_inf
                    clitic_orphans.append(w)
            gerund_added += 1

    # Report
    print(f"\n--- Clitic Routing ---")
    print(f"  Tier 1+2 (merge): {len(clitic_merge)} "
          f"({len(clitic_merge) - len(clitic_orphans)} to conjugated form, "
          f"{len(clitic_orphans)} orphans to infinitive)")
    print(f"  Tier 3 (keep separate): {len(clitic_keep)}")
    if gerund_added:
        print(f"  Gerund+clitic (programmatic): {gerund_added}")

    # Write output
    output = {
        "clitic_merge": dict(sorted(clitic_merge.items())),
        "clitic_orphans": sorted(clitic_orphans),
        "clitic_keep": sorted(clitic_keep),
        "stats": {
            "inventory_words": len(inv_words),
            "wikt_clitic_forms": len(clitic_map),
            "clitic_merge": len(clitic_merge),
            "clitic_keep": len(clitic_keep),
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
