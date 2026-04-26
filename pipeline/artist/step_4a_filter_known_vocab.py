#!/usr/bin/env python3
"""
Step 4: Route artist vocabulary to its sense-assignment bucket.

Five phases, one source of truth for "known Spanish", no heuristic detectors:

  Phase 1: Curated drops        (noise ∪ extra_english ∪ proper_nouns.drop)
                                + regex for 3+ repeated letters (jajajajaja)
                                + Wiktionary all-PROPN (unambiguous names)
  Phase 2: Known Spanish        (spanish_forms.json lookup); words also in
                                cognates.drop split off to exclude.cognate,
                                rest go to classifier by POS
  Phase 3: Clitic + derivation  (strip clitic, check base in verb forms;
                                or resolve diminutive/superlative)
  Phase 4: English fallback     (en_50k for words not in spanish_forms)
  Phase 5: Frequency floor
           → everything else   → sense_discovery

Output bucket names (word_routing.json schema_version 2):
  - exclude.{english, cognate, proper_nouns, noise, low_frequency}
    cognate is a flat list (no per-word voter dict).
    noise was previously called interjections; the rename matches what the
    bucket actually holds (single-letter / ad-lib / hype noises).
  - classifier.{normal_vocab, conjugation, elision}
    Was biencoder.* — renamed because the runtime classifier (biencoder vs
    Gemini) is a per-invocation choice; the buckets are agnostic metadata.
  - derivation_map: {form: base}
    Hoisted out of classifier.* so the classifier section is uniformly list-
    shaped. Sibling of clitic_merge.
  - sense_discovery: [...]
    Was gemini — renamed because "no SD/wiktionary sense menu, needs a model
    to invent senses" describes the bucket; whichever model does the work is
    a runtime choice.
  - clitic_merge, clitic_orphans, clitic_keep, stats, _meta, schema_version

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
        --artist-dir "Artists/spanish/Bad Bunny"
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
from util_1a_artist_config import (  # noqa: E402
    add_artist_arg, load_shared_list, load_curation_section, SHARED_DIR,
)

STEP_VERSION = 4
STEP_VERSION_NOTES = {
    1: "initial: 6 phases with heuristic detectors",
    2: "+ cognate skip, Wikt safety-nets, residual clitic fallback",
    3: "simplified: canonical spanish_forms.json; dropped spaCy/cap-ratio/regex-interj/suffix-rule; one clitic rule",
    4: "schema_version 2: bucket renames (biencoder→classifier, gemini→sense_discovery, interjections→noise); cognate flattened; derivation hoisted to derivation_map; sectioned curation files (proper_nouns/cognates/noise have drop+keep)",
}

# Bumped whenever the output JSON schema changes in a way consumers must
# notice (key renames, shape changes). Independent of STEP_VERSION which
# tracks the producer's behaviour.
SCHEMA_VERSION = 2

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


def _load_section(filename, section):
    """Lower-cased frozenset of one section of a sectioned curation file.

    Wraps ``load_curation_section`` so step_4a's curation loads are uniformly
    typed. Missing files / missing sections both return an empty frozenset.
    """
    return frozenset(w.lower() for w in load_curation_section(filename, section))


def _strip_acute(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if c != "\u0301")


# ---------------------------------------------------------------------------
# Clitic detection — the one rule
# ---------------------------------------------------------------------------

def strip_clitic(word, verb_forms, conj_reverse=None):
    """Return (base, clitic) if word is verb+clitic, else None.

    Imperatives drop an accent when clitics attach (baja → bájame). Try the
    accented and accent-stripped base against the verb-form set.

    If ``conj_reverse`` (the verbecc form→lemma map) is provided, resolve the
    stripped surface to its infinitive. This prevents párame → para (the
    ambiguous imperative that also means "for") from displacing the proper
    base verb párame → parar.
    """
    for clitic in _CLITIC_PRONOUNS:
        if word.endswith(clitic) and len(word) > len(clitic) + 2:
            base = word[:-len(clitic)]
            for candidate in (base, _strip_acute(base)):
                if candidate in verb_forms:
                    if conj_reverse:
                        entries = conj_reverse.get(candidate, [])
                        if entries:
                            lemma = entries[0].get("lemma")
                            if lemma:
                                return (lemma, clitic)
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

    # Load verbecc form→lemma map for clitic base resolution. Without it,
    # `párame` strips to `para` which is the ambiguous imperative/preposition;
    # with it, resolves to infinitive `parar`.
    conj_reverse_path = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "layers", "conjugation_reverse.json")
    conj_reverse = {}
    if os.path.isfile(conj_reverse_path):
        with open(conj_reverse_path, "r", encoding="utf-8") as f:
            conj_reverse = json.load(f)
        print(f"  conjugation_reverse: {len(conj_reverse)} forms")

    # Curations — sectioned files (drop + keep in one file).
    # Each curation has a "drop" list (words to filter into a bucket) and a
    # "keep" list (override — words that look like the filtered category but
    # are real Spanish vocab and must survive). `keep` wins on conflicts.
    noise_drop = _load_section("noise.json", "drop")
    noise_keep = _load_section("noise.json", "keep")
    noise = noise_drop - noise_keep

    extra_english = _maybe_load_shared("extra_english.json")  # one-direction; no keep counterpart

    drop_propn = _load_section("proper_nouns.json", "drop")
    allow_propn = _load_section("proper_nouns.json", "keep")
    conflicts = drop_propn & allow_propn
    if conflicts:
        print(f"  [WARN] proper_nouns drop/keep conflicts (keep wins): {sorted(conflicts)[:10]}")
        drop_propn = drop_propn - allow_propn

    always_skip_cognate = _load_section("cognates.json", "drop")
    always_teach = _load_section("cognates.json", "keep")

    print(f"  Curations: {len(noise)} noise (={len(noise_drop)}-{len(noise_keep)}), "
          f"{len(extra_english)} extra_english, "
          f"{len(drop_propn)} drop_propn, {len(allow_propn)} allow_propn, "
          f"{len(always_skip_cognate)} skip_cognate, {len(always_teach)} always_teach")

    # ------------------------------------------------------------------
    # Routing state
    # ------------------------------------------------------------------
    remaining = set(artist_words)
    buckets = {
        "english": set(),
        "cognate": set(),             # flat set; was {word: {voters: [...]}} in schema_v1
        "proper_nouns": set(),
        "noise": set(),               # was "interjections" in schema_v1
        "low_frequency": set(),
        "normal_vocab": set(),
        "conjugation": set(),
        "elision": set(),
        "derivation": {},             # word -> base; written to top-level derivation_map at output time
        "clitic_merge": {},           # word -> (base, clitic_pronoun)
    }
    trail = {w: {"freq": word_freq[w]} for w in artist_words}

    # ------------------------------------------------------------------
    # Phase 1 — Curated drops + obvious-noise regex + Wikt all-PROPN
    # ------------------------------------------------------------------
    print("\n--- Phase 1: Curated drops ---")

    # 1a. Noise (ad-libs, single letters, hype noises). The keep section of
    #     noise.json has already been subtracted, so function words ('a',
    #     'o', 'y', 'e', 'u') survive this filter.
    matched = (remaining & noise) - allow_propn
    buckets["noise"] |= matched
    remaining -= matched
    for w in matched:
        trail[w]["bucket"] = "noise"
        trail[w]["source"] = "curated_noise"
    print(f"  Curated noise:        {len(matched)}")

    # 1b. Regex: words with 3+ repeated letters (jajajajaja, brrrrr, wooo).
    #     This safety-net is intentionally not affected by noise.json's keep
    #     section — no real Spanish word triple-repeats a letter.
    matched = {w for w in remaining if _REPEAT_RE.search(w)}
    buckets["noise"] |= matched
    remaining -= matched
    for w in matched:
        trail[w]["bucket"] = "noise"
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
        # cognates.json (drop section) with the obvious loanwords (bikini,
        # bolero, chalet, …). Parsimony > false-positive automated detection.
        # The richer multi-voter provenance lives in step_7c_flag_cognates →
        # cognates.json layer; here we only need the boolean "drop or not".
        if w in always_skip_cognate and w not in always_teach:
            buckets["cognate"].add(w)
            trail[w]["bucket"] = "cognate"
            trail[w]["cognate_source"] = "curated"
            remaining.discard(w)
            cog_count += 1
            continue

        # Not a cognate — route to classifier by POS.
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
        result = strip_clitic(w, verb_forms, conj_reverse)
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

    sense_discovery = sorted(remaining, key=lambda w: -word_freq[w])
    for w in remaining:
        trail[w]["bucket"] = "sense_discovery"

    elapsed = time.time() - start_time

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    n_exclude = (len(buckets["english"]) + len(buckets["cognate"]) +
                 len(buckets["proper_nouns"]) + len(buckets["noise"]) +
                 len(buckets["low_frequency"]))
    n_classifier = (len(buckets["normal_vocab"]) + len(buckets["conjugation"]) +
                    len(buckets["elision"]))
    print(f"\n=== Word Routing Summary ===")
    print(f"  Input words: {len(artist_words)}")
    print(f"  EXCLUDE ({n_exclude}):")
    print(f"    English:       {len(buckets['english'])}")
    print(f"    Cognate:       {len(buckets['cognate'])}")
    print(f"    Proper nouns:  {len(buckets['proper_nouns'])}")
    print(f"    Noise:         {len(buckets['noise'])}")
    print(f"    Low frequency: {len(buckets['low_frequency'])}")
    print(f"  CLASSIFIER ({n_classifier}):")
    print(f"    Normal vocab:  {len(buckets['normal_vocab'])}")
    print(f"    Conjugation:   {len(buckets['conjugation'])}")
    print(f"    Elision:       {len(buckets['elision'])}")
    print(f"  DERIVATION_MAP: {len(buckets['derivation'])}")
    print(f"  SENSE_DISCOVERY ({len(sense_discovery)})")
    print(f"  CLITIC_MERGE:   {len(buckets['clitic_merge'])}")
    print(f"  Time: {elapsed:.1f}s")

    # ------------------------------------------------------------------
    # Disjoint-bucket assertion
    # ------------------------------------------------------------------
    seen = {}
    overlaps = []
    flat = {
        "english": buckets["english"],
        "cognate": buckets["cognate"],
        "proper_nouns": buckets["proper_nouns"],
        "noise": buckets["noise"],
        "low_frequency": buckets["low_frequency"],
        "normal_vocab": buckets["normal_vocab"],
        "conjugation": buckets["conjugation"],
        "elision": buckets["elision"],
        "derivation_map": set(buckets["derivation"].keys()),
        "clitic_merge": set(buckets["clitic_merge"].keys()),
        "sense_discovery": set(remaining),
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
        "schema_version": SCHEMA_VERSION,
        "exclude": {
            "english": sorted(buckets["english"]),
            "cognate": sorted(buckets["cognate"]),
            "proper_nouns": sorted(buckets["proper_nouns"]),
            "noise": sorted(buckets["noise"]),
            "low_frequency": sorted(buckets["low_frequency"]),
        },
        "classifier": {
            "normal_vocab": sorted(buckets["normal_vocab"]),
            "conjugation": sorted(buckets["conjugation"]),
            "elision": sorted(buckets["elision"]),
        },
        "derivation_map": buckets["derivation"],
        "sense_discovery": sense_discovery,
        "clitic_merge": buckets["clitic_merge"],
        # clitic_orphans / clitic_keep are populated by NORMAL-MODE
        # step_4a_route_clitics and consumed by step_8a/step_8b. Artist mode
        # moved tier-3 logic into step_8b so we always write empty lists for
        # schema parity with normal mode — never let a downstream consumer
        # raise KeyError just because we routed differently here.
        "clitic_orphans": [],
        "clitic_keep": [],
        "stats": {
            "input_words": len(artist_words),
            "exclude": n_exclude,
            "classifier": n_classifier,
            "derivation_map": len(buckets["derivation"]),
            "sense_discovery": len(sense_discovery),
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
