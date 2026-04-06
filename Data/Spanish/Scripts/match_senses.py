#!/usr/bin/env python3
"""
match_senses.py — Step 5: Assign example sentences to word senses.

Default: uses sentence-transformers (local PyTorch) for semantic similarity.
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
MIN_SENSE_FREQUENCY = 0.05  # drop senses with < 5% of examples
SENSE_MERGE_THRESHOLD = 0.70  # merge same-POS senses with cosine sim above this
EMBEDDING_MODEL = "paraphrase-multilingual-mpnet-base-v2"  # 768-dim, multilingual
EMBEDDING_BATCH_SIZE = 256
SAVE_INTERVAL = 2000  # intermediate save every N words

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


# ---------------------------------------------------------------------------
# Local embedding classifier (sentence-transformers)
# ---------------------------------------------------------------------------

def build_embedding_index(senses_data, examples_data, inventory):
    """Collect all unique texts that need embedding. Returns:
    - text_list: ordered list of unique texts
    - text_to_idx: text -> index in text_list
    """
    text_to_idx = {}
    text_list = []

    def add_text(text):
        if text not in text_to_idx:
            text_to_idx[text] = len(text_list)
            text_list.append(text)

    for entry in inventory:
        word_id = entry["id"]
        key = "{}|{}".format(entry["word"], entry["lemma"])
        senses = senses_data.get(key, [])
        examples = examples_data.get(word_id, [])
        if len(senses) < 2 or not examples:
            continue
        for s in senses:
            add_text(enrich_sense_text(s))
        for ex in examples:
            eng = ex.get("english", "")
            spa = ex.get("target", "")
            if eng:
                # Include Spanish for bilingual disambiguation
                embed_key = "{} [Spanish: {}]".format(eng, spa) if spa else eng
                add_text(embed_key)

    return text_list, text_to_idx


def embed_all_texts(text_list):
    """Embed all texts locally using sentence-transformers."""
    from sentence_transformers import SentenceTransformer

    print("Loading model '{}'...".format(EMBEDDING_MODEL))
    model = SentenceTransformer(EMBEDDING_MODEL)

    total = len(text_list)
    print("Embedding {:,} unique texts (batch size {})...".format(
        total, EMBEDDING_BATCH_SIZE))

    start = time.time()
    embeddings = model.encode(
        text_list,
        batch_size=EMBEDDING_BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,  # pre-normalize so dot product = cosine sim
    )
    elapsed = time.time() - start
    print("  Done in {:.1f}s ({:.0f} embeddings/sec, dim={})".format(
        elapsed, total / elapsed, embeddings.shape[1]))

    return embeddings


def classify_example_embedding(sentence_english, senses, text_to_idx, embeddings):
    """Classify using cosine similarity of pre-normalized embeddings."""
    import numpy as np

    sent_idx = text_to_idx.get(sentence_english)
    if sent_idx is None:
        return 0, 0.0

    sent_emb = embeddings[sent_idx]

    scores = []
    for s in senses:
        sense_text = enrich_sense_text(s)
        sense_idx = text_to_idx.get(sense_text)
        if sense_idx is None:
            scores.append(0.0)
            continue
        # dot product of normalized vectors = cosine similarity
        scores.append(float(np.dot(sent_emb, embeddings[sense_idx])))

    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    sorted_scores = sorted(scores, reverse=True)
    confidence = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) >= 2 else 0.0
    return best_idx, confidence


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
    method = "local embeddings ({})".format(EMBEDDING_MODEL) if use_embeddings else "keyword overlap"
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

    # Build embeddings if needed
    text_to_idx = None
    embeddings = None
    if use_embeddings:
        print()
        text_list, text_to_idx = build_embedding_index(
            senses_data, examples_data, inventory)
        if text_list:
            embeddings = embed_all_texts(text_list)
        else:
            print("  No texts to embed — falling back to keyword overlap")
            use_embeddings = False

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
        "confidence_sum": 0.0,
        "confidence_count": 0,
        "active_senses": defaultdict(int),
    }

    classify_start = time.time()
    total_entries = len(inventory)

    for entry_num, entry in enumerate(inventory):
        # Progress + intermediate save
        if entry_num > 0 and entry_num % SAVE_INTERVAL == 0:
            elapsed = time.time() - classify_start
            print("  {:,}/{:,} words ({:.1f}s) — saving checkpoint...".format(
                entry_num, total_entries, elapsed), flush=True)
            with open(partial_file, "w", encoding="utf-8") as f:
                json.dump({"next_entry": entry_num, "assignments": output},
                          f, ensure_ascii=False)

        if entry_num < start_from:
            continue

        if (entry_num + 1) == total_entries:
            elapsed = time.time() - classify_start
            print("  {:,}/{:,} words ({:.1f}s)".format(
                entry_num + 1, total_entries, elapsed), flush=True)

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

        # Case 3: Single sense — all examples go to it
        if len(senses) == 1:
            stats["single_sense"] += 1
            indices = list(range(min(len(examples), MAX_EXAMPLES_PER_MEANING)))
            output[word_id] = [{"sense_idx": 0, "examples": indices}]
            stats["active_senses"][1] += 1
            continue

        # Case 4: Multi-sense — classify
        stats["multi_sense"] += 1
        sense_example_indices = [[] for _ in senses]

        for ex_idx, ex in enumerate(examples):
            eng = ex.get("english", "")
            if not eng:
                sense_example_indices[0].append(ex_idx)
                continue

            if use_embeddings:
                spa = ex.get("target", "")
                embed_key = "{} [Spanish: {}]".format(eng, spa) if spa else eng
                best_idx, confidence = classify_example_embedding(
                    embed_key, senses, text_to_idx, embeddings)
            else:
                best_idx, confidence = classify_example_keyword(eng, senses)

            sense_example_indices[best_idx].append(ex_idx)
            stats["confidence_sum"] += confidence
            stats["confidence_count"] += 1

        # Merge same-POS senses with high embedding similarity.
        # Combines example pools so synonym senses don't dilute each other.
        if use_embeddings and len(senses) >= 2:
            import numpy as np
            merged_into = {}  # sense_idx -> merge target sense_idx
            for i in range(len(senses)):
                if i in merged_into:
                    continue
                si_text = enrich_sense_text(senses[i])
                si_idx = text_to_idx.get(si_text)
                if si_idx is None:
                    continue
                for j in range(i + 1, len(senses)):
                    if j in merged_into:
                        continue
                    if senses[i]["pos"] != senses[j]["pos"]:
                        continue
                    sj_text = enrich_sense_text(senses[j])
                    sj_idx = text_to_idx.get(sj_text)
                    if sj_idx is None:
                        continue
                    sim = float(np.dot(embeddings[si_idx], embeddings[sj_idx]))
                    if sim >= SENSE_MERGE_THRESHOLD:
                        merged_into[j] = i
                        sense_example_indices[i].extend(sense_example_indices[j])
                        sense_example_indices[j] = []
                        stats["merged_senses"] = stats.get("merged_senses", 0) + 1

        # Build assignments — filter by frequency threshold, cap examples
        total_classified = sum(len(idx) for idx in sense_example_indices)
        assignments = []
        filtered_senses = 0
        for i, indices in enumerate(sense_example_indices):
            if not indices:
                continue
            # Drop senses below frequency threshold (only when we have
            # enough examples for the threshold to be meaningful)
            if total_classified >= 5:
                freq = len(indices) / total_classified
                if freq < MIN_SENSE_FREQUENCY:
                    filtered_senses += 1
                    continue
            assignments.append({
                "sense_idx": i,
                "examples": indices[:MAX_EXAMPLES_PER_MEANING],
            })
        stats["filtered_senses"] = stats.get("filtered_senses", 0) + filtered_senses

        # Fallback: if no sense survived filtering, assign all to first
        if not assignments:
            indices = list(range(min(len(examples), MAX_EXAMPLES_PER_MEANING)))
            assignments = [{"sense_idx": 0, "examples": indices}]

        output[word_id] = assignments
        stats["active_senses"][len(assignments)] += 1

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
    avg_conf = (stats["confidence_sum"] / stats["confidence_count"]
                if stats["confidence_count"] > 0 else 0)

    conf_label = "Avg cosine margin" if use_embeddings else "Avg keyword confidence"

    print("\n{}".format("=" * 55))
    print("SENSE ASSIGNMENT RESULTS ({})".format(method))
    print("{}".format("=" * 55))
    print("Total vocabulary:          {:>6,}".format(total))
    print("No Wiktionary senses:      {:>6,}".format(stats["no_senses"]))
    print("Single sense:              {:>6,}".format(stats["single_sense"]))
    print("Multi-sense (classified):  {:>6,}".format(stats["multi_sense"]))
    print("No examples:               {:>6,}".format(stats["no_examples"]))
    print()
    print("{}: {:.4f}".format(conf_label, avg_conf))
    print("Senses merged (sim>={:.2f}): {:>5,}".format(
        SENSE_MERGE_THRESHOLD, stats.get("merged_senses", 0)))
    print("Senses filtered (<{:.0f}%): {:>6,}".format(
        MIN_SENSE_FREQUENCY * 100, stats.get("filtered_senses", 0)))
    print()
    print("Active senses per word:")
    for n in sorted(stats["active_senses"]):
        count = stats["active_senses"][n]
        print("  {} senses: {:>6,} words".format(n, count))

    total_time = time.time() - classify_start
    print("\nTotal classification time: {:.1f}s".format(total_time))


if __name__ == "__main__":
    main()
