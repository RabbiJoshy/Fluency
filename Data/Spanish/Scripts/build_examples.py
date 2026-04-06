#!/usr/bin/env python3
"""
build_examples.py — Step 2: Match Tatoeba example sentences to vocabulary.

Reads the word inventory and Tatoeba corpus, finds example sentences for each
word, scores them by easiness, and writes a keyed examples layer.

Usage:
    python3 Data/Spanish/Scripts/build_examples.py

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/corpora/tatoeba/spa.txt
    Data/Spanish/spanish_ranks.json

Output:
    Data/Spanish/layers/examples_raw.json  — {id: [{target, english, easiness}]}
"""

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from statistics import median

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INVENTORY_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"
TATOEBA_FILE = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "tatoeba" / "spa.txt"
RANKS_FILE = PROJECT_ROOT / "Data" / "Spanish" / "spanish_ranks.json"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "examples_raw.json"

SENTINEL_RANK = 999_999
MAX_EXAMPLES_PER_WORD = 8
MIN_SENTENCE_WORDS = 3
MAX_SENTENCE_WORDS = 25

_TOKEN_RE = re.compile(r"[a-záéíóúüñ]+")


def strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def tokenize(text):
    return _TOKEN_RE.findall(text.lower())


def compute_easiness(spanish_text, word_to_rank):
    tokens = tokenize(spanish_text)
    if not tokens:
        return SENTINEL_RANK
    ranks = []
    for t in tokens:
        rank = word_to_rank.get(t)
        if rank is None:
            rank = word_to_rank.get(strip_accents(t))
        if rank is None:
            rank = SENTINEL_RANK
        ranks.append(rank)
    return int(median(ranks))


def load_tatoeba(path):
    sentences = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                eng, spa = parts[0].strip(), parts[1].strip()
                if eng and spa:
                    sentences.append((eng, spa))
    return sentences


def build_sentence_index(sentences):
    index = defaultdict(list)
    for i, (eng, spa) in enumerate(sentences):
        tokens = tokenize(spa)
        if len(tokens) < MIN_SENTENCE_WORDS or len(tokens) > MAX_SENTENCE_WORDS:
            continue
        seen = set()
        for t in tokens:
            norm = strip_accents(t)
            if norm not in seen:
                seen.add(norm)
                index[norm].append(i)
    return index


def select_examples(candidate_indices, sentences, word_to_rank,
                    max_examples=MAX_EXAMPLES_PER_WORD):
    scored = []
    seen_targets = set()
    for idx in candidate_indices:
        eng, spa = sentences[idx]
        key = spa.lower().strip()
        if key in seen_targets:
            continue
        seen_targets.add(key)
        easiness = compute_easiness(spa, word_to_rank)
        scored.append({"target": spa, "english": eng, "easiness": easiness})
    scored.sort(key=lambda x: x["easiness"])
    return scored[:max_examples]


def main():
    print("Loading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        inventory = json.load(f)
    print(f"  {len(inventory)} entries")

    print("Loading spanish_ranks.json...")
    with open(RANKS_FILE, encoding="utf-8") as f:
        word_to_rank = json.load(f)
    print(f"  {len(word_to_rank)} rank entries")

    print("Loading Tatoeba corpus...")
    sentences = load_tatoeba(TATOEBA_FILE)
    print(f"  {len(sentences)} sentence pairs")

    print("Building sentence index...")
    sentence_index = build_sentence_index(sentences)
    print(f"  {len(sentence_index)} unique normalized tokens indexed")

    print("Matching examples to vocabulary...")
    output = {}
    coverage = {"0": 0, "1-2": 0, "3-5": 0, "5+": 0}
    total_examples = 0

    for entry in inventory:
        word_norm = strip_accents(entry["word"].lower())
        candidate_indices = sentence_index.get(word_norm, [])
        examples = select_examples(candidate_indices, sentences, word_to_rank)

        if examples:
            output[entry["id"]] = examples

        n = len(examples)
        total_examples += n
        if n == 0:
            coverage["0"] += 1
        elif n <= 2:
            coverage["1-2"] += 1
        elif n <= 5:
            coverage["3-5"] += 1
        else:
            coverage["5+"] += 1

    print(f"\nWriting {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print("RESULTS")
    print(f"{'='*50}")
    print(f"Total vocabulary entries: {len(inventory)}")
    print(f"Total examples attached:  {total_examples}")
    print(f"")
    print(f"Coverage breakdown:")
    print(f"  0 examples:   {coverage['0']:5d} words")
    print(f"  1-2 examples: {coverage['1-2']:5d} words")
    print(f"  3-5 examples: {coverage['3-5']:5d} words")
    print(f"  5+ examples:  {coverage['5+']:5d} words")
    print(f"")
    pct = 100 * (len(inventory) - coverage["0"]) / len(inventory)
    print(f"Words with at least 1 example: {pct:.1f}%")


if __name__ == "__main__":
    main()
