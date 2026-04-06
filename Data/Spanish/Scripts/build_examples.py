#!/usr/bin/env python3
"""
build_examples.py — Build vocabulary.json from frequency CSV + corpus examples.

Generates the vocabulary from scratch using:
  - SpanishRawWiki.csv as source of truth (rank, word, lemma)
  - Tatoeba sentence pairs for example sentences
  - spanish_ranks.json for easiness scoring
  - 6-char hex IDs via md5(word|lemma)

Usage:
    python3 Data/Spanish/Scripts/build_examples.py

Run from the project root (Fluency/).
"""

import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from statistics import median

# ---------------------------------------------------------------------------
# Paths (relative to project root)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
CSV_SOURCE = PROJECT_ROOT / "Data" / "Spanish" / "SpanishRawWiki.csv"
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


def strip_accents(s):
    """Remove diacritics for accent-normalized matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def tokenize(text):
    """Lowercase tokenize Spanish text, keeping only letter tokens."""
    return _TOKEN_RE.findall(text.lower())


# ---------------------------------------------------------------------------
# ID generation (mirrors Artists/scripts/merge_to_master.py)
# ---------------------------------------------------------------------------
def make_stable_id(word, lemma, used):
    """6-char hex ID from md5(word|lemma). On collision, slide the hash window."""
    h = hashlib.md5((word + "|" + lemma).encode("utf-8")).hexdigest()
    base_id = h[:6]

    if base_id not in used:
        return base_id

    for start in range(1, len(h) - 5):
        candidate = h[start:start + 6]
        if candidate not in used:
            return candidate

    val = int(base_id, 16) + 1
    while True:
        candidate = format(val % 0xFFFFFF, "06x")
        if candidate not in used:
            return candidate
        val += 1


# ---------------------------------------------------------------------------
# Vocabulary building from CSV
# ---------------------------------------------------------------------------
def load_csv_vocab(path):
    """
    Load SpanishRawWiki.csv -> list of entries with rank, word, lemma, id.
    Computes most_frequent_lemma_instance flag.
    """
    entries = []
    used_ids = set()

    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = row["word"]
            lemma = row["lemma"]
            rank = int(row["rank"])
            word_id = make_stable_id(word, lemma, used_ids)
            used_ids.add(word_id)

            entries.append({
                "rank": rank,
                "word": word,
                "lemma": lemma,
                "id": word_id,
                "examples": [],
            })

    # Compute most_frequent_lemma_instance:
    # For each lemma, the entry with the lowest rank (highest frequency) gets True
    seen_lemmas = {}
    for entry in entries:
        lemma = entry["lemma"].lower()
        if lemma not in seen_lemmas:
            seen_lemmas[lemma] = entry
    for entry in entries:
        entry["most_frequent_lemma_instance"] = (
            entry is seen_lemmas[entry["lemma"].lower()]
        )

    return entries


# ---------------------------------------------------------------------------
# Easiness scoring (mirrors Artists/scripts/8_rerank.py)
# ---------------------------------------------------------------------------
def compute_easiness(spanish_text, word_to_rank):
    """
    Compute sentence difficulty as median Spanish frequency rank of tokens.
    Lower = easier (more common words).
    """
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


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------
def load_tatoeba(path):
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
def build_sentence_index(sentences):
    """
    Build mapping: normalized_token -> [sentence_indices].
    Uses accent-normalized tokens so 'aquí' matches vocab entry 'aqui'.
    """
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


# ---------------------------------------------------------------------------
# Example selection
# ---------------------------------------------------------------------------
def select_examples(candidate_indices, sentences, word_to_rank,
                    max_examples=MAX_EXAMPLES_PER_WORD):
    """
    Score candidates by easiness, deduplicate, pick top N.
    Returns list of {"target": ..., "english": ..., "easiness": ...}.
    """
    scored = []
    seen_targets = set()
    for idx in candidate_indices:
        eng, spa = sentences[idx]
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

    scored.sort(key=lambda x: x["easiness"])
    return scored[:max_examples]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("Loading vocabulary from CSV...")
    vocab = load_csv_vocab(CSV_SOURCE)
    print(f"  {len(vocab)} entries")

    lemma_true = sum(1 for e in vocab if e["most_frequent_lemma_instance"])
    print(f"  {lemma_true} unique lemma representatives")

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
        word_norm = strip_accents(entry["word"].lower())
        candidate_indices = sentence_index.get(word_norm, [])
        examples = select_examples(candidate_indices, sentences, word_to_rank)

        entry["examples"] = examples

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

    # Write output
    print(f"\nWriting {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)

    # Report
    print(f"\n{'='*50}")
    print("RESULTS")
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
