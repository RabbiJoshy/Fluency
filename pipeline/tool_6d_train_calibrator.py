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

import sys
sys.path.insert(0, str(REPO))
from pipeline.util_6d_wsd_features import (  # noqa: E402
    FEATURES, FEATURE_VERSION, build as build_features, companion_features,
    structural_features)


def split_of(word: str) -> str:
    """Frozen word-level split. A per-item split would leak: items sharing a word
    share a menu and a prototype."""
    return "dev" if int(hashlib.sha1(word.encode()).hexdigest()[:8], 16) % 100 < 35 else "test"


def _tuple_of(word, sense):
    return ((sense.get("headword") or word).strip().lower(), (sense.get("pos") or "").strip())


def featurise(r: dict, tk: dict | None, menus: dict, no_companion=False,
              no_structural=False) -> list[float]:
    menu = menus.get(r["word"], {})
    comp = ([0.0] * 5 if no_companion else
            companion_features(r["word"], r["sent"], menu, r.get("pred_leaf"), _tuple_of))
    struct = ([0.0] * 5 if no_structural else
              structural_features(r["word"], r["sent"], menu, r.get("pred_leaf"), _tuple_of))
    pred_sense = menu.get(r.get("pred_leaf")) or {}
    order = list(menu)
    mpos = order.index(r["pred_leaf"]) if r.get("pred_leaf") in order else 0
    return build_features(
        tuple_gap=r["tgap"], class_gap=r["cgap"], n_tup=r["n_tup"], n_leaf=r["n_leaf"],
        sent_len=len(r["sent"].split()), pred_tuple=tuple(r["pred_tup"]),
        pred_empty=not (pred_sense.get("translation") or "").strip(),
        token=((0.0, 0.0, 0.0) if tk is None else
               (1.0, tk["gap"], float(tuple(tk["pred"]) == tuple(r["pred_tup"])))),
        companion=comp, structural=struct, menu_pos=mpos)


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
    ap.add_argument("--no-companion", action="store_true",
                    help="ablation: zero the used-with features")
    ap.add_argument("--no-structural", action="store_true",
                    help="ablation: zero the grammatical-construction features")
    ap.add_argument("--target", default="tup", choices=["tup", "leaf"],
                    help="what the calibrator predicts. `tup` is lemma+POS, which "
                         "is what shipped and is 88.7%% accurate on gold -- nearly "
                         "saturated, so the score has little to rank. `leaf` is the "
                         "exact sense, 53.1%% on the same rows: it is what the card "
                         "actually displays, context note included.")
    ap.add_argument("--band-high", type=float, default=0.0,
                    help="precision the HIGH band must hold on held-out data. "
                         "Default 0.99 for --target tup, 0.90 for --target leaf: "
                         "leaf accuracy is 53%% at base, so demanding 99%% there "
                         "finds no cut at all and every item lands in high, which "
                         "silently switches escalation OFF.")
    ap.add_argument("--band-medium", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    menu_raw = json.loads((REPO / "Data/Spanish/layers/sense_menu/spanishdict.json")
                          .read_text(encoding="utf-8"))
    menus = {w: {sid: v for e in ent for sid, v in e.get("senses", {}).items()}
             for w, ent in menu_raw.items()}

    rows = [r for r in json.loads(Path(args.rows).read_text()) if r["n_tup"] > 1]
    tok = {}
    if args.token and Path(args.token).exists():
        for t in json.loads(Path(args.token).read_text()):
            tok[(t["word"], t["sent"])] = t
    print(f"{len(rows):,} training items; {len(tok):,} carry token predictions")

    X = np.array([featurise(r, tok.get((r["word"], r["sent"])), menus,
                            args.no_companion, args.no_structural)
                  for r in rows], np.float64)
    tgt = "ok_tup" if args.target == "tup" else "ok_leaf"
    y = np.array([int(r[tgt]) for r in rows])
    print(f"  target {tgt}: {y.mean():.2%} positive")
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

    # Band cuts are P(correct) thresholds read off the held-out curve, not
    # guessed. step_6e reads them from the manifest.
    band_cuts = {}
    order = np.argsort(-p)
    hi = args.band_high or (0.99 if args.target == "tup" else 0.90)
    md = args.band_medium or (0.95 if args.target == "tup" else 0.70)
    prec = {"high": hi, "medium": md}
    for label, target in (("high", hi), ("medium", md)):
        good = cut = 0
        for i, j in enumerate(order, 1):
            good += y[tst][j]
            if good / i >= target:
                cut = float(p[j])
        if not cut:
            # No prefix of the ranking holds that precision. Leaving the cut at
            # 0 would put EVERY item in the band -- for `high` that turns the
            # escalation gate off without saying so. Fail towards escalating.
            cut = float(p.max()) + 1e-6
            print(f"  !! no cut reaches {target:.0%} precision for `{label}`; "
                  f"band left EMPTY (cut {cut:.4f}) so nothing is silently trusted")
        band_cuts[label] = round(cut, 4)
    print(f"\n  band cuts from the held-out curve: "
          f"high P>={band_cuts['high']:.4f} ({hi:.0%} {tgt}), "
          f"medium P>={band_cuts['medium']:.4f} ({md:.0%} {tgt})")

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
        "feature_version": FEATURE_VERSION,
        "n_train": len(rows),
        "held_out_yield_at_99": round(got, 4),
        "band_cuts": band_cuts,
        "target": tgt,
        "band_precision_targets": prec,
        "ablations": {"no_companion": args.no_companion,
                      "no_structural": args.no_structural},
        "tuple_gap_yield_at_99": round(base, 4),
        "trained": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
        "note": "refit on all rows after the held-out estimate above",
    }, ensure_ascii=False, indent=2))
    print(f"\nwrote {out.relative_to(REPO)}/calibrator.joblib")


if __name__ == "__main__":
    main()
