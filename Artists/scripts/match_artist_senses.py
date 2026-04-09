#!/usr/bin/env python3
"""
match_artist_senses.py — Assign artist lyric examples to word senses using
local bi-encoder embeddings.

When an artist is run with --no-gemini (or senses come from the master via
another artist's Gemini run), lyric examples get dumped on the first sense.
This script uses bi-encoder cosine similarity to classify each lyric line
to the correct sense — the same approach used in normal-mode match_senses.py,
but adapted for artist layer file formats.

At artist scale (~600-3000 lines to classify), this runs in under 30 seconds.

Sense sources (in priority order):
  1. senses_gemini.json (this artist's Gemini analysis)
  2. senses_wiktionary.json (normal-mode dictionary senses — unbiased fallback)
  3. Master vocabulary senses (last resort)

Classification methods (per example):
  - Bilingual bi-encoder (English + Spanish) — 84% accuracy
  - Spanish-only bi-encoder (multilingual model) — 72% accuracy
  - Keyword overlap fallback — ~70% accuracy, instant

Modes:
  --biencoder    Bi-encoder cosine similarity (default)
  --keyword-only Keyword overlap (instant, ~70% accuracy)

Usage (from project root):
    .venv/bin/python3 Artists/scripts/match_artist_senses.py --artist-dir Artists/Rosalia
    .venv/bin/python3 Artists/scripts/match_artist_senses.py --artist-dir "Artists/Bad Bunny" --keyword-only

Inputs:
    {artist}/data/layers/word_inventory.json
    {artist}/data/layers/examples_raw.json
    {artist}/data/layers/example_translations.json
    {artist}/data/layers/senses_gemini.json
    Data/Spanish/layers/senses_wiktionary.json  (fallback)

Outputs:
    {artist}/data/layers/sense_assignments.json
"""

import argparse
import json
import re
import time
from collections import defaultdict
from pathlib import Path

from _artist_config import add_artist_arg, load_artist_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WIKTIONARY_SENSES_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "senses_wiktionary.json"

MIN_SENSE_FREQUENCY = 0.05
# Multilingual model: 84% bilingual, 72% Spanish-only (handles both)
CLASSIFY_MODEL = "paraphrase-multilingual-mpnet-base-v2"

_POS_LABELS = {
    "VERB": "verb", "NOUN": "noun", "ADJ": "adjective",
    "ADV": "adverb", "ADP": "preposition",
    "CCONJ": "conjunction", "PRON": "pronoun",
    "DET": "determiner", "INTJ": "interjection",
    "NUM": "numeral", "PART": "particle",
    "PHRASE": "phrase", "CONTRACTION": "contraction",
}


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
    sentence_words = tokenize_english(sentence_english)
    scores = []
    for s in senses:
        sense_words = tokenize_english(s["translation"])
        scores.append(len(sentence_words & sense_words) if sense_words else 0)
    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    return best_idx


# ---------------------------------------------------------------------------
# Sense resolution (Gemini -> Wiktionary -> Master fallback)
# ---------------------------------------------------------------------------

def load_wiktionary_senses():
    """Load normal-mode Wiktionary senses as fallback."""
    if WIKTIONARY_SENSES_FILE.exists():
        with open(WIKTIONARY_SENSES_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def resolve_senses(word, gemini_senses, wiktionary_senses, master):
    """Find senses for a word using priority: Gemini > Wiktionary > Master.

    Returns (senses_list, source_label) or (None, None) if no senses found.
    """
    # 1. Gemini senses (this artist's analysis)
    for key, s_list in gemini_senses.items():
        if key.startswith(word + "|"):
            return s_list, "gemini"

    # 2. Wiktionary senses (normal-mode dictionary — unbiased)
    for key, s_list in wiktionary_senses.items():
        if key.startswith(word + "|"):
            if len(s_list) >= 1:
                return s_list, "wiktionary"

    # 3. Master vocabulary senses (from other artists' Gemini runs)
    for mid, mentry in master.items():
        if mentry.get("word") == word and mentry.get("senses"):
            return mentry["senses"], "master"

    return None, None


# ---------------------------------------------------------------------------
# Bi-encoder classification
# ---------------------------------------------------------------------------

def classify_with_biencoder(work_items, output, translations, model_name=None):
    """Classify artist lyric examples using bi-encoder cosine similarity.

    Uses bilingual text (English + Spanish) when English translation is
    available, falls back to Spanish-only for untranslated examples.
    The multilingual mpnet model handles both.
    """
    from sentence_transformers import SentenceTransformer
    import numpy as np

    model_name = model_name or CLASSIFY_MODEL
    print("Loading classifier model '%s'..." % model_name)
    model = SentenceTransformer(model_name)

    # Collect all example texts — bilingual when possible, Spanish-only otherwise
    print("\nPreparing example texts...")
    example_texts = []
    example_map = []  # (work_idx, example_idx)
    bilingual_count = 0
    spanish_only_count = 0

    for wi, (word, senses, examples, keep_indices, source) in enumerate(work_items):
        for ei, ex in enumerate(examples):
            spanish = ex.get("spanish", "")
            trans_info = translations.get(spanish, {})
            english = trans_info.get("english", "")

            if english and spanish:
                text = "%s [Spanish: %s]" % (english, spanish)
                bilingual_count += 1
            elif spanish:
                text = spanish
                spanish_only_count += 1
            else:
                continue  # no text at all — skip

            example_texts.append(text)
            example_map.append((wi, ei))

    print("  %d examples to embed (%d bilingual, %d Spanish-only)" % (
        len(example_texts), bilingual_count, spanish_only_count))

    # Collect all sense texts (raw "pos: translation" — best for bi-encoder)
    sense_texts = []
    sense_map = []  # (work_idx, original_sense_idx)
    for wi, (word, senses, examples, keep_indices, source) in enumerate(work_items):
        for ki in keep_indices:
            s = senses[ki]
            label = _POS_LABELS.get(s["pos"], s["pos"])
            sense_texts.append("%s: %s" % (label, s["translation"]))
            sense_map.append((wi, ki))
    print("  %d sense texts to embed" % len(sense_texts))

    if not example_texts:
        print("  No examples to classify")
        return

    # Embed in batch
    print("\nEmbedding examples...")
    t0 = time.time()
    example_embs = model.encode(example_texts, normalize_embeddings=True,
                                show_progress_bar=False, batch_size=64)
    print("  Done in %.1fs" % (time.time() - t0))

    print("Embedding senses...")
    t0 = time.time()
    sense_embs = model.encode(sense_texts, normalize_embeddings=True,
                              show_progress_bar=False, batch_size=64)
    print("  Done in %.1fs" % (time.time() - t0))

    # Build per-word sense embedding lookup
    word_sense_embs = defaultdict(list)
    for flat_idx, (wi, ki) in enumerate(sense_map):
        word_sense_embs[wi].append((ki, sense_embs[flat_idx]))

    # Build per-word example embedding lookup
    word_example_embs = defaultdict(list)
    for flat_idx, (wi, ei) in enumerate(example_map):
        word_example_embs[wi].append((ei, example_embs[flat_idx]))

    # Classify each word
    print("\nClassifying %d words by cosine similarity..." % len(work_items))
    t0 = time.time()
    for wi, (word, senses, examples, keep_indices, source) in enumerate(work_items):
        sense_example_indices = [[] for _ in senses]

        ex_pairs = word_example_embs.get(wi, [])
        sn_pairs = word_sense_embs.get(wi, [])

        if ex_pairs and sn_pairs:
            ex_indices, ex_vecs = zip(*ex_pairs)
            sn_indices, sn_vecs = zip(*sn_pairs)
            sims = np.dot(np.array(ex_vecs), np.array(sn_vecs).T)

            for row, ei in enumerate(ex_indices):
                best_col = int(np.argmax(sims[row]))
                best_sense_idx = sn_indices[best_col]
                sense_example_indices[best_sense_idx].append(ei)

        # Any examples that didn't get embedded (no text at all) go to first sense
        embedded_indices = set(ei for ei, _ in ex_pairs)
        for ei in range(len(examples)):
            if ei not in embedded_indices:
                sense_example_indices[keep_indices[0] if keep_indices else 0].append(ei)

        # Frequency filter
        total_classified = sum(len(idx) for idx in sense_example_indices)
        assignments = []
        for i, indices in enumerate(sense_example_indices):
            if not indices:
                continue
            if total_classified >= 5:
                freq = len(indices) / total_classified
                if freq < MIN_SENSE_FREQUENCY:
                    continue
            assignments.append({
                "sense_idx": i,
                "examples": indices,
                "method": "biencoder",
            })

        if not assignments:
            assignments = [{"sense_idx": 0, "examples": list(range(len(examples))), "method": "biencoder"}]

        output[word] = assignments

    elapsed = time.time() - t0
    print("  Done in %.1fs" % elapsed)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Assign artist lyric examples to senses using local embeddings")
    add_artist_arg(parser)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--biencoder", action="store_true", default=True,
                      help="Bi-encoder cosine similarity (default)")
    mode.add_argument("--keyword-only", action="store_true",
                      help="Keyword overlap (instant, ~70%% accuracy)")
    parser.add_argument("--model", type=str, default=CLASSIFY_MODEL,
                        help="Sentence-transformers model (default: %s)" % CLASSIFY_MODEL)
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing sense_assignments.json")
    args = parser.parse_args()

    artist_dir = args.artist_dir
    config = load_artist_config(artist_dir)
    layers_dir = Path(artist_dir) / "data" / "layers"

    use_keyword = args.keyword_only
    method = "keyword overlap" if use_keyword else "bi-encoder"
    print("Artist sense matching (%s)" % method)
    print("Artist: %s" % config["name"])

    # Check if assignments already exist
    output_file = layers_dir / "sense_assignments.json"
    if output_file.exists() and not args.force:
        print("\nsense_assignments.json already exists. Use --force to overwrite.")
        return

    # Load inputs
    print("\nLoading layers...")
    with open(layers_dir / "word_inventory.json", encoding="utf-8") as f:
        inventory = json.load(f)
    print("  word_inventory: %d entries" % len(inventory))

    with open(layers_dir / "examples_raw.json", encoding="utf-8") as f:
        examples_data = json.load(f)
    print("  examples_raw: %d entries" % len(examples_data))

    senses_path = layers_dir / "senses_gemini.json"
    gemini_senses = {}
    if senses_path.exists():
        with open(senses_path, encoding="utf-8") as f:
            gemini_senses = json.load(f)
        print("  senses_gemini: %d entries" % len(gemini_senses))
    else:
        print("  senses_gemini: (not found)")

    translations_path = layers_dir / "example_translations.json"
    translations = {}
    if translations_path.exists():
        with open(translations_path, encoding="utf-8") as f:
            translations = json.load(f)
        print("  example_translations: %d entries" % len(translations))
    else:
        print("  example_translations: (not found)")

    # Load fallback sense sources
    wiktionary_senses = load_wiktionary_senses()
    if wiktionary_senses:
        print("  senses_wiktionary (fallback): %d entries" % len(wiktionary_senses))

    master_path = PROJECT_ROOT / "Artists" / "vocabulary_master.json"
    master = {}
    if master_path.exists():
        with open(master_path, encoding="utf-8") as f:
            master = json.load(f)
        print("  vocabulary_master (fallback): %d entries" % len(master))

    # Build work items for multi-sense words
    print("\nPreparing work items...")
    output = {}
    work_items = []  # (word, senses, examples, keep_indices, source)
    single_sense_count = 0
    no_senses_count = 0
    no_examples_count = 0
    sense_sources = defaultdict(int)

    for inv_entry in inventory:
        word = inv_entry["word"]
        examples = examples_data.get(word, [])

        # Resolve senses with fallback chain
        word_senses, source = resolve_senses(word, gemini_senses, wiktionary_senses, master)

        if not word_senses:
            no_senses_count += 1
            continue

        sense_sources[source] += 1

        if not examples:
            no_examples_count += 1
            output[word] = [{"sense_idx": 0, "examples": []}]
            continue

        if len(word_senses) == 1:
            single_sense_count += 1
            output[word] = [{"sense_idx": 0, "examples": list(range(len(examples)))}]
            continue

        keep_indices = list(range(len(word_senses)))

        if use_keyword:
            # Keyword fallback — process inline
            sense_example_indices = [[] for _ in word_senses]
            for ex_idx, ex in enumerate(examples):
                spanish = ex.get("spanish", "")
                trans_info = translations.get(spanish, {})
                eng = trans_info.get("english", "")
                if not eng:
                    sense_example_indices[0].append(ex_idx)
                    continue
                best_idx = classify_example_keyword(eng, word_senses)
                sense_example_indices[best_idx].append(ex_idx)

            total_classified = sum(len(idx) for idx in sense_example_indices)
            assignments = []
            for i, indices in enumerate(sense_example_indices):
                if not indices:
                    continue
                if total_classified >= 5 and len(indices) / total_classified < MIN_SENSE_FREQUENCY:
                    continue
                assignments.append({"sense_idx": i, "examples": indices, "method": "keyword"})
            if not assignments:
                assignments = [{"sense_idx": 0, "examples": list(range(len(examples))), "method": "keyword"}]
            output[word] = assignments
        else:
            work_items.append((word, word_senses, examples, keep_indices, source))

    print("  Single-sense (no classification): %d" % single_sense_count)
    print("  Multi-sense to classify: %d" % len(work_items))
    print("  No senses: %d" % no_senses_count)
    print("  No examples: %d" % no_examples_count)
    print("  Sense sources: %s" % dict(sense_sources))

    # Check translation coverage for multi-sense examples
    if work_items and not use_keyword:
        total_ex = sum(len(ex) for _, _, ex, _, _ in work_items)
        has_eng = 0
        for _, _, examples, _, _ in work_items:
            for ex in examples:
                spanish = ex.get("spanish", "")
                if translations.get(spanish, {}).get("english"):
                    has_eng += 1
        spa_only = total_ex - has_eng
        print("  Classification breakdown: %d bilingual, %d Spanish-only" % (has_eng, spa_only))

    t0 = time.time()

    if work_items and not use_keyword:
        classify_with_biencoder(work_items, output, translations, model_name=args.model)
    elif use_keyword:
        print("\nKeyword classification done (instant)")

    # Write output
    print("\nWriting %s..." % output_file)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0

    # Report
    from collections import Counter
    active = Counter(len(v) for v in output.values())
    print("\n" + "=" * 55)
    print("ARTIST SENSE ASSIGNMENT RESULTS (%s)" % method)
    print("=" * 55)
    print("Total assignments:         %6d" % len(output))
    print("Single sense:              %6d" % single_sense_count)
    print("Multi-sense (classified):  %6d" % len(work_items))
    print("No senses:                 %6d" % no_senses_count)
    print("No examples:               %6d" % no_examples_count)
    print("Elapsed:                   %.1fs" % elapsed)
    print()
    print("Sense sources:")
    for src in ("gemini", "wiktionary", "master"):
        if sense_sources.get(src):
            print("  %-12s %6d words" % (src, sense_sources[src]))
    print()
    print("Active senses per word:")
    for n in sorted(active):
        print("  %d senses: %6d words" % (n, active[n]))


if __name__ == "__main__":
    main()
