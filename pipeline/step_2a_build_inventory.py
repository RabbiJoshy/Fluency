#!/usr/bin/env python3
"""
step_2a_build_inventory.py — Build word inventory from frequency CSV.

Reads SpanishRawWiki.csv and produces the base word inventory with stable
6-char hex IDs. This is the foundation layer that all other steps reference.

Stores corpus_count (raw frequency from corpus) rather than rank — the builder
computes sort position from corpus_count.

Homograph disambiguation: when a surface form maps to multiple lemmas (e.g.
"como" → como|como + como|comer), the raw corpus_count is identical for both.
This step redistributes the count using spaCy POS-tagging over Tatoeba sentences
for noun/verb splits, and a manual overrides file for verb/verb collisions.

Usage:
    python3 pipeline/step_2a_build_inventory.py
    python3 pipeline/step_2a_build_inventory.py --skip-homographs

Inputs:
    Data/Spanish/SpanishRawWiki.csv
    Data/Spanish/corpora/tatoeba/spa.txt  (for homograph disambiguation)
    Data/Spanish/layers/homograph_overrides.json  (manual verb/verb ratios)

Output:
    Data/Spanish/layers/word_inventory.json
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSV_SOURCE = PROJECT_ROOT / "Data" / "Spanish" / "SpanishRawWiki.csv"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"
TATOEBA_FILE = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "tatoeba" / "spa.txt"
OVERRIDES_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "homograph_overrides.json"

# Cap on Tatoeba sentences to process per surface form
MAX_SENTENCES_PER_WORD = 20


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


def load_tatoeba():
    """Load Spanish sentences from Tatoeba corpus."""
    sentences = []
    if not TATOEBA_FILE.exists():
        print(f"  WARNING: Tatoeba file not found at {TATOEBA_FILE}")
        return sentences
    with open(TATOEBA_FILE, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                sentences.append(parts[1])  # Spanish sentence
    return sentences


def compute_homograph_ratios(entries, skip=False):
    """Disambiguate homograph surface forms and return {word: {lemma: ratio}}.

    Runs spaCy over Tatoeba sentences to determine which lemma interpretation
    dominates for each surface form. Manual overrides (from homograph_overrides.json)
    take priority over spaCy for cases where the tagger is unreliable.
    Returns ratios that sum to 1.0 per surface form.
    """
    if skip:
        return {}

    # Group entries by surface form to find homographs
    by_word = defaultdict(list)
    for entry in entries:
        by_word[entry["word"]].append(entry)

    homographs = {w: ents for w, ents in by_word.items() if len(ents) > 1}
    if not homographs:
        return {}

    all_words = {}  # word -> list of lemmas
    for word, ents in homographs.items():
        all_words[word] = [e["lemma"] for e in ents]

    print(f"\n  Homographs: {len(homographs)} total")

    ratios = {}

    # --- Manual overrides (corrections for spaCy errors) ---
    overrides = {}
    if OVERRIDES_FILE.exists():
        with open(OVERRIDES_FILE, encoding="utf-8") as f:
            overrides = json.load(f)
        print(f"  Loaded {len(overrides)} manual overrides from {OVERRIDES_FILE.name}")

    # Apply overrides first (they take priority over spaCy)
    for word, lemma_ratios in overrides.items():
        if word in homographs:
            ratios[word] = lemma_ratios

    # --- spaCy disambiguation for all remaining homographs ---
    spacy_todo = {w: ls for w, ls in all_words.items() if w not in ratios}
    if not spacy_todo:
        print("  All homographs covered by overrides, skipping spaCy.")
        return ratios

    print(f"  Running spaCy on {len(spacy_todo)} homographs...")
    try:
        import spacy
        nlp = spacy.load("es_core_news_lg")
    except (ImportError, OSError) as e:
        print(f"  WARNING: spaCy not available ({e}), using equal split for all")
        for word, lemmas in homographs.items():
            if word not in ratios:
                n = len(lemmas)
                ratios[word] = {l: 1.0 / n for l in lemmas}
        return ratios

    # Load Tatoeba sentences
    tatoeba = load_tatoeba()
    if not tatoeba:
        print("  WARNING: No Tatoeba sentences, using equal split")
        for word, lemmas in homographs.items():
            if word not in ratios:
                n = len(lemmas)
                ratios[word] = {l: 1.0 / n for l in lemmas}
        return ratios
    print(f"  Loaded {len(tatoeba)} Tatoeba sentences")

    # Pre-index: for each homograph word, find matching sentences
    word_sentences = {}
    for word in spacy_todo:
        pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
        matches = [s for s in tatoeba if pattern.search(s)][:MAX_SENTENCES_PER_WORD]
        if matches:
            word_sentences[word] = matches

    print(f"  Found Tatoeba sentences for {len(word_sentences)}/{len(spacy_todo)} words")

    # Process with spaCy
    resolved = 0
    no_sentences = 0
    total_todo = len(spacy_todo)
    for i, (word, lemmas) in enumerate(spacy_todo.items()):
        if (i + 1) % 100 == 0 or i + 1 == total_todo:
            print(f"    {i + 1}/{total_todo}...", end="\r", flush=True)
        sents = word_sentences.get(word)
        if not sents:
            # No Tatoeba coverage — equal split
            no_sentences += 1
            ratios[word] = {l: 1.0 / len(lemmas) for l in lemmas}
            continue

        # Run spaCy and tally lemmas
        lemma_counts = defaultdict(int)
        doc = nlp("\n\n".join(sents))
        for token in doc:
            if token.text.lower() == word.lower():
                spacy_lemma = token.lemma_.lower()
                lemma_counts[spacy_lemma] += 1

        total = sum(lemma_counts.values())
        if total == 0:
            ratios[word] = {l: 1.0 / len(lemmas) for l in lemmas}
            continue

        # Map spaCy lemmas to our inventory lemmas
        word_ratios = {}
        matched_count = 0
        for lemma in lemmas:
            count = lemma_counts.get(lemma.lower(), 0)
            # Also check for case variants (spaCy sometimes capitalises)
            for spacy_l, spacy_c in lemma_counts.items():
                if spacy_l.lower() == lemma.lower() and spacy_l != lemma.lower():
                    count += spacy_c
            word_ratios[lemma] = count
            matched_count += count

        # Distribute any unmatched spaCy lemmas proportionally
        # (spaCy may lemmatise to something not in our inventory)
        unmatched = total - matched_count
        if unmatched > 0 and matched_count > 0:
            for lemma in word_ratios:
                word_ratios[lemma] += unmatched * (word_ratios[lemma] / matched_count)
        elif unmatched > 0 and matched_count == 0:
            # spaCy didn't map to any of our lemmas — equal split
            word_ratios = {l: 1.0 / len(lemmas) for l in lemmas}
            ratios[word] = word_ratios
            continue

        # Normalise to ratios
        ratio_total = sum(word_ratios.values())
        if ratio_total > 0:
            ratios[word] = {l: c / ratio_total for l, c in word_ratios.items()}
        else:
            ratios[word] = {l: 1.0 / len(lemmas) for l in lemmas}
        resolved += 1

    print(f"  spaCy resolved: {resolved}, no Tatoeba sentences: {no_sentences}")

    return ratios


def main():
    parser = argparse.ArgumentParser(description="Build word inventory from frequency CSV")
    parser.add_argument("--skip-homographs", action="store_true",
                        help="Skip homograph disambiguation (faster, keeps 50/50 split)")
    args = parser.parse_args()

    print("Loading vocabulary from CSV...")
    entries = []
    used_ids = set()

    with open(CSV_SOURCE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = row["word"]
            lemma = row["lemma"]
            corpus_count = int(float(row["occurrences_ppm"]))
            word_id = make_stable_id(word, lemma, used_ids)
            used_ids.add(word_id)

            entries.append({
                "word": word,
                "lemma": lemma,
                "id": word_id,
                "corpus_count": corpus_count,
            })

    # --- Homograph disambiguation ---
    ratios = compute_homograph_ratios(entries, skip=args.skip_homographs)
    if ratios:
        adjusted = 0
        for entry in entries:
            word = entry["word"]
            if word in ratios and entry["lemma"] in ratios[word]:
                ratio = ratios[word][entry["lemma"]]
                entry["corpus_count"] = max(1, int(entry["corpus_count"] * ratio))
                entry["homograph_ratio"] = round(ratio, 4)
                adjusted += 1
        print(f"  Adjusted corpus_count for {adjusted} homograph entries")

    # --- Homograph cross-references (sibling IDs) ---
    by_word = defaultdict(list)
    for entry in entries:
        by_word[entry["word"]].append(entry)
    for word, ents in by_word.items():
        if len(ents) > 1:
            for entry in ents:
                siblings = [e["id"] for e in ents if e["id"] != entry["id"]]
                if siblings:
                    entry["homograph_ids"] = siblings

    # Compute most_frequent_lemma_instance:
    # For each lemma, the entry with the highest corpus_count gets True
    seen_lemmas = {}
    for entry in entries:
        lemma = entry["lemma"].lower()
        if lemma not in seen_lemmas or entry["corpus_count"] > seen_lemmas[lemma]["corpus_count"]:
            seen_lemmas[lemma] = entry
    for entry in entries:
        entry["most_frequent_lemma_instance"] = (
            entry is seen_lemmas[entry["lemma"].lower()]
        )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    lemma_reps = sum(1 for e in entries if e["most_frequent_lemma_instance"])
    homograph_count = sum(1 for e in entries if "homograph_ratio" in e)
    print(f"\n  {len(entries)} entries, {lemma_reps} unique lemma representatives")
    if homograph_count:
        print(f"  {homograph_count} entries with homograph ratios applied")


if __name__ == "__main__":
    main()
