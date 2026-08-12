#!/usr/bin/env python3
"""Score a method against the acceptable-set labels.

  python score2.py --method embed_v1 --corpus spanishdict --split test

Two harnesses, reported side by side:

  EXACT       did it return the sense SpanishDict filed the example under.
              Free — no human needed — but it punishes leaf-splitting, which is
              not an error, so it is a lower bound and never the headline.
  ACCEPTABLE  is the pick inside the hand-labelled acceptable set for that
              sentence. Anything outside it is BAD by definition. This is the
              metric: never show a learner a wrong sense.

Sentences marked exclude:true in the labels are dropped (English-source rows, and
rows where the only correct leaf has an empty translation, so no right answer
exists to find).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys

from common import HERE, LABEL_DIR, read_corpus

sys.path.insert(0, str(HERE))


def load_labels(corpus):
    p = LABEL_DIR / f"{corpus}.acceptable.jsonl"
    if not p.exists():
        raise SystemExit(f"no labels for {corpus}: {p}")
    return {r["word"]: r for r in
            (json.loads(l) for l in open(p, encoding="utf-8") if l.strip())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", required=True)
    ap.add_argument("--corpus", default="spanishdict")
    ap.add_argument("--split", default="test", choices=["dev", "test", "all"])
    ap.add_argument("--show-bad", action="store_true")
    args = ap.parse_args()

    labels = load_labels(args.corpus)
    rows = {r["id"]: r for r in read_corpus(args.corpus)}
    mod = importlib.import_module(f"methods.{args.method}")
    preds = mod.run(args.corpus, "all")

    scored = []
    skipped = 0
    for s_id, sense_id, conf in preds:
        r = rows.get(s_id)
        if not r:
            continue
        if args.split != "all" and r["split"] != args.split:
            continue
        lab = labels.get(r["word"])
        if not lab or lab.get("exclude"):
            skipped += 1
            continue
        scored.append({
            "conf": conf, "word": r["word"], "sentence": r["sentence"],
            "pick": sense_id,
            "acceptable": sense_id in lab["acceptable"],
            "exact": r.get("gold") == sense_id,
            "has_gold": "gold" in r,
        })
    scored.sort(key=lambda x: -x["conf"])
    n = len(scored)
    if not n:
        raise SystemExit("nothing scored")

    print(f"\n{args.method} on {args.corpus}/{args.split}")
    print(f"  {n} sentences scored, {skipped} excluded by label file")
    has_gold = [x for x in scored if x["has_gold"]]

    print("\n  keep top   n     ACCEPTABLE (the metric)   BAD      exact-leaf")
    for f in (0.10, 0.25, 0.50, 0.75, 1.00):
        k = max(1, int(n * f))
        band = scored[:k]
        acc = sum(x["acceptable"] for x in band) / k
        ex = ([x["exact"] for x in band if x["has_gold"]])
        exs = f"{sum(ex)/len(ex):.1%}" if ex else "n/a"
        print(f"  {f:>7.0%}   {k:>3}   {acc:>18.1%}   {1-acc:>6.1%}   {exs:>10}")

    print("\n  yield at a BAD-rate ceiling:")
    for tgt in (0.00, 0.02, 0.05, 0.10):
        best = 0
        bad = 0
        for i, x in enumerate(scored, 1):
            bad += not x["acceptable"]
            if bad / i <= tgt:
                best = i
        print(f"    BAD <= {tgt:>4.0%}   yield {best/n:>6.1%}  ({best} of {n})")
    print(f"\n  NOTE: {n} sentences resolves a BAD rate no finer than "
          f"1-in-{n} = {1/n:.1%}.")

    if args.show_bad:
        print("\n  BAD picks, most confident first:")
        for x in [x for x in scored if not x["acceptable"]][:25]:
            print(f"    [{x['word']}] {x['sentence'][:70]}")
            print(f"       picked {x['pick']}  conf={x['conf']:.4f}")


if __name__ == "__main__":
    main()
