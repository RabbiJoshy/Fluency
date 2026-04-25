#!/usr/bin/env python3
"""tool_5e_build_synonyms_layer.py — build the synonyms/antonyms layer file.

Reads ``Data/Spanish/Senses/spanishdict/thesaurus_cache.json`` (produced by
``tool_5c_scrape_spanishdict_thesaurus.py``) and writes
``Data/Spanish/layers/synonyms.json`` keyed by lemma:

    {
      "bonito": {
        "synonyms": [{"word": "lindo", "strength": 2, "context": "beautiful"}, ...],
        "antonyms": [{"word": "feo", "strength": 2, "context": "unattractive"}, ...]
      }
    }

Strength is the absolute value of SpanishDict's signed ``relationship`` enum
(``+2`` strong, ``+1`` weak/related on the synonym side; ``-2``/``-1`` on
the antonym side). The sign determines the bucket; the magnitude lets the
UI render strong synonyms larger than weak ones.

Algorithm — for each cached lemma:

1. Identify the headword's own sense IDs (``senses`` rows whose ``wordId``
   matches ``headword.id``). A lemma can have multiple senses (e.g. mesa =
   table / plateau / board / committee).
2. For every ``senseLinks`` row that touches one of those sense IDs at
   either end, follow the *other* end back to its sense → ``wordId`` →
   ``linkedWords[wordId].source`` (the actual Spanish word string).
3. Bucket on the sign of ``relationship``. Dedup by ``(word, |strength|)``.
   Sort each bucket by strength descending, then alphabetically.

Usage:

    .venv/bin/python3 pipeline/tool_5e_build_synonyms_layer.py
"""

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

from util_5c_spanishdict import SPANISHDICT_THESAURUS_CACHE


DEFAULT_OUT = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "synonyms.json"


def build_for_lemma(lemma, payload):
    """Return ``{synonyms: [...], antonyms: [...]}`` or ``None`` if no data."""
    if not isinstance(payload, dict) or "headword" not in payload:
        return None
    headword = payload.get("headword") or {}
    headword_word_id = headword.get("id")
    senses = payload.get("senses") or []
    sense_links = payload.get("senseLinks") or []
    linked_words = payload.get("linkedWords") or []

    if headword_word_id is None or not senses or not sense_links:
        return None

    headword_sense_ids = {
        s.get("id") for s in senses if s.get("wordId") == headword_word_id
    }
    if not headword_sense_ids:
        return None

    sense_lookup = {
        s.get("id"): {
            "word_id": s.get("wordId"),
            "context_en": (s.get("contextEn") or "").strip(),
            "context_es": (s.get("contextEs") or "").strip(),
        }
        for s in senses
        if s.get("id") is not None
    }
    word_lookup = {
        w.get("id"): (w.get("source") or "").strip()
        for w in linked_words
        if w.get("id") is not None
    }

    headword_source = (headword.get("source") or "").strip().lower()
    bucketed = {"synonyms": {}, "antonyms": {}}

    for link in sense_links:
        a = link.get("senseLinkA")
        b = link.get("senseLinkB")
        rel = link.get("relationship")
        if rel is None:
            continue
        if a in headword_sense_ids:
            other = b
        elif b in headword_sense_ids:
            other = a
        else:
            continue
        sense = sense_lookup.get(other)
        if not sense:
            continue
        word = word_lookup.get(sense["word_id"], "").strip()
        if not word or word.lower() == headword_source:
            continue
        bucket = "synonyms" if rel > 0 else "antonyms"
        strength = abs(rel)
        # Use English context when present (matches the UI language); fall
        # back to Spanish so the disambiguator at least renders.
        context = sense["context_en"] or sense["context_es"]
        key = (word.lower(), strength)
        existing = bucketed[bucket].get(key)
        # Prefer the entry with a non-empty context if we'd otherwise drop
        # one to dedup.
        if existing is None or (not existing.get("context") and context):
            bucketed[bucket][key] = {
                "word": word,
                "strength": strength,
                **({"context": context} if context else {}),
            }

    def sort_bucket(items):
        return sorted(
            items.values(),
            key=lambda e: (-e["strength"], e["word"].lower()),
        )

    synonyms = sort_bucket(bucketed["synonyms"])
    antonyms = sort_bucket(bucketed["antonyms"])
    if not synonyms and not antonyms:
        return None
    out = {}
    if synonyms:
        out["synonyms"] = synonyms
    if antonyms:
        out["antonyms"] = antonyms
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache",
        default=str(SPANISHDICT_THESAURUS_CACHE),
        help="Input thesaurus cache path (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="Output layer path (default: %(default)s)",
    )
    args = parser.parse_args()

    cache_path = Path(args.cache)
    if not cache_path.is_file():
        raise SystemExit(f"Missing thesaurus cache: {cache_path}")

    with open(cache_path, "r", encoding="utf-8") as f:
        cache = json.load(f)

    layer = {}
    skipped_empty = 0
    skipped_error = 0
    for lemma, payload in cache.items():
        if payload is None:
            skipped_empty += 1
            continue
        if isinstance(payload, dict) and "error" in payload and "headword" not in payload:
            skipped_error += 1
            continue
        out = build_for_lemma(lemma, payload)
        if out is not None:
            layer[lemma] = out

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_layer = {k: layer[k] for k in sorted(layer)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(sorted_layer, f, ensure_ascii=False, indent=2)

    total_syn = sum(len(v.get("synonyms", [])) for v in layer.values())
    total_ant = sum(len(v.get("antonyms", [])) for v in layer.values())
    print(f"Read {len(cache)} cache entries "
          f"({skipped_empty} empty, {skipped_error} errors).")
    print(f"Wrote {len(layer)} lemmas with thesaurus data → {out_path}")
    print(f"  synonyms: {total_syn} edges")
    print(f"  antonyms: {total_ant} edges")


if __name__ == "__main__":
    main()
