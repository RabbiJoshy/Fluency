#!/usr/bin/env python3
"""
match_senses.py — Step 4: Assign example sentences to word senses.

Reads the examples and senses layers, classifies each example to its
best-matching sense using keyword overlap, and writes an assignments layer.

Usage:
    python3 Data/Spanish/Scripts/match_senses.py

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/layers/examples_raw.json
    Data/Spanish/layers/senses_wiktionary.json

Output:
    Data/Spanish/layers/sense_assignments.json
"""

import json
import re
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"
INVENTORY_FILE = LAYERS / "word_inventory.json"
EXAMPLES_FILE = LAYERS / "examples_raw.json"
SENSES_FILE = LAYERS / "senses_wiktionary.json"
OUTPUT_FILE = LAYERS / "sense_assignments.json"

MAX_EXAMPLES_PER_MEANING = 5

# ---------------------------------------------------------------------------
# Keyword overlap matching
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-z]+")

_STOP_WORDS = {
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "is", "it",
    "be", "as", "or", "by", "and", "not", "with", "from", "that", "this",
    "but", "are", "was", "were", "been", "has", "have", "had", "do", "does",
    "did", "will", "would", "can", "could", "may", "might", "shall", "should",
    "up", "out", "if", "so", "no", "into", "over", "also", "its", "one",
    "e", "g", "etc", "very", "just", "about", "more", "some", "than",
}


def tokenize_english(text):
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP_WORDS
            and len(w) > 1}


def classify_example(sentence_english, senses):
    """
    Classify an English sentence to the best-matching sense.
    Returns (best_sense_index, confidence).
    """
    sentence_words = tokenize_english(sentence_english)
    scores = []
    for s in senses:
        sense_words = tokenize_english(s["translation"])
        scores.append(len(sentence_words & sense_words) if sense_words else 0)

    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    sorted_scores = sorted(scores, reverse=True)
    confidence = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) >= 2 else 0
    return best_idx, confidence


def main():
    print("Loading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        inventory = json.load(f)
    print(f"  {len(inventory)} entries")

    print("Loading examples...")
    with open(EXAMPLES_FILE, encoding="utf-8") as f:
        examples_data = json.load(f)
    print(f"  {len(examples_data)} entries with examples")

    print("Loading senses...")
    with open(SENSES_FILE, encoding="utf-8") as f:
        senses_data = json.load(f)
    print(f"  {len(senses_data)} sense entries")

    print("\nAssigning examples to senses...")
    output = {}
    stats = {
        "no_senses": 0,
        "single_sense": 0,
        "multi_sense": 0,
        "no_examples": 0,
        "confidence_sum": 0.0,
        "confidence_count": 0,
        "active_senses": defaultdict(int),
    }

    for entry in inventory:
        word_id = entry["id"]
        key = f"{entry['word']}|{entry['lemma']}"
        senses = senses_data.get(key, [])
        examples = examples_data.get(word_id, [])

        # Case 1: No senses
        if not senses:
            stats["no_senses"] += 1
            # No assignment possible — builder will handle fallback
            continue

        # Case 2: No examples
        if not examples:
            stats["no_examples"] += 1
            # Assign to first sense with empty examples
            output[word_id] = [{"sense_idx": 0, "examples": []}]
            stats["active_senses"][1] += 1
            continue

        # Case 3: Single sense — all examples go to it
        if len(senses) == 1:
            stats["single_sense"] += 1
            indices = list(range(min(len(examples), MAX_EXAMPLES_PER_MEANING)))
            output[word_id] = [{"sense_idx": 0, "examples": indices}]
            stats["active_senses"][1] += 1
            continue

        # Case 4: Multi-sense — classify by keyword overlap
        stats["multi_sense"] += 1
        sense_example_indices = [[] for _ in senses]

        for ex_idx, ex in enumerate(examples):
            eng = ex.get("english", "")
            if not eng:
                sense_example_indices[0].append(ex_idx)
                continue
            best_idx, confidence = classify_example(eng, senses)
            sense_example_indices[best_idx].append(ex_idx)
            stats["confidence_sum"] += confidence
            stats["confidence_count"] += 1

        # Build assignments — only senses that got examples
        assignments = []
        for i, indices in enumerate(sense_example_indices):
            if indices:
                assignments.append({
                    "sense_idx": i,
                    "examples": indices[:MAX_EXAMPLES_PER_MEANING],
                })

        # Fallback: if no sense matched, assign all to first
        if not assignments:
            indices = list(range(min(len(examples), MAX_EXAMPLES_PER_MEANING)))
            assignments = [{"sense_idx": 0, "examples": indices}]

        output[word_id] = assignments
        stats["active_senses"][len(assignments)] += 1

    print(f"\nWriting {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Report
    total = len(inventory)
    avg_conf = (stats["confidence_sum"] / stats["confidence_count"]
                if stats["confidence_count"] > 0 else 0)

    print(f"\n{'='*55}")
    print("SENSE ASSIGNMENT RESULTS")
    print(f"{'='*55}")
    print(f"Total vocabulary:          {total:>6}")
    print(f"No Wiktionary senses:      {stats['no_senses']:>6}")
    print(f"Single sense:              {stats['single_sense']:>6}")
    print(f"Multi-sense (classified):  {stats['multi_sense']:>6}")
    print(f"No examples:               {stats['no_examples']:>6}")
    print(f"")
    print(f"Avg keyword confidence:     {avg_conf:.3f}")
    print(f"")
    print(f"Active senses per word:")
    for n in sorted(stats["active_senses"]):
        count = stats["active_senses"][n]
        print(f"  {n} senses: {count:>6} words")


if __name__ == "__main__":
    main()
