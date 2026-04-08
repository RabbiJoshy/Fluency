#!/usr/bin/env python3
"""
build_mwes.py — Extract multi-word expressions from Wiktionary derived terms.

Scans kaikki-spanish.jsonl.gz for the `derived` field on word entries and
collects multi-word items, attaching each phrase to its Wiktionary parent word.
Also collects standalone pos="phrase"/pos="prep_phrase" entries, which get
reverse-indexed to their content words in the inventory.

Usage:
    python3 Data/Spanish/Scripts/build_mwes.py

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/corpora/wiktionary/kaikki-spanish.jsonl.gz

Output:
    Data/Spanish/layers/mwe_phrases.json
"""

import gzip
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INVENTORY_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"
WIKT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "wiktionary" / "kaikki-spanish.jsonl.gz"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "mwe_phrases.json"

MIN_WORDS = 2

_SKIP_RE = re.compile(r'^[\d\s]+$|^\w$')


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def tokenize_phrase(phrase: str) -> list[str]:
    """Split a phrase into lowercase tokens, stripping punctuation."""
    return [w.lower() for w in re.findall(r"[\w']+", phrase, re.UNICODE)]


def main():
    # Load inventory
    print("Loading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        inventory = json.load(f)

    word_to_id = {}
    word_to_rank = {}
    for i, entry in enumerate(inventory):
        w = entry["word"].lower()
        if w not in word_to_id:
            word_to_id[w] = entry["id"]
            word_to_rank[w] = i  # inventory is sorted by frequency desc, so index = rank

    print(f"  {len(word_to_id)} unique inventory words")

    # Scan Wiktionary
    print(f"Scanning {WIKT_FILE}...")
    mwe_by_word_id = defaultdict(list)
    # Standalone phrases need reverse-indexing since they have no parent word
    standalone_phrases = []
    # Headword glosses: any multi-word entry's first English gloss (for enrichment)
    headword_glosses = {}
    stats = {"derived": 0, "standalone": 0, "derived_attached": 0}

    with gzip.open(WIKT_FILE, "rt", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            parent_word = item.get("word", "").lower()
            raw_pos = item.get("pos", "")

            # Collect headword glosses for any multi-word entry
            hw = item.get("word", "").strip()
            if " " in hw and hw.lower() not in headword_glosses:
                for s in item.get("senses", []):
                    glosses = s.get("glosses", [])
                    if glosses and len(glosses[0]) >= 2:
                        headword_glosses[hw.lower()] = glosses[0]
                        break

            # Source 1: Standalone phrase entries — collect for later reverse-indexing
            if raw_pos in ("phrase", "prep_phrase"):
                senses = item.get("senses", [])
                glosses = []
                for s in senses:
                    for g in s.get("glosses", []):
                        if len(g) >= 2:
                            glosses.append(g)
                            break
                translation = "; ".join(glosses[:2]) if glosses else ""
                expr = item.get("word", "").strip()
                tokens = tokenize_phrase(expr)
                if len(tokens) >= MIN_WORDS and not _SKIP_RE.match(expr):
                    standalone_phrases.append({
                        "expression": expr,
                        "translation": translation,
                    })
                    stats["standalone"] += 1

            # Source 2: Derived terms — attach to parent word
            parent_id = word_to_id.get(parent_word) or word_to_id.get(strip_accents(parent_word))
            derived = item.get("derived", [])
            for d in derived:
                dword = d.get("word", "").strip()
                if not dword:
                    continue
                tokens = tokenize_phrase(dword)
                if len(tokens) < MIN_WORDS:
                    continue
                if _SKIP_RE.match(dword):
                    continue

                stats["derived"] += 1
                if not parent_id:
                    continue

                translation = d.get("english", "") or d.get("translation", "") or ""
                mwe_entry = {"expression": dword}
                if translation:
                    mwe_entry["translation"] = translation

                # Deduplicate on same parent
                existing = {m["expression"].lower() for m in mwe_by_word_id[parent_id]}
                if dword.lower() not in existing:
                    mwe_by_word_id[parent_id].append(mwe_entry)
                    stats["derived_attached"] += 1

    print(f"  Derived multi-word items: {stats['derived']}")
    print(f"    Attached to inventory: {stats['derived_attached']}")
    print(f"  Standalone phrases: {stats['standalone']}")

    # Reverse-index standalone phrases: attach to longest content word in inventory
    standalone_attached = 0
    # Build a translation lookup from standalone phrases for enriching derived items
    standalone_translations = {}
    for sp in standalone_phrases:
        key = sp["expression"].lower()
        if sp["translation"]:
            standalone_translations[key] = sp["translation"]

        # Find the best host: least frequent (highest rank) inventory word in the phrase
        tokens = tokenize_phrase(sp["expression"])
        best_rank = -1
        best_id = None
        for t in tokens:
            t_norm = strip_accents(t)
            wid = word_to_id.get(t) or word_to_id.get(t_norm)
            rank = word_to_rank.get(t, word_to_rank.get(t_norm, -1))
            if wid and rank > best_rank:
                best_rank = rank
                best_id = wid

        if not best_id:
            continue

        existing = {m["expression"].lower() for m in mwe_by_word_id[best_id]}
        if key not in existing:
            mwe_entry = {"expression": sp["expression"]}
            if sp["translation"]:
                mwe_entry["translation"] = sp["translation"]
            mwe_by_word_id[best_id].append(mwe_entry)
            standalone_attached += 1

    print(f"    Standalone attached: {standalone_attached}")

    # Enrich untranslated MWEs from headword glosses and standalone translations
    enriched = 0
    for wid, mwes in mwe_by_word_id.items():
        for mwe in mwes:
            if not mwe.get("translation"):
                key = mwe["expression"].lower()
                trans = (standalone_translations.get(key)
                         or headword_glosses.get(key))
                if trans:
                    mwe["translation"] = trans
                    enriched += 1
    print(f"  Enriched from Wiktionary headword glosses: {enriched}")
    print(f"  Headword glosses available: {len(headword_glosses)}")

    # Sort: translated first, then by expression length
    for wid in mwe_by_word_id:
        mwe_by_word_id[wid].sort(key=lambda m: (not m.get("translation"), len(m["expression"])))

    # Write output
    print(f"\nWriting {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(mwe_by_word_id), f, ensure_ascii=False, indent=2)

    # Stats
    total_memberships = sum(len(v) for v in mwe_by_word_id.values())
    words_with_mwes = len(mwe_by_word_id)
    translated = sum(
        1 for mwes in mwe_by_word_id.values()
        for m in mwes if m.get("translation")
    )

    print(f"\n{'='*55}")
    print("MWE EXTRACTION RESULTS")
    print(f"{'='*55}")
    print(f"Words with MWEs:         {words_with_mwes:>6}")
    print(f"Total MWE memberships:   {total_memberships:>6}")
    print(f"  With translation:      {translated:>6}")
    print(f"  Without translation:   {total_memberships - translated:>6}")

    # Sample output
    print("\nSample entries:")
    sample_words = {"verdad", "mano", "hacer", "dar", "ojo", "cuenta"}
    for entry in inventory:
        if entry["word"] in sample_words and entry["id"] in mwe_by_word_id:
            sample_words.discard(entry["word"])
            mwes = mwe_by_word_id[entry["id"]]
            print(f"\n  {entry['word']} ({len(mwes)} MWEs):")
            for m in mwes[:5]:
                trans = m.get("translation", "(no translation)")
                print(f"    {m['expression']:30s}  {trans}")
            if len(mwes) > 5:
                print(f"    ... and {len(mwes) - 5} more")
            if not sample_words:
                break


if __name__ == "__main__":
    main()
