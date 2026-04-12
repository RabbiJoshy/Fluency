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

from _artist_config import (add_artist_arg, load_artist_config, assign_sense_ids,
                           METHOD_PRIORITY, best_method_priority)

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_senses import (load_wiktionary, lookup_senses, clean_translation,
                          merge_similar_senses)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WIKTIONARY_SENSES_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "senses_wiktionary.json"
WIKTIONARY_RAW_PATH = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "wiktionary" / "kaikki-spanish.jsonl.gz"

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

    for wi, item in enumerate(work_items):
        word, senses, examples, keep_indices, source = item[:5]
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
    for wi, item in enumerate(work_items):
        word, senses, examples, keep_indices, source = item[:5]
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
    for wi, item in enumerate(work_items):
        word, senses, examples, keep_indices, source = item[:5]
        id_list = item[5] if len(item) > 5 else None

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

        # Frequency filter + output
        total_classified = sum(len(idx) for idx in sense_example_indices)
        assignments = []
        for i, indices in enumerate(sense_example_indices):
            if not indices:
                continue
            if total_classified >= 5:
                freq = len(indices) / total_classified
                if freq < MIN_SENSE_FREQUENCY:
                    continue
            sid = id_list[i] if i < len(id_list) else id_list[0]
            assignments.append({"sense": sid, "examples": indices})
        if not assignments:
            assignments = [{"sense": id_list[0], "examples": list(range(len(examples)))}]
        output[word] = {"biencoder": assignments}

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
    parser.add_argument("--normal-only", action="store_true",
                        help="Only classify words that exist in normal-mode senses. "
                             "Writes to senses_wiktionary.json / sense_assignments_wiktionary.json")
    args = parser.parse_args()

    artist_dir = args.artist_dir
    config = load_artist_config(artist_dir)
    layers_dir = Path(artist_dir) / "data" / "layers"

    use_keyword = args.keyword_only
    method = "keyword overlap" if use_keyword else "bi-encoder"
    print("Artist sense matching (%s)" % method)
    print("Artist: %s" % config["name"])

    # Always write to wiktionary format (new pipeline)
    output_file = layers_dir / "sense_assignments_wiktionary.json"
    senses_output_file = layers_dir / "senses_wiktionary.json"

    # No early exit — priority checking handles skip logic per-word

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

    # Load Wiktionary (raw, full 118K entries)
    print("Loading English Wiktionary...")
    wikt_index, wikt_redirects = load_wiktionary(WIKTIONARY_RAW_PATH)

    # Also keep the normal-mode senses layer for backward compat
    wiktionary_senses = load_wiktionary_senses()
    if wiktionary_senses:
        print("  senses_wiktionary (normal-mode): %d entries" % len(wiktionary_senses))

    # Load eswiktionary dialect senses (appended to menu)
    eswikt_index = {}
    import pickle as _pickle
    eswikt_cache = PROJECT_ROOT / "Data/Spanish/corpora/wiktionary/kaikki-eswiktionary-raw.jsonl.gz.eswikt_dialect.cache.pkl"
    if eswikt_cache.exists():
        with open(eswikt_cache, "rb") as f:
            _, eswikt_index = _pickle.load(f)
        print("  eswiktionary dialect senses: %d words" % len(eswikt_index))

    master_path = PROJECT_ROOT / "Artists" / "vocabulary_master.json"
    master = {}
    if master_path.exists():
        with open(master_path, encoding="utf-8") as f:
            master = json.load(f)
        print("  vocabulary_master (fallback): %d entries" % len(master))

    # Load existing assignments for priority checking
    existing_assigns = {}
    if output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            existing_assigns = json.load(f)

    my_method = "keyword" if use_keyword else "biencoder"
    my_priority = METHOD_PRIORITY.get(my_method, 0)

    # Build work items for multi-sense words
    print("\nPreparing work items...")
    output = {}
    work_items = []  # (word, senses, examples, keep_indices, source)
    single_sense_count = 0
    no_senses_count = 0
    no_examples_count = 0
    skipped_priority = 0
    sense_sources = defaultdict(int)

    normal_only_senses = {}  # word|lemma -> senses (for writing senses_wiktionary.json)
    skipped_not_normal = 0

    for inv_entry in inventory:
        word = inv_entry["word"]
        examples = examples_data.get(word, [])

        # Skip words with equal or higher priority assignments
        if word in existing_assigns and not args.force:
            existing_priority = best_method_priority(existing_assigns[word])
            if existing_priority >= my_priority:
                skipped_priority += 1
                continue

        # Look up senses from raw Wiktionary (full 118K, not just 11K normal-mode)
        lemma = word
        # Try to get lemma from gemini senses or normal-mode senses
        for key in gemini_senses:
            if key.startswith(word + "|"):
                lemma = key.split("|", 1)[1]
                break
        else:
            for key in wiktionary_senses:
                if key.startswith(word + "|"):
                    lemma = key.split("|", 1)[1]
                    break

        # In --normal-only mode: only process words in the normal-mode senses layer
        if args.normal_only:
            wikt_key = None
            for key in wiktionary_senses:
                if key.startswith(word + "|"):
                    wikt_key = key
                    break
            if not wikt_key:
                skipped_not_normal += 1
                continue

        # Look up senses from raw Wiktionary
        en_senses = lookup_senses(word, lemma, wikt_index, wikt_redirects)
        if en_senses:
            for s in en_senses:
                s["translation"] = clean_translation(s["translation"])
            en_senses = merge_similar_senses(en_senses)

        word_senses = []
        if en_senses:
            for s in en_senses:
                s_copy = dict(s)
                if "source" not in s_copy:
                    s_copy["source"] = "en-wikt"
                word_senses.append(s_copy)

        # Append eswiktionary dialect senses
        for lookup in sorted(set([word, lemma])):
            for es_sense in eswikt_index.get(lookup, []):
                word_senses.append({
                    "pos": es_sense["pos"],
                    "translation": es_sense["gloss_es"],
                    "source": "es-wikt",
                })

        if not word_senses:
            no_senses_count += 1
            continue

        wl_key = "%s|%s" % (word, lemma)
        source = "wiktionary"

        # Build ID map for new format output
        id_map = assign_sense_ids(word_senses)
        normal_only_senses[wl_key] = id_map

        sense_sources[source] += 1

        if not examples:
            no_examples_count += 1
            continue

        # Get sense IDs (new format)
        id_list = list(id_map.keys())

        if len(word_senses) == 1:
            single_sense_count += 1
            output[word] = {"wiktionary-auto": [{"sense": id_list[0],
                                                  "examples": list(range(len(examples)))}]}
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
                assignments.append({"sense": id_list[i], "examples": indices})
            if not assignments:
                assignments = [{"sense": id_list[0], "examples": list(range(len(examples)))}]
            output[word] = {"keyword": assignments}
        else:
            work_items.append((word, word_senses, examples, keep_indices, source, id_list))

    if skipped_priority:
        print("  Skipped (higher-priority method exists): %d" % skipped_priority)
    if args.normal_only:
        print("  Skipped (not in normal mode): %d" % skipped_not_normal)
    print("  Single-sense (no classification): %d" % single_sense_count)
    print("  Multi-sense to classify: %d" % len(work_items))
    print("  No senses: %d" % no_senses_count)
    print("  No examples: %d" % no_examples_count)
    print("  Sense sources: %s" % dict(sense_sources))

    # Check translation coverage for multi-sense examples
    if work_items and not use_keyword:
        total_ex = sum(len(item[2]) for item in work_items)
        has_eng = 0
        for item in work_items:
            examples = item[2]
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

    # Merge with existing assignments (add biencoder alongside other methods)
    if output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            existing = json.load(f)
        for word, word_data in output.items():
            if isinstance(word_data, dict):
                if word not in existing or not isinstance(existing[word], dict):
                    existing[word] = {}
                existing[word].update(word_data)
            else:
                existing[word] = word_data
        output = existing

    print("\nWriting %s..." % output_file)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Write/merge the senses layer
    if senses_output_file and normal_only_senses:
        existing_senses = {}
        if senses_output_file.exists():
            with open(senses_output_file, encoding="utf-8") as f:
                existing_senses = json.load(f)
        existing_senses.update(normal_only_senses)
        print("Writing %s (%d entries)..." % (senses_output_file, len(existing_senses)))
        with open(senses_output_file, "w", encoding="utf-8") as f:
            json.dump(existing_senses, f, ensure_ascii=False, indent=2)

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
