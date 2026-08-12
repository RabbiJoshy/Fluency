#!/usr/bin/env python3
"""Print a panel compactly enough to be labelled in one pass.

For each sentence: the menu, with each leaf given a short index. Labelling means
naming the indices that are ACCEPTABLE for that sentence — everything unnamed is
BAD by default, which is the right default for a "never show a bad option" metric.
"""

from __future__ import annotations

import argparse
import json

from common import load_menu, read_corpus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="spanishdict")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--n", type=int, default=50)
    args = ap.parse_args()

    rows = read_corpus(args.corpus)
    menu = load_menu("Bad Bunny" if args.corpus == "badbunny" else None)
    rows = rows[args.start:args.start + args.n]

    for r in rows:
        m = menu.get(r["word"], {})
        print(f'### {r["id"]}  [{r["word"]}]  {r["sentence"]}')
        for i, (sid_, v) in enumerate(m.items()):
            g = (v.get("translation") or "(EMPTY)")
            c = v.get("context") or ""
            star = " *" if r.get("gold") == sid_ else ""
            print(f'  {i}|{sid_} {v.get("pos","")} {g}'
                  + (f" ({c})" if c else "") + star)
        print()


if __name__ == "__main__":
    main()
