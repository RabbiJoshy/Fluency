#!/usr/bin/env python3
"""
match_senses.py — Step 5: Assign example sentences to word senses.

Uses a cross-encoder for sentence-to-sense classification (most accurate),
plus a bi-encoder for post-classification sense merging (cosine similarity).

Cross-encoder scores all (sentence, sense) pairs per word in one batch.
Only multi-sense words are processed; single-sense words skip classification.

Fallback: --keyword-only uses keyword overlap (instant, ~70% accuracy).

Usage:
    python3 Data/Spanish/Scripts/match_senses.py
    python3 Data/Spanish/Scripts/match_senses.py --keyword-only

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/layers/examples_raw.json
    Data/Spanish/layers/senses_wiktionary.json

Output:
    Data/Spanish/layers/sense_assignments.json
"""

import argparse
import json
import re
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"
INVENTORY_FILE = LAYERS / "word_inventory.json"
EXAMPLES_FILE = LAYERS / "examples_raw.json"
SENSES_FILE = LAYERS / "senses_wiktionary.json"
OUTPUT_FILE = LAYERS / "sense_assignments.json"

MAX_EXAMPLES_PER_MEANING = 5
MAX_CLASSIFY_EXAMPLES = 20  # cap examples used for classification (frequency voting)
MIN_SENSE_FREQUENCY = 0.05  # drop senses with < 5% of examples
SENSE_MERGE_THRESHOLD = 0.70  # merge same-POS senses with cosine sim above this
BIENCODER_MODEL = "paraphrase-multilingual-mpnet-base-v2"  # for sense merge only
CROSSENCODER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
SAVE_INTERVAL = 500  # intermediate save every N multi-sense words

# ---------------------------------------------------------------------------
# POS enrichment for embedding
# ---------------------------------------------------------------------------
_POS_LABELS = {
    "VERB": "verb meaning",
    "NOUN": "noun meaning",
    "ADJ": "adjective meaning",
    "ADV": "adverb meaning",
    "ADP": "preposition meaning",
    "CCONJ": "conjunction meaning",
    "PRON": "pronoun meaning",
    "DET": "determiner meaning",
    "INTJ": "interjection meaning",
    "NUM": "numeral meaning",
    "PART": "particle meaning",
    "PHRASE": "phrase meaning",
    "CONTRACTION": "contraction meaning",
}


def enrich_sense_text(sense):
    """Build embedding-friendly text from a sense dict.
    Uses detail field when available for richer context."""
    label = _POS_LABELS.get(sense["pos"], sense["pos"])
    text = sense.get("detail") or sense["translation"]
    return "{}: {}".format(label, text)


def bilingual_text(ex):
    """Build bilingual text from an example dict."""
    eng = ex.get("english", "")
    spa = ex.get("target", "")
    if eng and spa:
        return "{} [Spanish: {}]".format(eng, spa)
    return eng


# ---------------------------------------------------------------------------
# Cross-encoder: batch classification per word
# ---------------------------------------------------------------------------

def load_crossencoder():
    """Load cross-encoder model."""
    from sentence_transformers import CrossEncoder
    print("Loading cross-encoder '{}'...".format(CROSSENCODER_MODEL))
    return CrossEncoder(CROSSENCODER_MODEL)


def classify_word_crossencoder(crossencoder, examples, senses, max_classify):
    """Classify all examples for one word in a single batch.

    Args:
        crossencoder: loaded CrossEncoder model
        examples: list of example dicts
        senses: list of sense dicts
        max_classify: max examples to use for classification

    Returns:
        sense_example_indices: list of lists, sense_idx -> [example indices]
        num_pairs: number of pairs scored
    """
    n_senses = len(senses)
    sense_texts = [enrich_sense_text(s) for s in senses]

    # Determine which examples to classify (cap at max_classify)
    classify_indices = []
    for ei, ex in enumerate(examples):
        eng = ex.get("english", "")
        if eng:
            classify_indices.append(ei)
        if len(classify_indices) >= max_classify:
            break

    if not classify_indices:
        return [[] for _ in senses], 0

    # Build all pairs for this word in one batch
    pairs = []
    pair_map = []  # (example_list_position, sense_idx)
    for ci, ei in enumerate(classify_indices):
        bt = bilingual_text(examples[ei])
        for si, st in enumerate(sense_texts):
            pairs.append((bt, st))
            pair_map.append((ci, si))

    # Score all pairs at once
    scores = crossencoder.predict(pairs).tolist()

    # Distribute: for each example, pick the sense with highest score
    sense_example_indices = [[] for _ in senses]
    for ci, ei in enumerate(classify_indices):
        example_scores = scores[ci * n_senses:(ci + 1) * n_senses]
        best_idx = max(range(n_senses), key=lambda i: example_scores[i])
        sense_example_indices[best_idx].append(ei)

    # Also assign non-English examples to sense 0
    for ei, ex in enumerate(examples):
        if not ex.get("english", "") and ei not in classify_indices:
            sense_example_indices[0].append(ei)

    return sense_example_indices, len(pairs)


# ---------------------------------------------------------------------------
# Bi-encoder: for sense-to-sense similarity (merge step only)
# ---------------------------------------------------------------------------

def build_sense_embeddings(senses_data, inventory):
    """Embed only sense texts for the merge step. Much smaller than full corpus."""
    from sentence_transformers import SentenceTransformer

    unique_texts = {}
    text_list = []

    for entry in inventory:
        key = "{}|{}".format(entry["word"], entry["lemma"])
        senses = senses_data.get(key, [])
        if len(senses) < 2:
            continue
        for s in senses:
            t = enrich_sense_text(s)
            if t not in unique_texts:
                unique_texts[t] = len(text_list)
                text_list.append(t)

    if not text_list:
        return {}, None

    print("Loading bi-encoder '{}' (sense merge only)...".format(BIENCODER_MODEL))
    model = SentenceTransformer(BIENCODER_MODEL)
    print("Embedding {:,} unique sense texts...".format(len(text_list)))
    start = time.time()
    embeddings = model.encode(text_list, normalize_embeddings=True, show_progress_bar=False)
    print("  Done in {:.1f}s".format(time.time() - start))

    return unique_texts, embeddings


# ---------------------------------------------------------------------------
# Keyword overlap classifier (fallback)
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


def classify_example_keyword(sentence_english, senses):
    """Classify using keyword overlap. Returns (best_sense_index, confidence)."""
    sentence_words = tokenize_english(sentence_english)
    scores = []
    for s in senses:
        sense_words = tokenize_english(s["translation"])
        scores.append(len(sentence_words & sense_words) if sense_words else 0)

    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    sorted_scores = sorted(scores, reverse=True)
    confidence = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) >= 2 else 0
    return best_idx, confidence


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Assign examples to senses")
    parser.add_argument("--keyword-only", action="store_true",
                        help="Use keyword overlap instead of embeddings")
    args = parser.parse_args()

    use_embeddings = not args.keyword_only
    method = "cross-encoder + bi-encoder merge" if use_embeddings else "keyword overlap"
    print("Sense matching method: {}".format(method))

    print("\nLoading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        inventory = json.load(f)
    print("  {:,} entries".format(len(inventory)))

    print("Loading examples...")
    with open(EXAMPLES_FILE, encoding="utf-8") as f:
        examples_data = json.load(f)
    print("  {:,} entries with examples".format(len(examples_data)))

    print("Loading senses...")
    with open(SENSES_FILE, encoding="utf-8") as f:
        senses_data = json.load(f)
    print("  {:,} sense entries".format(len(senses_data)))

    # Load models if needed
    crossencoder = None
    sense_text_to_idx = None
    sense_embeddings = None
    if use_embeddings:
        print()
        crossencoder = load_crossencoder()
        sense_text_to_idx, sense_embeddings = build_sense_embeddings(
            senses_data, inventory)

    # Load partial progress if it exists (resume after crash)
    partial_file = OUTPUT_FILE.with_suffix(".partial.json")
    output = {}
    start_from = 0
    if partial_file.exists():
        try:
            with open(partial_file, encoding="utf-8") as f:
                saved = json.load(f)
            output = saved.get("assignments", {})
            start_from = saved.get("next_entry", 0)
            print("\nResuming from entry {:,} ({:,} assignments loaded from partial save)".format(
                start_from, len(output)))
        except (json.JSONDecodeError, KeyError):
            print("\nCorrupt partial file, starting fresh")
            output = {}
            start_from = 0

    print("\nAssigning examples to senses...")
    stats = {
        "no_senses": 0,
        "single_sense": 0,
        "multi_sense": 0,
        "no_examples": 0,
        "total_pairs": 0,
        "active_senses": defaultdict(int),
        "merged_senses": 0,
        "filtered_senses": 0,
    }

    classify_start = time.time()
    total_entries = len(inventory)
    multi_processed = 0

    for entry_num, entry in enumerate(inventory):
        if entry_num < start_from:
            continue

        word_id = entry["id"]
        key = "{}|{}".format(entry["word"], entry["lemma"])
        senses = senses_data.get(key, [])
        examples = examples_data.get(word_id, [])

        # Case 1: No senses
        if not senses:
            stats["no_senses"] += 1
            continue

        # Case 2: No examples
        if not examples:
            stats["no_examples"] += 1
            output[word_id] = [{"sense_idx": 0, "examples": []}]
            stats["active_senses"][1] += 1
            continue

        # Case 3: Single sense — all examples go to it, no classification
        if len(senses) == 1:
            stats["single_sense"] += 1
            indices = list(range(min(len(examples), MAX_EXAMPLES_PER_MEANING)))
            output[word_id] = [{"sense_idx": 0, "examples": indices}]
            stats["active_senses"][1] += 1
            continue

        # Case 4: Multi-sense — classify
        stats["multi_sense"] += 1
        multi_processed += 1

        # Progress + checkpoint
        if multi_processed % SAVE_INTERVAL == 0:
            elapsed = time.time() - classify_start
            rate = stats["total_pairs"] / elapsed if elapsed > 0 else 0
            print("  {:,}/{:,} words | {:,} multi-sense | {:,} pairs scored ({:.0f}/sec, {:.1f}s)".format(
                entry_num + 1, total_entries, multi_processed,
                stats["total_pairs"], rate, elapsed), flush=True)
            with open(partial_file, "w", encoding="utf-8") as f:
                json.dump({"next_entry": entry_num, "assignments": output},
                          f, ensure_ascii=False)

        if use_embeddings:
            sense_example_indices, n_pairs = classify_word_crossencoder(
                crossencoder, examples, senses, MAX_CLASSIFY_EXAMPLES)
            stats["total_pairs"] += n_pairs
        else:
            sense_example_indices = [[] for _ in senses]
            for ex_idx, ex in enumerate(examples):
                eng = ex.get("english", "")
                if not eng:
                    sense_example_indices[0].append(ex_idx)
                    continue
                best_idx, _ = classify_example_keyword(eng, senses)
                sense_example_indices[best_idx].append(ex_idx)

        # Merge same-POS senses with high embedding similarity
        if use_embeddings and sense_embeddings is not None and len(senses) >= 2:
            import numpy as np
            for i in range(len(senses)):
                si_text = enrich_sense_text(senses[i])
                si_idx = sense_text_to_idx.get(si_text)
                if si_idx is None:
                    continue
                for j in range(i + 1, len(senses)):
                    if not sense_example_indices[j]:
                        continue
                    if senses[i]["pos"] != senses[j]["pos"]:
                        continue
                    sj_text = enrich_sense_text(senses[j])
                    sj_idx = sense_text_to_idx.get(sj_text)
                    if sj_idx is None:
                        continue
                    sim = float(np.dot(sense_embeddings[si_idx], sense_embeddings[sj_idx]))
                    if sim >= SENSE_MERGE_THRESHOLD:
                        sense_example_indices[i].extend(sense_example_indices[j])
                        sense_example_indices[j] = []
                        stats["merged_senses"] += 1

        # Filter by frequency threshold, cap examples
        total_classified = sum(len(idx) for idx in sense_example_indices)
        assignments = []
        for i, indices in enumerate(sense_example_indices):
            if not indices:
                continue
            if total_classified >= 5:
                freq = len(indices) / total_classified
                if freq < MIN_SENSE_FREQUENCY:
                    stats["filtered_senses"] += 1
                    continue
            assignments.append({
                "sense_idx": i,
                "examples": indices[:MAX_EXAMPLES_PER_MEANING],
            })

        # Fallback: if no sense survived filtering, assign all to first
        if not assignments:
            indices = list(range(min(len(examples), MAX_EXAMPLES_PER_MEANING)))
            assignments = [{"sense_idx": 0, "examples": indices}]

        output[word_id] = assignments
        stats["active_senses"][len(assignments)] += 1

    elapsed = time.time() - classify_start
    print("  {:,}/{:,} words | {:,} multi-sense | {:,} pairs scored ({:.1f}s)".format(
        total_entries, total_entries, multi_processed,
        stats["total_pairs"], elapsed), flush=True)

    # Write final output
    print("\nWriting {}...".format(OUTPUT_FILE))
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Clean up partial file
    if partial_file.exists():
        partial_file.unlink()
        print("  Removed partial checkpoint")

    # Report
    total = len(inventory)
    rate = stats["total_pairs"] / elapsed if elapsed > 0 else 0

    print("\n{}".format("=" * 55))
    print("SENSE ASSIGNMENT RESULTS ({})".format(method))
    print("{}".format("=" * 55))
    print("Total vocabulary:          {:>6,}".format(total))
    print("No Wiktionary senses:      {:>6,}".format(stats["no_senses"]))
    print("Single sense:              {:>6,}".format(stats["single_sense"]))
    print("Multi-sense (classified):  {:>6,}".format(stats["multi_sense"]))
    print("No examples:               {:>6,}".format(stats["no_examples"]))
    print()
    print("Total pairs scored:        {:>8,}".format(stats["total_pairs"]))
    print("Throughput:                {:>6,.0f} pairs/sec".format(rate))
    print("Senses merged (sim>={:.2f}): {:>5,}".format(
        SENSE_MERGE_THRESHOLD, stats["merged_senses"]))
    print("Senses filtered (<{:.0f}%): {:>6,}".format(
        MIN_SENSE_FREQUENCY * 100, stats["filtered_senses"]))
    print()
    print("Active senses per word:")
    for n in sorted(stats["active_senses"]):
        count = stats["active_senses"][n]
        print("  {} senses: {:>6,} words".format(n, count))

    print("\nTotal time: {:.1f}s ({:.1f} min)".format(elapsed, elapsed / 60))


if __name__ == "__main__":
    main()
