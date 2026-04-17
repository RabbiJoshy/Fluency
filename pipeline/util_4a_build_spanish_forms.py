#!/usr/bin/env python3
"""Build the canonical Spanish forms lookup used by step_4a.

Produces Data/Spanish/layers/spanish_forms.json — a dict mapping every known
Spanish surface form to a comma-separated list of POS tags. Sources, merged:

  - Wiktionary (kaikki-spanish): all entries, including form-of inflections
    that verbecc misses (arrepentí, disfrazaste, enganchaste, comente).
  - verbecc conjugations (conjugation_reverse.json): complete conjugation
    tables for the verbs verbecc covers.
  - Normal-mode vocabulary.json: the curated canonical wordlist.

Output schema: {surface_form: pos_string}
    where pos_string is comma-joined sorted unique POS tags:
    "casa" -> "noun,verb"
    "arrepentí" -> "verb"

Run: .venv/bin/python3 pipeline/util_4a_build_spanish_forms.py
"""

import gzip
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_THIS_DIR)

WIKT_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "Senses", "wiktionary", "kaikki-spanish.jsonl.gz")
CONJ_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "layers", "conjugation_reverse.json")
NORMAL_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "vocabulary.json")
OUT_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "layers", "spanish_forms.json")


def _pos_to_pretty(raw):
    """Map Wiktionary raw pos strings to canonical short tags."""
    mapping = {
        "verb": "verb",
        "noun": "noun",
        "name": "name",
        "adj": "adj",
        "adv": "adv",
        "intj": "intj",
        "prep": "prep",
        "pron": "pron",
        "det": "det",
        "conj": "conj",
        "num": "num",
        "article": "det",
        "particle": "particle",
        "suffix": "suffix",
        "prefix": "prefix",
        "phrase": "phrase",
    }
    return mapping.get(raw, raw)


def main():
    forms = {}

    # 1. Wiktionary — lemma entries + form-of inflections
    if not os.path.isfile(WIKT_PATH):
        print(f"ERROR: {WIKT_PATH} not found", file=sys.stderr)
        sys.exit(1)
    print(f"Loading Wiktionary from {WIKT_PATH}...")
    n_wikt = 0
    with gzip.open(WIKT_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            w = e.get("word", "").lower()
            if not w:
                continue
            pos = _pos_to_pretty(e.get("pos", "") or "")
            if not pos:
                continue
            forms.setdefault(w, set()).add(pos)
            n_wikt += 1
    print(f"  {n_wikt} Wiktionary entries -> {len(forms)} unique surface forms")

    # 2. verbecc conjugations
    if os.path.isfile(CONJ_PATH):
        print(f"Loading verbecc from {CONJ_PATH}...")
        with open(CONJ_PATH, "r", encoding="utf-8") as f:
            conj = json.load(f)
        for w in conj:
            forms.setdefault(w.lower(), set()).add("verb")
        print(f"  {len(conj)} verbecc forms merged")

    # 3. Normal-mode curated vocabulary
    if os.path.isfile(NORMAL_PATH):
        print(f"Loading normal-mode vocab from {NORMAL_PATH}...")
        with open(NORMAL_PATH, "r", encoding="utf-8") as f:
            vocab = json.load(f)
        n_added = 0
        for entry in vocab:
            w = entry.get("word", "").lower()
            if not w:
                continue
            # Infer POS from the entry if present
            ppos = entry.get("pos") or entry.get("part_of_speech") or ""
            if ppos:
                forms.setdefault(w, set()).add(_pos_to_pretty(ppos.lower()))
            else:
                forms.setdefault(w, set())  # presence without POS info
            n_added += 1
        print(f"  {n_added} normal-mode vocab entries merged")

    # Serialize as {word: "pos1,pos2"} for compactness
    out = {w: ",".join(sorted(poses)) for w, poses in forms.items()}

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    print(f"Writing {len(out)} forms -> {OUT_PATH}")
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    # Stats
    verb_count = sum(1 for v in out.values() if "verb" in v.split(","))
    noun_count = sum(1 for v in out.values() if "noun" in v.split(","))
    name_count = sum(1 for v in out.values() if "name" in v.split(","))
    print(f"\nForm counts:")
    print(f"  verb forms: {verb_count}")
    print(f"  noun forms: {noun_count}")
    print(f"  name-only:  {sum(1 for v in out.values() if v == 'name')}")
    print(f"  total:      {len(out)}")
    print(f"File size: {os.path.getsize(OUT_PATH) / 1_048_576:.1f} MB")


if __name__ == "__main__":
    main()
