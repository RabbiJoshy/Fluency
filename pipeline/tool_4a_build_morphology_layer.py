#!/usr/bin/env python3
"""Build a Wiktionary-derived morphology layer for builders to consume.

Reads ``Data/Spanish/Senses/wiktionary/kaikki-spanish.jsonl.gz`` and writes
``Data/Spanish/layers/morphology.json`` keyed by surface word, value is a
list of ``{lemma, mood, tense, person?}`` candidates — same shape as
``conjugation_reverse.json`` so step_8a/step_8b can swap or layer them
trivially.

Wiktionary covers ~42% more verb forms than verbecc on the master vocab
(voseo, Latin American slang, clitic-bundled infinitives), and tags are
already in English-vocabulary inflection terms so the conversion to
verbecc's mood/tense/person tuple is mechanical.

Usage:

    .venv/bin/python3 pipeline/tool_4a_build_morphology_layer.py
"""

import argparse
import gzip
import json
import os
import sys
from collections import defaultdict

# pipeline/ is on sys.path when invoked as a script via the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util_4a_morphology import tags_to_morphology


def build_layer(raw_path):
    """Walk kaikki dump, collect morphology per (word, lemma) pair."""
    by_word = defaultdict(list)
    seen_keys = set()  # (word, lemma, mood, tense, person) — dedup across senses
    verb_entries = 0
    form_of_senses = 0
    emitted = 0

    with gzip.open(raw_path, "rt", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            if obj.get("lang_code") != "es":
                continue
            if obj.get("pos") != "verb":
                continue
            verb_entries += 1
            word = (obj.get("word") or "").strip().lower()
            if not word:
                continue
            for sense in obj.get("senses") or []:
                form_of = sense.get("form_of") or []
                if not form_of:
                    continue
                form_of_senses += 1
                tags = sense.get("tags") or []
                triple = tags_to_morphology(tags)
                if triple is None:
                    continue
                triples = triple if isinstance(triple, list) else [triple]
                for fo in form_of:
                    lemma = (fo.get("word") or "").strip().lower()
                    if not lemma:
                        continue
                    for t in triples:
                        person = t.get("person", "")
                        key = (word, lemma, t["mood"], t["tense"], person)
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        # Match verbecc's shape exactly (empty-string person
                        # for non-finite forms) so builders can treat the two
                        # lookups as interchangeable.
                        by_word[word].append({
                            "lemma": lemma,
                            "mood": t["mood"],
                            "tense": t["tense"],
                            "person": person,
                        })
                        emitted += 1

    return by_word, {
        "verb_entries": verb_entries,
        "form_of_senses": form_of_senses,
        "emitted": emitted,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw",
        default="Data/Spanish/Senses/wiktionary/kaikki-spanish.jsonl.gz",
        help="Path to kaikki Spanish raw dump (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        default="Data/Spanish/layers/morphology.json",
        help="Output path (default: %(default)s)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.raw):
        raise SystemExit(f"Missing raw Wiktionary dump: {args.raw}")

    print(f"Reading {args.raw}...")
    by_word, stats = build_layer(args.raw)
    print(f"  Verb entries scanned: {stats['verb_entries']:,}")
    print(f"  Verb form-of senses:  {stats['form_of_senses']:,}")
    print(f"  Morphology rows:      {stats['emitted']:,}")
    print(f"  Distinct surfaces:    {len(by_word):,}")

    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sorted_payload = {w: by_word[w] for w in sorted(by_word)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sorted_payload, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
