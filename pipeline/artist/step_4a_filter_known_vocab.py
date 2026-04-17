#!/usr/bin/env python3
"""
Step 4: Route artist vocabulary to its sense-assignment bucket.

Five phases, one source of truth for "known Spanish", no heuristic detectors:

  Phase 1: Curated drops        (noise ∪ extra_english ∪ drop_proper_nouns)
                                + regex for 3+ repeated letters (jajajajaja)
                                + Wiktionary all-PROPN (unambiguous names)
  Phase 2: Known Spanish        (spanish_forms.json lookup); words also in
                                en_50k or CogNet split off to exclude.cognate,
                                rest go to biencoder by POS
  Phase 3: Clitic + derivation  (strip clitic, check base in verb forms;
                                or resolve diminutive/superlative)
  Phase 4: English fallback     (en_50k for words not in spanish_forms)
  Phase 5: Frequency floor
           → everything else   → gemini

Principles:
  - One canonical 'is this Spanish?' source: Data/Spanish/layers/spanish_forms.json
    (built from Wiktionary form-of + verbecc + normal_vocab).
  - Clitic detection is ONE rule: word ends in clitic pronoun AND base is a
    known verb form. No POS guards, no preterite guards — the verb form set
    is comprehensive enough that spurious matches can't happen.
  - No spaCy, no cap-ratio heuristics, no regex interjection patterns. If a
    name or ad-lib leaks through, add it to the curation file.

Reads:  <artist-dir>/data/elision_merge/vocab_evidence_merged.json
        Data/Spanish/layers/spanish_forms.json
        Data/English/en_50k_wordlist.txt
        shared/cognet_spa_eng.json
        Artists/curations/*.json
Writes: <artist-dir>/data/known_vocab/word_routing.json
        <artist-dir>/data/known_vocab/word_routing_debug.json

Usage:
    .venv/bin/python3 pipeline/artist/step_4a_filter_known_vocab.py \
        --artist-dir "Artists/Bad Bunny"
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from pipeline.util_pipeline_meta import make_meta  # noqa: E402
from pipeline.util_4a_routing import resolve_derivation  # noqa: E402

sys.path.insert(0, _THIS_DIR)
from util_1a_artist_config import add_artist_arg, load_shared_list, SHARED_DIR  # noqa: E402

STEP_VERSION = 3
STEP_VERSION_NOTES = {
    1: "initial: 6 phases with heuristic detectors",
    2: "+ cognate skip, Wikt safety-nets, residual clitic fallback",
    3: "simplified: canonical spanish_forms.json; dropped spaCy/cap-ratio/regex-interj/suffix-rule; one clitic rule",
}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SPANISH_FORMS_PATH = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "layers", "spanish_forms.json")
EN_50K_PATH = os.path.join(_PROJECT_ROOT, "Data", "English", "en_50k_wordlist.txt")
ELISION_MAPPING_PATH = os.path.join(SHARED_DIR, "elision_mapping.json")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Longest-first so 'nos' is tried before 'se' for 'enseñarnos'.
_CLITIC_PRONOUNS = ("nos", "les", "los", "las", "me", "te", "se", "lo", "la", "le")
# Safety-net: any word with 3+ consecutive identical letters is noise
# (jajajajajajaja, brrrrr, woooo, aaaahhhh).
_REPEAT_RE = re.compile(r"(.)\1{2,}")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_spanish_forms(path):
    """Return {word: set(pos)} from the canonical spanish_forms.json."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {w: set(pos_str.split(",")) if pos_str else set() for w, pos_str in data.items()}


def load_en_50k(path):
    words = set()
    if not os.path.exists(path):
        return words
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if parts:
                words.add(parts[0].lower())
    return words


def _maybe_load_shared(name):
    try:
        return frozenset(w.lower() for w in load_shared_list(name))
    except FileNotFoundError:
        return frozenset()


def _strip_acute(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if c != "\u0301")


# ---------------------------------------------------------------------------
# Clitic detection — the one rule
# ---------------------------------------------------------------------------

def strip_clitic(word, verb_forms):
    """Return (base, clitic) if word is verb+clitic, else None.

    Imperatives drop an accent when clitics attach (baja → bájame). Try the
    accented and accent-stripped base against the verb-form set. Done.
    """
    for clitic in _CLITIC_PRONOUNS:
        if word.endswith(clitic) and len(word) > len(clitic) + 2:
            base = word[:-len(clitic)]
            for candidate in (base, _strip_acute(base)):
                if candidate in verb_forms:
                    return (candidate, clitic)
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Step 4: Route artist vocabulary.")
    add_artist_arg(parser)
    parser.add_argument("--min-freq", type=int, default=2,
                        help="Minimum corpus frequency to keep (default 2).")
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    input_path = os.path.join(artist_dir, "data", "elision_merge", "vocab_evidence_merged.json")
    output_dir = os.path.join(artist_dir, "data", "known_vocab")
    output_path = os.path.join(output_dir, "word_routing.json")
    debug_path = os.path.join(output_dir, "word_routing_debug.json")
    os.makedirs(output_dir, exist_ok=True)

    start_time = time.time()

    # ------------------------------------------------------------------
    # Load artist data
    # ------------------------------------------------------------------
    print(f"Loading {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        all_words = json.load(f)
    word_freq = {e["word"].lower(): e.get("corpus_count", 0) for e in all_words}
    artist_words = set(word_freq.keys())
    print(f"  {len(artist_words)} input words")

    # ------------------------------------------------------------------
    # Load the ONE Spanish source of truth
    # ------------------------------------------------------------------
    if not os.path.isfile(SPANISH_FORMS_PATH):
        print(f"\nERROR: {SPANISH_FORMS_PATH} not found.")
        print("Run: .venv/bin/python3 pipeline/util_4a_build_spanish_forms.py")
        sys.exit(1)
    print(f"Loading {SPANISH_FORMS_PATH}")
    spanish_forms = load_spanish_forms(SPANISH_FORMS_PATH)
    verb_forms = {w for w, pos in spanish_forms.items() if "verb" in pos}
    propn_only = {w for w, pos in spanish_forms.items() if pos == {"name"}}
    print(f"  {len(spanish_forms)} Spanish forms ({len(verb_forms)} verb, {len(propn_only)} name-only)")

    # Load en_50k for the English fallback phase
    en_50k = load_en_50k(EN_50K_PATH)
    print(f"  en_50k: {len(en_50k)} words")

    # Curations
    noise = _maybe_load_shared("noise.json") | _maybe_load_shared("interjections.json")
    extra_english = _maybe_load_shared("extra_english.json")
    drop_propn = _maybe_load_shared("drop_proper_nouns.json") | _maybe_load_shared("known_proper_nouns.json")
    allow_propn = _maybe_load_shared("allow_proper_nouns.json") | _maybe_load_shared("not_proper_nouns.json")
    always_teach = _maybe_load_shared("always_teach.json")
    always_skip_cognate = _maybe_load_shared("always_skip_cognate.json")

    # Resolve drop/allow conflicts: allow wins
    conflicts = drop_propn & allow_propn
    if conflicts:
        print(f"  [WARN] drop/allow propn conflicts (allow wins): {sorted(conflicts)[:10]}")
        drop_propn = drop_propn - allow_propn

    print(f"  Curations: {len(noise)} noise, {len(extra_english)} extra_english, "
          f"{len(drop_propn)} drop_propn, {len(allow_propn)} allow_propn, "
          f"{len(always_teach)} always_teach")

    # ------------------------------------------------------------------
    # Routing state
    # ------------------------------------------------------------------
    remaining = set(artist_words)
    buckets = {
        "english": set(),
        "cognate": {},                # word -> {"voter": source}
        "proper_nouns": set(),
        "interjections": set(),       # bucket name kept for output compat
        "low_frequency": set(),
        "normal_vocab": set(),
        "conjugation": set(),
        "elision": set(),
        "derivation": {},             # word -> base
        "shared": set(),              # unused in simplified pipeline
        "clitic_merge": {},           # word -> (base, clitic_pronoun)
    }
    trail = {w: {"freq": word_freq[w]} for w in artist_words}

    # ------------------------------------------------------------------
    # Phase 1 — Curated drops + obvious-noise regex + Wikt all-PROPN
    # ------------------------------------------------------------------
    print("\n--- Phase 1: Curated drops ---")

    # 1a. Noise (ad-libs, single letters, interjections)
    matched = (remaining & noise) - allow_propn
    buckets["interjections"] |= matched
    remaining -= matched
    for w in matched:
        trail[w]["bucket"] = "interjections"
        trail[w]["source"] = "curated_noise"
    print(f"  Curated noise:        {len(matched)}")

    # 1b. Regex: words with 3+ repeated letters
    matched = {w for w in remaining if _REPEAT_RE.search(w)}
    buckets["interjections"] |= matched
    remaining -= matched
    for w in matched:
        trail[w]["bucket"] = "interjections"
        trail[w]["source"] = "regex_repeat"
    print(f"  Repeated-letter noise: {len(matched)}")

    # 1c. Curated extra_english
    matched = remaining & extra_english
    buckets["english"] |= matched
    remaining -= matched
    for w in matched:
        trail[w]["bucket"] = "english"
        trail[w]["source"] = "curated_extra_english"
    print(f"  Curated extra_english: {len(matched)}")

    # 1d. Curated drop proper nouns
    matched = (remaining & drop_propn) - allow_propn
    buckets["proper_nouns"] |= matched
    remaining -= matched
    for w in matched:
        trail[w]["bucket"] = "proper_nouns"
        trail[w]["source"] = "curated_drop"
    print(f"  Curated drop_propn:    {len(matched)}")

    # 1e. Wiktionary all-PROPN (words whose ONLY POS is `name`)
    matched = (remaining & propn_only) - allow_propn
    buckets["proper_nouns"] |= matched
    remaining -= matched
    for w in matched:
        trail[w]["bucket"] = "proper_nouns"
        trail[w]["source"] = "wikt_all_propn"
    print(f"  Wikt all-PROPN:        {len(matched)}")

    # ------------------------------------------------------------------
    # Phase 2 — Known Spanish, split into cognate (loanword, exclude) vs
    # biencoder (learnable). A word is a cognate if it's Spanish AND either
    # also in en_50k or in CogNet. always_teach.json overrides.
    # ------------------------------------------------------------------
    print("\n--- Phase 2: Known Spanish (cognate-aware) ---")
    cog_count = 0
    for w in list(remaining):
        pos = spanish_forms.get(w)
        if pos is None:
            continue
        trail[w]["wikt_pos"] = sorted(pos)

        # Cognate check (curation-only). en_50k is too polluted with Spanish
        # loan-tokens (nada, para, todo, vida, noche all appear in it) to use
        # as an automated voter. CogNet has similar noise. Users curate
        # always_skip_cognate.json with the obvious loanwords (bikini, bolero,
        # chalet, …). Parsimony > false-positive automated detection.
        if w in always_skip_cognate and w not in always_teach:
            buckets["cognate"][w] = {"voters": ["curated"]}
            trail[w]["bucket"] = "cognate"
            trail[w]["cognate_voters"] = ["curated"]
            remaining.discard(w)
            cog_count += 1
            continue

        # Not a cognate — route to biencoder by POS.
        if "verb" in pos:
            buckets["conjugation"].add(w)
            trail[w]["bucket"] = "conjugation"
        else:
            buckets["normal_vocab"].add(w)
            trail[w]["bucket"] = "normal_vocab"
        trail[w]["source"] = "spanish_forms"
        remaining.discard(w)
    print(f"  Cognates:     {cog_count}")
    print(f"  Normal vocab: {len(buckets['normal_vocab'])}  Conjugation: {len(buckets['conjugation'])}")

    # ------------------------------------------------------------------
    # Phase 3 — Clitic + derivation (on words NOT recognized by Phase 2)
    # ------------------------------------------------------------------
    print("\n--- Phase 3: Clitic + derivation ---")

    # 3a. Clitic: one rule.
    clitic_count = 0
    for w in list(remaining):
        result = strip_clitic(w, verb_forms)
        if result is None:
            continue
        base, clitic = result
        buckets["clitic_merge"][w] = base
        trail[w]["bucket"] = "clitic_merge"
        trail[w]["clitic_base"] = base
        trail[w]["clitic_pronoun"] = clitic
        remaining.discard(w)
        clitic_count += 1
    print(f"  Clitic merges: {clitic_count}")

    # 3b. Derivation (diminutive / superlative) — reuse existing resolver
    deriv_count = 0
    known_forms_set = set(spanish_forms.keys())
    for w in list(remaining):
        base = resolve_derivation(w, known_forms_set)
        if base:
            buckets["derivation"][w] = base
            trail[w]["bucket"] = "derivation"
            trail[w]["derivation_base"] = base
            remaining.discard(w)
            deriv_count += 1
    print(f"  Derivations:   {deriv_count}")

    # 3c. Elision mapping skip forms — words step 3 chose to leave alone
    if os.path.exists(ELISION_MAPPING_PATH):
        with open(ELISION_MAPPING_PATH, "r", encoding="utf-8") as f:
            elision_mapping = json.load(f)
        skip_forms = {e["word"] for e in elision_mapping if e.get("action") == "skip"}
        matched = remaining & skip_forms
        buckets["elision"] |= matched
        remaining -= matched
        for w in matched:
            trail[w]["bucket"] = "elision"
            trail[w]["source"] = "elision_skip"
        if matched:
            print(f"  Elision skips: {len(matched)}")

    # ------------------------------------------------------------------
    # Phase 4 — English fallback
    #   en_50k for words NOT in spanish_forms (survived Phase 2 so they
    #   aren't Spanish; obvious English that the wordlist covers).
    # ------------------------------------------------------------------
    print("\n--- Phase 4: English fallback ---")
    en_count = 0
    for w in list(remaining):
        if w in en_50k and w not in spanish_forms:
            buckets["english"].add(w)
            trail[w]["bucket"] = "english"
            trail[w]["source"] = "en_50k"
            remaining.discard(w)
            en_count += 1
    print(f"  English (en_50k, not Spanish): {en_count}")

    # ------------------------------------------------------------------
    # Phase 5 — Frequency floor; everything else → gemini
    # ------------------------------------------------------------------
    print("\n--- Phase 5: Frequency floor ---")
    lo_count = 0
    for w in list(remaining):
        if word_freq[w] < args.min_freq:
            buckets["low_frequency"].add(w)
            trail[w]["bucket"] = "low_frequency"
            trail[w]["source"] = f"freq<{args.min_freq}"
            remaining.discard(w)
            lo_count += 1
    print(f"  Low frequency: {lo_count}")

    gemini = sorted(remaining, key=lambda w: -word_freq[w])
    for w in remaining:
        trail[w]["bucket"] = "gemini"

    elapsed = time.time() - start_time

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    n_exclude = (len(buckets["english"]) + len(buckets["cognate"]) +
                 len(buckets["proper_nouns"]) + len(buckets["interjections"]) +
                 len(buckets["low_frequency"]))
    n_biencoder = (len(buckets["normal_vocab"]) + len(buckets["conjugation"]) +
                   len(buckets["elision"]) + len(buckets["derivation"]))
    print(f"\n=== Word Routing Summary ===")
    print(f"  Input words: {len(artist_words)}")
    print(f"  EXCLUDE ({n_exclude}):")
    print(f"    English:       {len(buckets['english'])}")
    print(f"    Cognate:       {len(buckets['cognate'])}")
    print(f"    Proper nouns:  {len(buckets['proper_nouns'])}")
    print(f"    Interjections: {len(buckets['interjections'])}")
    print(f"    Low frequency: {len(buckets['low_frequency'])}")
    print(f"  BIENCODER ({n_biencoder}):")
    print(f"    Normal vocab:  {len(buckets['normal_vocab'])}")
    print(f"    Conjugation:   {len(buckets['conjugation'])}")
    print(f"    Elision:       {len(buckets['elision'])}")
    print(f"    Derivation:    {len(buckets['derivation'])}")
    print(f"  GEMINI ({len(gemini)})")
    print(f"  CLITIC MERGE:   {len(buckets['clitic_merge'])}")
    print(f"  Time: {elapsed:.1f}s")

    # ------------------------------------------------------------------
    # Disjoint-bucket assertion
    # ------------------------------------------------------------------
    seen = {}
    overlaps = []
    flat = {
        "english": buckets["english"],
        "cognate": set(buckets["cognate"].keys()),
        "proper_nouns": buckets["proper_nouns"],
        "interjections": buckets["interjections"],
        "low_frequency": buckets["low_frequency"],
        "normal_vocab": buckets["normal_vocab"],
        "conjugation": buckets["conjugation"],
        "elision": buckets["elision"],
        "derivation": set(buckets["derivation"].keys()),
        "clitic_merge": set(buckets["clitic_merge"].keys()),
        "gemini": set(remaining),
    }
    for name, s in flat.items():
        for w in s:
            if w in seen:
                overlaps.append((w, seen[w], name))
            else:
                seen[w] = name
    missing = artist_words - set(seen)
    if overlaps:
        print(f"\n[ERROR] {len(overlaps)} bucket overlaps, first 10:")
        for w, a, b in overlaps[:10]:
            print(f"  {w!r}: {a} and {b}")
    if missing:
        print(f"\n[ERROR] {len(missing)} words in no bucket: {sorted(missing)[:10]}")
    if overlaps or missing:
        sys.exit("Disjoint-bucket assertion failed.")
    print(f"\nDisjoint-bucket assertion OK ({len(seen)} words partitioned)")

    # ------------------------------------------------------------------
    # Write main output
    # ------------------------------------------------------------------
    output = {
        "exclude": {
            "english": sorted(buckets["english"]),
            "cognate": {w: buckets["cognate"][w] for w in sorted(buckets["cognate"])},
            "proper_nouns": sorted(buckets["proper_nouns"]),
            "interjections": sorted(buckets["interjections"]),
            "low_frequency": sorted(buckets["low_frequency"]),
        },
        "biencoder": {
            "normal_vocab": sorted(buckets["normal_vocab"]),
            "conjugation": sorted(buckets["conjugation"]),
            "elision": sorted(buckets["elision"]),
            "derivation": buckets["derivation"],
            "shared": sorted(buckets["shared"]),
        },
        "gemini": gemini,
        "clitic_merge": buckets["clitic_merge"],
        "clitic_orphans": [],  # deprecated — kept for downstream compat
        "clitic_keep": [],      # deprecated — tier-3 semantics moved to build phase
        "stats": {
            "input_words": len(artist_words),
            "exclude": n_exclude,
            "biencoder": n_biencoder,
            "gemini": len(gemini),
            "cognate": len(buckets["cognate"]),
            "clitic_merge": len(buckets["clitic_merge"]),
            "clitic_keep": 0,
            "min_freq": args.min_freq,
        },
        "_meta": make_meta("filter_known_vocab", STEP_VERSION),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Wrote {output_path}")

    # Debug dump
    for w in artist_words:
        trail[w]["in_spanish_forms"] = w in spanish_forms
        trail[w]["in_en_50k"] = w in en_50k
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump({w: trail[w] for w in sorted(artist_words)}, f, indent=2, ensure_ascii=False)
    print(f"Wrote {debug_path}")


if __name__ == "__main__":
    main()
