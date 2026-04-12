#!/usr/bin/env python3
"""
Step 4: Classify artist vocabulary for sense-mapping method selection.

All words appear in the artist deck — this step determines which method
assigns senses to each word (bi-encoder vs Gemini). Runs in six phases:

  Phase 1: Junk detection (interjections + proper nouns) on full set
  Phase 2: Known vocabulary (normal-mode vocab + conjugation + elision)
  Phase 3: English detection (50k wordlist + lingua)
  Phase 4: Wiktionary reclassification (English tiebreaker for known-vocab)
  Phase 5: spaCy NER (slow, on remaining only)
  Phase 6: Frequency threshold

The remaining words — mostly Caribbean/regional slang — go to Gemini
in step 6. All other words get bi-encoder sense mapping via
match_artist_senses.py.

Reads:  <artist-dir>/data/elision_merge/vocab_evidence_merged.json
        Data/Spanish/vocabulary.json
        Data/Spanish/layers/conjugation_reverse.json
        Data/Spanish/layers/senses_wiktionary.json
        Data/Spanish/corpora/wiktionary/kaikki-spanish.jsonl.gz
        Data/English/en_50k_wordlist.txt
        Artists/curations/*.json
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
CONJ_REVERSE_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "layers", "conjugation_reverse.json")
ELISION_MAPPING_PATH = os.path.join(SHARED_DIR, "elision_mapping.json")
WIKTIONARY_SENSES_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "layers", "senses_wiktionary.json")
WIKTIONARY_RAW_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "corpora", "wiktionary", "kaikki-spanish.jsonl.gz")
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


def load_wiktionary_raw(path):
    """Load raw Wiktionary JSONL.

    Returns (word_set, all_propn, clitic_map, verbs_with_refl_senses):
      word_set: all lowercase word forms that have any entry.
      all_propn: words where EVERY entry has pos="name" (proper nouns).
      clitic_map: {clitic_word: (base_verb, clitics, is_reflexive)} for
                  form-of entries with clitic pronouns ("combined with").
      verbs_with_refl_senses: set of base verbs that have at least one
                              non-form-of sense tagged 'reflexive' or 'pronominal'.
    """
    import gzip
    from collections import defaultdict
    word_poses = defaultdict(set)  # word -> set of raw POS values
    clitic_map = {}  # clitic_word -> (base_verb, [clitics], is_reflexive)
    verbs_with_refl_senses = set()
    if not os.path.exists(path):
        return set(), set(), {}, set()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            w = entry.get("word", "")
            if not w:
                continue
            wl = w.lower()
            raw_pos = entry.get("pos", "")
            word_poses[wl].add(raw_pos)
            for s in entry.get("senses", []):
                tags = set(s.get("tags", []))
                # Collect verbs with reflexive/pronominal senses
                if raw_pos == "verb" and "form-of" not in tags:
                    if "reflexive" in tags or "pronominal" in tags:
                        verbs_with_refl_senses.add(wl)
                # Collect clitic form-of entries
                if "form-of" in tags:
                    gloss = (s.get("glosses") or [""])[0]
                    if "combined with" in gloss:
                        links = s.get("links", [])
                        if links and isinstance(links[0], list):
                            base = links[0][0].lower()
                            clitics = [l[0].lower() for l in links[1:]
                                       if isinstance(l, list)]
                            is_refl = "reflexive" in tags or "se" in clitics
                            if base and base != wl:
                                clitic_map[wl] = (base, clitics, is_refl)
    words = set(word_poses.keys())
    all_propn = {w for w, poses in word_poses.items()
                 if poses and poses <= {"name"}}
    return words, all_propn, clitic_map, verbs_with_refl_senses


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
    known_normal_vocab = set()  # in normal-mode deck
    known_conjugation = set()   # known verb inflection
    known_elision = set()       # elision whose canonical form is known
    known_shared = set()        # in shared curated lists
    english = set()             # English (wordlist + lingua + reclassified)
    interjections_detected = set()  # interjections (Wiktionary POS + regex + curated)
    proper_nouns_detected = set()   # proper nouns (cap ratio + NER + curated)
    low_frequency = set()       # below min-freq threshold

    remaining = set(artist_words)

    # Pre-compute elision candidates (checked after wordlists load)
    elision_candidates = {}  # word -> set of canonical forms
    for w in remaining:
        candidates = elision_canonical(w)
        if candidates:
            elision_candidates[w] = candidates

    # ===================================================================
    # Load all wordlists and detection resources upfront
    # ===================================================================
    print("Loading wordlists and detection resources...")

    # Normal mode vocabulary
    if os.path.exists(NORMAL_VOCAB_PATH):
        normal_words = load_normal_vocab(NORMAL_VOCAB_PATH)
        print("  Normal vocab: %d word forms" % len(normal_words))
    else:
        normal_words = set()
        print("  WARNING: %s not found" % NORMAL_VOCAB_PATH)

    # Conjugation reverse lookup
    if os.path.exists(CONJ_REVERSE_PATH):
        conj_forms = load_conjugation_forms(CONJ_REVERSE_PATH)
        print("  Conjugation forms: %d" % len(conj_forms))
    else:
        conj_forms = set()
        print("  WARNING: %s not found" % CONJ_REVERSE_PATH)

    # English 50k wordlist
    en_50k = load_en_50k(EN_50K_PATH)
    if en_50k:
        print("  English 50k: %d words" % len(en_50k))
    else:
        print("  WARNING: %s not found" % EN_50K_PATH)

    # Shared curated lists
    proper_nouns_curated = frozenset(w.lower() for w in load_shared_list("proper_nouns.json"))
    interjections_curated = frozenset(w.lower() for w in load_shared_list("interjections.json"))
    extra_english = frozenset(w.lower() for w in load_shared_list("extra_english.json"))
    shared_all = proper_nouns_curated | interjections_curated | extra_english
    print("  Curated: %d proper nouns, %d interjections, %d English" %
          (len(proper_nouns_curated), len(interjections_curated), len(extra_english)))

    # Curated proper noun allow/deny lists
    known_propn = frozenset(w.lower() for w in load_shared_list("known_proper_nouns.json"))
    not_propn = frozenset(w.lower() for w in load_shared_list("not_proper_nouns.json"))

    # Wiktionary POS interjections (words where ALL senses = INTJ)
    wikt_intj = set()
    if not args.no_nlp_detect:
        wikt_intj = load_wiktionary_interjections(WIKTIONARY_SENSES_PATH)
        print("  Wiktionary all-INTJ: %d words" % len(wikt_intj))

    # Raw Wiktionary (word set + POS-based proper noun detection + clitic data)
    print("  Loading raw Wiktionary...")
    wikt_spanish, wikt_propn, wikt_clitic_map, wikt_refl_verbs = load_wiktionary_raw(WIKTIONARY_RAW_PATH)
    print("  Raw Wiktionary: %d word forms, %d all-PROPN, %d clitic forms, %d verbs with reflexive senses" %
          (len(wikt_spanish), len(wikt_propn), len(wikt_clitic_map), len(wikt_refl_verbs)))

    # ===================================================================
    # Clitic detection: identify verb+clitic forms for merging into base verb
    # Three tiers based on Wiktionary data:
    #   Tier 1+2 (clitic_merge): non-reflexive clitics OR reflexive where
    #            base verb has no reflexive-tagged senses → merge into base
    #   Tier 3: reflexive where base verb HAS reflexive senses → keep separate
    #           (these get their own Wiktionary index entries via build_senses.py)
    # ===================================================================
    clitic_merge = {}  # word -> base_verb (tier 1+2, will be merged)
    clitic_keep = set()  # tier 3, kept as separate entries
    for w in artist_words:
        if w not in wikt_clitic_map:
            continue
        base, clitics, is_refl = wikt_clitic_map[w]
        if is_refl and base in wikt_refl_verbs:
            clitic_keep.add(w)  # tier 3: meaning-shifting reflexive
        else:
            clitic_merge[w] = base  # tier 1+2: safe to merge
    if clitic_merge or clitic_keep:
        print("\n--- Clitic detection ---")
        print("  Tier 1+2 (merge into base verb): %d" % len(clitic_merge))
        print("  Tier 3 (keep separate, reflexive): %d" % len(clitic_keep))

    # ===================================================================
    # Phase 1: JUNK DETECTION (full word set, fast detectors)
    # Interjections and proper nouns have no Spanish ambiguity —
    # "mmm" is always an interjection, "LeBron" is always a name.
    # ===================================================================
    print("\n--- Phase 1: Junk detection (full set) ---")

    if not args.no_nlp_detect:
        # 1a. Curated interjections
        matched = remaining & interjections_curated
        interjections_detected |= matched
        remaining -= matched
        print("  Curated interjections: %d" % len(matched))

        # 1b. Wiktionary POS interjections (all senses = INTJ)
        matched = remaining & wikt_intj
        interjections_detected |= matched
        remaining -= matched
        print("  Wiktionary all-INTJ: %d" % len(matched))

        # 1c. Regex interjection patterns
        regex_intj = detect_interjections(remaining, interjections_curated)
        interjections_detected |= regex_intj
        remaining -= regex_intj
        print("  Interjection regex: %d" % len(regex_intj))

        # 1d. Wiktionary POS proper nouns (all senses = name)
        matched = (remaining & wikt_propn) - not_propn
        proper_nouns_detected |= matched
        remaining -= matched
        print("  Wiktionary all-PROPN: %d" % len(matched))

        # 1e. Curated proper nouns
        curated_propn = (known_propn & remaining) - not_propn - interjections_curated
        proper_nouns_detected |= curated_propn
        remaining -= curated_propn
        print("  Curated proper nouns: %d" % len(curated_propn))

        # 1f. Capitalization-ratio proper nouns
        cap_propn = detect_propn_by_capitalization(
            remaining, word_entries, args.min_cap_count, args.min_cap_ratio)
        cap_new = (cap_propn - not_propn - interjections_curated) & remaining
        proper_nouns_detected |= cap_new
        remaining -= cap_new
        print("  Capitalization proper nouns: %d" % len(cap_new))

    print("  Total junk: %d interjections, %d proper nouns" %
          (len(interjections_detected), len(proper_nouns_detected)))

    # ===================================================================
    # Phase 2: KNOWN VOCABULARY (on remaining after junk removal)
    # ===================================================================
    print("\n--- Phase 2: Known vocabulary ---")

    # 2a. Normal-mode vocab
    matched = remaining & normal_words
    known_normal_vocab |= matched
    remaining -= matched
    print("  Normal-mode vocab: %d" % len(matched))

    # 2b. Conjugation reverse lookup
    matched = remaining & conj_forms
    known_conjugation |= matched
    remaining -= matched
    print("  Conjugation forms: %d" % len(matched))

    # 2c. Elision resolution (canonical forms against known wordlists)
    all_known = normal_words | conj_forms
    for w in list(remaining):
        if w in elision_candidates:
            for candidate in elision_candidates[w]:
                if candidate.lower() in all_known:
                    known_elision.add(w)
                    remaining.discard(w)
                    break

    # Load skip forms from step 3's elision mapping — non-s-elision
    # forms that step 3 identified but chose not to merge.
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

    print("  Elisions: %d" % len(known_elision))

    # 2d. Shared curated lists
    matched = remaining & shared_all
    known_shared |= matched
    remaining -= matched
    print("  Shared curated: %d" % len(matched))

    # ===================================================================
    # Phase 3: ENGLISH DETECTION (on remaining after known vocab)
    # ===================================================================
    print("\n--- Phase 3: English detection ---")

    # 3a. English 50k wordlist (fast)
    if en_50k:
        matched = remaining & en_50k
        english |= matched
        remaining -= matched
        print("  English 50k wordlist: %d" % len(matched))

    # 3b. Lingua classifier (slow — benefits from reduced set)
    if not args.no_lingua:
        print("  Running lingua (threshold=%.2f)..." % args.lingua_threshold)
        lingua_english = classify_english(remaining, threshold=args.lingua_threshold)
        english |= lingua_english
        remaining -= lingua_english
        print("  Lingua English: %d" % len(lingua_english))
    else:
        print("  Skipping lingua (--no-lingua)")

    # ===================================================================
    # Phase 4: WIKTIONARY RECLASSIFICATION (on known-vocab words)
    # English tiebreaker: word in English 50k AND not in Spanish Wiktionary.
    # Interjections/proper nouns already caught in Phase 1.
    # ===================================================================
    print("\n--- Phase 4: Wiktionary reclassification ---")
    reclass_pool = known_normal_vocab | known_conjugation
    reclass_english = set()
    for w in reclass_pool:
        if w in en_50k and w.lower() not in wikt_spanish:
            reclass_english.add(w)
    english |= reclass_english
    known_normal_vocab -= reclass_english
    known_conjugation -= reclass_english
    print("  Reclassified %d known-vocab → english (in en_50k, not in Wiktionary)" %
          len(reclass_english))

    # ===================================================================
    # Phase 5: spaCy NER (slow — on remaining only)
    # ===================================================================
    if not args.no_nlp_detect and not args.no_spacy:
        print("\n--- Phase 5: spaCy NER ---")
        spacy_propn = detect_propn_by_spacy(remaining, word_entries)
        spacy_propn -= not_propn
        spacy_new = spacy_propn & remaining
        proper_nouns_detected |= spacy_new
        remaining -= spacy_new
        print("  spaCy NER: %d additional proper nouns" % len(spacy_new))

    # ===================================================================
    # Phase 6: FREQUENCY THRESHOLD
    # ===================================================================
    print("\nApplying frequency threshold (min_freq=%d)..." % args.min_freq)
    for w in list(remaining):
        if word_freq.get(w, 0) < args.min_freq:
            low_frequency.add(w)
            remaining.discard(w)
    print("  Removed %d words (freq < %d)" % (len(low_frequency), args.min_freq))

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    elapsed = time.time() - start_time
    total_known_vocab = len(known_normal_vocab) + len(known_conjugation)
    total_skipped = (total_known_vocab + len(known_elision) + len(known_shared) +
                     len(english) + len(interjections_detected) +
                     len(proper_nouns_detected) + len(low_frequency))

    print("\n=== Filter Summary ===")
    print("  Input words:          %d" % len(artist_words))
    print("  Known normal vocab:   %d" % len(known_normal_vocab))
    print("  Known conjugation:    %d" % len(known_conjugation))
    print("  Known elisions:       %d" % len(known_elision))
    print("  Shared curated lists: %d" % len(known_shared))
    print("  English (all):        %d (en_50k + lingua + reclassified)" % len(english))
    print("  Interjections:        %d (curated + Wiktionary POS + regex)" % len(interjections_detected))
    print("  Proper nouns:         %d (curated + capitalization + NER)" % len(proper_nouns_detected))
    print("  Low frequency:        %d (freq < %d)" % (len(low_frequency), args.min_freq))
    print("  ---")
    print("  Total skipped:        %d (%.0f%%)" % (total_skipped, total_skipped * 100 / len(artist_words)))
    print("  Remaining for Gemini: %d" % len(remaining))
    print("  Time: %.1f seconds" % elapsed)

    # ---------------------------------------------------------------
    # Write output
    # ---------------------------------------------------------------
    output = {
        "known_normal_vocab": sorted(known_normal_vocab),
        "known_conjugation": sorted(known_conjugation),
        "known_elision": sorted(known_elision),
        "known_shared": sorted(known_shared),
        "english": sorted(english),
        "interjections_detected": sorted(interjections_detected),
        "proper_nouns_detected": sorted(proper_nouns_detected),
        "low_frequency": sorted(low_frequency),
        "remaining": sorted(remaining, key=lambda w: word_freq.get(w, 0), reverse=True),
        "clitic_merge": clitic_merge,  # word -> base_verb (tier 1+2)
        "stats": {
            "input_words": len(artist_words),
            "known_normal_vocab": len(known_normal_vocab),
            "known_conjugation": len(known_conjugation),
            "known_elision": len(known_elision),
            "known_shared": len(known_shared),
            "english": len(english),
            "interjections_detected": len(interjections_detected),
            "proper_nouns_detected": len(proper_nouns_detected),
            "low_frequency": len(low_frequency),
            "clitic_merge": len(clitic_merge),
            "clitic_keep": len(clitic_keep),
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
