#!/usr/bin/env python3
"""
Step 4: Classify artist vocabulary for sense-mapping method selection.

All words appear in the artist deck — this step determines which method
assigns senses to each word (bi-encoder vs Gemini). Runs in seven phases:

  Phase 1: Junk detection (interjections + proper nouns) on full set
  Phase 2: Known vocabulary (normal-mode vocab + conjugation + elision)
  Phase 2.5: Transparent-cognate skip (Sp Wikt ∩ en_50k with cognate voters)
  Phase 3: English detection (50k wordlist - Spanish Wiktionary + lingua)
  Phase 4: Wiktionary reclassification (English tiebreaker for known-vocab)
  Phase 5: spaCy NER (slow, on remaining only)
  Phase 6: Frequency threshold + residual clitic fallback

The remaining words — mostly Caribbean/regional slang — go to Gemini
in step 6. All other words get local sense assignment via
step_6b_assign_senses_local.py.

Reads:  <artist-dir>/data/elision_merge/vocab_evidence_merged.json
        Data/Spanish/vocabulary.json
        Data/Spanish/layers/conjugation_reverse.json
        Data/Spanish/layers/sense_menu.json
        Data/Spanish/Senses/wiktionary/kaikki-spanish.jsonl.gz
        Data/English/en_50k_wordlist.txt
        Artists/curations/*.json
Writes: <artist-dir>/data/known_vocab/word_routing.json
        <artist-dir>/data/known_vocab/word_routing_debug.json

Usage (from project root):
    .venv/bin/python3 pipeline/artist/step_4a_filter_known_vocab.py --artist-dir "Artists/Bad Bunny"
    .venv/bin/python3 pipeline/artist/step_4a_filter_known_vocab.py --artist-dir "Artists/Rosalía" --min-freq 2
    .venv/bin/python3 pipeline/artist/step_4a_filter_known_vocab.py --artist-dir "Artists/Bad Bunny" --no-lingua
    .venv/bin/python3 pipeline/artist/step_4a_filter_known_vocab.py --artist-dir "Artists/Bad Bunny" --no-nlp-detect
"""

import gzip
import json
import os
import re
import sys
import argparse
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pipeline.util_pipeline_meta import make_meta  # noqa: E402
from pipeline.util_4a_routing import (  # noqa: E402
    classify_clitics,
    load_wiktionary_clitic_data,
    resolve_derivation,
    strip_clitic_pronouns,
)

# Bump when routing categories, detection phases, or output schema change.
STEP_VERSION = 2
STEP_VERSION_NOTES = {
    1: "6 phases: junk → known_vocab → english → wiktionary → NER → freq+derivation",
    2: "+ cognate Phase 2.5, Wiktionary safety-nets on propn/english, residual clitic fallback, disjoint-bucket assertion, debug dump",
}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util_1a_artist_config import add_artist_arg, load_shared_list, SHARED_DIR

# Shared cognate scorer (suffix rules + CogNet + phonetic normalization)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "shared"))
from flag_cognates import cognate_score, normalize, split_english_glosses, _load_cognet  # noqa: E402

# Paths relative to project root (derived from this file's location)
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
ARTISTS_DIR = os.path.dirname(SCRIPTS_DIR)
PROJECT_ROOT = os.path.dirname(ARTISTS_DIR)

NORMAL_VOCAB_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "vocabulary.json")
CONJ_REVERSE_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "layers", "conjugation_reverse.json")
ELISION_MAPPING_PATH = os.path.join(SHARED_DIR, "elision_mapping.json")
WIKTIONARY_SENSES_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "layers", "sense_menu.json")
WIKTIONARY_RAW_PATH = os.path.join(PROJECT_ROOT, "Data", "Spanish", "Senses", "wiktionary", "kaikki-spanish.jsonl.gz")
EN_50K_PATH = os.path.join(PROJECT_ROOT, "Data", "English", "en_50k_wordlist.txt")

# D-elision regexes: backup for when step 3 can't merge plural/feminine variants.
# Step 3 is now responsible for merging -a'o/-a'a/-a'os/-a'as/-í'o/-í'a/-í'os/-í'as.
# These stay here as a safety-net for when step 3 is bypassed.
_D_ELISION_PATTERNS = [
    (re.compile(r"^(.+)a'o$"), "ado"),
    (re.compile(r"^(.+)a'a$"), "ada"),
    (re.compile(r"^(.+)a'os$"), "ados"),
    (re.compile(r"^(.+)a'as$"), "adas"),
    (re.compile(r"^(.+)í'o$"), "ido"),
    (re.compile(r"^(.+)í'a$"), "ida"),
    (re.compile(r"^(.+)í'os$"), "idos"),
    (re.compile(r"^(.+)í'as$"), "idas"),
]

# Clitic pronouns used by the residual fallback (Phase 6 sweep). Longest-first.
_CLITIC_PRONOUNS = ("nos", "les", "los", "las", "me", "te", "se", "lo", "la", "le")


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
        candidates.add(stem)
        candidates.add(stem + "s")
        candidates.add(stem + "d")
        candidates.add(stem + "z")
        candidates.add(stem + "r")

    # D-elision variants: backup for step 3 misses + feminine/plural forms
    for pattern, suffix in _D_ELISION_PATTERNS:
        m = pattern.match(word)
        if m:
            candidates.add(m.group(1) + suffix)

    # Apostrophe in middle: common contractions
    if "'" in word and not word.endswith("'"):
        parts = word.split("'")
        if len(parts) == 2:
            prefix_expansions = {"pa": "para", "po": "por", "to": "todo"}
            expanded = prefix_expansions.get(parts[0])
            if expanded:
                candidates.add(expanded)
                candidates.add(parts[1])
                suffix_expansions = {"l": "el"}
                suffix_exp = suffix_expansions.get(parts[1])
                if suffix_exp:
                    candidates.add(suffix_exp)

    # Common known mappings for very frequent forms
    known = {
        "pa'": "para", "pa": "para", "na'": "nada", "to'": "todo", "to": "todo",
        "tá": "está", "tás": "estás", "toy": "estoy", "tamos": "estamos",
        "vamo": "vamos", "vo'a": "voy", "pa'l": "para", "to'a": "toda",
        "to'as": "todas", "to's": "todos", "toas": "todas", "tó": "todo",
        "to'ito": "todito", "ma'i": "mami", "oí'te": "oíste", "de'o": "dedo",
        "a'o": "ado", "dies'": "diez", "ná'": "nada", "pá'": "para", "tó'": "todo",
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
    """Words where EVERY sense in Wiktionary has pos=INTJ."""
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        senses = json.load(f)
    intj_words = set()
    for wl_key, sense_list in senses.items():
        if not sense_list:
            continue
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
# Cognate Phase 2.5 helpers
# ---------------------------------------------------------------------------

def load_wikt_english_glosses(path):
    """Return {word: [english_gloss_string, ...]} from raw Wiktionary JSONL.

    Loads full per-sense glosses so the cognate voters can score each one.
    """
    glosses = {}
    if not os.path.exists(path):
        return glosses
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            w = entry.get("word", "")
            if not w:
                continue
            wl = w.lower()
            for s in entry.get("senses", []):
                for g in (s.get("glosses") or []):
                    if g:
                        glosses.setdefault(wl, []).append(g)
    return glosses


def cognate_voters(word, wikt_glosses, cognet):
    """Return a dict of voter names → True for every cognate signal that fires.

    Voters (most to least confident):
      identical_gloss — word appears verbatim in one of its own Sp Wikt English glosses
      suffix_rule     — cognate_score() ≥ 0.9 on any gloss token
      cognet          — normalize(word) is a key in the CogNet spa→eng map

    Empty dict means "no cognate signal" (so the word is NOT transparent).
    """
    voters = {}
    wn = normalize(word)

    if cognet and wn in cognet:
        voters["cognet"] = True

    glosses = wikt_glosses.get(word, [])
    if glosses:
        # Collect all gloss tokens / phrases once
        gloss_tokens = set()
        for g in glosses:
            for part in split_english_glosses(g):
                gloss_tokens.add(part)
                for tok in part.split():
                    gloss_tokens.add(tok)

        # identical_gloss: same normalized form appears in the glosses
        if any(normalize(t) == wn for t in gloss_tokens):
            voters["identical_gloss"] = True

        # suffix_rule: cognate score ≥ 0.9 with any gloss token
        best = 0.0
        for t in gloss_tokens:
            score = cognate_score(word, t)
            if score > best:
                best = score
                if best >= 1.0:
                    break
        if best >= 0.9:
            voters["suffix_rule"] = True
            voters["_best_score"] = round(best, 3)

    return voters


# ---------------------------------------------------------------------------
# NLP detection: regex interjection patterns
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


# ---------------------------------------------------------------------------
# Curated proper-noun loader with conflict detection
# ---------------------------------------------------------------------------

def _maybe_load(name):
    """load_shared_list that tolerates a missing file (returns [])."""
    try:
        return load_shared_list(name)
    except FileNotFoundError:
        return []


def load_propn_curations():
    """Load drop/allow proper-noun lists with back-compat for legacy filenames.

    Preferred filenames:
      drop_proper_nouns.json   — words to EXCLUDE from the deck (proper nouns)
      allow_proper_nouns.json  — words detectors must NOT flag as proper nouns
    Legacy (still supported):
      known_proper_nouns.json  → drop
      proper_nouns.json        → drop (merged)
      not_proper_nouns.json    → allow

    Logs any conflict (word present in both drop and allow lists).
    """
    drop = set()
    for fn in ("drop_proper_nouns.json", "known_proper_nouns.json", "proper_nouns.json"):
        for w in _maybe_load(fn):
            drop.add(w.lower())

    allow = set()
    for fn in ("allow_proper_nouns.json", "not_proper_nouns.json"):
        for w in _maybe_load(fn):
            allow.add(w.lower())

    conflicts = drop & allow
    if conflicts:
        print("  [WARN] %d conflicting entries in drop/allow propn lists — allow wins: %s"
              % (len(conflicts), sorted(conflicts)[:20]))
    # Allow wins (subtracted from drop to avoid confusion downstream)
    drop -= allow
    return drop, allow


# ---------------------------------------------------------------------------
# Residual clitic fallback: second pass on gemini-bound words
# ---------------------------------------------------------------------------

_ACUTE_STRIP = str.maketrans({"á":"a","é":"e","í":"i","ó":"o","ú":"u","Á":"A","É":"E","Í":"I","Ó":"O","Ú":"U"})


def residual_clitic_fallback(candidates, known_word_set):
    """For each candidate word, try to strip trailing clitic pronouns and look
    up the base in the known-word set. Returns {word: base} for hits.

    Catches verb+clitic forms that Wiktionary's "combined with" entries miss
    (ponme, llévame, perdóname, mirarte, hacerlo, córtala, …).
    """
    found = {}
    for w in candidates:
        if len(w) < 5:
            continue
        base_lookups = []
        # Up to two clitic pronouns (haciéndomelo)
        remaining = w
        for _ in range(2):
            matched = False
            for cl in _CLITIC_PRONOUNS:
                if remaining.endswith(cl) and len(remaining) > len(cl) + 2:
                    stripped = remaining[:-len(cl)]
                    # Try with and without acute accents
                    base_lookups.append(stripped)
                    base_lookups.append(stripped.translate(_ACUTE_STRIP))
                    remaining = stripped
                    matched = True
                    break
            if not matched:
                break
        if not base_lookups:
            continue
        for base in base_lookups:
            if base in known_word_set:
                found[w] = base
                break
    return found


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Step 4: Classify artist vocabulary for sense-mapping routing"
    )
    add_artist_arg(parser)
    parser.add_argument("--min-freq", type=int, default=2,
        help="Minimum corpus frequency to keep (default: 2, i.e. cut hapax legomena)")
    parser.add_argument("--lingua-threshold", type=float, default=0.90,
        help="Confidence threshold for English classification (default: 0.90)")
    parser.add_argument("--no-lingua", action="store_true",
        help="Skip lingua English detection (faster, keeps some English words)")
    parser.add_argument("--no-spacy", action="store_true",
        help="Skip spaCy NER proper noun detection (faster)")
    parser.add_argument("--no-nlp-detect", action="store_true",
        help="Skip all NLP detection filters (old behavior)")
    parser.add_argument("--no-cognate", action="store_true",
        help="Skip Phase 2.5 cognate-skip layer (keeps cognates in the deck)")
    parser.add_argument("--min-cap-count", type=int, default=5,
        help="Min mid-line capitalized occurrences for proper noun detection (default: 5)")
    parser.add_argument("--min-cap-ratio", type=float, default=0.8,
        help="Min capitalization ratio for proper noun detection (default: 0.8)")
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    input_path = os.path.join(artist_dir, "data", "elision_merge", "vocab_evidence_merged.json")
    output_dir = os.path.join(artist_dir, "data", "known_vocab")
    output_path = os.path.join(output_dir, "word_routing.json")
    debug_path = os.path.join(output_dir, "word_routing_debug.json")
    os.makedirs(output_dir, exist_ok=True)

    start_time = time.time()

    # Load artist vocabulary
    print("Loading %s..." % input_path)
    with open(input_path, "r", encoding="utf-8") as f:
        all_words = json.load(f)
    word_freq = {entry["word"].lower(): entry.get("corpus_count", 0) for entry in all_words}
    artist_words = set(word_freq.keys())
    print("  %d words loaded" % len(artist_words))

    word_entries = {entry["word"].lower(): entry for entry in all_words}

    # Bucket tracking
    known_normal_vocab = set()
    known_conjugation = set()
    known_elision = set()
    known_shared = set()
    english = set()
    cognates = {}  # word -> voter dict (from Phase 2.5)
    interjections_detected = set()
    proper_nouns_detected = set()
    low_frequency = set()
    # debug trail: word -> dict of per-phase signals
    debug_trail = {w: {} for w in artist_words}

    remaining = set(artist_words)

    # Pre-compute elision candidates
    elision_candidates = {}
    for w in remaining:
        candidates = elision_canonical(w)
        if candidates:
            elision_candidates[w] = candidates

    # ==================================================================
    # Load all wordlists and detection resources
    # ==================================================================
    print("Loading wordlists and detection resources...")

    if os.path.exists(NORMAL_VOCAB_PATH):
        normal_words = load_normal_vocab(NORMAL_VOCAB_PATH)
        print("  Normal vocab: %d word forms" % len(normal_words))
    else:
        normal_words = set()
        print("  WARNING: %s not found" % NORMAL_VOCAB_PATH)

    if os.path.exists(CONJ_REVERSE_PATH):
        conj_forms = load_conjugation_forms(CONJ_REVERSE_PATH)
        print("  Conjugation forms: %d" % len(conj_forms))
    else:
        conj_forms = set()
        print("  WARNING: %s not found" % CONJ_REVERSE_PATH)

    en_50k = load_en_50k(EN_50K_PATH)
    if en_50k:
        print("  English 50k: %d words" % len(en_50k))
    else:
        print("  WARNING: %s not found" % EN_50K_PATH)

    # Shared curated lists (shared bucket = keep in deck but bypass normal-vocab lookup)
    interjections_curated = frozenset(w.lower() for w in load_shared_list("interjections.json"))
    extra_english = frozenset(w.lower() for w in load_shared_list("extra_english.json"))

    # Proper-noun curations (drop = exclude; allow = don't flag)
    drop_propn, allow_propn = load_propn_curations()

    # always_teach: words that LOOK like cognates but should stay learnable
    always_teach = frozenset(w.lower() for w in _maybe_load("always_teach.json"))

    # always_skip_cognate: words obviously transparent that voters miss
    always_skip_cognate = frozenset(w.lower() for w in _maybe_load("always_skip_cognate.json"))

    # NOTE: extra_english routes to exclude.english (Phase 3a), not biencoder.shared.
    # Only genuinely-Spanish curated lists belong in `shared_all`.
    shared_all = frozenset()  # (reserved for future keep-in-deck curations)
    print("  Curated: %d drop-propn, %d allow-propn, %d interjections, %d extra-english, "
          "%d always-teach, %d always-skip-cognate" %
          (len(drop_propn), len(allow_propn), len(interjections_curated), len(extra_english),
           len(always_teach), len(always_skip_cognate)))

    # Wiktionary POS interjections (words where ALL senses = INTJ)
    wikt_intj = set()
    if not args.no_nlp_detect:
        wikt_intj = load_wiktionary_interjections(WIKTIONARY_SENSES_PATH)
        print("  Wiktionary all-INTJ: %d words" % len(wikt_intj))

    # Raw Wiktionary: word set + proper-noun set + clitic map + reflexive verbs
    print("  Loading raw Wiktionary...")
    wikt_spanish, wikt_propn, wikt_clitic_map, wikt_refl_verbs = load_wiktionary_clitic_data(WIKTIONARY_RAW_PATH)
    print("  Raw Wiktionary: %d word forms, %d all-PROPN, %d clitic forms, %d reflexive verbs" %
          (len(wikt_spanish), len(wikt_propn), len(wikt_clitic_map), len(wikt_refl_verbs)))

    # Wiktionary per-word POS (for safety-net checks)
    wikt_pos = {}  # word -> set of POS
    if os.path.exists(WIKTIONARY_RAW_PATH):
        with gzip.open(WIKTIONARY_RAW_PATH, "rt", encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                w = e.get("word", "").lower()
                if w:
                    wikt_pos.setdefault(w, set()).add(e.get("pos", "") or "")

    # Cognate-phase resources
    wikt_glosses = {}
    cognet = {}
    if not args.no_cognate:
        print("  Loading Wiktionary glosses (for cognate voters)...")
        wikt_glosses = load_wikt_english_glosses(WIKTIONARY_RAW_PATH)
        print("  Wiktionary gloss map: %d words" % len(wikt_glosses))
        cognet = _load_cognet()
        print("  CogNet: %d Sp→En entries" % len(cognet))

    # ==================================================================
    # Clitic detection (tier 1+2 merge, tier 3 keep, orphans)
    # ==================================================================
    gerund_clitic_all = normal_words | conj_forms | wikt_spanish
    clitic_merge, clitic_orphans, clitic_keep, gerund_clitic_added = classify_clitics(
        artist_words, wikt_clitic_map, wikt_refl_verbs, gerund_clitic_all,
    )

    if clitic_merge or clitic_keep:
        print("\n--- Clitic detection ---")
        print("  Tier 1+2 (merge into base verb): %d (%d to surface form, %d orphans to infinitive)"
              % (len(clitic_merge), len(clitic_merge) - len(clitic_orphans), len(clitic_orphans)))
        print("  Tier 3 (keep separate, reflexive): %d" % len(clitic_keep))
        if gerund_clitic_added:
            print("  Gerund+clitic (programmatic): %d" % gerund_clitic_added)

    # P4.1 FIX: clitic buckets are exclusive — subtract from `remaining` so these
    # words don't leak into english/propn/gemini downstream.
    remaining -= set(clitic_merge.keys())
    remaining -= clitic_keep
    for w in clitic_merge:
        debug_trail.setdefault(w, {})["clitic_merge"] = clitic_merge[w]
    for w in clitic_keep:
        debug_trail.setdefault(w, {})["clitic_keep"] = True

    # ==================================================================
    # Phase 1: JUNK DETECTION (interjections + proper nouns on full set)
    # ==================================================================
    print("\n--- Phase 1: Junk detection (full set) ---")

    if not args.no_nlp_detect:
        # 1a. Curated interjections
        matched = remaining & interjections_curated
        interjections_detected |= matched
        remaining -= matched
        for w in matched:
            debug_trail[w]["interjection_source"] = "curated"
        print("  Curated interjections: %d" % len(matched))

        # 1b. Wiktionary all-INTJ
        matched = remaining & wikt_intj
        interjections_detected |= matched
        remaining -= matched
        for w in matched:
            debug_trail[w]["interjection_source"] = "wikt_all_intj"
        print("  Wiktionary all-INTJ: %d" % len(matched))

        # 1c. Regex interjection patterns
        regex_intj = detect_interjections(remaining, interjections_curated)
        interjections_detected |= regex_intj
        remaining -= regex_intj
        for w in regex_intj:
            debug_trail[w]["interjection_source"] = "regex"
        print("  Interjection regex: %d" % len(regex_intj))

        # 1d. Wiktionary all-PROPN
        matched = (remaining & wikt_propn) - allow_propn
        proper_nouns_detected |= matched
        remaining -= matched
        for w in matched:
            debug_trail[w]["propn_source"] = "wikt_all_propn"
        print("  Wiktionary all-PROPN: %d" % len(matched))

        # 1e. Curated drop-propn
        curated_propn = (drop_propn & remaining) - allow_propn - interjections_curated
        proper_nouns_detected |= curated_propn
        remaining -= curated_propn
        for w in curated_propn:
            debug_trail[w]["propn_source"] = "curated_drop"
        print("  Curated drop proper nouns: %d" % len(curated_propn))

        # 1f. Capitalization-ratio propns — WITH Wiktionary safety-net (P2.1)
        cap_propn = detect_propn_by_capitalization(
            remaining, word_entries, args.min_cap_count, args.min_cap_ratio)
        # Safety-net: skip any cap-ratio hit that has a non-name POS in Wikt,
        # unless it's already in the curated drop list (overrides the net).
        wikt_safe = set()
        for w in cap_propn:
            if w in drop_propn:
                continue  # curated drop wins
            poses = wikt_pos.get(w, set())
            if poses and poses - {"name"}:
                wikt_safe.add(w)
        cap_propn -= wikt_safe
        cap_new = (cap_propn - allow_propn - interjections_curated) & remaining
        proper_nouns_detected |= cap_new
        remaining -= cap_new
        for w in cap_new:
            debug_trail[w]["propn_source"] = "cap_ratio"
        print("  Capitalization proper nouns: %d (%d filtered by Wikt safety-net)" %
              (len(cap_new), len(wikt_safe)))

    print("  Total junk: %d interjections, %d proper nouns" %
          (len(interjections_detected), len(proper_nouns_detected)))

    # ==================================================================
    # Phase 2: KNOWN VOCABULARY
    # ==================================================================
    print("\n--- Phase 2: Known vocabulary ---")

    # 2a. Normal-mode vocab
    matched = remaining & normal_words
    known_normal_vocab |= matched
    remaining -= matched
    for w in matched:
        debug_trail[w]["known_source"] = "normal_vocab"
    print("  Normal-mode vocab: %d" % len(matched))

    # 2b. Conjugation reverse lookup
    matched = remaining & conj_forms
    known_conjugation |= matched
    remaining -= matched
    for w in matched:
        debug_trail[w]["known_source"] = "conjugation"
    print("  Conjugation forms: %d" % len(matched))

    # 2c. Elision resolution against known wordlists + Wiktionary
    all_known = normal_words | conj_forms | wikt_spanish
    for w in list(remaining):
        if w in elision_candidates:
            for candidate in elision_candidates[w]:
                if candidate.lower() in all_known:
                    known_elision.add(w)
                    remaining.discard(w)
                    debug_trail[w]["known_source"] = "elision:" + candidate.lower()
                    break

    # Load skip forms from step 3's elision mapping
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
                debug_trail[w]["known_source"] = "elision:skip_form"

    print("  Elisions: %d" % len(known_elision))

    # 2d. Shared curated lists (non-propn keep-in-deck curations)
    matched = remaining & shared_all
    known_shared |= matched
    remaining -= matched
    for w in matched:
        debug_trail[w]["known_source"] = "shared_curated"
    print("  Shared curated: %d" % len(matched))

    # 2e. Morphological derivations
    known_derivation = {}
    deriv_lookup = normal_words | conj_forms | wikt_spanish
    for w in list(remaining):
        if w in clitic_merge or w in clitic_keep:
            continue
        base = resolve_derivation(w, deriv_lookup)
        if base:
            known_derivation[w] = base
            remaining.discard(w)
            debug_trail[w]["known_source"] = "derivation:" + base
    if known_derivation:
        print("  Derivations: %d" % len(known_derivation))

    # ==================================================================
    # Phase 2.5: COGNATE SKIP (new)
    # Catches transparent loanwords (bikini, bolero, bluetooth, casual)
    # BEFORE English detection, so they get tagged correctly.
    # ==================================================================
    if not args.no_cognate:
        print("\n--- Phase 2.5: Transparent cognate skip ---")
        for w in list(remaining):
            if w in always_teach:
                continue  # override: user explicitly wants this learned
            if w in always_skip_cognate:
                cognates[w] = {"curated": True}
                remaining.discard(w)
                debug_trail[w]["cognate_voters"] = {"curated": True}
                continue
            # Only attempt voting if the word exists in Spanish Wiktionary
            # (otherwise there's no Spanish sense to call it a cognate OF).
            if w not in wikt_spanish:
                continue
            voters = cognate_voters(w, wikt_glosses, cognet)
            # Require at least one strong voter. "cognet" alone is weak (noisy data);
            # require identical_gloss OR suffix_rule, or cognet AND something else.
            strong = voters.get("identical_gloss") or voters.get("suffix_rule")
            if strong or (voters.get("cognet") and len(voters) >= 2):
                cognates[w] = voters
                remaining.discard(w)
                debug_trail[w]["cognate_voters"] = voters
        n_identical = sum(1 for v in cognates.values() if v.get("identical_gloss"))
        n_suffix = sum(1 for v in cognates.values() if v.get("suffix_rule"))
        n_cognet = sum(1 for v in cognates.values() if v.get("cognet"))
        n_curated = sum(1 for v in cognates.values() if v.get("curated"))
        print("  Cognates: %d (identical_gloss=%d, suffix_rule=%d, cognet=%d, curated=%d)" %
              (len(cognates), n_identical, n_suffix, n_cognet, n_curated))

    # ==================================================================
    # Phase 3: ENGLISH DETECTION (with Wiktionary safety-net)
    # ==================================================================
    print("\n--- Phase 3: English detection ---")

    # 3a-pre. Curated extra-English (English contractions, rap slang)
    if extra_english:
        matched = remaining & extra_english
        english |= matched
        remaining -= matched
        for w in matched:
            debug_trail[w]["english_source"] = "curated_extra_english"
        print("  Curated extra-English: %d" % len(matched))

    # 3a. English 50k wordlist — subtract Spanish Wiktionary first (P3.1)
    if en_50k:
        candidates = remaining & en_50k
        if wikt_spanish:
            # Only flag as English if NOT in Spanish Wiktionary. Words in Sp Wikt
            # that survived Phase 2.5 are genuinely Spanish (either non-cognate
            # loanwords or core Spanish words that happen to share an English
            # spelling — "real", "no", "si").
            candidates -= wikt_spanish
        english |= candidates
        remaining -= candidates
        for w in candidates:
            debug_trail[w]["english_source"] = "en_50k_not_wikt"
        print("  English 50k (non-Wikt): %d" % len(candidates))

    # 3b. Lingua classifier on remaining
    if not args.no_lingua:
        print("  Running lingua (threshold=%.2f)..." % args.lingua_threshold)
        lingua_english = classify_english(remaining, threshold=args.lingua_threshold)
        # Lingua can have false positives on short Spanish words; keep the
        # Wiktionary safety-net here too.
        lingua_english -= wikt_spanish
        english |= lingua_english
        remaining -= lingua_english
        for w in lingua_english:
            debug_trail[w]["english_source"] = "lingua"
        print("  Lingua English: %d" % len(lingua_english))
    else:
        print("  Skipping lingua (--no-lingua)")

    # ==================================================================
    # Phase 4: WIKTIONARY RECLASSIFICATION
    # (Retroactively reclassify known-vocab words that look English-only.)
    # ==================================================================
    print("\n--- Phase 4: Wiktionary reclassification ---")
    reclass_pool = known_normal_vocab | known_conjugation
    reclass_english = set()
    for w in reclass_pool:
        if w in en_50k and w.lower() not in wikt_spanish:
            reclass_english.add(w)
    english |= reclass_english
    known_normal_vocab -= reclass_english
    known_conjugation -= reclass_english
    for w in reclass_english:
        debug_trail[w]["english_source"] = "reclass"
    print("  Reclassified %d known-vocab → english (in en_50k, not in Wiktionary)" %
          len(reclass_english))

    # ==================================================================
    # Phase 5: spaCy NER — WITH Wiktionary safety-net (P2.1)
    # ==================================================================
    if not args.no_nlp_detect and not args.no_spacy:
        print("\n--- Phase 5: spaCy NER ---")
        spacy_propn = detect_propn_by_spacy(remaining, word_entries)
        # Safety-net: skip NER hits that have a non-name POS in Wiktionary,
        # unless curated drop list overrides.
        wikt_safe = set()
        for w in spacy_propn:
            if w in drop_propn:
                continue
            poses = wikt_pos.get(w, set())
            if poses and poses - {"name"}:
                wikt_safe.add(w)
        spacy_propn -= wikt_safe
        spacy_propn -= allow_propn
        spacy_new = spacy_propn & remaining
        proper_nouns_detected |= spacy_new
        remaining -= spacy_new
        for w in spacy_new:
            debug_trail[w]["propn_source"] = "spacy_ner"
        print("  spaCy NER: %d additional proper nouns (%d filtered by Wikt safety-net)" %
              (len(spacy_new), len(wikt_safe)))

    # ==================================================================
    # Phase 6a: RESIDUAL CLITIC FALLBACK (P4.2)
    # For any remaining word ending in a clitic pronoun, try stripping and
    # looking up the base in the known-word set. Moves hits to clitic_merge.
    # ==================================================================
    print("\n--- Phase 6a: Residual clitic fallback ---")
    fallback = residual_clitic_fallback(remaining, all_known | artist_words)
    if fallback:
        clitic_merge.update(fallback)
        for w in fallback:
            remaining.discard(w)
            debug_trail[w]["clitic_merge"] = fallback[w]
            debug_trail[w]["clitic_source"] = "residual_fallback"
    print("  Residual clitic merge: %d" % len(fallback))

    # ==================================================================
    # Phase 6b: FREQUENCY THRESHOLD
    # ==================================================================
    print("\nApplying frequency threshold (min_freq=%d)..." % args.min_freq)
    for w in list(remaining):
        if word_freq.get(w, 0) < args.min_freq:
            low_frequency.add(w)
            remaining.discard(w)
            debug_trail[w]["low_freq"] = True
    print("  Removed %d words (freq < %d)" % (len(low_frequency), args.min_freq))

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    elapsed = time.time() - start_time
    n_exclude = (len(english) + len(proper_nouns_detected) + len(interjections_detected)
                 + len(low_frequency) + len(cognates))
    n_biencoder = (len(known_normal_vocab) + len(known_conjugation) + len(known_elision)
                   + len(known_derivation) + len(known_shared))

    print("\n=== Word Routing Summary ===")
    print("  Input words:          %d" % len(artist_words))
    print("  ---")
    print("  EXCLUDE (%d):" % n_exclude)
    print("    English:            %d" % len(english))
    print("    Cognate:            %d (transparent loanwords)" % len(cognates))
    print("    Proper nouns:       %d" % len(proper_nouns_detected))
    print("    Interjections:      %d" % len(interjections_detected))
    print("    Low frequency:      %d (freq < %d)" % (len(low_frequency), args.min_freq))
    print("  BIENCODER (%d):" % n_biencoder)
    print("    Normal vocab:       %d" % len(known_normal_vocab))
    print("    Conjugation:        %d" % len(known_conjugation))
    print("    Elision:            %d" % len(known_elision))
    print("    Derivation:         %d (diminutive + gerund+clitic)" % len(known_derivation))
    print("    Shared curated:     %d" % len(known_shared))
    print("  GEMINI (%d):          %s" % (len(remaining), "(Caribbean slang, regional vocab)"))
    print("  CLITIC MERGE:         %d (+ %d tier 3 kept separate)" % (len(clitic_merge), len(clitic_keep)))
    print("  ---")
    print("  Time: %.1f seconds" % elapsed)

    # ---------------------------------------------------------------
    # C1 — DISJOINT BUCKET ASSERTION
    # Every input word must appear in exactly one bucket.
    # ---------------------------------------------------------------
    buckets = {
        "english": english,
        "cognate": set(cognates.keys()),
        "proper_nouns": proper_nouns_detected,
        "interjections": interjections_detected,
        "low_frequency": low_frequency,
        "normal_vocab": known_normal_vocab,
        "conjugation": known_conjugation,
        "elision": known_elision,
        "derivation": set(known_derivation.keys()),
        "shared": known_shared,
        "gemini": remaining,
        "clitic_merge": set(clitic_merge.keys()),
        "clitic_keep": set(clitic_keep),
    }
    seen = {}
    overlaps = []
    for name, s in buckets.items():
        for w in s:
            if w in seen:
                overlaps.append((w, seen[w], name))
            else:
                seen[w] = name
    covered = set(seen.keys())
    missing = artist_words - covered
    if overlaps:
        print("\n[ERROR] %d words appear in multiple buckets (first 20):" % len(overlaps))
        for w, a, b in overlaps[:20]:
            print("  %r: %s and %s" % (w, a, b))
    if missing:
        print("\n[ERROR] %d input words missing from all buckets (first 20): %s" %
              (len(missing), sorted(missing)[:20]))
    if overlaps or missing:
        raise SystemExit("Disjoint-bucket assertion failed; see errors above.")
    print("\nDisjoint-bucket assertion OK (%d words fully partitioned)" % len(covered))

    # ---------------------------------------------------------------
    # Write main output
    # ---------------------------------------------------------------
    output = {
        "exclude": {
            "english": sorted(english),
            "cognate": {w: cognates[w] for w in sorted(cognates)},
            "proper_nouns": sorted(proper_nouns_detected),
            "interjections": sorted(interjections_detected),
            "low_frequency": sorted(low_frequency),
        },
        "biencoder": {
            "normal_vocab": sorted(known_normal_vocab),
            "conjugation": sorted(known_conjugation),
            "elision": sorted(known_elision),
            "derivation": known_derivation,
            "shared": sorted(known_shared),
        },
        "gemini": sorted(remaining, key=lambda w: word_freq.get(w, 0), reverse=True),
        "clitic_merge": clitic_merge,
        "clitic_orphans": sorted(clitic_orphans),
        "clitic_keep": sorted(clitic_keep),
        "stats": {
            "input_words": len(artist_words),
            "exclude": n_exclude,
            "biencoder": n_biencoder,
            "gemini": len(remaining),
            "cognate": len(cognates),
            "clitic_merge": len(clitic_merge),
            "clitic_keep": len(clitic_keep),
            "min_freq": args.min_freq,
            "lingua_threshold": args.lingua_threshold if not args.no_lingua else None,
        },
    }
    output["_meta"] = make_meta("filter_known_vocab", STEP_VERSION)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("Wrote %s" % output_path)

    # ---------------------------------------------------------------
    # C4 — DEBUG DUMP
    # Per-word detection trail (source + Wikt POS) for audit/grepping.
    # ---------------------------------------------------------------
    debug_out = {}
    for w in sorted(artist_words):
        trail = debug_trail.get(w, {})
        trail["freq"] = word_freq.get(w, 0)
        trail["wikt_pos"] = sorted(wikt_pos.get(w, set()))
        trail["in_wikt"] = w in wikt_spanish
        trail["in_en_50k"] = w in en_50k
        trail["bucket"] = seen.get(w, "unknown")
        debug_out[w] = trail
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump(debug_out, f, indent=2, ensure_ascii=False)
    print("Wrote %s" % debug_path)


if __name__ == "__main__":
    main()
