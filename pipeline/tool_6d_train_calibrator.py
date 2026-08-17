#!/usr/bin/env python3
"""tool_6d_train_calibrator — learn the ranker that decides what to keep.

Every WSD method measured in this project is complementary and none of them can
be *combined* on its own terms: the Gemini cascade has no usable ranking signal
(self-reported certainty is flat at ~92% across every bucket) and the token
prototypes rank badly alone (1.0% yield at 99%). The calibrator is the piece that
turns that complementarity into yield.

Measured 2026-08-17, frozen word-level split, inference-only features
(Data/Spanish/Intermediates/wsd_sense_harness/README.md §8/§9):

    class gap (what shipped before 2026-08-16)   0.0% yield at 99%
    tuple gap                                   22.3%
    calibrated, gloss signals only               24.2%
    calibrated + mBERT token features            44.4%
    calibrated + BETO  token features            53.7%

Gloss-side signals are exhausted by the tuple gap; the win is combining
INDEPENDENT methods. `--ablate-token` in bench_calibrator.py is the control that
attributes it.

Trains on the dictionary gold produced by
`pipeline/wsd_harness/bench_tuple_accuracy.py --out` plus the token predictions
from `bench_token_prototypes.py --out`, and writes a joblib model plus a manifest
recording exactly which feature order it expects.

    python3 pipeline/tool_6d_train_calibrator.py --rows ROWS.json --token TOK.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "Data/Spanish/layers/wsd_calibrator"

# The feature order is a CONTRACT. step_6d must build its vector identically, so
# it is written into the manifest and asserted at load time.
FEATURES = [
    "tuple_gap", "class_gap", "class_gap_collapsed", "n_tup", "n_leaf",
    "leaf_split_ratio", "sent_len", "pred_is_se", "pred_is_verb", "pred_is_nounadj",
    "token_available", "token_gap", "token_agrees",
]


def split_of(word: str) -> str:
    """Frozen word-level split. A per-item split would leak: items sharing a word
    share a menu and a prototype."""
    return "dev" if int(hashlib.sha1(word.encode()).hexdigest()[:8], 16) % 100 < 35 else "test"


def featurise(r: dict, tk: dict | None) -> list[float]:
    return [
        r["tgap"],
        r["cgap"],
        float(r["cgap"] >= 0.999),          # the collapsed-class pathology
        r["n_tup"], r["n_leaf"],
        r["n_leaf"] / max(r["n_tup"], 1),
        len(r["sent"].split()),
        float(str(r["pred_tup"][0]).endswith("se")),
        float(r["pred_tup"][1] == "VERB"),
        float(r["pred_tup"][1] in ("NOUN", "ADJ")),
        0.0 if tk is None else 1.0,
        0.0 if tk is None else tk["gap"],
        0.0 if tk is None else float(tuple(tk["pred"]) == tuple(r["pred_tup"])),
    ]


def yield_at(scores, ok, target=0.99):
    order = np.argsort(-scores)
    good = best = 0
    for i, j in enumerate(order, 1):
        good += ok[j]
        if good / i >= target:
            best = i
    return best / len(ok)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True, help="bench_tuple_accuracy --out json")
    ap.add_argument("--token", default="", help="bench_token_prototypes --out json")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = [r for r in json.loads(Path(args.rows).read_text()) if r["n_tup"] > 1]
    tok = {}
    if args.token and Path(args.token).exists():
        for t in json.loads(Path(args.token).read_text()):
            tok[(t["word"], t["sent"])] = t
    print(f"{len(rows):,} training items; {len(tok):,} carry token predictions")

    X = np.array([featurise(r, tok.get((r["word"], r["sent"]))) for r in rows], np.float64)
    y = np.array([int(r["ok_tup"]) for r in rows])
    words = [r["word"] for r in rows]
    dev = np.array([split_of(w) == "dev" for w in words])
    tst = ~dev
    print(f"  dev {dev.sum():,}  test {tst.sum():,}  ({len(set(words)):,} words, frozen split)")

    from sklearn.ensemble import HistGradientBoostingClassifier

    model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                           max_leaf_nodes=15, random_state=0)
    model.fit(X[dev], y[dev])
    p = model.predict_proba(X[tst])[:, 1]
    base = yield_at(X[tst][:, 0], y[tst])
    got = yield_at(p, y[tst])
    print(f"\n  tuple gap alone   yield@99% {base:>6.1%}")
    print(f"  calibrated        yield@99% {got:>6.1%}")
    print(f"\n  {'keep top':>9}{'tuple gap':>12}{'calibrated':>12}")
    for K in (10, 20, 30, 40, 50):
        k = max(1, int(tst.sum() * K / 100))
        a = y[tst][np.argsort(-X[tst][:, 0])[:k]].mean()
        b = y[tst][np.argsort(-p)[:k]].mean()
        print(f"  {K:>8}%{a:>12.2%}{b:>12.2%}")

    if args.dry_run:
        return print("\n--dry-run: nothing written")

    # Refit on everything for the shipped model — the split existed to get an
    # honest estimate, and that estimate is now recorded above.
    final = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                           max_leaf_nodes=15, random_state=0)
    final.fit(X, y)

    import joblib
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, out / "calibrator.joblib")
    (out / "manifest.json").write_text(json.dumps({
        "features": FEATURES,
        "n_train": len(rows),
        "held_out_yield_at_99": round(got, 4),
        "tuple_gap_yield_at_99": round(base, 4),
        "trained": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
        "note": "refit on all rows after the held-out estimate above",
    }, ensure_ascii=False, indent=2))
    print(f"\nwrote {out.relative_to(REPO)}/calibrator.joblib")


if __name__ == "__main__":
    main()
