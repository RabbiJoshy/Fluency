#!/usr/bin/env python3
"""
step_8a_assemble_vocabulary.py — Assemble final vocabulary from all layers.

Surface-word-first pipeline version. Iterates the inventory by surface word,
finds all word|lemma entries in sense_assignments_lemma.json, redistributes
corpus_count across lemmas proportionally, and generates hex IDs at assembly
time.

Reads all layer files and produces the final split output for the front end:
  - vocabulary.index.json  (lean, eager load — no examples)
  - vocabulary.examples.json (lazy load — examples keyed by ID)
  - vocabulary.json (full monolith for debugging)

Sort order is determined by corpus_count (descending). The front end computes
rank from array position on load, so no rank field is stored.

Usage:
    python3 pipeline/step_8a_assemble_vocabulary.py

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/layers/examples_raw.json
    Data/Spanish/layers/sense_menu.json
    Data/Spanish/layers/sense_assignments_lemma.json
    Data/Spanish/layers/mwe_phrases.json (optional)
    Data/Spanish/layers/cognates.json (optional)
    Data/Spanish/layers/conjugation_reverse.json (optional)

Outputs:
    Data/Spanish/vocabulary.index.json
    Data/Spanish/vocabulary.examples.json
    Data/Spanish/vocabulary.json
"""

import gzip
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import argparse

from util_5c_sense_paths import sense_menu_path, sense_assignments_lemma_path
from util_5c_spanishdict import (
    SPANISHDICT_SURFACE_CACHE,
    conjugation_lemma_from_possible_results,
)
from util_6a_assignment_format import load_assignments, resolve_best_per_example

# Keyword-tier priority ceiling for meaning-level assignment_method stamping.
# Mirrors pipeline/artist/step_8b_assemble_artist_vocabulary.py.
KEYWORD_PRIORITY_THRESHOLD = 15
from util_6a_method_priority import METHOD_PRIORITY
from util_8a_assembly_helpers import make_stable_id, split_count_proportionally
from util_pipeline_config import get_default_min_priority
from util_pipeline_meta import make_meta, write_sidecar

# Default language; overridden by --language at runtime.
NORMAL_MODE_LANGUAGE = "spanish"

STEP_VERSION = 2
STEP_VERSION_NOTES = {
    1: "monolith + index + examples split, hex IDs, lemma-proportional counts",
    2: "group per-sense assignments by sense_idx so foreign-sid fallbacks don't duplicate meanings",
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Path globals — bound at runtime in main() once --language is known.
LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"
OUTPUT_DIR = PROJECT_ROOT / "Data" / "Spanish"
WIKTIONARY_RAW = PROJECT_ROOT / "Data" / "Spanish" / "Senses" / "wiktionary" / "kaikki-spanish.jsonl.gz"


def _bind_paths(language):
    """Rebind LAYERS / OUTPUT_DIR / WIKTIONARY_RAW from --language."""
    global LAYERS, OUTPUT_DIR, WIKTIONARY_RAW, NORMAL_MODE_LANGUAGE
    NORMAL_MODE_LANGUAGE = language
    lang_dir = language.capitalize()
    LAYERS = PROJECT_ROOT / "Data" / lang_dir / "layers"
    OUTPUT_DIR = PROJECT_ROOT / "Data" / lang_dir
    WIKTIONARY_RAW = PROJECT_ROOT / "Data" / lang_dir / "Senses" / "wiktionary" / f"kaikki-{language}.jsonl.gz"


def load_clitic_map(path):
    """Scan Wiktionary JSONL for verb+clitic form-of entries.

    Returns (clitic_map, verbs_with_refl_senses):
      clitic_map: {word: (base_verb, is_reflexive)}
      verbs_with_refl_senses: set of verbs with reflexive-tagged senses.
    """
    clitic_map = {}
    verbs_with_refl = set()
    if not path.exists():
        return clitic_map, verbs_with_refl
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            w = entry.get("word", "")
            if not w:
                continue
            wl = w.lower()
            raw_pos = entry.get("pos", "")
            for s in entry.get("senses", []):
                tags = set(s.get("tags", []))
                if raw_pos == "verb" and "form-of" not in tags:
                    if "reflexive" in tags or "pronominal" in tags:
                        verbs_with_refl.add(wl)
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
                                clitic_map[wl] = (base, is_refl)
    return clitic_map, verbs_with_refl


# ---------------------------------------------------------------------------
# Translation cleaning (same logic as step_5c_build_senses.py)
# ---------------------------------------------------------------------------
_CLARIFICATION_STARTERS = {
    "used", "especially", "usually", "often", "expressing", "indicating",
    "introducing", "denotes", "denoting", "state", "adverbial", "in", "for",
    "with", "as", "when", "because", "can", "may", "e.g.", "i.e.",
    "including", "similar", "sometimes", "literally", "figuratively",
    "by", "from", "implies", "also", "regarded",
    "accusative", "dative", "genitive", "nominative", "declined",
    "apocopic", "conjugated", "inflected", "preceded",
}

_PAREN_RE = re.compile(r'\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)')


def clean_translation(gloss):
    text = gloss.strip()

    # Strip parenthetical clarifications
    matches = list(_PAREN_RE.finditer(text))
    for m in reversed(matches):
        inner = m.group(1).strip()
        first_word = inner.split()[0].lower().rstrip(".,;:") if inner else ""
        if len(inner) > 30:
            strip_it = True
        elif "etc" in inner.lower() or "e.g." in inner.lower() or "i.e." in inner.lower():
            strip_it = True
        elif first_word in _CLARIFICATION_STARTERS:
            strip_it = True
        elif first_word in ("a", "an", "the") and len(inner) < 25:
            strip_it = False
        else:
            strip_it = True
        if strip_it:
            text = text[:m.start()] + text[m.end():]
    text = text.strip()

    # Truncate comma chains
    parts = text.split(", ")
    if len(parts) >= 4:
        text = ", ".join(parts[:3])

    # Strip semicolon usage notes
    semi_parts = text.split("; ")
    if len(semi_parts) > 1:
        kept = []
        for part in semi_parts:
            first_word = part.strip().split()[0].lower().rstrip(".,;:") if part.strip() else ""
            if first_word in _CLARIFICATION_STARTERS:
                break
            sub = part.split(", ")
            if len(sub) >= 3:
                part = ", ".join(sub[:2])
            kept.append(part)
        if len(kept) >= 4:
            kept = kept[:3]
        text = "; ".join(kept)

    text = text.strip().rstrip(",;")
    return text if text else gloss


# ---------------------------------------------------------------------------
# Inventory format detection + normalisation
# ---------------------------------------------------------------------------

def _is_surface_word_inventory(inventory):
    """True if inventory uses the new surface-word-first format."""
    if not inventory:
        return False
    sample = inventory[0]
    return "known_lemmas" in sample and "id" not in sample


def _normalise_inventory(inventory):
    """Return (surface_word_inventory, is_new_format).

    Old format: [{word, lemma, id, corpus_count, most_frequent_lemma_instance}]
    New format: [{word, corpus_count, known_lemmas: [...]}]

    Old format is collapsed into surface-word entries on the fly so the rest of
    the code can use a single path.  Pre-split per-lemma counts are preserved
    in ``lemma_counts`` so the assembly loop can skip the proportional split.
    """
    if _is_surface_word_inventory(inventory):
        return inventory, True

    # Old format -- group by surface word
    by_word = defaultdict(lambda: {"corpus_count": 0, "lemmas": [], "lemma_counts": {}})
    for entry in inventory:
        word = entry["word"].lower()
        rec = by_word[word]
        rec["word"] = entry["word"]
        lemma = entry.get("lemma", entry["word"])
        count = entry.get("corpus_count", 0)
        rec["corpus_count"] += count
        rec["lemmas"].append(lemma)
        rec["lemma_counts"][lemma] = count
    result = []
    for word, rec in by_word.items():
        result.append({
            "word": rec["word"],
            "corpus_count": rec["corpus_count"],
            "known_lemmas": sorted(set(rec["lemmas"])),
            "lemma_counts": rec["lemma_counts"],
        })
    return result, False


# ---------------------------------------------------------------------------
# Sense-menu helpers
# ---------------------------------------------------------------------------

def _is_analysis_based_menu(senses_data):
    """True if the sense menu uses the new analysis-based format."""
    if not senses_data:
        return False
    sample_key = next(iter(senses_data))
    sample_val = senses_data[sample_key]
    if not isinstance(sample_val, list) or not sample_val:
        return False
    first = sample_val[0]
    return isinstance(first, dict) and "senses" in first and isinstance(first.get("senses"), dict)


def get_senses_for_lemma(senses_data, word, lemma, is_analysis_format):
    """Return a flat list of sense dicts and a {sense_id: sense} map for a word|lemma.

    Handles both the old flat-list format (keyed by word|lemma) and the new
    analysis-based format (keyed by word, analyses with headword + senses dict).
    """
    if is_analysis_format:
        analyses = senses_data.get(word, [])
        for analysis in analyses:
            headword = analysis.get("headword", word)
            if headword == lemma:
                sense_map = analysis.get("senses", {})
                flat = list(sense_map.values())
                return flat, sense_map
        # Fallback: try first analysis if lemma matches word
        if lemma == word and analyses:
            sense_map = analyses[0].get("senses", {})
            return list(sense_map.values()), sense_map
        return [], {}
    else:
        # Old format: word|lemma key -> flat list of sense dicts
        key = "%s|%s" % (word, lemma)
        senses = senses_data.get(key, [])
        if isinstance(senses, list):
            # Build ID map from pos|translation hashes for compatibility
            sense_map = {}
            for s in senses:
                full_hash = hashlib.md5(
                    ("%s|%s" % (s["pos"], s["translation"])).encode("utf-8")
                ).hexdigest()
                for length in range(3, len(full_hash) + 1):
                    sid = full_hash[:length]
                    if sid not in sense_map:
                        break
                sense_map[sid] = s
            return senses, sense_map
        return [], {}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Assemble final vocabulary from layers")
    parser.add_argument("--language", choices=("spanish", "french"), default="spanish",
                        help="Target language (default: spanish)")
    parser.add_argument("--sense-source", choices=("wiktionary", "spanishdict"),
                        default="spanishdict",
                        help="Sense source to assemble from (default: spanishdict)")
    parser.add_argument("--remainders", action="store_true",
                        help="Emit SENSE_CYCLE remainder buckets for unassigned examples "
                             "(default: off — cleaner cards; unassigned examples dropped)")
    parser.add_argument("--min-priority", type=int, default=None,
                        help="Drop assignments whose method priority is below N. "
                             "Their examples become orphans (eligible for remainders "
                             "when --remainders is on). Defaults from "
                             "config/config.json languages.{language}.pipelineDefaults.minPriority; "
                             "falls back to 0 when unset. "
                             "Useful values: 15 (skip keyword-tier), 30 (biencoder+), "
                             "50 (Gemini only).")
    args = parser.parse_args()
    _bind_paths(args.language)
    default_min_priority = get_default_min_priority(NORMAL_MODE_LANGUAGE, fallback=0)
    if args.min_priority is None:
        args.min_priority = default_min_priority
        print("min-priority: %d (from config/config.json: languages.%s.pipelineDefaults)"
              % (args.min_priority, NORMAL_MODE_LANGUAGE))
    else:
        print("min-priority: %d (from --min-priority flag)" % args.min_priority)

    # Load all layers
    print("Loading layers...")

    with open(LAYERS / "word_inventory.json", encoding="utf-8") as f:
        raw_inventory = json.load(f)
    print(f"  word_inventory: {len(raw_inventory)} raw entries")

    inventory, is_new_inv = _normalise_inventory(raw_inventory)
    print(f"  normalised to {len(inventory)} surface words"
          f" ({'new' if is_new_inv else 'old'} format)")

    with open(LAYERS / "examples_raw.json", encoding="utf-8") as f:
        examples_raw = json.load(f)
    print(f"  examples_raw: {len(examples_raw)} entries with examples")

    # When old inventory has hex-ID-keyed layer files, remap to surface words.
    # Build hex->word mapping from the raw inventory (only for old format).
    hex_to_word = {}
    if not is_new_inv:
        for entry in raw_inventory:
            eid = entry.get("id")
            if eid:
                hex_to_word[eid] = entry["word"].lower()

    def _rekey_to_surface(data, label):
        """Re-key a dict from hex IDs to surface words, merging duplicates."""
        if not hex_to_word or not data:
            return data
        # Check if already surface-word keyed (no hex ID keys found)
        sample_keys = list(data.keys())[:10]
        if any(k in hex_to_word for k in sample_keys):
            rekeyed = {}
            for k, v in data.items():
                word = hex_to_word.get(k, k)
                if word in rekeyed:
                    # Merge: concatenate lists
                    if isinstance(rekeyed[word], list) and isinstance(v, list):
                        rekeyed[word] = rekeyed[word] + v
                    else:
                        rekeyed[word] = v
                else:
                    rekeyed[word] = v
            print(f"  {label}: rekeyed {len(data)} hex entries -> {len(rekeyed)} surface words")
            return rekeyed
        return data

    examples_raw = _rekey_to_surface(examples_raw, "examples_raw")

    menu_path = sense_menu_path(LAYERS, args.sense_source)
    with open(menu_path, encoding="utf-8") as f:
        senses_data = json.load(f)
    is_analysis_menu = _is_analysis_based_menu(senses_data)
    print(f"  sense_menu ({args.sense_source}): {len(senses_data)} entries"
          f" ({'analysis-based' if is_analysis_menu else 'flat'})")

    # Load sense assignments (prefer lemma-split version)
    assignments_path = sense_assignments_lemma_path(LAYERS, args.sense_source)
    assignments_label = "sense_assignments_lemma/%s" % args.sense_source
    if not assignments_path.exists():
        from util_5c_sense_paths import sense_assignments_path as _sa_path
        assignments_path = _sa_path(LAYERS, args.sense_source)
        assignments_label = "sense_assignments/%s" % args.sense_source
    if assignments_path.exists():
        assignments = load_assignments(assignments_path)
        print(f"  {assignments_label}: {len(assignments)} assigned entries")
    else:
        assignments = {}
        print(f"  sense_assignments: (not found, proceeding without)")

    # Merge POS-refined layer (overwrites per-word methods with pos-* variants)
    pos_path = LAYERS / "sense_assignments_pos.json"
    if pos_path.exists():
        with open(pos_path, encoding="utf-8") as f:
            pos_assigns = json.load(f)
        for k, methods in pos_assigns.items():
            if k not in assignments:
                assignments[k] = {}
            if isinstance(assignments[k], dict):
                assignments[k].update(methods)
        print(f"  sense_assignments_pos: {len(pos_assigns)} POS-refined entries merged")

    # Load curated translation overrides (shared/ at project root, with
    # archive fallback for files relocated during the refactor).
    curated = {}
    curated_path = PROJECT_ROOT / "shared" / "curated_translations.json"
    if not curated_path.exists():
        _archived = PROJECT_ROOT / "shared" / "archive" / "curated_translations.json"
        if _archived.exists():
            curated_path = _archived
    if curated_path.exists():
        with open(curated_path, encoding="utf-8") as f:
            raw_curated = json.load(f)
        # Apply only entries whose mode matches the current --sense-source,
        # or that explicitly target "all" (or legacy "shared"/"normal" that
        # predate per-source scoping). mode="archive" and anything else is
        # retained in the file but never applied.
        active_modes = {args.sense_source, "all", "shared", "normal"}
        for k, v in raw_curated.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict):
                if v.get("mode") in active_modes:
                    curated[k] = v
            else:
                curated[k] = {"translation": v, "pos": "X"}
        print(f"  curated_translations: {len(curated)} overrides "
              f"(filtered by sense-source={args.sense_source!r})")

    mwe_path = LAYERS / "mwe_phrases.json"
    if mwe_path.exists():
        with open(mwe_path, encoding="utf-8") as f:
            mwe_data = json.load(f)
        mwe_data = _rekey_to_surface(mwe_data, "mwe_phrases")
        print(f"  mwe_phrases: {len(mwe_data)} words with MWEs")
    else:
        mwe_data = {}
        print("  mwe_phrases: (not found, skipping)")

    cognates_path = LAYERS / "cognates.json"
    if cognates_path.exists():
        with open(cognates_path, encoding="utf-8") as f:
            cognates = json.load(f)
        print(f"  cognates: {len(cognates)} entries")
    else:
        cognates = {}
        print("  cognates: (not found, skipping)")

    conj_reverse_path = LAYERS / "conjugation_reverse.json"
    if conj_reverse_path.exists():
        with open(conj_reverse_path, encoding="utf-8") as f:
            conj_reverse = json.load(f)
        print(f"  conjugation_reverse: {len(conj_reverse)} forms")
    else:
        conj_reverse = {}
        print("  conjugation_reverse: (not found, skipping)")

    # Wiktionary-derived morphology layer (tool_4a_build_morphology_layer).
    # Same shape as conjugation_reverse — used as the primary source for
    # mood/tense/person stamping because Wiktionary covers ~42% more verb
    # forms than verbecc on this corpus (voseo, regional slang, clitic
    # bundles). Verbecc remains the fallback for the canonical paradigms
    # Wiktionary skips.
    morphology_path = LAYERS / "morphology.json"
    if morphology_path.exists():
        with open(morphology_path, encoding="utf-8") as f:
            wikt_morph = json.load(f)
        print(f"  morphology (wiktionary): {len(wikt_morph)} forms")
    else:
        wikt_morph = {}
        print("  morphology (wiktionary): (not found, falling back to verbecc only)")

    # SpanishDict-derived synonyms/antonyms layer (tool_5e_build_synonyms_layer).
    # Keyed by lemma; value is {synonyms: [...], antonyms: [...]} where each
    # item is {word, strength, context?}. Strength is the absolute relationship
    # value (2 = strong, 1 = weak/related). Optional — runs without when the
    # thesaurus cache hasn't been built yet.
    synonyms_path = LAYERS / "synonyms.json"
    if synonyms_path.exists():
        with open(synonyms_path, encoding="utf-8") as f:
            synonyms_layer = json.load(f)
        print(f"  synonyms (spanishdict): {len(synonyms_layer)} lemmas")
    else:
        synonyms_layer = {}
        print("  synonyms (spanishdict): (not found, skipping)")

    # SpanishDict surface cache — needed for `related_lemma`, the
    # morphological pointer SpanishDict attaches to words whose
    # dictionary headword is lexicalised separately from their
    # conjugation source (classic case: ``hay`` is its own dict
    # headword but ``possible_results`` flags it as a conjugation of
    # ``haber``). See util_5c_spanishdict.conjugation_lemma_from_possible_results.
    if SPANISHDICT_SURFACE_CACHE.exists():
        with open(SPANISHDICT_SURFACE_CACHE, encoding="utf-8") as f:
            spanishdict_surface_cache = json.load(f)
        print(f"  spanishdict_surface_cache: {len(spanishdict_surface_cache)} entries")
    else:
        spanishdict_surface_cache = {}
        print("  spanishdict_surface_cache: (not found, related_lemma disabled)")

    # Clitic routing: read from word_routing.json (produced by step_4a_route_clitics.py)
    routing_path = LAYERS / "word_routing.json"
    clitic_merge_map = {}  # word -> base_form
    clitic_keep_set = set()
    if routing_path.exists():
        with open(routing_path, encoding="utf-8") as f:
            routing = json.load(f)
        clitic_merge_map = routing.get("clitic_merge", {})
        clitic_keep_set = set(routing.get("clitic_keep", []))
        print(f"\n  word_routing: {len(clitic_merge_map)} clitic_merge, "
              f"{len(clitic_keep_set)} clitic_keep")
    else:
        print("\n  word_routing.json not found — skipping clitic merge")
        print("    (run step_4a_route_clitics.py to enable)")

    # Build lookup: surface word -> inventory entry (for clitic base verb lookup)
    inv_by_word = {e["word"].lower(): e for e in inventory}

    # Pre-index: for each assignment key "word|lemma", build word -> [lemma] mapping
    assignment_lemmas_by_word = defaultdict(list)
    for key in assignments:
        if "|" in key:
            w, lem = key.split("|", 1)
            assignment_lemmas_by_word[w.lower()].append(lem)

    # In old format, also seed lemma info from the raw inventory entries
    if not is_new_inv:
        for entry in raw_inventory:
            w = entry["word"].lower()
            lem = entry.get("lemma", w)
            if lem not in assignment_lemmas_by_word[w]:
                assignment_lemmas_by_word[w].append(lem)

    # Apply clitic merge routing
    clitic_merged_words = set()
    clitic_data = {}
    id_migration = {}

    for wl, base_form in clitic_merge_map.items():
        entry = inv_by_word.get(wl)
        if not entry:
            continue
        base_entry = inv_by_word.get(base_form)
        if not base_entry:
            continue

        # Add clitic count to base
        base_entry["corpus_count"] = base_entry.get("corpus_count", 0) + entry.get("corpus_count", 0)

        # Find the clitic's lemma assignments
        clitic_lemmas = assignment_lemmas_by_word.get(wl, [wl])
        clitic_assigns_all = {}
        for lem in clitic_lemmas:
            key = "%s|%s" % (wl, lem)
            raw = assignments.get(key, {})
            if isinstance(raw, dict):
                clitic_assigns_all.update(raw)

        first_lemma = clitic_lemmas[0] if clitic_lemmas else wl
        clitic_senses, _ = get_senses_for_lemma(
            senses_data, wl, first_lemma, is_analysis_menu)
        translation = clitic_senses[0]["translation"] if clitic_senses else ""

        clitic_exs = examples_raw.get(wl, examples_raw.get(entry.get("id", ""), []))

        clitic_data[wl] = {
            "base_verb": base_form,
            "lemma": first_lemma,
            "corpus_count": entry.get("corpus_count", 0),
            "translation": translation,
            "assignments": clitic_assigns_all,
            "examples": clitic_exs,
        }
        base_entry.setdefault("variants", []).append(wl)
        clitic_merged_words.add(wl)

    if clitic_data:
        print(f"  {len(clitic_data)} clitic forms merged into base verbs")

    # Build vocabulary
    print("\nAssembling vocabulary...")
    used_ids = set()  # track hex IDs for collision avoidance
    all_entries = []   # (word, lemma, corpus_count, entry_dict) for sorting
    stats = {"no_senses": 0, "with_examples": 0, "cleaned": 0, "with_mwes": 0,
             "with_morphology": 0, "with_synonyms": 0, "clitic_merged": len(clitic_data)}

    for inv_entry in inventory:
        word = inv_entry["word"]
        wl = word.lower()

        if wl in clitic_merged_words:
            continue

        total_count = inv_entry.get("corpus_count", 0)

        # Find all word|lemma keys from assignments for this surface word
        lemmas = assignment_lemmas_by_word.get(wl, [])

        # Also check known_lemmas from the inventory (new format)
        if inv_entry.get("known_lemmas"):
            for kl in inv_entry["known_lemmas"]:
                if kl not in lemmas:
                    lemmas.append(kl)

        # Fallback: word|word if no lemma assignments found
        if not lemmas:
            lemmas = [wl]

        # Deduplicate while preserving order
        seen_lemmas = set()
        unique_lemmas = []
        for lem in lemmas:
            if lem not in seen_lemmas:
                seen_lemmas.add(lem)
                unique_lemmas.append(lem)
        lemmas = unique_lemmas

        # Split corpus_count across lemmas.
        # If old-format pre-split counts are available, use them directly.
        # Otherwise, split proportionally based on assigned example counts.
        pre_split = inv_entry.get("lemma_counts")
        if pre_split and all(lem in pre_split for lem in lemmas):
            split_counts = [pre_split[lem] for lem in lemmas]
        elif len(lemmas) == 1:
            split_counts = [total_count]
        else:
            example_counts = []
            for lem in lemmas:
                key = "%s|%s" % (wl, lem)
                raw_assigns = assignments.get(key, {})
                n = 0
                if isinstance(raw_assigns, dict):
                    for items in raw_assigns.values():
                        for item in items:
                            n += len(item.get("examples", []))
                example_counts.append(n)
            split_counts = split_count_proportionally(total_count, example_counts)

        # Examples and MWEs are shared across all lemmas of the same surface word
        # Look up by surface word first, then by old hex ID for backward compat
        word_examples = examples_raw.get(wl, examples_raw.get(
            inv_entry.get("id", ""), []))
        word_mwes_raw = mwe_data.get(wl, mwe_data.get(
            inv_entry.get("id", ""), []))

        # Produce one output entry per lemma
        for i, lemma in enumerate(lemmas):
            entry_count = split_counts[i]
            key = "%s|%s" % (wl, lemma)

            # Generate hex ID at assembly time
            hex_id = make_stable_id(wl, lemma, used_ids)
            used_ids.add(hex_id)

            # Look up senses
            senses, sense_id_map = get_senses_for_lemma(
                senses_data, wl, lemma, is_analysis_menu)
            id_list = list(sense_id_map.keys())

            # Resolve assignments: per-example highest-priority method wins.
            # Each sense becomes one meaning; examples inside a meaning may
            # carry different methods (stamped per-example downstream).
            raw_assigns = assignments.get(key, {})
            per_sense = (resolve_best_per_example(raw_assigns, min_priority=args.min_priority)
                         if isinstance(raw_assigns, dict) else {})

            # Group per-sense examples by sense_idx. Multiple sids can resolve
            # to the same idx when foreign sense IDs (e.g. from a phrasebook
            # analysis folded into this lemma) fall back to sense_idx=0; without
            # this merge we'd emit one duplicate meaning per such sid.
            by_idx = {}  # sense_idx -> list of example entries
            for sid, ex_list in per_sense.items():
                if sid in sense_id_map:
                    sense_idx = id_list.index(sid)
                elif senses:
                    sense_idx = 0
                else:
                    continue
                by_idx.setdefault(sense_idx, []).extend(ex_list)

            word_assignments = [
                {"sense_idx": idx, "examples": exs}
                for idx, exs in by_idx.items()
            ]

            # Build meanings from senses + assignments
            meanings_full = []
            meanings_lean = []
            examples_by_meaning = []

            curated_entry = curated.get(key)

            if not senses:
                stats["no_senses"] += 1
                c_trans = curated_entry["translation"] if curated_entry else ""
                c_pos = curated_entry.get("pos", "X") if curated_entry else "X"
                if word_examples:
                    fallback_examples = word_examples[:5]
                    meanings_full.append({
                        "pos": c_pos, "translation": c_trans, "frequency": "1.00",
                        "examples": fallback_examples,
                    })
                    meanings_lean.append({
                        "pos": c_pos, "translation": c_trans, "frequency": "1.00",
                    })
                    examples_by_meaning.append(fallback_examples)
            elif not word_assignments:
                if curated_entry:
                    cleaned = curated_entry["translation"]
                    pos = curated_entry.get("pos") or senses[0]["pos"]
                else:
                    cleaned = clean_translation(senses[0]["translation"])
                    pos = senses[0]["pos"]
                meaning_lean = {
                    "pos": pos,
                    "translation": cleaned,
                    "frequency": "1.00",
                }
                if cleaned != senses[0]["translation"]:
                    meaning_lean["detail"] = senses[0]["translation"]
                src = senses[0].get("source")
                if src:
                    meaning_lean["source"] = src
                meanings_lean.append(meaning_lean)
                meanings_full.append({**meaning_lean, "examples": []})
                examples_by_meaning.append([])
            else:
                total_assigned = sum(len(a["examples"]) for a in word_assignments)
                for a in word_assignments:
                    sense_idx = a.get("sense_idx", 0)
                    if sense_idx >= len(senses):
                        continue
                    sense = senses[sense_idx]
                    ex_list = a.get("examples", [])  # [{"ex_idx", "method"}]

                    # Build per-example dicts with method stamps.
                    exs = []
                    methods_in_meaning = set()
                    for entry in ex_list:
                        ex_idx = entry.get("ex_idx")
                        method = entry.get("method")
                        if ex_idx is None or ex_idx >= len(word_examples):
                            continue
                        src = word_examples[ex_idx]
                        if isinstance(src, dict):
                            ex_copy = dict(src)
                            if method:
                                ex_copy["assignment_method"] = method
                                methods_in_meaning.add(method)
                            exs.append(ex_copy)
                        else:
                            exs.append(src)

                    freq = len(ex_list) / total_assigned if total_assigned > 0 else 0
                    if curated_entry:
                        cleaned = curated_entry["translation"]
                        pos = curated_entry.get("pos") or sense["pos"]
                    else:
                        cleaned = clean_translation(sense["translation"])
                        pos = sense["pos"]
                    meaning_lean = {
                        "pos": pos,
                        "translation": cleaned,
                        "frequency": f"{freq:.2f}",
                    }
                    detail = sense.get("detail", "")
                    if not detail and cleaned != sense["translation"]:
                        detail = sense["translation"]
                    if detail and detail != cleaned:
                        meaning_lean["detail"] = detail
                        stats["cleaned"] += 1
                    src = sense.get("source")
                    if src:
                        meaning_lean["source"] = src
                    # Preserve the SpanishDict context field for later
                    # disambiguation: if two senses share (pos, translation)
                    # but have different contexts, we'll expose the context
                    # on those meaning rows.
                    ctx = sense.get("context")
                    if ctx:
                        meaning_lean["context"] = ctx

                    # Meaning-level stamp: only when every contributing method
                    # is keyword-tier (0 < prio <= KEYWORD_PRIORITY_THRESHOLD).
                    # Front-end uses this as a low-trust caveat for the whole
                    # meaning; non-keyword methods suppress it.
                    if methods_in_meaning and all(
                        0 < METHOD_PRIORITY.get(m, 0) <= KEYWORD_PRIORITY_THRESHOLD
                        for m in methods_in_meaning
                    ):
                        stamp = max(methods_in_meaning,
                                    key=lambda m: METHOD_PRIORITY.get(m, 0))
                        meaning_lean["assignment_method"] = stamp

                    meanings_lean.append(meaning_lean)
                    meanings_full.append({**meaning_lean, "examples": exs})
                    examples_by_meaning.append(exs)

            # Always collapse meaning rows that share (pos, translation, context).
            # Context preserves distinctions SpanishDict makes between senses
            # with the same surface translation (e.g. 'uno' as numeral vs
            # impersonal). Rows with same pos+translation AND matching/empty
            # context collapse; rows with same pos+translation but differing
            # contexts stay separate. After dedup, context is surfaced on
            # the visible translation ONLY when it's needed to disambiguate
            # (i.e. another meaning shares this pos+translation).
            if len(meanings_lean) > 1:
                merged_lean = {}
                merged_full = {}
                merged_exs = {}
                order = []
                for m_lean, m_full, exs in zip(meanings_lean, meanings_full, examples_by_meaning):
                    key2 = (m_lean.get("pos"), m_lean.get("translation"), m_lean.get("context") or "")
                    if key2 not in merged_lean:
                        order.append(key2)
                        merged_lean[key2] = dict(m_lean)
                        merged_full[key2] = {**m_full, "examples": list(exs)}
                        merged_exs[key2] = list(exs)
                    else:
                        # Accumulate frequency; extend examples
                        try:
                            f1 = float(merged_lean[key2].get("frequency", 0))
                            f2 = float(m_lean.get("frequency", 0))
                            merged_lean[key2]["frequency"] = f"{f1 + f2:.2f}"
                            merged_full[key2]["frequency"] = merged_lean[key2]["frequency"]
                        except (TypeError, ValueError):
                            pass
                        merged_exs[key2].extend(exs)
                        merged_full[key2]["examples"] = list(merged_exs[key2])
                        # Keep the detail field from the most-frequent original
                        # meaning (heuristic) — since all were curated to the
                        # same translation, detail is the only differentiator.
                meanings_lean = [merged_lean[k] for k in order]
                meanings_full = [merged_full[k] for k in order]
                examples_by_meaning = [merged_exs[k] for k in order]

            # Context is preserved as its own field on each meaning row
            # when available from the source menu (SpanishDict sub-sense
            # label like "to move fast" for correr→to run). The front end
            # renders it as a subtitle/tag under the translation; dedup
            # already keyed on (pos, translation, context) so rows with
            # distinct contexts remain as separate meanings.

            if not meanings_lean:
                continue

            # MWE memberships (shared across lemmas of the same surface word)
            mwe_memberships = None
            mwe_examples_by_idx = None
            if word_mwes_raw:
                mwe_memberships = []
                mwe_examples_by_idx = []
                for mwe in word_mwes_raw:
                    mwe_entry = {"expression": mwe["expression"]}
                    if mwe.get("translation"):
                        mwe_entry["translation"] = mwe["translation"]
                    # Two context tiers:
                    #   * ``context`` — real, structured, scraped from
                    #     SpanishDict's per-phrase page (authoritative).
                    #   * ``context_heuristic`` — split off the quickdef
                    #     string by regex (best-effort). UI prefers ``context``
                    #     and falls back to ``context_heuristic`` only when
                    #     the real field is missing.
                    if mwe.get("context"):
                        mwe_entry["context"] = mwe["context"]
                    if mwe.get("context_heuristic"):
                        mwe_entry["context_heuristic"] = mwe["context_heuristic"]
                    if mwe.get("source"):
                        mwe_entry["source"] = mwe["source"]
                    mwe_memberships.append(mwe_entry)
                    expr_lower = mwe["expression"].lower()
                    matched_exs = [
                        ex for ex in word_examples
                        if expr_lower in (ex.get("target", "") or ex.get("spanish", "")).lower()
                    ]
                    mwe_examples_by_idx.append(matched_exs[:5])
                stats["with_mwes"] += 1

            # Morphology stamping. Wiktionary first (richer coverage —
            # voseo, regional slang, clitic bundles), verbecc fills the
            # canonical-paradigm gaps Wiktionary skips. Both lookups share
            # the {lemma, mood, tense, person} shape.
            morphology = None
            if wl != lemma.lower():
                lemma_l = lemma.lower()
                matches = [
                    {"mood": c["mood"], "tense": c["tense"], "person": c["person"]}
                    for c in wikt_morph.get(wl, [])
                    if c["lemma"] == lemma_l
                ]
                if not matches and conj_reverse:
                    matches = [
                        {"mood": c["mood"], "tense": c["tense"], "person": c["person"]}
                        for c in conj_reverse.get(wl, [])
                        if c["lemma"] == lemma_l
                    ]
                if len(matches) == 1:
                    morphology = matches[0]
                elif len(matches) > 1:
                    morphology = matches
            elif wl == lemma.lower():
                has_verb = any(m["pos"] == "VERB" for m in senses)
                if has_verb:
                    morphology = {"mood": "infinitivo"}

            # Synonyms / antonyms — looked up by lemma (since they're a
            # property of the lexeme, not the surface form). A multi-form
            # paradigm (hablar / hablo / habla / habló) all reuse the same
            # hablar entry from the layer.
            syn_entry = synonyms_layer.get(lemma.lower()) or {}
            synonyms_list = syn_entry.get("synonyms") or None
            antonyms_list = syn_entry.get("antonyms") or None

            # Cognate signals (keyed by word|lemma)
            cognate_obj = cognates.get(key)
            if isinstance(cognate_obj, (int, float)):
                cognate_obj = {"score": cognate_obj}
            elif cognate_obj is True:
                cognate_obj = {"score": 1.0}

            # Remainder-bucket toggle: drop SENSE_CYCLE / unassigned meaning
            # rows unless explicitly enabled. Normal-mode builder doesn't
            # currently emit these, but the filter is safe and consistent
            # with the artist builder — future remainder logic here will
            # pick up the toggle automatically.
            if not args.remainders:
                def _keep(m):
                    return m.get("pos") != "SENSE_CYCLE" and not m.get("unassigned")
                filtered_full = []
                filtered_lean = []
                filtered_exs = []
                for m_full, m_lean, exs in zip(meanings_full, meanings_lean, examples_by_meaning):
                    if _keep(m_lean):
                        filtered_full.append(m_full)
                        filtered_lean.append(m_lean)
                        filtered_exs.append(exs)
                meanings_full = filtered_full
                meanings_lean = filtered_lean
                examples_by_meaning = filtered_exs
                if not meanings_lean:
                    continue

            # `related_lemma` — SpanishDict's morphological pointer for
            # lexicalised conjugated-form headwords. Stamped only when the
            # SD pointer differs from this card's semantic lemma, so it
            # doesn't duplicate information already on the card. UI uses
            # this to surface the related verb's paradigm when the card's
            # own lemma has no inline conjugation data (e.g. ``hay`` has
            # ``lemma=hay`` but ``related_lemma=haber``, so the panel can
            # fall through to haber's paradigm labelled as related).
            related_lemma = None
            sd_entry = spanishdict_surface_cache.get(word.lower())
            if sd_entry:
                sd_conj = conjugation_lemma_from_possible_results(sd_entry)
                if sd_conj and sd_conj != lemma:
                    related_lemma = sd_conj

            # Collect the entry (sort and compute most_frequent later)
            all_entries.append({
                "word": word,
                "lemma": lemma,
                "id": hex_id,
                "corpus_count": entry_count,
                "meanings_full": meanings_full,
                "meanings_lean": meanings_lean,
                "examples_by_meaning": examples_by_meaning,
                "cognate_obj": cognate_obj,
                "mwe_memberships": mwe_memberships,
                "mwe_examples_by_idx": mwe_examples_by_idx,
                "morphology": morphology,
                "synonyms": synonyms_list,
                "antonyms": antonyms_list,
                "variants": inv_entry.get("variants"),
                "related_lemma": related_lemma,
            })
            if morphology:
                stats["with_morphology"] += 1
            if synonyms_list or antonyms_list:
                stats["with_synonyms"] += 1

    # Re-sort by corpus_count desc so lemma-split entries slot into their
    # true frequency position (otherwise e.g. para|parar (323) would sit
    # right after para|para (6145) because both inherited inventory order).
    all_entries.sort(key=lambda e: -e["corpus_count"])

    # Compute most_frequent_lemma_instance: for each lemma, the word|lemma
    # entry with the highest corpus_count gets True
    lemma_best = {}  # lemma -> (best_count, best_idx)
    for idx, e in enumerate(all_entries):
        lem = e["lemma"]
        cc = e["corpus_count"]
        if lem not in lemma_best or cc > lemma_best[lem][0]:
            lemma_best[lem] = (cc, idx)

    for idx, e in enumerate(all_entries):
        e["most_frequent_lemma_instance"] = (lemma_best.get(e["lemma"], (-1, -1))[1] == idx)

    # Write clitic layer (now that we have hex IDs for base verbs)
    if clitic_data:
        # Build base_word -> hex_id lookup from assembled entries
        base_hex_lookup = {}
        for e in all_entries:
            base_hex_lookup.setdefault(e["word"].lower(), {})[e["lemma"]] = e["id"]

        clitic_by_id = {}
        for cword, cinfo in clitic_data.items():
            # Generate a hex ID for the clitic itself
            clitic_hex = make_stable_id(cword, cinfo["lemma"], used_ids)
            used_ids.add(clitic_hex)
            cinfo["id"] = clitic_hex

            # Find the base verb's hex ID
            base_word = cinfo["base_verb"]
            base_lemmas = base_hex_lookup.get(base_word, {})
            base_id = next(iter(base_lemmas.values()), None) if base_lemmas else None
            cinfo["base_id"] = base_id

            clitic_by_id[clitic_hex] = cinfo

            if base_id:
                id_migration[clitic_hex] = base_id

        clitic_path = LAYERS / "clitic_forms.json"
        with open(clitic_path, "w", encoding="utf-8") as f:
            json.dump(clitic_by_id, f, ensure_ascii=False, indent=2)
        print(f"  Clitic forms: {len(clitic_by_id)} entries -> {clitic_path}")

        if id_migration:
            archive_dir = LAYERS / "archive"
            archive_dir.mkdir(exist_ok=True)
            migration_path = archive_dir / "clitic_id_migration.json"
            with open(migration_path, "w", encoding="utf-8") as f:
                json.dump(id_migration, f, ensure_ascii=False, indent=2)
            print(f"  ID migration: {len(id_migration)} mappings -> {migration_path}")

    # Precompute: base_id -> {clitic_id: clitic_word} for variant annotation
    merged_ids_by_base = {}
    for cword, cinfo in clitic_data.items():
        bid = cinfo.get("base_id")
        cid = cinfo.get("id")
        if bid and cid:
            merged_ids_by_base.setdefault(bid, {})[cid] = cword

    # Build final output lists
    monolith = []
    index = []
    examples_out = {}

    for e in all_entries:
        word_id = e["id"]

        mono_entry = {
            "word": e["word"],
            "lemma": e["lemma"],
            "id": word_id,
            "corpus_count": e["corpus_count"],
            "most_frequent_lemma_instance": e["most_frequent_lemma_instance"],
            "meanings": e["meanings_full"],
        }
        if e["cognate_obj"]:
            mono_entry["cognate_score"] = e["cognate_obj"]["score"]
            if e["cognate_obj"].get("cognet"):
                mono_entry["cognet_cognate"] = True
        if e["mwe_memberships"]:
            mono_entry["mwe_memberships"] = e["mwe_memberships"]
        if e["morphology"]:
            mono_entry["morphology"] = e["morphology"]
        if e.get("synonyms"):
            mono_entry["synonyms"] = e["synonyms"]
        if e.get("antonyms"):
            mono_entry["antonyms"] = e["antonyms"]
        if e.get("related_lemma"):
            mono_entry["related_lemma"] = e["related_lemma"]
        if e.get("variants"):
            mono_entry["variants"] = e["variants"]
            merged_ids = merged_ids_by_base.get(word_id)
            if merged_ids:
                mono_entry["merged_clitic_ids"] = merged_ids
        monolith.append(mono_entry)

        idx_entry = {
            "word": e["word"],
            "lemma": e["lemma"],
            "id": word_id,
            "corpus_count": e["corpus_count"],
            "most_frequent_lemma_instance": e["most_frequent_lemma_instance"],
            "meanings": e["meanings_lean"],
        }
        if e["cognate_obj"]:
            idx_entry["cognate_score"] = e["cognate_obj"]["score"]
            if e["cognate_obj"].get("cognet"):
                idx_entry["cognet_cognate"] = True
        if e["mwe_memberships"]:
            idx_entry["mwe_memberships"] = e["mwe_memberships"]
        if e["morphology"]:
            idx_entry["morphology"] = e["morphology"]
        if e.get("synonyms"):
            idx_entry["synonyms"] = e["synonyms"]
        if e.get("antonyms"):
            idx_entry["antonyms"] = e["antonyms"]
        if e.get("related_lemma"):
            idx_entry["related_lemma"] = e["related_lemma"]
        index.append(idx_entry)

        ex_entry = {}
        if any(e["examples_by_meaning"]):
            ex_entry["m"] = e["examples_by_meaning"]
            stats["with_examples"] += 1
        if e["mwe_examples_by_idx"] and any(e["mwe_examples_by_idx"]):
            ex_entry["w"] = e["mwe_examples_by_idx"]
        if ex_entry:
            examples_out[word_id] = ex_entry

    # Write outputs
    monolith_path = OUTPUT_DIR / "vocabulary.json"
    index_path = OUTPUT_DIR / "vocabulary.index.json"
    examples_path = OUTPUT_DIR / "vocabulary.examples.json"

    print(f"\nWriting {monolith_path}...")
    with open(monolith_path, "w", encoding="utf-8") as f:
        json.dump(monolith, f, ensure_ascii=False, indent=2)
    write_sidecar(monolith_path, make_meta("assemble_vocabulary", STEP_VERSION))

    print(f"Writing {index_path}...")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    write_sidecar(index_path, make_meta("assemble_vocabulary", STEP_VERSION))

    print(f"Writing {examples_path}...")
    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(examples_out, f, ensure_ascii=False)
    write_sidecar(examples_path, make_meta("assemble_vocabulary", STEP_VERSION))

    # Report
    print(f"\n{'='*55}")
    print("BUILD RESULTS")
    print(f"{'='*55}")
    print(f"Total entries:      {len(monolith):>6}")
    print(f"With examples:      {stats['with_examples']:>6}")
    print(f"No senses (pos=X):  {stats['no_senses']:>6}")
    print(f"Translations cleaned: {stats['cleaned']:>5}")
    print(f"With MWEs:          {stats['with_mwes']:>6}")
    print(f"With morphology:    {stats['with_morphology']:>6}")
    print(f"With synonyms:      {stats['with_synonyms']:>6}")
    print(f"Clitics merged:     {stats['clitic_merged']:>6}")
    print()

    # Sample output
    print("Sample entries:")
    sample_words = ["tiempo", "banco", "mejor", "hacer"]
    for entry in monolith:
        if entry["word"] in sample_words:
            sample_words.remove(entry["word"])
            print(f"\n  {entry['word']}|{entry['lemma']}:")
            for m in entry["meanings"]:
                n_ex = len(m.get("examples", []))
                ex = m["examples"][0]["english"][:50] if m.get("examples") else "(none)"
                print(f"    {m['pos']:>6} {m['translation']:>30}  "
                      f"freq={m['frequency']}  ex({n_ex}): {ex}")
            if not sample_words:
                break


if __name__ == "__main__":
    main()
