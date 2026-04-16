#!/usr/bin/env python3
"""
step_5d_build_mwes.py — Extract multi-word expressions from Wiktionary derived terms.

Scans kaikki-spanish.jsonl.gz for the `derived` field on word entries and
collects multi-word items, attaching each phrase to its Wiktionary parent word.
Also collects standalone pos="phrase"/pos="prep_phrase" entries, which get
reverse-indexed to their content words in the inventory.

Usage:
    python3 pipeline/step_5d_build_mwes.py

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/Senses/wiktionary/kaikki-spanish.jsonl.gz

Output:
    Data/Spanish/layers/mwe_phrases.json  — {word: [{expression, translation?, corpus_freq?}]}
"""

import gzip
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import ahocorasick

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
from util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

STEP_VERSION = 1
STEP_VERSION_NOTES = {
    1: "wiktionary MWE extraction + aho-corasick subs counting, 10/word cap",
}
INVENTORY_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"
WIKT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "wiktionary" / "kaikki-spanish.jsonl.gz"
OPENSUBS_FILE = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "opensubtitles" / "OpenSubtitles.en-es.es"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "mwe_phrases.json"

MAX_MWES_PER_WORD = 10
MAX_TRANSLATION_LEN = 100
MIN_FREQ_RATIO = 0.02  # MWE must appear in >= 2% of parent word's lines
SAMPLE_STRIDE = 10  # read every Nth line from OpenSubtitles

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

    word_set = set()
    word_to_rank = {}
    for i, entry in enumerate(inventory):
        w = entry["word"].lower()
        if w not in word_set:
            word_set.add(w)
            word_to_rank[w] = i  # inventory is sorted by frequency desc, so index = rank

    print(f"  {len(word_set)} unique inventory words")

    # Scan Wiktionary
    print(f"Scanning {WIKT_FILE}...")
    mwe_by_word = defaultdict(list)
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
            parent_in_inv = parent_word in word_set or strip_accents(parent_word) in word_set
            parent_key = parent_word if parent_word in word_set else strip_accents(parent_word)
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
                if not parent_in_inv:
                    continue

                translation = d.get("english", "") or d.get("translation", "") or ""
                mwe_entry = {"expression": dword}
                if translation:
                    mwe_entry["translation"] = translation

                # Deduplicate on same parent
                existing = {m["expression"].lower() for m in mwe_by_word[parent_key]}
                if dword.lower() not in existing:
                    mwe_by_word[parent_key].append(mwe_entry)
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
        best_word = None
        for t in tokens:
            t_norm = strip_accents(t)
            in_inv = t in word_set or t_norm in word_set
            matched_word = t if t in word_set else (t_norm if t_norm in word_set else None)
            rank = word_to_rank.get(t, word_to_rank.get(t_norm, -1))
            if in_inv and rank > best_rank:
                best_rank = rank
                best_word = matched_word

        if not best_word:
            continue

        existing = {m["expression"].lower() for m in mwe_by_word[best_word]}
        if key not in existing:
            mwe_entry = {"expression": sp["expression"]}
            if sp["translation"]:
                mwe_entry["translation"] = sp["translation"]
            mwe_by_word[best_word].append(mwe_entry)
            standalone_attached += 1

    print(f"    Standalone attached: {standalone_attached}")

    # Enrich untranslated MWEs from headword glosses and standalone translations
    enriched = 0
    for parent_w, mwes in mwe_by_word.items():
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

    # --- Count corpus frequency via Aho-Corasick on OpenSubtitles sample ---
    total_before = sum(len(v) for v in mwe_by_word.values())
    print(f"\nCounting corpus frequency ({OPENSUBS_FILE.name}, 1/{SAMPLE_STRIDE} sample)...")
    all_expressions = {}  # expression_lower -> list of (parent_word, idx) pointers
    for parent_w, mwes in mwe_by_word.items():
        for i, m in enumerate(mwes):
            key = m["expression"].lower()
            all_expressions.setdefault(key, []).append((parent_w, i))

    # Collect parent words that need counting (only those with MWEs)
    parent_words = set(mwe_by_word.keys())

    A = ahocorasick.Automaton()
    for expr in all_expressions:
        A.add_word(expr, expr)
    A.make_automaton()

    expr_counts = {e: 0 for e in all_expressions}
    word_counts = {w: 0 for w in parent_words}
    parent_word_set = parent_words
    t0 = time.time()
    line_count = 0
    with open(OPENSUBS_FILE, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i % SAMPLE_STRIDE != 0:
                continue
            line_count += 1
            low = line.lower()
            # Count MWE expressions via Aho-Corasick
            for _, expr in A.iter(low):
                expr_counts[expr] += 1
            # Count parent words — iterate the smaller set (line tokens)
            for tok in low.split():
                if tok in parent_word_set:
                    word_counts[tok] += 1

    elapsed = time.time() - t0
    nonzero = sum(1 for c in expr_counts.values() if c > 0)
    print(f"  Scanned {line_count:,} lines in {elapsed:.1f}s")
    print(f"  Expressions with >0 hits: {nonzero}/{len(all_expressions)}")

    # Attach corpus_freq to each MWE entry
    for expr, pointers in all_expressions.items():
        freq = expr_counts[expr]
        for parent_w, idx in pointers:
            mwe_by_word[parent_w][idx]["corpus_freq"] = freq

    # --- Filter by frequency ratio (MWE freq / parent word freq) ---
    ratio_removed = 0
    for w in list(mwe_by_word):
        wf = word_counts.get(w, 0)
        if wf == 0:
            continue  # can't compute ratio, keep all
        filtered = []
        for m in mwe_by_word[w]:
            mf = m.get("corpus_freq", 0)
            ratio = mf / wf
            if ratio >= MIN_FREQ_RATIO:
                filtered.append(m)
            else:
                ratio_removed += 1
        mwe_by_word[w] = filtered
        if not mwe_by_word[w]:
            del mwe_by_word[w]
    print(f"  Ratio filter (>={MIN_FREQ_RATIO:.0%} of parent word): removed {ratio_removed}")

    # --- Truncate long translations ---
    for mwes in mwe_by_word.values():
        for m in mwes:
            trans = m.get("translation", "")
            if len(trans) > MAX_TRANSLATION_LEN:
                parts = re.split(r"[;,]\s*", trans)
                result = parts[0]
                for part in parts[1:]:
                    candidate = result + ", " + part
                    if len(candidate) > MAX_TRANSLATION_LEN:
                        break
                    result = candidate
                if len(result) > MAX_TRANSLATION_LEN:
                    result = result[:MAX_TRANSLATION_LEN - 3] + "..."
                m["translation"] = result

    # --- Sort by corpus frequency (descending), cap per word ---
    for w in list(mwe_by_word):
        mwe_by_word[w].sort(key=lambda m: -m.get("corpus_freq", 0))
        mwe_by_word[w] = mwe_by_word[w][:MAX_MWES_PER_WORD]
        if not mwe_by_word[w]:
            del mwe_by_word[w]

    total_after = sum(len(v) for v in mwe_by_word.values())
    print(f"\n  Before filtering: {total_before:,} MWEs across {len(mwe_by_word):,} words")
    print(f"  After cap ({MAX_MWES_PER_WORD}/word): {total_after:,} MWEs")

    # Write output
    print(f"\nWriting {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(mwe_by_word), f, ensure_ascii=False, indent=2)
    write_sidecar(OUTPUT_FILE, make_meta("build_mwes", STEP_VERSION))

    # Stats
    words_with_mwes = len(mwe_by_word)
    translated = sum(
        1 for mwes in mwe_by_word.values()
        for m in mwes if m.get("translation")
    )

    print(f"\n{'='*55}")
    print("MWE EXTRACTION RESULTS")
    print(f"{'='*55}")
    print(f"Words with MWEs:         {words_with_mwes:>6}")
    print(f"Total MWE memberships:   {total_after:>6}")
    print(f"  With translation:      {translated:>6}")
    print(f"  Without translation:   {total_after - translated:>6}")

    # Sample output — show top MWEs by corpus frequency
    print("\nSample entries:")
    sample_words = {"verdad", "mano", "hacer", "dar", "ojo", "cuenta"}
    for entry in inventory:
        w = entry["word"]
        if w in sample_words and w in mwe_by_word:
            sample_words.discard(w)
            mwes = mwe_by_word[w]
            print(f"\n  {entry['word']} ({len(mwes)} MWEs):")
            for m in mwes[:5]:
                trans = m.get("translation", "(no translation)")
                freq = m.get("corpus_freq", 0)
                print(f"    {m['expression']:30s}  freq={freq:<6}  {trans}")
            if len(mwes) > 5:
                print(f"    ... and {len(mwes) - 5} more")
            if not sample_words:
                break


if __name__ == "__main__":
    main()
