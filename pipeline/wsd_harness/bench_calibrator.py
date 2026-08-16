#!/usr/bin/env python3
"""Does combining the available signals rank better than the tuple gap alone?

The tuple gap is the only signal measured so far with a usable ordering (22.7%
yield at 99% on the production slice). A calibrator is only worth building if the
COMBINATION beats it. This tests that and nothing else.

Features are restricted to what exists at inference time — the model's own
outputs and the menu's shape. No gold-derived feature is allowed in.

Split is the frozen word-level hash from common.py (sha1(word) % 100 < 35 -> dev),
so no word appears in both halves; a per-item split would leak, because items
sharing a word share a menu and a prototype.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

import numpy as np

S = Path("/private/tmp/claude-501/-Users-joshuathomasamar-PycharmProjects-Fluency"
         "/3fbda742-82e7-4ae2-9ed3-d7fe8df59759/scratchpad")


def split_of(word):
    return "dev" if int(hashlib.sha1(word.encode()).hexdigest()[:8], 16) % 100 < 35 else "test"


def yield_at(scores, ok, target=0.99):
    order = np.argsort(-scores)
    good = best = 0
    for i, j in enumerate(order, 1):
        good += ok[j]
        if good / i >= target:
            best = i
    return best / len(ok)


def build(rows, tokmap):
    X, y, w, grp = [], [], [], []
    for r in rows:
        tk = tokmap.get((r["word"], r["sent"]))
        feats = [
            r["tgap"],                              # the incumbent signal
            r["cgap"],                              # 1.0 flags the collapsed-class case
            min(r["cgap"], 1.0) * (r["cgap"] < 0.999),   # cgap with the 1.0 pathology split out
            float(r["cgap"] >= 0.999),
            r["n_tup"], r["n_leaf"],
            r["n_leaf"] / max(r["n_tup"], 1),       # leaf-splitting factor
            len(r["sent"].split()),
            float(r["pred_tup"][0].endswith("se")),
            float(r["pred_tup"][1] == "VERB"),
            float(r["pred_tup"][1] in ("NOUN", "ADJ")),
        ]
        if tokmap:
            feats += [
                0.0 if tk is None else 1.0,
                0.0 if tk is None else tk["gap"],
                0.0 if tk is None else float(tuple(tk["pred"]) == tuple(r["pred_tup"])),
            ]
        X.append(feats)
        y.append(int(r["ok_tup"]))
        w.append(r["word"])
        grp.append(r["tgap"])
    return np.array(X, np.float64), np.array(y), w, np.array(grp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", default=str(S / "tp.json"))
    ap.add_argument("--token", default=str(S / "token_preds.json"))
    ap.add_argument("--ablate-token", action="store_true",
                    help="restrict to the token population but DROP token features "
                         "— the control that isolates what mBERT actually adds")
    ap.add_argument("--with-token", action="store_true",
                    help="restrict to items the token method also scored")
    args = ap.parse_args()

    rows = [r for r in json.loads(Path(args.rows).read_text()) if r["n_tup"] > 1]
    tokmap = {}
    if Path(args.token).exists():
        for t in json.loads(Path(args.token).read_text()):
            tokmap[(t["word"], t["sent"])] = t
    if args.with_token or args.ablate_token:
        rows = [r for r in rows if (r["word"], r["sent"]) in tokmap]
    if not args.with_token:
        tokmap = {}
    print(f"{len(rows):,} items; token features: {'on' if tokmap else 'off'}")

    X, y, words, tgap = build(rows, tokmap)
    dev = np.array([split_of(w) == "dev" for w in words])
    tst = ~dev
    print(f"  dev {dev.sum():,}  test {tst.sum():,}  "
          f"(frozen word-level split, {len(set(words)):,} words)")

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    base = yield_at(tgap[tst], y[tst])
    print(f"\n{'model':<34}{'test acc':>10}{'yield@99%':>12}")
    print(f"{'tuple gap alone (incumbent)':<34}{y[tst].mean():>10.2%}{base:>12.1%}")

    sc = StandardScaler().fit(X[dev])
    lr = LogisticRegression(max_iter=2000, C=1.0).fit(sc.transform(X[dev]), y[dev])
    p_lr = lr.predict_proba(sc.transform(X[tst]))[:, 1]
    print(f"{'logistic regression':<34}{'':>10}{yield_at(p_lr, y[tst]):>12.1%}")

    gb = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                        max_leaf_nodes=15, random_state=0)
    gb.fit(X[dev], y[dev])
    p_gb = gb.predict_proba(X[tst])[:, 1]
    print(f"{'gradient boosting':<34}{'':>10}{yield_at(p_gb, y[tst]):>12.1%}")

    # what the calibrator buys at fixed coverage, which is the product question
    print(f"\n{'keep top':>9}{'tuple gap':>12}{'calibrated':>12}")
    for K in (10, 20, 30, 40, 50):
        k = max(1, int(tst.sum() * K / 100))
        a = y[tst][np.argsort(-tgap[tst])[:k]].mean()
        b = y[tst][np.argsort(-p_gb)[:k]].mean()
        print(f"{K:>8}%{a:>12.2%}{b:>12.2%}")


if __name__ == "__main__":
    main()
