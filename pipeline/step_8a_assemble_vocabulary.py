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
from util_6a_method_priority import METHOD_PRIORITY
from util_8a_assembly_helpers import make_stable_id, split_count_proportionally

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"
OUTPUT_DIR = PROJECT_ROOT / "Data" / "Spanish"
WIKTIONARY_RAW = PROJECT_ROOT / "Data" / "Spanish" / "Senses" / "wiktionary" / "kaikki-spanish.jsonl.gz"


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
    parser.add_argument("--sense-source", choices=("wiktionary", "spanishdict"),
                        default="wiktionary",
                        help="Sense source to assemble from (default: wiktionary)")
    args = parser.parse_args()

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
        with open(assignments_path, encoding="utf-8") as f:
            assignments = json.load(f)
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

    # Load curated translation overrides (shared/ at project root)
    curated = {}
    curated_path = PROJECT_ROOT / "shared" / "curated_translations.json"
    if curated_path.exists():
        with open(curated_path, encoding="utf-8") as f:
            raw_curated = json.load(f)
        for k, v in raw_curated.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict):
                if v.get("mode") in ("shared", "normal"):
                    curated[k] = v
            else:
                curated[k] = {"translation": v, "pos": "X"}
        print(f"  curated_translations: {len(curated)} overrides")

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

    # Clitic detection: skip verb+clitic forms, write separate clitic layer
    print("\nDetecting clitics...")
    clitic_map, verbs_with_refl = load_clitic_map(WIKTIONARY_RAW)
    print(f"  Wiktionary: {len(clitic_map)} clitic forms,"
          f" {len(verbs_with_refl)} verbs with reflexive senses")

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

    # Clitic detection works on surface words
    clitic_merged_words = set()  # surface words to skip in entry loop
    clitic_data = {}             # surface_word -> clitic info dict
    id_migration = {}            # old clitic hex -> base hex (for reversibility)

    for entry in inventory:
        wl = entry["word"].lower()
        if wl not in clitic_map:
            continue
        base_verb, is_refl = clitic_map[wl]
        if is_refl and base_verb in verbs_with_refl:
            continue  # tier 3: keep separate
        base_entry = inv_by_word.get(base_verb)
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

        # Get senses for the clitic (try first lemma)
        first_lemma = clitic_lemmas[0] if clitic_lemmas else wl
        clitic_senses, _ = get_senses_for_lemma(
            senses_data, wl, first_lemma, is_analysis_menu)
        translation = clitic_senses[0]["translation"] if clitic_senses else ""

        # Get examples (keyed by surface word or hex ID)
        clitic_exs = examples_raw.get(wl, examples_raw.get(entry.get("id", ""), []))

        clitic_data[wl] = {
            "base_verb": base_verb,
            "lemma": first_lemma,
            "corpus_count": entry.get("corpus_count", 0),
            "translation": translation,
            "assignments": clitic_assigns_all,
            "examples": clitic_exs,
        }
        base_entry.setdefault("variants", []).append(wl)
        clitic_merged_words.add(wl)

    if clitic_data:
        print(f"  {len(clitic_data)} clitic forms skipped from deck, data in clitic layer")

    # Build vocabulary
    print("\nAssembling vocabulary...")
    used_ids = set()  # track hex IDs for collision avoidance
    all_entries = []   # (word, lemma, corpus_count, entry_dict) for sorting
    stats = {"no_senses": 0, "with_examples": 0, "cleaned": 0, "with_mwes": 0,
             "with_morphology": 0, "clitic_merged": len(clitic_data)}

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

            # Resolve assignments
            raw_assigns = assignments.get(key, {})
            word_assignments = []
            if isinstance(raw_assigns, dict) and raw_assigns:
                best_method = max(raw_assigns.keys(),
                                  key=lambda m: METHOD_PRIORITY.get(m, -1))
                for a in raw_assigns[best_method]:
                    sid = a.get("sense")
                    if sid and sid in sense_id_map:
                        word_assignments.append({
                            "sense_idx": id_list.index(sid),
                            "examples": a.get("examples", []),
                        })
                    elif senses:
                        word_assignments.append({
                            "sense_idx": 0,
                            "examples": a.get("examples", []),
                        })

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
                else:
                    cleaned = clean_translation(senses[0]["translation"])
                meaning_lean = {
                    "pos": senses[0]["pos"],
                    "translation": cleaned,
                    "frequency": "1.00",
                }
                if cleaned != senses[0]["translation"]:
                    meaning_lean["detail"] = senses[0]["translation"]
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
                    exs = [word_examples[j] for j in a.get("examples", [])
                           if j < len(word_examples)]
                    freq = len(exs) / total_assigned if total_assigned > 0 else 0
                    if curated_entry:
                        cleaned = curated_entry["translation"]
                    else:
                        cleaned = clean_translation(sense["translation"])
                    meaning_lean = {
                        "pos": sense["pos"],
                        "translation": cleaned,
                        "frequency": f"{freq:.2f}",
                    }
                    detail = sense.get("detail", "")
                    if not detail and cleaned != sense["translation"]:
                        detail = sense["translation"]
                    if detail and detail != cleaned:
                        meaning_lean["detail"] = detail
                        stats["cleaned"] += 1
                    meanings_lean.append(meaning_lean)
                    meanings_full.append({**meaning_lean, "examples": exs})
                    examples_by_meaning.append(exs)

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

            # Morphology from conjugation reverse lookup
            morphology = None
            if wl != lemma.lower() and conj_reverse:
                candidates = conj_reverse.get(wl, [])
                matches = [{"mood": c["mood"], "tense": c["tense"], "person": c["person"]}
                           for c in candidates if c["lemma"] == lemma.lower()]
                if len(matches) == 1:
                    morphology = matches[0]
                elif len(matches) > 1:
                    morphology = matches
            elif wl == lemma.lower():
                has_verb = any(m["pos"] == "VERB" for m in senses)
                if has_verb:
                    morphology = {"mood": "infinitivo"}

            # Cognate signals (keyed by word|lemma)
            cognate_obj = cognates.get(key)
            if isinstance(cognate_obj, (int, float)):
                cognate_obj = {"score": cognate_obj}
            elif cognate_obj is True:
                cognate_obj = {"score": 1.0}

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
                "variants": inv_entry.get("variants"),
            })
            if morphology:
                stats["with_morphology"] += 1

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

    print(f"Writing {index_path}...")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)

    print(f"Writing {examples_path}...")
    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(examples_out, f, ensure_ascii=False)

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
