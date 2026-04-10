#!/usr/bin/env python3
"""
Step 4: Pre-tag vocabulary words to save Gemini tokens in step 6.

Detects three categories using cheap local methods:
  1. Proper nouns — capitalization ratio + spaCy NER + curated known list
  2. Interjections — regex patterns for sound effects / onomatopoeia
  3. English words — lingua language detection on example lines

Words tagged here are skipped by step 6's Gemini analysis. Precision matters
more than recall: a missed proper noun just costs a few Gemini tokens, but a
false positive loses a real vocabulary word from the deck.

No API key needed. Runs in seconds (--no-spacy --no-lingua) to ~60s (full).

Reads:  <artist-dir>/data/word_counts/vocab_evidence.json
        Artists/shared/known_proper_nouns.json, not_proper_nouns.json,
        interjections.json, extra_english.json
Writes: <artist-dir>/data/proper_nouns/detected_proper_nouns.json

Usage (from project root):
    .venv/bin/python3 Artists/scripts/4_detect_proper_nouns.py --artist-dir "Artists/Bad Bunny"
    .venv/bin/python3 Artists/scripts/4_detect_proper_nouns.py --artist-dir "Artists/Rosalía" --no-spacy
"""

import json
import os
import time
import argparse
import re
from typing import Dict, Set


from _artist_config import add_artist_arg, load_shared_list


# ---------------------------------------------------------------------------
# Proper noun detection: capitalization
# ---------------------------------------------------------------------------

def detect_propn_by_capitalization(vocab_data, min_count=5, min_ratio=0.8):
    """Words capitalized mid-line at a high ratio are likely proper nouns."""
    cap_counts = {}   # type: Dict[str, int]
    total_counts = {}  # type: Dict[str, int]

    for entry in vocab_data:
        for ex in entry.get("examples", []):
            line = ex.get("line", "")
            words = line.split()
            for i, w in enumerate(words):
                clean = re.sub(r"[^\w'\-áéíóúñü]", "", w)
                if not clean or len(clean) < 2:
                    continue
                lower = clean.lower()
                total_counts[lower] = total_counts.get(lower, 0) + 1
                if i > 0 and clean[0].isupper():
                    cap_counts[lower] = cap_counts.get(lower, 0) + 1

    detected = set()
    for w, cc in cap_counts.items():
        total = total_counts.get(w, 1)
        if cc >= min_count and cc / total >= min_ratio:
            detected.add(w)

    return detected, cap_counts, total_counts


# ---------------------------------------------------------------------------
# Proper noun detection: spaCy NER
# ---------------------------------------------------------------------------

def detect_propn_by_spacy(vocab_data):
    """spaCy NER on example lines. Returns words tagged PER/LOC/ORG."""
    try:
        import spacy
    except ImportError:
        print("  [WARN] spaCy not installed — skipping NER pass")
        return set()
    try:
        nlp = spacy.load("es_core_news_lg")
    except OSError:
        print("  [WARN] es_core_news_lg not found — skipping NER pass")
        return set()

    print("  Running spaCy NER on %d words..." % len(vocab_data))
    word_examples = {}  # type: Dict[str, str]
    for entry in vocab_data:
        word = entry["word"].lower()
        if word not in word_examples:
            for ex in entry.get("examples", []):
                line = ex.get("line", "")
                if len(line) > 10:
                    word_examples[word] = line
                    break

    detected = set()  # type: Set[str]
    start = time.time()
    for entry in vocab_data:
        word = entry["word"].lower()
        line = word_examples.get(word, word)
        doc = nlp(line)
        for ent in doc.ents:
            if ent.text.lower() == word and ent.label_ in ("PER", "LOC", "ORG"):
                detected.add(word)
                break
    print("  spaCy found %d entities in %.1fs" % (len(detected), time.time() - start))
    return detected


# ---------------------------------------------------------------------------
# Interjection detection: regex patterns
# ---------------------------------------------------------------------------

_INTERJECTION_PATTERNS = [
    re.compile(r'^[wb]r+[aeiou]*$'),     # brr, brra, wrrr
    re.compile(r'^pr+[aeiou]*$'),         # prr, prra, prru
    re.compile(r'^sk[r]*t+$'),            # skrt, skrrt
    re.compile(r'^[jh]a+[jh]?a*$'),      # ja, jaja, jajaja, ha, haha
    re.compile(r'^[jh]e+[jh]?e*$'),      # je, jeje, he, hehe
    re.compile(r'^[uoa]h+$'),            # uh, uhh, oh, ohh, ah, ahh
    re.compile(r'^[eaio]h[aeiou]?h?$'),  # eh, eha, ah
    re.compile(r'^sh+$'),                 # shh, shhh
    re.compile(r'^[mh]m+$'),             # mm, mmm, hm, hmm
    re.compile(r'^ya+h*$'),              # ya, yah, yaah
    re.compile(r'^ye+[ah]*$'),           # yeh, yeah, yeaah
    re.compile(r'^na+h*$'),              # na, nah, naah
    re.compile(r'^w[oua]+h*$'),          # woo, wooh, wuh, wuuh, wouh
    re.compile(r'^[dt]u+h+$'),           # duh, tuh
    re.compile(r'^bo+$'),                # boo, booo
    re.compile(r'^a+y+$'),              # ay, ayy, ayyy
    re.compile(r'^r+a+h?$'),            # rra, rrra, rah
    re.compile(r'^e+y+$'),              # ey, eyy, eyyy
    re.compile(r'^hu+h?$'),             # hu, huh, huuh
]

_INTERJECTION_EXCEPTIONS = frozenset({
    "ya", "na", "je", "he", "oh", "ah", "ay", "eh",
    "bora", "monta", "bro", "pre", "pri", "pro", "bo", "ye",
})


def detect_interjections(vocab_data, known_interjections):
    """Detect interjections using regex patterns + shared list."""
    detected = set()  # type: Set[str]
    for entry in vocab_data:
        w = entry["word"].lower()
        w_stripped = w.replace("'", "")
        if w in known_interjections:
            detected.add(w)
            continue
        if len(w_stripped) < 2 or len(w_stripped) > 15:
            continue
        if w_stripped in _INTERJECTION_EXCEPTIONS:
            continue
        if len(w_stripped) >= 3 and len(set(w_stripped)) == 1:
            detected.add(w)
            continue
        if re.search(r'(.)\1\1', w_stripped):
            detected.add(w)
            continue
        for pat in _INTERJECTION_PATTERNS:
            if pat.match(w_stripped):
                detected.add(w)
                break
    return detected


# ---------------------------------------------------------------------------
# English detection: lingua
# ---------------------------------------------------------------------------

def detect_english_by_lingua(vocab_data, known_english):
    """Words where ALL example lines are detected as English by lingua."""
    try:
        from lingua import Language, LanguageDetectorBuilder
    except ImportError:
        print("  [WARN] lingua not installed — skipping English detection")
        return set()

    print("  Building lingua detector...")
    detector = LanguageDetectorBuilder.from_languages(
        Language.SPANISH, Language.ENGLISH
    ).build()

    detected = set(known_english)  # type: Set[str]
    start = time.time()
    for entry in vocab_data:
        w = entry["word"].lower()
        if w in detected:
            continue
        examples = entry.get("examples", [])
        lines = [ex.get("line", "") for ex in examples[:3] if ex.get("line", "")]
        if not lines:
            continue
        eng_count = sum(1 for l in lines
                        if detector.detect_language_of(l) == Language.ENGLISH)
        if eng_count == len(lines):
            detected.add(w)

    print("  lingua found %d English words in %.1fs" % (len(detected), time.time() - start))
    return detected


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Step 4: Pre-tag proper nouns, interjections, and English words")
    add_artist_arg(parser)
    parser.add_argument("--no-spacy", action="store_true",
                        help="Skip spaCy NER pass (faster)")
    parser.add_argument("--no-lingua", action="store_true",
                        help="Skip lingua English detection (faster)")
    parser.add_argument("--min-cap-count", type=int, default=5)
    parser.add_argument("--min-cap-ratio", type=float, default=0.8)
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    input_path = os.path.join(artist_dir, "data", "word_counts", "vocab_evidence.json")
    output_path = os.path.join(artist_dir, "data", "layers", "detected_proper_nouns.json")

    KNOWN_PROPER_NOUNS = frozenset(load_shared_list("known_proper_nouns.json"))
    NOT_PROPER_NOUNS = frozenset(load_shared_list("not_proper_nouns.json"))
    KNOWN_INTERJECTIONS = frozenset(load_shared_list("interjections.json"))
    KNOWN_ENGLISH = frozenset(load_shared_list("extra_english.json"))
    exclude = NOT_PROPER_NOUNS | KNOWN_INTERJECTIONS | KNOWN_ENGLISH

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print("Loading %s..." % input_path)
    with open(input_path, "r", encoding="utf-8") as f:
        vocab_data = json.load(f)
    print("  %d vocabulary entries" % len(vocab_data))
    vocab_words = {entry["word"].lower() for entry in vocab_data}

    # --- Proper nouns ---
    print("\n--- Proper nouns ---")
    cap_detected, _, _ = detect_propn_by_capitalization(
        vocab_data, min_count=args.min_cap_count, min_ratio=args.min_cap_ratio)
    print("  Capitalization: %d" % len(cap_detected))

    spacy_detected = set()
    if not args.no_spacy:
        spacy_detected = detect_propn_by_spacy(vocab_data)

    known_in_vocab = KNOWN_PROPER_NOUNS & vocab_words
    all_propn = (cap_detected | spacy_detected | known_in_vocab) - exclude
    propn_in_vocab = sorted(all_propn & vocab_words)
    print("  Total: %d in vocabulary" % len(propn_in_vocab))

    # --- Interjections ---
    print("\n--- Interjections ---")
    all_intj = detect_interjections(vocab_data, KNOWN_INTERJECTIONS)
    intj_in_vocab = sorted(all_intj & vocab_words)
    print("  Total: %d in vocabulary" % len(intj_in_vocab))

    # --- English ---
    print("\n--- English ---")
    if not args.no_lingua:
        all_english = detect_english_by_lingua(vocab_data, KNOWN_ENGLISH)
    else:
        all_english = set(KNOWN_ENGLISH)
        print("  lingua skipped — shared list only (%d)" % len(all_english))
    english_in_vocab = sorted(all_english & vocab_words)
    print("  Total: %d in vocabulary" % len(english_in_vocab))

    # --- Summary ---
    total_tagged = len(set(propn_in_vocab) | set(intj_in_vocab) | set(english_in_vocab))
    print("\n=== Summary ===")
    print("  Proper nouns:   %4d" % len(propn_in_vocab))
    print("  Interjections:  %4d" % len(intj_in_vocab))
    print("  English:        %4d" % len(english_in_vocab))
    print("  Total tagged:   %4d / %d (%.0f%% will skip Gemini)" %
          (total_tagged, len(vocab_words), 100 * total_tagged / len(vocab_words)))

    output = {
        "proper_nouns": propn_in_vocab,
        "interjections": intj_in_vocab,
        "english": english_in_vocab,
        "in_vocab_count": len(propn_in_vocab),
        "total_tagged": total_tagged,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("  Wrote %s" % output_path)


if __name__ == "__main__":
    main()
