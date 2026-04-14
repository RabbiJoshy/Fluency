#!/usr/bin/env python3
"""Attach Wiktionary morphology metadata to existing sense_menu.json files.

This enriches menu entries in place without touching sense assignments.

Added field per sense:
  morphology: {
    "surface": "<surface word>",
    "lemma": "<menu lemma>",
    "morph_tags": [...],
    "form_of": [...],
    "is_form_of": true/false
  }
"""

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path

from step_5c_build_senses import POS_MAP


def collect_surface_words(menu):
    return sorted({key.split("|", 1)[0] for key in menu})


def load_raw_morphology(raw_path, target_words):
    """Collect aggregate raw Wiktionary morphology by surface word + POS."""
    target = set(w.lower() for w in target_words)
    result = defaultdict(lambda: defaultdict(lambda: {
        "morph_tags": set(),
        "form_of": set(),
        "is_form_of": False,
    }))

    with gzip.open(raw_path, "rt", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            if obj.get("lang_code") != "es":
                continue
            word = obj.get("word", "").lower()
            if word not in target:
                continue
            pos = POS_MAP.get(obj.get("pos", ""))
            if not pos:
                continue

            meta = result[word][pos]
            for sense in obj.get("senses", []):
                tags = set(sense.get("tags", []) or [])
                if tags:
                    meta["morph_tags"].update(tags)
                form_of = sense.get("form_of", []) or []
                if form_of:
                    meta["is_form_of"] = True
                    for fo in form_of:
                        lemma = fo.get("word")
                        if lemma:
                            meta["form_of"].add(lemma)

    # Convert sets to sorted lists for JSON output
    final = {}
    for word, pos_map in result.items():
        final[word] = {}
        for pos, meta in pos_map.items():
            final[word][pos] = {
                "morph_tags": sorted(meta["morph_tags"]),
                "form_of": sorted(meta["form_of"]),
                "is_form_of": meta["is_form_of"],
            }
    return final


def enrich_menu(menu, raw_meta):
    enriched = 0
    for key, value in menu.items():
        if "|" in key:
            surface, lemma = key.split("|", 1)
        else:
            surface, lemma = key, key
        per_pos = raw_meta.get(surface.lower(), {})

        senses = value.values() if isinstance(value, dict) else value
        for sense in senses:
            pos = sense.get("pos")
            morph = per_pos.get(pos, {"morph_tags": [], "form_of": [], "is_form_of": False})
            sense["morphology"] = {
                "surface": surface,
                "lemma": lemma,
                "morph_tags": morph["morph_tags"],
                "form_of": morph["form_of"],
                "is_form_of": morph["is_form_of"],
            }
            enriched += 1
    return enriched


def main():
    parser = argparse.ArgumentParser(description="Enrich sense menus with Wiktionary morphology metadata")
    parser.add_argument("menu_paths", nargs="+", help="Path(s) to sense_menu.json files")
    args = parser.parse_args()

    raw_path = Path("Data/Spanish/corpora/wiktionary/kaikki-spanish.jsonl.gz")
    if not raw_path.exists():
        raise SystemExit(f"Missing raw Wiktionary file: {raw_path}")

    menus = []
    all_surface_words = set()
    for menu_path_str in args.menu_paths:
        menu_path = Path(menu_path_str)
        with open(menu_path, encoding="utf-8") as f:
            menu = json.load(f)
        menus.append((menu_path, menu))
        all_surface_words.update(collect_surface_words(menu))

    print(f"Collecting raw morphology for {len(all_surface_words)} surface words...")
    raw_meta = load_raw_morphology(raw_path, all_surface_words)

    for menu_path, menu in menus:
        count = enrich_menu(menu, raw_meta)
        with open(menu_path, "w", encoding="utf-8") as f:
            json.dump(menu, f, ensure_ascii=False, indent=2)
        print(f"Enriched {menu_path} ({count} sense entries)")


if __name__ == "__main__":
    main()
