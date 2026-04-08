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
    python3 Data/Spanish/Scripts/build_vocabulary.py

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

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"
OUTPUT_DIR = PROJECT_ROOT / "Data" / "Spanish"

# ---------------------------------------------------------------------------
# Translation cleaning (same logic as build_senses.py / finalize_vocabulary.py)
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
        print(f"  cognates: {len(cognates)} transparent cognates")
    else:
        cognates = {}
        print("  cognates: (not found, skipping)")

    # Build vocabulary
    print("\nAssembling vocabulary...")
    monolith = []
    index = []
    examples_out = {}
    stats = {"no_senses": 0, "with_examples": 0, "cleaned": 0, "with_mwes": 0}

    for entry in inventory:
        word_id = entry["id"]
        key = f"{entry['word']}|{entry['lemma']}"
        senses = senses_data.get(key, [])
        word_examples = examples_raw.get(word_id, [])
        word_assignments = assignments.get(word_id, [])

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
                sense_idx = a["sense_idx"]
                if sense_idx >= len(senses):
                    continue
                sense = senses[sense_idx]

                # Gather actual example objects
                exs = [word_examples[i] for i in a["examples"]
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
                mwe_memberships.append(mwe_entry)
                # Find examples containing this MWE expression
                expr_lower = mwe["expression"].lower()
                matched_exs = [
                    ex for ex in word_examples
                    if expr_lower in (ex.get("target", "") or ex.get("spanish", "")).lower()
                ]
                mwe_examples_by_idx.append(matched_exs[:5])
            stats["with_mwes"] += 1

        # Cognate flag
        cognate_key = f"{entry['word']}|{entry['lemma']}"
        is_cognate = cognate_key in cognates

        # Monolith entry
        mono_entry = {
            "word": entry["word"],
            "lemma": entry["lemma"],
            "id": word_id,
            "corpus_count": entry.get("corpus_count", 0),
            "most_frequent_lemma_instance": entry["most_frequent_lemma_instance"],
            "meanings": meanings_full,
        }
        if is_cognate:
            mono_entry["is_transparent_cognate"] = True
        if mwe_memberships:
            mono_entry["mwe_memberships"] = mwe_memberships
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
        if is_cognate:
            idx_entry["is_transparent_cognate"] = True
        if mwe_memberships:
            idx_entry["mwe_memberships"] = mwe_memberships
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
