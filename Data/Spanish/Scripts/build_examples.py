#!/usr/bin/env python3
"""
build_examples.py — Build vocabulary.json with corpus-sourced example sentences.

Takes the existing vocabulary structure (word/lemma/meanings) and matches
example sentences from parallel corpora (Tatoeba, later OpenSubtitles).

Usage:
    python3 Data/Spanish/Scripts/build_examples.py

Run from the project root (Fluency/).

Inputs:
    Data/Spanish/vocabulary.json          — word/lemma/meanings structure (updated in-place)
    Data/Spanish/corpora/tatoeba/spa.txt  — Tatoeba sentence pairs
    Data/Spanish/spanish_ranks.json       — frequency ranks for easiness

Output:
    Data/Spanish/vocabulary.json          — same file, with examples replaced
"""

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from statistics import median

# ---------------------------------------------------------------------------
# Paths (relative to project root)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
VOCAB_INPUT = PROJECT_ROOT / "Data" / "Spanish" / "vocabulary.json"
TATOEBA_FILE = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "tatoeba" / "spa.txt"
RANKS_FILE = PROJECT_ROOT / "Data" / "Spanish" / "spanish_ranks.json"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "vocabulary.json"

SENTINEL_RANK = 999_999
MAX_EXAMPLES_PER_WORD = 8
MIN_SENTENCE_WORDS = 3   # Skip very short sentences like "Ve." / "Hola."
MAX_SENTENCE_WORDS = 25  # Skip very long sentences

# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-záéíóúüñ]+")


def strip_accents(s: str) -> str:
    """Remove diacritics for accent-normalized matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def tokenize(text: str) -> list[str]:
    """Lowercase tokenize Spanish text, keeping only letter tokens."""
    return _TOKEN_RE.findall(text.lower())


# ---------------------------------------------------------------------------
# Easiness scoring (mirrors Artists/scripts/8_rerank.py)
# ---------------------------------------------------------------------------
def compute_easiness(spanish_text: str, word_to_rank: dict) -> int:
    """
    Compute sentence difficulty as median Spanish frequency rank of tokens.
    Lower = easier (more common words).
    """
    tokens = tokenize(spanish_text)
    if not tokens:
        return SENTINEL_RANK

    ranks = []
    for t in tokens:
        # Try exact match first, then accent-stripped
        rank = word_to_rank.get(t)
        if rank is None:
            rank = word_to_rank.get(strip_accents(t))
        if rank is None:
            rank = SENTINEL_RANK
        ranks.append(rank)

    return int(median(ranks))


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------
def load_tatoeba(path: Path) -> list[tuple[str, str]]:
    """Load Tatoeba TSV: English\\tSpanish\\tAttribution -> [(english, spanish)]"""
    sentences = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                eng, spa = parts[0].strip(), parts[1].strip()
                if eng and spa:
                    sentences.append((eng, spa))
    return sentences


# ---------------------------------------------------------------------------
# Sentence index
# ---------------------------------------------------------------------------
def build_sentence_index(
    sentences: list[tuple[str, str]],
) -> dict[str, list[int]]:
    """
    Build mapping: normalized_token -> [sentence_indices].
    Uses accent-normalized tokens so 'aquí' matches vocab entry 'aqui'.
    """
    index = defaultdict(list)
    for i, (eng, spa) in enumerate(sentences):
        tokens = tokenize(spa)
        # Filter sentences that are too short or too long
        if len(tokens) < MIN_SENTENCE_WORDS or len(tokens) > MAX_SENTENCE_WORDS:
            continue
        seen = set()
        for t in tokens:
            norm = strip_accents(t)
            if norm not in seen:
                seen.add(norm)
                index[norm].append(i)
    return index


# ---------------------------------------------------------------------------
# Example selection
# ---------------------------------------------------------------------------
def select_examples(
    candidate_indices: list[int],
    sentences: list[tuple[str, str]],
    word_to_rank: dict,
    max_examples: int = MAX_EXAMPLES_PER_WORD,
) -> list[dict]:
    """
    Score candidates by easiness, deduplicate, pick top N.
    Returns list of {"target": ..., "english": ..., "easiness": ...}.
    """
    scored = []
    seen_targets = set()
    for idx in candidate_indices:
        eng, spa = sentences[idx]
        # Deduplicate by Spanish text (lowercased)
        key = spa.lower().strip()
        if key in seen_targets:
            continue
        seen_targets.add(key)

        easiness = compute_easiness(spa, word_to_rank)
        scored.append({
            "target": spa,
            "english": eng,
            "easiness": easiness,
        })

    # Sort by easiness (easier first)
    scored.sort(key=lambda x: x["easiness"])

    return scored[:max_examples]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("Loading vocabulary...")
    with open(VOCAB_INPUT, encoding="utf-8") as f:
        vocab = json.load(f)
    print(f"  {len(vocab)} entries")

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

    # Stats tracking
    coverage = {"0": 0, "1-2": 0, "3-5": 0, "5+": 0}
    total_examples = 0

    print("Matching examples to vocabulary...")
    for entry in vocab:
        word = entry["word"].lower()
        word_norm = strip_accents(word)

        # Find candidate sentences
        candidate_indices = sentence_index.get(word_norm, [])

        # Select best examples
        examples = select_examples(
            candidate_indices, sentences, word_to_rank
        )

        # Track stats
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

        # Attach examples to meanings
        # For now: all examples go to every meaning (no sense-specific matching)
        for meaning in entry.get("meanings", []):
            meaning["examples"] = examples

    # Write output
    print(f"\nWriting {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)

    # Report
    print(f"\n{'='*50}")
    print(f"RESULTS")
    print(f"{'='*50}")
    print(f"Total vocabulary entries: {len(vocab)}")
    print(f"Total examples attached:  {total_examples}")
    print(f"")
    print(f"Coverage breakdown:")
    print(f"  0 examples:   {coverage['0']:5d} words")
    print(f"  1-2 examples: {coverage['1-2']:5d} words")
    print(f"  3-5 examples: {coverage['3-5']:5d} words")
    print(f"  5+ examples:  {coverage['5+']:5d} words")
    print(f"")
    pct = 100 * (len(vocab) - coverage["0"]) / len(vocab)
    print(f"Words with at least 1 example: {pct:.1f}%")


if __name__ == "__main__":
    main()
