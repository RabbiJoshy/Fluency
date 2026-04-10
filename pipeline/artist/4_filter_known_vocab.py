#!/usr/bin/env python3
"""
Step 4: Filter known vocabulary to reduce Gemini workload in step 6.

Runs a chain of set-difference filters to identify words that don't need
LLM analysis. Standard Spanish words, known conjugated forms, English
loanwords, and rare hapax legomena are tagged for skipping.

The remaining words — mostly Caribbean/regional slang, profanity, and a
handful of proper nouns — are the only ones sent to Gemini in step 6.

Typical reduction: ~11,500 words → ~600-850 (93% fewer Gemini calls).

Reads:  <artist-dir>/data/elision_merge/vocab_evidence_merged.json
        Data/Spanish/vocabulary.json
        Data/Spanish/es_50k_wordlist.txt
        Data/Spanish/layers/conjugation_reverse.json
        Artists/curations/proper_nouns.json, interjections.json, extra_english.json
Writes: <artist-dir>/data/known_vocab/skip_words.json

Usage (from project root):
    .venv/bin/python3 Artists/scripts/4_filter_known_vocab.py --artist-dir "Artists/Bad Bunny"
    .venv/bin/python3 Artists/scripts/4_filter_known_vocab.py --artist-dir "Artists/Rosalía" --min-freq 2
    .venv/bin/python3 Artists/scripts/4_filter_known_vocab.py --artist-dir "Artists/Bad Bunny" --no-lingua
"""

import json
import os
import re
import sys
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _artist_config import add_artist_arg, load_shared_list, SHARED_DIR

# Paths relative to project root (derived from this file's location)
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
ARTISTS_DIR = os.path.dirname(SCRIPTS_DIR)
PROJECT_ROOT = os.path.dirname(ARTISTS_DIR)

NORMAL_VOCAB_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "vocabulary.json")
ES_50K_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "es_50k_wordlist.txt")
CONJ_REVERSE_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "layers", "conjugation_reverse.json")
ELISION_MAPPING_PATH = os.path.join(SHARED_DIR, "elision_mapping.json")

# D-elision regexes: Caribbean d-drop in past participles and derivatives.
# Step 5 handles -a'o/-í'o when a canonical counterpart exists in the corpus.
# These are backups for when step 3 can't merge (no counterpart), plus
# feminine/plural variants that step 3 doesn't cover at all.
_D_ELISION_PATTERNS = [
    (re.compile(r"^(.+)a'o$"), "ado"),     # -a'o  -> -ado   (masc sing)
    (re.compile(r"^(.+)a'a$"), "ada"),     # -a'a  -> -ada   (fem sing)
    (re.compile(r"^(.+)a'os$"), "ados"),   # -a'os -> -ados  (masc pl)
    (re.compile(r"^(.+)a'as$"), "adas"),   # -a'as -> -adas  (fem pl)
    (re.compile(r"^(.+)í'o$"), "ido"),     # -í'o  -> -ido   (masc sing)
    (re.compile(r"^(.+)í'a$"), "ida"),     # -í'a  -> -ida   (fem sing)
    (re.compile(r"^(.+)í'os$"), "idos"),   # -í'os -> -idos  (masc pl)
    (re.compile(r"^(.+)í'as$"), "idas"),   # -í'as -> -idas  (fem pl)
]


def load_es_50k(path):
    """Load the 50k Spanish frequency wordlist (word count format)."""
    words = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if parts:
                words.add(parts[0].lower())
    return words


def load_normal_vocab(path):
    """Load word forms from normal mode vocabulary."""
    with open(path, "r", encoding="utf-8") as f:
        vocab = json.load(f)
    return set(entry["word"].lower() for entry in vocab)


def load_conjugation_forms(path):
    """Load all inflected forms from the conjugation reverse lookup."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return set(k.lower() for k in data.keys())


def elision_canonical(word):
    """Map common non-s-elision contractions to their standard forms.

    Returns a set of candidate standard forms to check against wordlists.
    S-elisions (lo' -> los) are already handled by step 3 merge. This
    covers the remaining contractions that step 3 skips.
    """
    candidates = set()

    # Apostrophe at end: try restoring common dropped endings
    if word.endswith("'"):
        stem = word[:-1]
        # pa' -> para, ma' -> mamá (less common), na' -> nada
        # verda' -> verdad, die' -> diez
        candidates.add(stem)           # try bare stem
        candidates.add(stem + "s")     # e.g. to' -> todos (already merged, but safety)
        candidates.add(stem + "d")     # verda' -> verdad
        candidates.add(stem + "z")     # die' -> diez
        candidates.add(stem + "r")     # possible verb infinitive truncation

    # D-elision variants: backup for step 3 misses + feminine/plural forms
    for pattern, suffix in _D_ELISION_PATTERNS:
        m = pattern.match(word)
        if m:
            candidates.add(m.group(1) + suffix)

    # Apostrophe in middle: common contractions
    if "'" in word and not word.endswith("'"):
        parts = word.split("'")
        if len(parts) == 2:
            prefix_expansions = {
                "pa": "para",
                "po": "por",
                "to": "todo",
            }
            expanded = prefix_expansions.get(parts[0])
            if expanded:
                candidates.add(expanded)
                candidates.add(parts[1])
                # Also try expanding the suffix: l -> el
                suffix_expansions = {"l": "el"}
                suffix_exp = suffix_expansions.get(parts[1])
                if suffix_exp:
                    candidates.add(suffix_exp)

    # Common known mappings for very frequent forms
    known = {
        "pa'": "para",
        "pa": "para",
        "na'": "nada",
        "to'": "todo",
        "to": "todo",
        "tá": "está",
        "tás": "estás",
        "toy": "estoy",
        "tamos": "estamos",
        "vamo": "vamos",
        "vo'a": "voy",
        "pa'l": "para",
        "to'a": "toda",
        "to'as": "todas",
        "to's": "todos",
        "toas": "todas",
        "tó": "todo",
        # Additional Caribbean/colloquial forms
        "to'ito": "todito",
        "ma'i": "mami",
        "oí'te": "oíste",
        "de'o": "dedo",
        "a'o": "ado",       # bare d-elision suffix (too short for regex)
        "dies'": "diez",    # diez with s-elision marker
    }
    if word in known:
        candidates.add(known[word])

    return candidates


def classify_english(words, threshold=0.90):
    """Use lingua to classify words as high-confidence English."""
    try:
        from lingua import Language, LanguageDetectorBuilder
    except ImportError:
        print("  WARNING: lingua not installed, skipping English detection")
        return set()

    detector = LanguageDetectorBuilder.from_languages(
        Language.SPANISH, Language.ENGLISH
    ).build()

    english = set()
    for w in words:
        confidences = detector.compute_language_confidence_values(w)
        en_conf = next(
            (c.value for c in confidences if c.language == Language.ENGLISH), 0
        )
        if en_conf >= threshold:
            english.add(w)

    return english


def main():
    parser = argparse.ArgumentParser(
        description="Step 4: Filter known vocabulary to reduce Gemini workload"
    )
    add_artist_arg(parser)
    parser.add_argument(
        "--min-freq", type=int, default=2,
        help="Minimum corpus frequency to keep (default: 2, i.e. cut hapax legomena)"
    )
    parser.add_argument(
        "--lingua-threshold", type=float, default=0.90,
        help="Confidence threshold for English classification (default: 0.90)"
    )
    parser.add_argument(
        "--no-lingua", action="store_true",
        help="Skip lingua English detection (faster, keeps some English words)"
    )
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    input_path = os.path.join(artist_dir, "data", "elision_merge", "vocab_evidence_merged.json")
    output_dir = os.path.join(artist_dir, "data", "known_vocab")
    output_path = os.path.join(output_dir, "skip_words.json")
    os.makedirs(output_dir, exist_ok=True)

    start_time = time.time()

    # Load artist vocabulary
    print("Loading %s..." % input_path)
    with open(input_path, "r", encoding="utf-8") as f:
        all_words = json.load(f)
    word_freq = {entry["word"].lower(): entry.get("corpus_count", 0) for entry in all_words}
    artist_words = set(word_freq.keys())
    print("  %d words loaded" % len(artist_words))

    # Track what each filter catches (for output and logging)
    known_spanish = set()   # found in 50k / normal vocab / conjugations
    known_elision = set()   # elision whose canonical form is known
    known_shared = set()    # in shared curated lists
    english = set()         # high-confidence English
    low_frequency = set()   # below min-freq threshold

    remaining = set(artist_words)

    # ---------------------------------------------------------------
    # Filter 1: Elision normalization
    # ---------------------------------------------------------------
    # Check if the canonical form of an elision is in any wordlist.
    # We do this first so elisions get tagged even if their contracted
    # form isn't in the 50k list. The actual check happens after we
    # load the wordlists (filters 2-4), but we pre-compute candidates.
    elision_candidates = {}  # word -> set of canonical forms
    for w in remaining:
        candidates = elision_canonical(w)
        if candidates:
            elision_candidates[w] = candidates

    # ---------------------------------------------------------------
    # Filter 2: Normal mode vocabulary
    # ---------------------------------------------------------------
    print("Loading normal mode vocabulary...")
    if os.path.exists(NORMAL_VOCAB_PATH):
        normal_words = load_normal_vocab(NORMAL_VOCAB_PATH)
        print("  %d word forms" % len(normal_words))
    else:
        normal_words = set()
        print("  WARNING: %s not found, skipping" % NORMAL_VOCAB_PATH)

    matched = remaining & normal_words
    known_spanish |= matched
    remaining -= matched
    print("  Removed %d words (normal mode vocab)" % len(matched))

    # ---------------------------------------------------------------
    # Filter 3: Spanish 50k frequency list
    # ---------------------------------------------------------------
    print("Loading es_50k wordlist...")
    if os.path.exists(ES_50K_PATH):
        es_50k = load_es_50k(ES_50K_PATH)
        print("  %d words" % len(es_50k))
    else:
        es_50k = set()
        print("  WARNING: %s not found, skipping" % ES_50K_PATH)

    matched = remaining & es_50k
    known_spanish |= matched
    remaining -= matched
    print("  Removed %d words (es_50k)" % len(matched))

    # ---------------------------------------------------------------
    # Filter 4: Conjugation reverse lookup
    # ---------------------------------------------------------------
    print("Loading conjugation reverse lookup...")
    if os.path.exists(CONJ_REVERSE_PATH):
        conj_forms = load_conjugation_forms(CONJ_REVERSE_PATH)
        print("  %d inflected forms" % len(conj_forms))
    else:
        conj_forms = set()
        print("  WARNING: %s not found, skipping" % CONJ_REVERSE_PATH)

    matched = remaining & conj_forms
    known_spanish |= matched
    remaining -= matched
    print("  Removed %d words (conjugation reverse)" % len(matched))

    # ---------------------------------------------------------------
    # Now resolve elisions: check if canonical forms hit any wordlist
    # ---------------------------------------------------------------
    all_known = normal_words | es_50k | conj_forms
    for w in list(remaining):
        if w in elision_candidates:
            for candidate in elision_candidates[w]:
                if candidate.lower() in all_known:
                    known_elision.add(w)
                    remaining.discard(w)
                    break

    # Load skip forms from step 3's elision mapping — these are non-s-elision
    # forms that step 3 identified but chose not to merge. Tag them as known.
    if os.path.exists(ELISION_MAPPING_PATH):
        with open(ELISION_MAPPING_PATH, "r", encoding="utf-8") as f:
            elision_mapping = json.load(f)
        skip_forms = frozenset(
            entry["word"] for entry in elision_mapping
            if entry.get("action") == "skip"
        )
        for w in list(remaining):
            if w in skip_forms:
                known_elision.add(w)
                remaining.discard(w)

    print("  Removed %d words (elision → known canonical form)" % len(known_elision))

    # ---------------------------------------------------------------
    # Filter 5: Shared curated lists
    # ---------------------------------------------------------------
    print("Loading shared curated lists...")
    proper_nouns = frozenset(w.lower() for w in load_shared_list("proper_nouns.json"))
    interjections = frozenset(w.lower() for w in load_shared_list("interjections.json"))
    extra_english = frozenset(w.lower() for w in load_shared_list("extra_english.json"))
    shared_all = proper_nouns | interjections | extra_english
    print("  %d proper nouns, %d interjections, %d English" %
          (len(proper_nouns), len(interjections), len(extra_english)))

    matched = remaining & shared_all
    known_shared |= matched
    remaining -= matched
    print("  Removed %d words (shared lists)" % len(matched))

    # ---------------------------------------------------------------
    # Filter 6: Lingua English detection
    # ---------------------------------------------------------------
    if not args.no_lingua:
        print("Running lingua English detection (threshold=%.2f)..." % args.lingua_threshold)
        english = classify_english(remaining, threshold=args.lingua_threshold)
        remaining -= english
        print("  Removed %d words (high-confidence English)" % len(english))
    else:
        print("Skipping lingua English detection (--no-lingua)")

    # ---------------------------------------------------------------
    # Filter 7: Frequency threshold
    # ---------------------------------------------------------------
    print("Applying frequency threshold (min_freq=%d)..." % args.min_freq)
    for w in list(remaining):
        if word_freq.get(w, 0) < args.min_freq:
            low_frequency.add(w)
            remaining.discard(w)
    print("  Removed %d words (freq < %d)" % (len(low_frequency), args.min_freq))

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    elapsed = time.time() - start_time
    total_skipped = len(known_spanish) + len(known_elision) + len(known_shared) + len(english) + len(low_frequency)

    print("\n=== Filter Summary ===")
    print("  Input words:          %d" % len(artist_words))
    print("  Known Spanish:        %d (normal vocab + es_50k + conjugations)" % len(known_spanish))
    print("  Known elisions:       %d (canonical form in wordlists)" % len(known_elision))
    print("  Shared curated lists: %d" % len(known_shared))
    print("  English (lingua):     %d" % len(english))
    print("  Low frequency:        %d (freq < %d)" % (len(low_frequency), args.min_freq))
    print("  ---")
    print("  Total skipped:        %d (%.0f%%)" % (total_skipped, total_skipped * 100 / len(artist_words)))
    print("  Remaining for Gemini: %d" % len(remaining))
    print("  Time: %.1f seconds" % elapsed)

    # ---------------------------------------------------------------
    # Write output
    # ---------------------------------------------------------------
    output = {
        "known_spanish": sorted(known_spanish),
        "known_elision": sorted(known_elision),
        "known_shared": sorted(known_shared),
        "english": sorted(english),
        "low_frequency": sorted(low_frequency),
        "remaining": sorted(remaining, key=lambda w: word_freq.get(w, 0), reverse=True),
        "stats": {
            "input_words": len(artist_words),
            "known_spanish": len(known_spanish),
            "known_elision": len(known_elision),
            "known_shared": len(known_shared),
            "english": len(english),
            "low_frequency": len(low_frequency),
            "total_skipped": total_skipped,
            "remaining": len(remaining),
            "min_freq": args.min_freq,
            "lingua_threshold": args.lingua_threshold if not args.no_lingua else None,
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("\nWrote %s" % output_path)


if __name__ == "__main__":
    main()
