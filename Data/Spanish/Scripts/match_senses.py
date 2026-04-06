#!/usr/bin/env python3
"""
match_senses.py — Assign example sentences to specific word senses.

Takes vocabulary.json (flat examples per word) and senses_wiktionary.json (sense
inventory), classifies each example sentence to its best-matching sense using
keyword overlap, and restructures vocabulary.json with a meanings array.

Usage:
    python3 Data/Spanish/Scripts/match_senses.py

Run from the project root (Fluency/).

Inputs:
    Data/Spanish/vocabulary.json         — flat examples per word
    Data/Spanish/senses_wiktionary.json  — Wiktionary sense inventory

Output:
    Data/Spanish/vocabulary.json         — restructured with meanings array
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
VOCAB_FILE = PROJECT_ROOT / "Data" / "Spanish" / "vocabulary.json"
SENSES_FILE = PROJECT_ROOT / "Data" / "Spanish" / "senses_wiktionary.json"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "vocabulary.json"

MAX_EXAMPLES_PER_MEANING = 5

# ---------------------------------------------------------------------------
# Keyword overlap matching
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-z]+")

# Common English words that don't help disambiguate senses
_STOP_WORDS = {
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "is", "it",
    "be", "as", "or", "by", "and", "not", "with", "from", "that", "this",
    "but", "are", "was", "were", "been", "has", "have", "had", "do", "does",
    "did", "will", "would", "can", "could", "may", "might", "shall", "should",
    "up", "out", "if", "so", "no", "into", "over", "also", "its", "one",
    "e", "g", "etc", "very", "just", "about", "more", "some", "than",
}


def tokenize_english(text):
    """Extract lowercase content words from English text."""
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP_WORDS
            and len(w) > 1}


def score_sentence_to_sense(sentence_words, sense_translation):
    """
    Score how well an English sentence matches a sense translation.
    Returns count of overlapping content words.
    """
    sense_words = tokenize_english(sense_translation)
    if not sense_words:
        return 0
    return len(sentence_words & sense_words)


def classify_example(sentence_english, senses):
    """
    Classify an English sentence to the best-matching sense.
    Returns (best_sense_index, confidence).
    Confidence = best_score - second_best_score.
    """
    sentence_words = tokenize_english(sentence_english)
    scores = [score_sentence_to_sense(sentence_words, s["translation"])
              for s in senses]

    best_idx = 0
    best_score = scores[0]
    for i, sc in enumerate(scores):
        if sc > best_score:
            best_score = sc
            best_idx = i

    # Confidence: gap between top 2
    sorted_scores = sorted(scores, reverse=True)
    confidence = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) >= 2 else 0

    return best_idx, confidence


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Load data
    print("Loading vocabulary...")
    with open(VOCAB_FILE, encoding="utf-8") as f:
        vocab = json.load(f)
    print(f"  {len(vocab)} entries")

    print("Loading Wiktionary senses...")
    with open(SENSES_FILE, encoding="utf-8") as f:
        senses_data = json.load(f)
    print(f"  {len(senses_data)} sense entries")

    # Assign examples to senses
    print("\nAssigning examples to senses...")
    stats = {
        "no_senses": 0,
        "single_sense": 0,
        "multi_sense": 0,
        "no_examples": 0,
        "confidence_sum": 0.0,
        "confidence_count": 0,
        "active_senses": defaultdict(int),
    }

    for entry in vocab:
        key = f"{entry['word']}|{entry['lemma']}"
        senses = senses_data.get(key, [])
        examples = entry.get("examples", [])

        # Remove flat examples key — will be replaced with meanings
        if "examples" in entry:
            del entry["examples"]

        # Case 1: No Wiktionary senses found
        if not senses:
            stats["no_senses"] += 1
            entry["meanings"] = [{
                "pos": "X",
                "translation": "",
                "frequency": "1.00",
                "examples": examples[:MAX_EXAMPLES_PER_MEANING],
            }] if examples else []
            stats["active_senses"][1 if examples else 0] += 1
            continue

        # Case 2: No examples for this word
        if not examples:
            stats["no_examples"] += 1
            entry["meanings"] = [{
                "pos": senses[0]["pos"],
                "translation": senses[0]["translation"],
                "frequency": "1.00",
                "examples": [],
            }]
            stats["active_senses"][1] += 1
            continue

        # Case 3: Single sense
        if len(senses) == 1:
            stats["single_sense"] += 1
            entry["meanings"] = [{
                "pos": senses[0]["pos"],
                "translation": senses[0]["translation"],
                "frequency": "1.00",
                "examples": examples[:MAX_EXAMPLES_PER_MEANING],
            }]
            stats["active_senses"][1] += 1
            continue

        # Case 4: Multi-sense — classify by keyword overlap
        stats["multi_sense"] += 1

        sense_examples = [[] for _ in senses]
        for ex in examples:
            eng = ex.get("english", "")
            if not eng:
                sense_examples[0].append(ex)
                continue

            best_idx, confidence = classify_example(eng, senses)
            sense_examples[best_idx].append(ex)

            stats["confidence_sum"] += confidence
            stats["confidence_count"] += 1

        # Build meanings array — only include senses that got examples
        total_assigned = sum(len(se) for se in sense_examples)
        meanings = []
        for i, sense in enumerate(senses):
            exs = sense_examples[i]
            if not exs:
                continue
            freq = len(exs) / total_assigned if total_assigned > 0 else 0
            meanings.append({
                "pos": sense["pos"],
                "translation": sense["translation"],
                "frequency": f"{freq:.2f}",
                "examples": exs[:MAX_EXAMPLES_PER_MEANING],
            })

        # If no sense got examples via keyword match, assign all to first sense
        if not meanings:
            meanings = [{
                "pos": senses[0]["pos"],
                "translation": senses[0]["translation"],
                "frequency": "1.00",
                "examples": examples[:MAX_EXAMPLES_PER_MEANING],
            }]

        entry["meanings"] = meanings
        stats["active_senses"][len(meanings)] += 1

    # Write output
    print(f"\nWriting {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)

    # Report
    total = len(vocab)
    avg_conf = (stats["confidence_sum"] / stats["confidence_count"]
                if stats["confidence_count"] > 0 else 0)

    print(f"\n{'='*55}")
    print("SENSE MATCHING RESULTS")
    print(f"{'='*55}")
    print(f"Total vocabulary:          {total:>6}")
    print(f"No Wiktionary senses:      {stats['no_senses']:>6}")
    print(f"Single sense:              {stats['single_sense']:>6}")
    print(f"Multi-sense (classified):  {stats['multi_sense']:>6}")
    print(f"No examples:               {stats['no_examples']:>6}")
    print(f"")
    print(f"Avg keyword confidence:     {avg_conf:.3f}")
    print(f"")
    print(f"Active senses per word after example assignment:")
    for n in sorted(stats["active_senses"]):
        count = stats["active_senses"][n]
        print(f"  {n} senses: {count:>6} words")

    # Show sample assignments
    print(f"\nSample multi-sense assignments:")
    sample_keys = ["banco|banco", "tiempo|tiempo", "rico|rico",
                   "carta|carta", "poder|poder"]
    for entry in vocab:
        key = f"{entry['word']}|{entry['lemma']}"
        if key in sample_keys:
            sample_keys.remove(key)
            print(f"\n  {key}:")
            for m in entry.get("meanings", []):
                exs = m.get("examples", [])
                ex_preview = exs[0]["english"][:50] if exs else "(none)"
                print(f"    {m['pos']:>6} {m['translation'][:35]:35s} "
                      f"freq={m['frequency']}  ex: {ex_preview}")
            if not sample_keys:
                break


if __name__ == "__main__":
    main()
