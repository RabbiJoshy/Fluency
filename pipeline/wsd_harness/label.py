#!/usr/bin/env python3
"""Clear the judgement queue.

  python label.py --queue queue.jsonl            # highest-confidence first
  python label.py --queue queue.jsonl --n 50

Keys: g = GOOD, o = OK (different leaf, same meaning), b = BAD (a learner would
learn something wrong), s = skip, q = save and quit.

Judgements append to judgements.jsonl and are permanent. Every future method reuses
them, so this cost is paid once, not once per experiment.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os

from common import append_judgements, load_judgements

KEYS = {"g": "GOOD", "o": "OK", "b": "BAD"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="queue.jsonl")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--judge", default=os.environ.get("USER", "josh"))
    args = ap.parse_args()

    J = load_judgements()
    items = [json.loads(l) for l in open(args.queue, encoding="utf-8") if l.strip()]
    items = [i for i in items if (i["sentence_id"], i["sense_id"]) not in J]
    items.sort(key=lambda i: -i["confidence"])
    items = items[:args.n]
    if not items:
        return print("queue is empty — nothing to judge")

    print(f"{len(items)} to judge.  g=GOOD  o=OK(same meaning)  b=BAD  s=skip  q=quit")
    print("BAD means: a learner shown this card would learn something wrong.\n")

    out = []
    for k, it in enumerate(items, 1):
        p = it["pick"]
        print(f"[{k}/{len(items)}]  {it['word']}")
        print(f"  {it['sentence']}")
        print(f"  -> {p.get('pos','')} · {p.get('translation','')}"
              f"{' (' + p['context'] + ')' if p.get('context') else ''}")
        others = [m for m in it["menu"] if m["sense_id"] != it["sense_id"]][:8]
        print("     menu: " + " | ".join(
            f"{m.get('translation','')}{'('+m['context']+')' if m.get('context') else ''}"
            for m in others))
        while True:
            c = input("  [g/o/b/s/q] ").strip().lower()
            if c in ("g", "o", "b", "s", "q"):
                break
        if c == "q":
            break
        if c == "s":
            continue
        out.append({"sentence_id": it["sentence_id"], "sense_id": it["sense_id"],
                    "label": KEYS[c], "judge": args.judge,
                    "date": dt.date.today().isoformat()})
        print()

    if out:
        append_judgements(out)
        print(f"\nsaved {len(out)} judgements")


if __name__ == "__main__":
    main()
