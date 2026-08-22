#!/usr/bin/env python3
"""tool_5c_probe_conjugation_fields — is SpanishDict's verb reading being discarded?

The question
------------
`pares` is a form of `parar`. Its cached surface entry holds a complete noun
menu for `par` and `possible_results: []`, so `parar` was never a candidate and
the card teaches "pair" on a line that means "stop".

`build_surface_entry` keeps exactly two things out of SpanishDict's response:
`dictionary_analyses`, and `possible_results` — which reads ONE field,
`dictionaryPossibleResults`, SpanishDict's "did you mean" hints. Everything else
in the blob is discarded at parse time and never cached, so whether the
conjugation pointer was present and dropped, or genuinely absent, cannot be
answered from disk.

This probe re-fetches a sample of noun/adjective-only surfaces, keeps the WHOLE
blob, and reports which keys carry a verb pointer. Read-only: it writes to
--out and touches no layer, menu or cache.

Sizing the population from `conjugation_reverse` was the mistake this replaces —
that table is incomplete, so it measures its own coverage, not SpanishDict's.

    python3 pipeline/tool_5c_probe_conjugation_fields.py --n 200
"""
from __future__ import annotations

import argparse, json, re, sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "pipeline"))
from util_5c_spanishdict import build_session, fetch_spanishdict_component  # noqa: E402

LAY = REPO / "Data/Spanish/layers"
VERBY = re.compile(r"conjugat|inflect|verb", re.I)


def verb_pointers(blob, surface):
    """Every place in the blob naming a lemma that is not the surface, with a
    verb/conjugation flavour. Walks the whole structure — the point is to find
    keys we are NOT reading."""
    hits = []
    def walk(node, path):
        if isinstance(node, dict):
            ctx = " ".join(str(v) for v in node.values() if isinstance(v, str))
            if VERBY.search(ctx) or VERBY.search(path):
                for k in ("wordSource", "source", "headword", "infinitive", "lemma", "result"):
                    v = node.get(k)
                    if isinstance(v, str) and v.strip() and v.strip().lower() != surface.lower():
                        if v.strip().endswith(("ar", "er", "ir", "arse", "erse", "irse")):
                            hits.append((path.split(".")[0] or "?", k, v.strip()))
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, path)
    walk(blob, "")
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=str(REPO / "Data/Spanish/Intermediates/wsd_prior_audit/conj_probe"))
    a = ap.parse_args()

    raw = json.loads((LAY / "sense_menu/spanishdict.json").read_text(encoding="utf-8"))
    menus = {w: {s: v for e in es for s, v in e.get("senses", {}).items()} for w, es in raw.items()}
    ex = json.loads((LAY / "examples_raw.json").read_text(encoding="utf-8"))

    pool = sorted(w for w in ex if menus.get(w)
                  and not any(s.get("pos") == "VERB" for s in menus[w].values())
                  and w.isalpha() and len(w) > 2)
    import random
    random.seed(a.seed)
    sample = random.sample(pool, min(a.n, len(pool)))
    # `pares` and `metas` are the two cases that started this; always include them.
    for w in ("pares", "metas"):
        if w in menus and w not in sample:
            sample.insert(0, w)

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    session = build_session()
    keys = Counter(); withptr = 0; done = 0; fails = 0
    findings = []
    for w in sample:
        cached = out / f"{w}.json"
        try:
            if cached.exists():
                blob = json.loads(cached.read_text(encoding="utf-8"))
            else:
                blob = fetch_spanishdict_component(session, w)
                cached.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            fails += 1
            continue
        done += 1
        hits = verb_pointers(blob, w)
        if hits:
            withptr += 1
            for top, k, v in hits:
                keys[f"{top} -> {k}"] += 1
            findings.append((w, sorted({v for _, _, v in hits})[:3],
                             sorted({t for t, _, _ in hits})))
        if done % 25 == 0:
            print(f"  {done}/{len(sample)}", flush=True)

    print("\n" + "=" * 62)
    print(f"probed {done} noun/adj-only surfaces ({fails} fetch failures)")
    print(f"a verb lemma is present in the response for: {withptr} ({withptr/max(done,1):.0%})")
    print("\nWHICH TOP-LEVEL KEY CARRIES IT (we currently read only")
    print("sdDictionaryResultsProps + dictionaryPossibleResults):")
    for k, n in keys.most_common(12):
        print(f"  {n:>4}  {k}")
    print("\nfirst 20 surfaces with a discarded verb lemma:")
    for w, lemmas, tops in findings[:20]:
        print(f"  {w:<14} -> {', '.join(lemmas):<28} [{', '.join(tops)}]")
    print(f"\nraw blobs saved to {out}")


if __name__ == "__main__":
    main()
