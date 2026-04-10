#!/usr/bin/env python3
"""
test_wiktionary_cascade.py — Test Wiktionary sense cascade on existing artist vocabulary.

Reads the existing artist monolith, replaces Gemini-invented senses with Wiktionary
senses + classifier. Writes a parallel monolith for A/B comparison in the browser
(?variant=cascade).

Does NOT modify any pipeline files, master vocabulary, or existing outputs.

Classifier options:
  --cross-encoder    Cross-encoder (sees example+sense pairs together, most accurate)
  --model MODEL      Bi-encoder model name (default: paraphrase-multilingual-mpnet-base-v2)
  --keyword-only     Keyword overlap (instant, lowest accuracy)

Usage (from project root):
    .venv/bin/python3 pipeline/artist/test_wiktionary_cascade.py --artist-dir "Artists/Bad Bunny" --cross-encoder
    .venv/bin/python3 pipeline/artist/test_wiktionary_cascade.py --artist-dir "Artists/Bad Bunny"
    .venv/bin/python3 pipeline/artist/test_wiktionary_cascade.py --artist-dir "Artists/Bad Bunny" --keyword-only
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

# Add pipeline dirs to path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "artist"))

from build_senses import load_wiktionary, lookup_senses, clean_translation, merge_similar_senses
from _artist_config import add_artist_arg, load_artist_config

WIKT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "wiktionary" / "kaikki-spanish.jsonl.gz"
BIENCODER_MODEL = "paraphrase-multilingual-mpnet-base-v2"
CROSS_ENCODER_MODEL = "cross-encoder/stsb-roberta-large"
MIN_SENSE_FREQUENCY = 0.05

_POS_LABELS = {
    "VERB": "verb", "NOUN": "noun", "ADJ": "adjective",
    "ADV": "adverb", "ADP": "preposition",
    "CCONJ": "conjunction", "PRON": "pronoun",
    "DET": "determiner", "INTJ": "interjection",
    "NUM": "numeral", "PART": "particle",
    "PHRASE": "phrase", "CONTRACTION": "contraction",
}


def collect_examples(entry):
    """Flatten all examples from an entry's meanings into one list."""
    examples = []
    for meaning in entry.get("meanings", []):
        for ex in meaning.get("examples", []):
            if ex not in examples:
                examples.append(ex)
    return examples


def build_meanings(wikt_senses, examples, assignments):
    """Build meanings array from Wiktionary senses + classified example assignments.

    assignments: list of sense indices, one per example.
    """
    sense_buckets = defaultdict(list)
    for ex_idx, sense_idx in enumerate(assignments):
        sense_buckets[sense_idx].append(examples[ex_idx])

    total = len(examples) or 1
    meanings = []
    for si, s in enumerate(wikt_senses):
        bucket = sense_buckets.get(si, [])
        if not bucket:
            continue
        freq = len(bucket) / total
        if total >= 5 and freq < MIN_SENSE_FREQUENCY:
            continue
        meanings.append({
            "pos": s["pos"],
            "translation": s["translation"],
            "frequency": "%.2f" % freq,
            "examples": bucket,
            "source": "wiktionary",
        })

    if not meanings and wikt_senses:
        meanings.append({
            "pos": wikt_senses[0]["pos"],
            "translation": wikt_senses[0]["translation"],
            "frequency": "1.00",
            "examples": examples,
            "source": "wiktionary",
        })

    return meanings


def classify_keyword(examples, senses):
    """Keyword overlap classification (instant, ~70% accuracy)."""
    import re
    STOP = {"a", "an", "the", "to", "of", "in", "on", "at", "for", "is", "it",
            "be", "as", "or", "by", "and", "not", "with", "from", "that", "this",
            "but", "are", "was", "were", "been", "has", "have", "had", "do", "does",
            "up", "out", "if", "so", "no", "into", "over", "its", "one", "very",
            "just", "about", "more", "some", "than"}
    word_re = re.compile(r"[a-z]+")

    def tokenize(text):
        return {w for w in word_re.findall(text.lower()) if w not in STOP and len(w) > 1}

    assignments = []
    for ex in examples:
        eng = ex.get("english", "")
        if not eng:
            assignments.append(0)
            continue
        sentence_words = tokenize(eng)
        scores = []
        for s in senses:
            sense_words = tokenize(s["translation"])
            scores.append(len(sentence_words & sense_words) if sense_words else 0)
        assignments.append(max(range(len(scores)), key=lambda i: scores[i]))
    return assignments


def classify_cross_encoder_batch(work_items, model):
    """Cross-encoder classification — scores (example, sense) pairs together.

    More accurate than bi-encoder because the model sees both texts at once.
    O(examples × senses) forward passes, but fast at artist scale.

    work_items: list of (examples, wikt_senses) tuples.
    Returns: list of assignment lists (one per work item).
    """
    import numpy as np

    # Build all (example_text, sense_text) pairs
    all_pairs = []
    pair_map = []  # (work_idx, example_idx, sense_idx)

    for wi, (examples, senses) in enumerate(work_items):
        for ei, ex in enumerate(examples):
            eng = ex.get("english", "")
            spa = ex.get("spanish", "")
            if eng and spa:
                ex_text = "%s [Spanish: %s]" % (eng, spa)
            elif spa:
                ex_text = spa
            else:
                ex_text = eng or ""

            for si, s in enumerate(senses):
                label = _POS_LABELS.get(s["pos"], s["pos"])
                sense_text = "%s: %s" % (label, s["translation"])
                all_pairs.append((ex_text, sense_text))
                pair_map.append((wi, ei, si))

    print("  %d (example, sense) pairs to score" % len(all_pairs))

    t0 = time.time()
    scores = model.predict(all_pairs, show_progress_bar=True, batch_size=64)
    print("  Scored in %.1fs" % (time.time() - t0))

    # Group scores by (work_idx, example_idx) and pick best sense
    from collections import defaultdict
    best = defaultdict(lambda: (-float("inf"), 0))  # (work_idx, example_idx) → (score, sense_idx)
    for flat_idx, (wi, ei, si) in enumerate(pair_map):
        score = float(scores[flat_idx])
        key = (wi, ei)
        if score > best[key][0]:
            best[key] = (score, si)

    # Build per-word assignment lists
    results = []
    for wi, (examples, senses) in enumerate(work_items):
        assignments = []
        for ei in range(len(examples)):
            _, best_si = best.get((wi, ei), (0, 0))
            assignments.append(best_si)
        results.append(assignments)

    return results


def classify_biencoder_batch(work_items, model):
    """Batch biencoder classification for all multi-sense words.

    work_items: list of (examples, wikt_senses) tuples.
    Returns: list of assignment lists (one per work item).
    """
    import numpy as np

    # Collect all texts for batch embedding
    all_example_texts = []
    all_sense_texts = []
    example_map = []  # (work_idx, example_idx)
    sense_map = []    # (work_idx, sense_idx)

    for wi, (examples, senses) in enumerate(work_items):
        for ei, ex in enumerate(examples):
            eng = ex.get("english", "")
            spa = ex.get("spanish", "")
            if eng and spa:
                text = "%s [Spanish: %s]" % (eng, spa)
            elif spa:
                text = spa
            else:
                text = ""
            all_example_texts.append(text)
            example_map.append((wi, ei))

        for si, s in enumerate(senses):
            label = _POS_LABELS.get(s["pos"], s["pos"])
            all_sense_texts.append("%s: %s" % (label, s["translation"]))
            sense_map.append((wi, si))

    print("  %d examples, %d senses to embed" % (len(all_example_texts), len(all_sense_texts)))

    t0 = time.time()
    ex_embs = model.encode(all_example_texts, normalize_embeddings=True,
                           show_progress_bar=True, batch_size=64)
    sn_embs = model.encode(all_sense_texts, normalize_embeddings=True,
                           show_progress_bar=True, batch_size=64)
    print("  Embedded in %.1fs" % (time.time() - t0))

    # Build per-word lookups
    word_ex = defaultdict(list)
    for flat_idx, (wi, ei) in enumerate(example_map):
        word_ex[wi].append((ei, ex_embs[flat_idx]))

    word_sn = defaultdict(list)
    for flat_idx, (wi, si) in enumerate(sense_map):
        word_sn[wi].append((si, sn_embs[flat_idx]))

    # Classify per word
    results = []
    for wi, (examples, senses) in enumerate(work_items):
        ex_pairs = word_ex.get(wi, [])
        sn_pairs = word_sn.get(wi, [])

        assignments = [0] * len(examples)

        if ex_pairs and sn_pairs:
            ex_indices, ex_vecs = zip(*ex_pairs)
            sn_indices, sn_vecs = zip(*sn_pairs)
            sims = np.dot(np.array(ex_vecs), np.array(sn_vecs).T)

            for row, ei in enumerate(ex_indices):
                best_col = int(np.argmax(sims[row]))
                assignments[ei] = sn_indices[best_col]

        results.append(assignments)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Test Wiktionary cascade on existing artist vocabulary")
    add_artist_arg(parser)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cross-encoder", action="store_true",
                      help="Cross-encoder (most accurate, scores example+sense pairs together)")
    mode.add_argument("--keyword-only", action="store_true",
                      help="Keyword overlap (instant, lowest accuracy)")
    parser.add_argument("--model", type=str, default=None,
                        help="Override model name (bi-encoder or cross-encoder)")
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    config = load_artist_config(artist_dir)
    use_cross_encoder = args.cross_encoder
    method = "keyword" if args.keyword_only else ("cross-encoder" if use_cross_encoder else "biencoder")

    # Load monolith
    vocab_path = os.path.join(artist_dir, config["vocabulary_file"])
    print("Loading monolith: %s" % vocab_path)
    with open(vocab_path, encoding="utf-8") as f:
        entries = json.load(f)
    print("  %d entries" % len(entries))

    # Load Wiktionary
    if not WIKT_FILE.exists():
        print("ERROR: Wiktionary file not found: %s" % WIKT_FILE)
        print("Download with:")
        print('  curl -L -o %s \\' % WIKT_FILE)
        print('    "https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl.gz"')
        sys.exit(1)
    wikt_index, redirects = load_wiktionary(WIKT_FILE)

    # Load classifier model
    model = None
    if not args.keyword_only:
        if use_cross_encoder:
            from sentence_transformers import CrossEncoder
            model_name = args.model or CROSS_ENCODER_MODEL
            print("\nLoading cross-encoder: %s" % model_name)
            model = CrossEncoder(model_name)
        else:
            from sentence_transformers import SentenceTransformer
            model_name = args.model or BIENCODER_MODEL
            print("\nLoading bi-encoder: %s" % model_name)
            model = SentenceTransformer(model_name)

    # --- Pass 1: categorize entries ---
    print("\nCategorizing %d entries..." % len(entries))
    cascade_entries = []
    biencoder_queue = []  # (position_in_cascade, examples, wikt_senses)

    stats = defaultdict(int)
    focus_words = {}

    for entry in entries:
        word = entry.get("word", "")
        lemma = entry.get("lemma", word)
        examples = collect_examples(entry)

        if not examples:
            stats["no_examples"] += 1
            cascade_entries.append(entry)
            continue

        wikt_senses = lookup_senses(word, lemma, wikt_index, redirects)

        if not wikt_senses:
            stats["gemini_fallback"] += 1
            cascade_entries.append(entry)
            continue

        # Clean verbose glosses and merge near-duplicates
        for s in wikt_senses:
            s["translation"] = clean_translation(s["translation"])
        wikt_senses = merge_similar_senses(wikt_senses)

        stats["wiktionary"] += 1

        if len(wikt_senses) == 1:
            stats["single_sense"] += 1
            new_entry = {k: v for k, v in entry.items() if k != "meanings"}
            new_entry["meanings"] = [{
                "pos": wikt_senses[0]["pos"],
                "translation": wikt_senses[0]["translation"],
                "frequency": "1.00",
                "examples": examples,
                "source": "wiktionary",
            }]
            cascade_entries.append(new_entry)
            if word in ("bicho", "rico", "candela", "gata", "loco", "tipo", "solo"):
                focus_words[word] = ("wiktionary-single", wikt_senses, new_entry["meanings"])
            continue

        # Multi-sense
        stats["multi_sense"] += 1

        if model:
            pos = len(cascade_entries)
            cascade_entries.append(None)  # placeholder
            biencoder_queue.append((pos, examples, wikt_senses, entry, word))
        else:
            assignments = classify_keyword(examples, wikt_senses)
            new_entry = {k: v for k, v in entry.items() if k != "meanings"}
            new_entry["meanings"] = build_meanings(wikt_senses, examples, assignments)
            cascade_entries.append(new_entry)
            if word in ("bicho", "rico", "candela", "gata", "loco", "tipo", "solo"):
                focus_words[word] = ("wiktionary-multi", wikt_senses, new_entry["meanings"])

    print("  Wiktionary match:  %d (%d single, %d multi)" % (
        stats["wiktionary"], stats["single_sense"], stats["multi_sense"]))
    print("  Gemini fallback:   %d" % stats["gemini_fallback"])
    print("  No examples:       %d" % stats["no_examples"])

    # --- Pass 2: batch classification ---
    if biencoder_queue:
        print("\nClassifying %d multi-sense words with %s..." % (len(biencoder_queue), method))
        work_items = [(examples, senses) for (_, examples, senses, _, _) in biencoder_queue]
        if use_cross_encoder:
            all_assignments = classify_cross_encoder_batch(work_items, model)
        else:
            all_assignments = classify_biencoder_batch(work_items, model)

        for (pos, examples, wikt_senses, entry, word), assignments in zip(biencoder_queue, all_assignments):
            new_entry = {k: v for k, v in entry.items() if k != "meanings"}
            new_entry["meanings"] = build_meanings(wikt_senses, examples, assignments)
            cascade_entries[pos] = new_entry
            if word in ("bicho", "rico", "candela", "gata", "loco", "tipo", "solo"):
                focus_words[word] = ("wiktionary-multi", wikt_senses, new_entry["meanings"])

    # --- Write output ---
    output_path = vocab_path.replace(".json", "_cascade_%s.json" % method)
    print("\nWriting cascade monolith: %s" % output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cascade_entries, f, ensure_ascii=False, indent=2)
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print("  %d entries, %.1f MB" % (len(cascade_entries), size_mb))

    # --- Focus word report ---
    if focus_words:
        print("\n" + "=" * 60)
        print("FOCUS WORD REPORT")
        print("=" * 60)
        for word in ("bicho", "rico", "candela", "gata", "loco", "tipo", "solo"):
            if word not in focus_words:
                print("\n%s: Gemini fallback (no Wiktionary match)" % word)
                continue
            source, wikt_senses, meanings = focus_words[word]
            print("\n%s (%s, %d Wiktionary senses):" % (word, source, len(wikt_senses)))
            for s in wikt_senses:
                print("  [wikt] %s: %s" % (s["pos"], s["translation"]))
            print("  Result:")
            for m in meanings:
                print("    %s: %s (freq=%s, %d examples)" % (
                    m["pos"], m["translation"], m["frequency"], len(m.get("examples", []))))

    # --- Summary ---
    print("\n" + "=" * 60)
    print("SUMMARY (%s)" % method)
    print("=" * 60)
    print("Total entries:       %6d" % len(entries))
    print("Wiktionary senses:   %6d (%.0f%%)" % (
        stats["wiktionary"], 100 * stats["wiktionary"] / len(entries)))
    print("  Single-sense:      %6d" % stats["single_sense"])
    print("  Multi-sense:       %6d" % stats["multi_sense"])
    print("Gemini fallback:     %6d (%.0f%%)" % (
        stats["gemini_fallback"], 100 * stats["gemini_fallback"] / len(entries)))
    print("No examples:         %6d" % stats["no_examples"])
    print()
    print("View in browser:")
    print("  Normal:  http://localhost:8765/?artist=bad-bunny")
    print("  This:    http://localhost:8765/?variant=cascade_%s&artist=bad-bunny" % method)


if __name__ == "__main__":
    main()
