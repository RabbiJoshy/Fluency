#!/usr/bin/env python3
"""tool_8a_patch_confidence_into_index — surface WSD confidence on each meaning.

step_8a keeps the index lean and drops fields it does not know about, so the
per-example confidence written by step_6d never reaches the app. This splices it
back on, keyed by sense_id, changing nothing else — card ids, examples,
frequencies and every other field are untouched.

Adds to each meaning that has an embedding assignment:
    confidence      max TUPLE gap over the examples assigned to this sense —
                    confidence in the (headword, POS), which is where learner
                    knowledge is recorded. Was the class gap until 2026-08-16;
                    that key omitted the headword and so returned maximum
                    confidence on undecided hacer/hacerse calls.
    band            high / medium / low, absolute cuts measured on 16,016
                    dictionary-gold sentences (99% / 95% accuracy)
    method          the assigning method id

Usage:
    python3 pipeline/tool_8a_patch_confidence_into_index.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LAYERS = REPO / "Data/Spanish/layers"
METHOD = "spanishdict-embed-v1"
HIGH_CUT, MEDIUM_CUT = 0.043, 0.020


def band(gap):
    return "high" if gap >= HIGH_CUT else "medium" if gap >= MEDIUM_CUT else "low"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    lem = json.loads((LAYERS / "sense_assignments_lemma/spanishdict.json")
                     .read_text(encoding="utf-8"))
    # (surface word, sense_id) -> best gap seen
    best = defaultdict(float)
    for key, methods in lem.items():
        w = key.split("|", 1)[0].lower()
        for item in (methods.get(METHOD) or []):
            sid = item.get("sense")
            for c in (item.get("confidence") or []):
                if c > best[(w, sid)]:
                    best[(w, sid)] = c

    idx_p = REPO / "Data/Spanish/vocabulary.index.json"
    idx = json.loads(idx_p.read_text(encoding="utf-8"))
    patched = words = 0
    counts = {"high": 0, "medium": 0, "low": 0}
    for e in idx:
        w = (e.get("word") or "").lower()
        hit = False
        for m in e.get("meanings") or []:
            g = best.get((w, m.get("sense_id")))
            if g is None:
                continue
            m["confidence"] = round(g, 4)
            m["band"] = band(g)
            m["method"] = METHOD
            counts[m["band"]] += 1
            patched += 1
            hit = True
        words += hit
    print(f"patched {patched} meanings on {words} cards  {counts}")
    if a.dry_run:
        return print("--dry-run: nothing written")
    idx_p.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {idx_p}")


if __name__ == "__main__":
    main()
