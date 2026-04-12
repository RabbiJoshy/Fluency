#!/usr/bin/env python3
"""
Step 4: Filter known vocabulary to reduce Gemini workload in step 6.

Runs a chain of set-difference filters to identify words that don't need
LLM analysis. Standard Spanish words, known conjugated forms, English
loanwords, and rare hapax legomena are tagged for skipping.

Also detects interjections, proper nouns, and English words using NLP
methods (Wiktionary POS, regex patterns, lingua on example lines,
spaCy NER, capitalization ratio). These categories are written to
skip_words.json for downstream use by build_wiktionary_senses.py.

The remaining words — mostly Caribbean/regional slang and profanity —
are the only ones sent to Gemini in step 6.

Typical reduction: ~11,500 words → ~600-850 (93% fewer Gemini calls).

Reads:  <artist-dir>/data/elision_merge/vocab_evidence_merged.json
        Data/Spanish/vocabulary.json
        Data/Spanish/es_50k_wordlist.txt
        Data/Spanish/layers/conjugation_reverse.json
        Data/Spanish/layers/senses_wiktionary.json
        Artists/curations/proper_nouns.json, interjections.json, extra_english.json
        Artists/curations/known_proper_nouns.json, not_proper_nouns.json
Writes: <artist-dir>/data/known_vocab/skip_words.json

Usage (from project root):
    .venv/bin/python3 pipeline/artist/4_filter_known_vocab.py --artist-dir "Artists/Bad Bunny"
    .venv/bin/python3 pipeline/artist/4_filter_known_vocab.py --artist-dir "Artists/Rosalía" --min-freq 2
    .venv/bin/python3 pipeline/artist/4_filter_known_vocab.py --artist-dir "Artists/Bad Bunny" --no-lingua
    .venv/bin/python3 pipeline/artist/4_filter_known_vocab.py --artist-dir "Artists/Bad Bunny" --no-nlp-detect
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
WIKTIONARY_SENSES_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "layers", "senses_wiktionary.json")
EN_50K_PATH = os.path.join(PROJECT_ROOT, "Data", "English", "en_50k_wordlist.txt")

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


def load_en_50k(path):
    """Load the English 50k frequency wordlist (word count format)."""
    words = set()
    if not os.path.exists(path):
        return words
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if parts:
                words.add(parts[0].lower())
    return words


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


# ---------------------------------------------------------------------------
# NLP detection: Wiktionary POS interjections
# ---------------------------------------------------------------------------

def load_wiktionary_interjections(path):
    """Words where EVERY sense in Wiktionary has pos=INTJ.

    Only flags pure-interjection words (e.g. 'ay', 'uy'). Words with mixed
    POS (e.g. 'ya' has INTJ + ADV) are NOT flagged — too many false positives.
    """
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        senses = json.load(f)
    intj_words = set()
    for wl_key, sense_list in senses.items():
        if not sense_list:
            continue
        # Handle both old (list) and new (dict-of-IDs) format
        if isinstance(sense_list, dict):
            entries = sense_list.values()
        else:
            entries = sense_list
        poses = {s.get("pos", "") for s in entries}
        if poses and poses <= {"INTJ"}:
            word = wl_key.split("|")[0]
            intj_words.add(word.lower())
    return intj_words


# ---------------------------------------------------------------------------
# NLP detection: regex interjection patterns
# (ported from 4_detect_proper_nouns.py)
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


def detect_interjections(words, known_interjections):
    """Detect interjections using regex patterns + shared list."""
    detected = set()
    for w in words:
        w_stripped = w.replace("'", "")
        if w in known_interjections:
            detected.add(w)
            continue
        if len(w_stripped) < 2 or len(w_stripped) > 15:
            continue
        if w_stripped in _INTERJECTION_EXCEPTIONS:
            continue
        # Triple-repeated single character
        if len(w_stripped) >= 3 and len(set(w_stripped)) == 1:
            detected.add(w)
            continue
        # Triple-repeated letter anywhere
        if re.search(r'(.)\1\1', w_stripped):
            detected.add(w)
            continue
        for pat in _INTERJECTION_PATTERNS:
            if pat.match(w_stripped):
                detected.add(w)
                break
    return detected


# ---------------------------------------------------------------------------
# NLP detection: proper nouns — capitalization ratio
# ---------------------------------------------------------------------------

def detect_propn_by_capitalization(words, word_entries, min_count=5, min_ratio=0.8):
    """Words capitalized mid-line at a high ratio are likely proper nouns."""
    cap_counts = {}
    total_counts = {}

    for w in words:
        entry = word_entries.get(w)
        if not entry:
            continue
        for ex in entry.get("examples", []):
            line = ex.get("line", "")
            line_words = line.split()
            for i, token in enumerate(line_words):
                clean = re.sub(r"[^\w'\-áéíóúñü]", "", token)
                if not clean or len(clean) < 2:
                    continue
                lower = clean.lower()
                if lower not in words:
                    continue
                total_counts[lower] = total_counts.get(lower, 0) + 1
                if i > 0 and clean[0].isupper():
                    cap_counts[lower] = cap_counts.get(lower, 0) + 1

    detected = set()
    for w, cc in cap_counts.items():
        total = total_counts.get(w, 1)
        if cc >= min_count and cc / total >= min_ratio:
            detected.add(w)

    return detected


# ---------------------------------------------------------------------------
# NLP detection: proper nouns — spaCy NER
# ---------------------------------------------------------------------------

def detect_propn_by_spacy(words, word_entries):
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

    print("  Running spaCy NER on %d words..." % len(words))
    detected = set()
    start = time.time()
    for w in words:
        entry = word_entries.get(w)
        if not entry:
            continue
        # Use first example line longer than 10 chars
        line = w
        for ex in entry.get("examples", []):
            l = ex.get("line", "")
            if len(l) > 10:
                line = l
                break
        doc = nlp(line)
        for ent in doc.ents:
            if ent.text.lower() == w and ent.label_ in ("PER", "LOC", "ORG"):
                detected.add(w)
                break
    print("  spaCy found %d entities in %.1fs" % (len(detected), time.time() - start))
    return detected


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
    parser.add_argument(
        "--no-spacy", action="store_true",
        help="Skip spaCy NER proper noun detection (faster)"
    )
    parser.add_argument(
        "--no-nlp-detect", action="store_true",
        help="Skip all NLP detection filters (old behavior)"
    )
    parser.add_argument(
        "--min-cap-count", type=int, default=5,
        help="Min mid-line capitalized occurrences for proper noun detection (default: 5)"
    )
    parser.add_argument(
        "--min-cap-ratio", type=float, default=0.8,
        help="Min capitalization ratio for proper noun detection (default: 0.8)"
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

    # Build word → entry lookup for NLP detection (needs examples)
    word_entries = {entry["word"].lower(): entry for entry in all_words}

    # Track what each filter catches (for output and logging)
    known_spanish = set()   # found in 50k / normal vocab / conjugations
    known_elision = set()   # elision whose canonical form is known
    known_shared = set()    # in shared curated lists
    english = set()         # high-confidence English (word-level)
    interjections_detected = set() # interjections (Wiktionary POS + regex)
    proper_nouns_detected = set()  # proper nouns (cap ratio + NER + curated)
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
    # Filter 6b: English 50k wordlist
    # ---------------------------------------------------------------
    # By this point all common Spanish words are gone, so overlap is
    # minimal. Words in this list that a learner would already know.
    print("Loading English 50k wordlist...")
    en_50k = load_en_50k(EN_50K_PATH)
    if en_50k:
        matched = remaining & en_50k
        english |= matched
        remaining -= matched
        print("  Removed %d words (English 50k wordlist)" % len(matched))
    else:
        print("  WARNING: %s not found, skipping" % EN_50K_PATH)

    # ---------------------------------------------------------------
    # NLP detection filters (new — skip with --no-nlp-detect)
    # ---------------------------------------------------------------
    if not args.no_nlp_detect:
        # Filter 6b: Wiktionary POS interjection check
        print("Loading Wiktionary POS for interjection detection...")
        wikt_intj = load_wiktionary_interjections(WIKTIONARY_SENSES_PATH)
        matched = remaining & wikt_intj
        interjections_detected |= matched
        remaining -= matched
        print("  Removed %d words (Wiktionary all-INTJ)" % len(matched))

        # Filter 6c: Regex interjection detection
        regex_intj = detect_interjections(remaining, interjections)
        interjections_detected |= regex_intj
        remaining -= regex_intj
        print("  Removed %d words (interjection regex patterns)" % len(regex_intj))

        # Filter 6d: Proper noun detection — capitalization ratio + curated
        print("Running proper noun detection (capitalization + curated)...")
        known_propn = frozenset(w.lower() for w in load_shared_list("known_proper_nouns.json"))
        not_propn = frozenset(w.lower() for w in load_shared_list("not_proper_nouns.json"))

        cap_propn = detect_propn_by_capitalization(
            remaining, word_entries, args.min_cap_count, args.min_cap_ratio)
        curated_propn = known_propn & remaining
        all_propn = (cap_propn | curated_propn) - not_propn - interjections
        proper_nouns_detected |= (all_propn & remaining)
        remaining -= proper_nouns_detected
        print("  Removed %d words (capitalization %d + curated %d, after exclusions)" % (
            len(proper_nouns_detected), len(cap_propn & remaining | cap_propn & proper_nouns_detected),
            len(curated_propn)))

        # Filter 6e: spaCy NER proper nouns
        if not args.no_spacy:
            spacy_propn = detect_propn_by_spacy(remaining, word_entries)
            spacy_propn -= not_propn
            spacy_new = spacy_propn & remaining
            proper_nouns_detected |= spacy_new
            remaining -= spacy_new
            print("  Removed %d additional words (spaCy NER)" % len(spacy_new))
    else:
        print("Skipping NLP detection filters (--no-nlp-detect)")

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
    total_skipped = (len(known_spanish) + len(known_elision) + len(known_shared) +
                     len(english) + len(interjections_detected) +
                     len(proper_nouns_detected) + len(low_frequency))

    print("\n=== Filter Summary ===")
    print("  Input words:          %d" % len(artist_words))
    print("  Known Spanish:        %d (normal vocab + es_50k + conjugations)" % len(known_spanish))
    print("  Known elisions:       %d (canonical form in wordlists)" % len(known_elision))
    print("  Shared curated lists: %d" % len(known_shared))
    print("  English (all):        %d (lingua + wordlist)" % len(english))
    print("  Interjections (NLP):  %d (Wiktionary POS + regex)" % len(interjections_detected))
    print("  Proper nouns (NLP):   %d (capitalization + NER + curated)" % len(proper_nouns_detected))
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
        "interjections_detected": sorted(interjections_detected),
        "proper_nouns_detected": sorted(proper_nouns_detected),
        "low_frequency": sorted(low_frequency),
        "remaining": sorted(remaining, key=lambda w: word_freq.get(w, 0), reverse=True),
        "stats": {
            "input_words": len(artist_words),
            "known_spanish": len(known_spanish),
            "known_elision": len(known_elision),
            "known_shared": len(known_shared),
            "english": len(english),
            "interjections_detected": len(interjections_detected),
            "proper_nouns_detected": len(proper_nouns_detected),
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
