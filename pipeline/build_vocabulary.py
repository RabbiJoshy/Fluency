#!/usr/bin/env python3
"""
build_vocabulary.py — Step 5: Assemble final vocabulary from all layers.

Reads all layer files and produces the final split output for the front end:
  - vocabulary.index.json  (lean, eager load — no examples)
  - vocabulary.examples.json (lazy load — examples keyed by ID)
  - vocabulary.json (full monolith for debugging)

Sort order is determined by corpus_count (descending). The front end computes
rank from array position on load, so no rank field is stored.

Usage:
    python3 pipeline/build_vocabulary.py

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/layers/examples_raw.json
    Data/Spanish/layers/senses_wiktionary.json
    Data/Spanish/layers/sense_assignments.json
    Data/Spanish/layers/mwe_phrases.json (optional)

Outputs:
    Data/Spanish/vocabulary.index.json
    Data/Spanish/vocabulary.examples.json
    Data/Spanish/vocabulary.json
"""

import gzip
import json
import re
import sys
from pathlib import Path

from method_priority import (METHOD_PRIORITY, best_method_priority,
                              make_sense_id, assign_sense_ids)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"
OUTPUT_DIR = PROJECT_ROOT / "Data" / "Spanish"
WIKTIONARY_RAW = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "wiktionary" / "kaikki-spanish.jsonl.gz"


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
# Translation cleaning (same logic as build_senses.py)
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
# Builder
# ---------------------------------------------------------------------------
def main():
    # Load all layers
    print("Loading layers...")

    with open(LAYERS / "word_inventory.json", encoding="utf-8") as f:
        inventory = json.load(f)
    print(f"  word_inventory: {len(inventory)} entries")

    with open(LAYERS / "examples_raw.json", encoding="utf-8") as f:
        examples_raw = json.load(f)
    print(f"  examples_raw: {len(examples_raw)} entries with examples")

    with open(LAYERS / "senses_wiktionary.json", encoding="utf-8") as f:
        senses_data = json.load(f)
    print(f"  senses_wiktionary: {len(senses_data)} sense entries")

    with open(LAYERS / "sense_assignments.json", encoding="utf-8") as f:
        assignments = json.load(f)
    print(f"  sense_assignments: {len(assignments)} assigned entries")

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
    print(f"  Wiktionary: {len(clitic_map)} clitic forms, {len(verbs_with_refl)} verbs with reflexive senses")

    inv_by_word = {e["word"].lower(): e for e in inventory}
    clitic_merged_ids = set()  # IDs to skip in entry loop
    clitic_data = {}  # word -> {base_verb, examples, assignments, ...}
    id_migration = {}

    for e in inventory:
        wl = e["word"].lower()
        if wl not in clitic_map:
            continue
        base_verb, is_refl = clitic_map[wl]
        if is_refl and base_verb in verbs_with_refl:
            continue  # tier 3: keep separate
        base_entry = inv_by_word.get(base_verb)
        if not base_entry:
            continue
        clitic_id = e["id"]
        base_id = base_entry["id"]
        # Add clitic count to base
        base_entry["corpus_count"] = base_entry.get("corpus_count", 0) + e.get("corpus_count", 0)
        # Build self-contained clitic entry
        clitic_exs = examples_raw.get(clitic_id, [])
        clitic_key = f"{e['word']}|{e['lemma']}"
        clitic_raw_assigns = assignments.get(clitic_key, assignments.get(clitic_id, {}))
        clitic_senses = senses_data.get(clitic_key, [])
        translation = clitic_senses[0]["translation"] if clitic_senses else ""
        # Normalize to method-aware format
        if isinstance(clitic_raw_assigns, dict):
            converted_assigns = clitic_raw_assigns
        elif isinstance(clitic_raw_assigns, list) and clitic_senses:
            # Old format: convert positional to sense-ID-keyed
            sid_map = assign_sense_ids(clitic_senses)
            id_list = list(sid_map.keys())
            method_name = "biencoder"
            if clitic_raw_assigns and isinstance(clitic_raw_assigns[0], dict):
                method_name = clitic_raw_assigns[0].get("method", "biencoder")
            items = []
            for a in clitic_raw_assigns:
                idx = a.get("sense_idx", 0)
                if idx < len(id_list):
                    items.append({"sense": id_list[idx], "examples": a.get("examples", [])})
            converted_assigns = {method_name: items} if items else {}
        else:
            converted_assigns = {}
        clitic_data[wl] = {
            "id": clitic_id,
            "base_verb": base_verb,
            "base_id": base_id,
            "lemma": e["lemma"],
            "corpus_count": e.get("corpus_count", 0),
            "translation": translation,
            "assignments": converted_assigns,
            "examples": clitic_exs,
        }
        base_entry.setdefault("variants", []).append(wl)
        clitic_merged_ids.add(clitic_id)
        id_migration[clitic_id] = base_id

    if clitic_data:
        print(f"  {len(clitic_data)} clitic forms skipped from deck, data in clitic layer")
        # Write clitic layer
        clitic_by_id = {info["id"]: info for info in clitic_data.values()}
        clitic_path = LAYERS / "clitic_forms.json"
        with open(clitic_path, "w", encoding="utf-8") as f:
            json.dump(clitic_by_id, f, ensure_ascii=False, indent=2)
        print(f"  Clitic forms: {len(clitic_by_id)} entries -> {clitic_path}")
        archive_dir = LAYERS / "archive"
        archive_dir.mkdir(exist_ok=True)
        migration_path = archive_dir / "clitic_id_migration.json"
        with open(migration_path, "w", encoding="utf-8") as f:
            json.dump(id_migration, f, ensure_ascii=False, indent=2)
        print(f"  ID migration: {len(id_migration)} mappings -> {migration_path}")

    # Precompute: base_id -> {clitic_id: clitic_word}
    merged_ids_by_base = {}
    for cword, cinfo in clitic_data.items():
        bid = cinfo.get("base_id")
        if bid:
            merged_ids_by_base.setdefault(bid, {})[cinfo["id"]] = cword

    # Build vocabulary
    print("\nAssembling vocabulary...")
    monolith = []
    index = []
    examples_out = {}
    stats = {"no_senses": 0, "with_examples": 0, "cleaned": 0, "with_mwes": 0,
             "with_morphology": 0, "clitic_merged": len(clitic_data)}

    for entry in inventory:
        if entry["id"] in clitic_merged_ids:
            continue
        word_id = entry["id"]
        key = f"{entry['word']}|{entry['lemma']}"
        senses = senses_data.get(key, [])
        word_examples = examples_raw.get(word_id, [])

        # Resolve assignments: new format (word|lemma key, method-keyed)
        # with fallback to old format (hex ID key, flat list)
        raw_assigns = assignments.get(key, assignments.get(word_id, {}))

        # Normalize to flat list of {sense_idx, examples} for downstream
        word_assignments = []
        if isinstance(raw_assigns, dict) and raw_assigns:
            # New format: {method: [{sense, examples}]}
            best_method = max(raw_assigns.keys(),
                              key=lambda m: METHOD_PRIORITY.get(m, -1))
            sense_id_map = assign_sense_ids(senses) if senses else {}
            id_list = list(sense_id_map.keys())
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
        elif isinstance(raw_assigns, list):
            # Old format: [{sense_idx, examples}]
            word_assignments = raw_assigns

        # Build meanings from senses + assignments
        meanings_full = []  # For monolith (with examples)
        meanings_lean = []  # For index (no examples)
        examples_by_meaning = []  # For examples file

        # Check for curated override
        curated_key = f"{entry['word'].lower()}|{entry['lemma']}"
        curated_entry = curated.get(curated_key)

        if not senses:
            # No senses: use curated override if available, else fallback
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
            # Senses exist but no assignment (shouldn't happen, but handle gracefully)
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
            # Normal case: build from assignments
            total_assigned = sum(len(a["examples"]) for a in word_assignments)

            for a in word_assignments:
                sense_idx = a.get("sense_idx", 0)
                if sense_idx >= len(senses):
                    continue
                sense = senses[sense_idx]

                # Gather actual example objects
                exs = [word_examples[i] for i in a.get("examples", [])
                       if i < len(word_examples)]

                # Compute frequency from assignment counts
                freq = len(exs) / total_assigned if total_assigned > 0 else 0

                # Clean translation (curated override replaces Wiktionary)
                if curated_entry:
                    cleaned = curated_entry["translation"]
                else:
                    cleaned = clean_translation(sense["translation"])
                meaning_lean = {
                    "pos": sense["pos"],
                    "translation": cleaned,
                    "frequency": f"{freq:.2f}",
                }
                # Preserve detail
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
            # Edge case: no meanings at all, skip
            continue

        # MWE memberships
        word_mwes = mwe_data.get(word_id, [])
        mwe_memberships = None
        mwe_examples_by_idx = None
        if word_mwes:
            mwe_memberships = []
            mwe_examples_by_idx = []
            for mwe in word_mwes:
                mwe_entry = {"expression": mwe["expression"]}
                if mwe.get("translation"):
                    mwe_entry["translation"] = mwe["translation"]
                if mwe.get("source"):
                    mwe_entry["source"] = mwe["source"]
                mwe_memberships.append(mwe_entry)
                # Find examples containing this MWE expression
                expr_lower = mwe["expression"].lower()
                matched_exs = [
                    ex for ex in word_examples
                    if expr_lower in (ex.get("target", "") or ex.get("spanish", "")).lower()
                ]
                mwe_examples_by_idx.append(matched_exs[:5])
            stats["with_mwes"] += 1

        # Morphology from conjugation reverse lookup
        morphology = None
        if entry["word"].lower() != entry["lemma"].lower() and conj_reverse:
            candidates = conj_reverse.get(entry["word"].lower(), [])
            matches = [{"mood": c["mood"], "tense": c["tense"], "person": c["person"]}
                       for c in candidates if c["lemma"] == entry["lemma"].lower()]
            if len(matches) == 1:
                morphology = matches[0]
            elif len(matches) > 1:
                morphology = matches
        elif entry["word"].lower() == entry["lemma"].lower():
            # Tag infinitives: word == lemma and has a VERB meaning
            has_verb = any(m["pos"] == "VERB" for m in senses)
            if has_verb:
                morphology = {"mood": "infinitivo"}

        # Cognate signals (single layer, object per entry)
        cognate_key = f"{entry['word']}|{entry['lemma']}"
        cognate_obj = cognates.get(cognate_key)
        # Backward compat: old format stores bare float or True
        if isinstance(cognate_obj, (int, float)):
            cognate_obj = {"score": cognate_obj}
        elif cognate_obj is True:
            cognate_obj = {"score": 1.0}

        # Monolith entry
        mono_entry = {
            "word": entry["word"],
            "lemma": entry["lemma"],
            "id": word_id,
            "corpus_count": entry.get("corpus_count", 0),
            "most_frequent_lemma_instance": entry["most_frequent_lemma_instance"],
            "meanings": meanings_full,
        }
        if cognate_obj:
            mono_entry["cognate_score"] = cognate_obj["score"]
            if cognate_obj.get("cognet"):
                mono_entry["cognet_cognate"] = True
        if mwe_memberships:
            mono_entry["mwe_memberships"] = mwe_memberships
        if entry.get("homograph_ids"):
            mono_entry["homograph_ids"] = entry["homograph_ids"]
        if morphology:
            mono_entry["morphology"] = morphology
            stats["with_morphology"] += 1
        if entry.get("variants"):
            mono_entry["variants"] = entry["variants"]
            merged_ids = merged_ids_by_base.get(word_id)
            if merged_ids:
                mono_entry["merged_clitic_ids"] = merged_ids
        monolith.append(mono_entry)

        # Index entry (no examples)
        idx_entry = {
            "word": entry["word"],
            "lemma": entry["lemma"],
            "id": word_id,
            "corpus_count": entry.get("corpus_count", 0),
            "most_frequent_lemma_instance": entry["most_frequent_lemma_instance"],
            "meanings": meanings_lean,
        }
        if cognate_obj:
            idx_entry["cognate_score"] = cognate_obj["score"]
            if cognate_obj.get("cognet"):
                idx_entry["cognet_cognate"] = True
        if mwe_memberships:
            idx_entry["mwe_memberships"] = mwe_memberships
        if entry.get("homograph_ids"):
            idx_entry["homograph_ids"] = entry["homograph_ids"]
        if morphology:
            idx_entry["morphology"] = morphology
        index.append(idx_entry)

        # Examples file
        ex_entry = {}
        if any(examples_by_meaning):
            ex_entry["m"] = examples_by_meaning
            stats["with_examples"] += 1
        if mwe_examples_by_idx and any(mwe_examples_by_idx):
            ex_entry["w"] = mwe_examples_by_idx
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
