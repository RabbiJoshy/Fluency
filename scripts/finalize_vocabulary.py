#!/usr/bin/env python3
"""
finalize_vocabulary.py — Shared finalize step for both normal and artist pipelines.

Reads a monolith vocabulary.json, cleans translations, preserves detail,
and splits into index + examples files for the front end.

Usage (from project root):
    python3 scripts/finalize_vocabulary.py --input Data/Spanish/vocabulary.json
    python3 scripts/finalize_vocabulary.py --input Artists/Bad\ Bunny/BadBunnyvocabulary.json

Inputs:
    Any vocabulary.json with meanings[].examples structure (normal or artist mode).

Outputs (derived from input path):
    *.index.json    — everything except examples (lean, front-end eager load)
    *.examples.json — examples keyed by ID: {id: {m: [[ex,...], ...], w: [[ex,...], ...]}}
"""

import argparse
import json
import re
import sys
from pathlib import Path

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


def clean_translation(gloss: str) -> str:
    """
    Trim a Wiktionary/Gemini gloss to flashcard-friendly length.
    1. Strip parenthetical clarifications (keep essential objects).
    2. Truncate comma-separated synonym chains (keep first 3).
    3. Strip semicolon-separated usage notes.
    """
    text = gloss.strip()

    # --- Step 1: Strip parenthetical clarifications (anywhere in gloss) ---
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

    # --- Step 2: Truncate comma-separated synonym chains ---
    parts = text.split(", ")
    if len(parts) >= 4:
        text = ", ".join(parts[:3])

    # --- Step 3: Strip semicolon usage notes ---
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
# Split vocabulary into index + examples
# ---------------------------------------------------------------------------
def finalize(input_path: str):
    """Read monolith, clean translations, split into index + examples."""
    input_path = Path(input_path)
    base = str(input_path).rsplit(".", 1)[0]
    index_path = base + ".index.json"
    examples_path = base + ".examples.json"

    print(f"Finalizing {input_path}...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    index = []
    examples = {}
    stats = {"total": len(data), "cleaned": 0, "with_examples": 0}

    for entry in data:
        idx_entry = {}

        for k, v in entry.items():
            if k == "meanings":
                idx_entry["meanings"] = []
                ex_m = []
                for m in v:
                    # Clean translation, preserve detail if changed
                    translation = m.get("translation", "")
                    cleaned = clean_translation(translation)
                    meaning = {
                        "pos": m.get("pos", ""),
                        "translation": cleaned,
                        "frequency": m.get("frequency", "1.00"),
                    }
                    # Preserve existing detail, or create one if cleaning changed text
                    detail = m.get("detail", "")
                    if not detail and cleaned != translation:
                        detail = translation
                    if detail and detail != cleaned:
                        meaning["detail"] = detail
                        stats["cleaned"] += 1

                    idx_entry["meanings"].append(meaning)
                    ex_m.append(m.get("examples", []))

                if any(ex_m):
                    examples[entry["id"]] = {"m": ex_m}
                    stats["with_examples"] += 1

            elif k == "mwe_memberships":
                # Optional — normal mode doesn't have MWEs
                mwes = []
                ex_w = []
                for mwe in (v or []):
                    mwes.append({
                        "expression": mwe.get("expression", ""),
                        "translation": mwe.get("translation", ""),
                    })
                    ex_w.append(mwe.get("examples", []))
                idx_entry["mwe_memberships"] = mwes
                if any(ex_w):
                    if entry["id"] not in examples:
                        examples[entry["id"]] = {
                            "m": [[] for _ in entry.get("meanings", [])]
                        }
                    examples[entry["id"]]["w"] = ex_w
            else:
                idx_entry[k] = v

        index.append(idx_entry)

    # Write outputs
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False)

    print(f"  {stats['total']} entries")
    print(f"  {stats['cleaned']} meanings had translations cleaned")
    print(f"  {stats['with_examples']} entries with examples")
    print(f"  -> {index_path}")
    print(f"  -> {examples_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Finalize vocabulary: clean translations, split into index + examples")
    parser.add_argument("--input", required=True,
                        help="Path to monolith vocabulary.json")
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(1)

    finalize(args.input)
    print("\nDone.")


if __name__ == "__main__":
    main()
