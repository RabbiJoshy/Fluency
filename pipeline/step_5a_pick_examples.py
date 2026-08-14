#!/usr/bin/env python3
"""step_5a_pick_examples — the free half of example selection.

Reads the harvest and the alignment scores, applies a selection policy, and
writes the chosen examples. Touches no corpus and mints no embeddings, so it
runs in seconds and can be re-run with different settings as often as you like.

Every run is stamped and kept under example_picks/, so two policies can be
compared directly:

    diff <(jq -S . example_picks/A.json) <(jq -S . example_picks/B.json)

It also renders layers/examples_raw.json for the existing step_6/7/8 chain, and
feeds the append-only example_store so a sentence classified under one policy
stays findable after another policy drops it.

Usage:
    python3 pipeline/step_5a_pick_examples.py
    python3 pipeline/step_5a_pick_examples.py --per-word 3 --label short-decks
    python3 pipeline/step_5a_pick_examples.py --align-floor 0.85 --include-held
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from util_5a_example_id import update_example_store  # noqa: E402

LAYERS = REPO / "Data/Spanish/layers"
SUBS = LAYERS / "subtitles"

ALIGN_FLOOR = 0.90
SCORE_WEIGHT = 0.15   # alignment dominates; structural score breaks ties
DUP_PREFIX = 25       # crude near-duplicate guard, as in the v2 builder


def load_bank(path):
    rows = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                rows[row["id"]] = row
    return rows


def choose(cands, bank, alignment, per_word, floor, weight):
    """Rank by alignment, then take one sentence per film where possible.

    Without the per-title rule a frequent word draws every example from whichever
    subtitle happened to be dense in it.
    """
    scored = []
    for sid in cands:
        row = bank.get(sid)
        if row is None:
            continue
        align = alignment.get(sid)
        if align is None:
            # Unscored. Normally that means "not embedded yet" and the sentence
            # is skipped; with the gate off it ranks on structural score alone,
            # which is what makes a zero-cost full-coverage build possible.
            if floor is None:
                scored.append((weight * row["score"], None, sid, row))
            continue
        if floor is not None and align < floor:
            continue
        scored.append((align + weight * row["score"], align, sid, row))
    scored.sort(key=lambda x: -x[0])

    def take(one_per_title):
        out, titles, seen_text = [], set(), []
        for rank, align, sid, row in scored:
            if any(row["es"][:DUP_PREFIX] == t for t in seen_text):
                continue
            title = (row.get("provenance") or {}).get("title_id")
            if one_per_title and title and title in titles:
                continue
            if title:
                titles.add(title)
            seen_text.append(row["es"][:DUP_PREFIX])
            out.append((sid, row, align, rank))
            if len(out) == per_word:
                break
        return out

    picked = take(True)
    if len(picked) < per_word:      # too few distinct films: relax the rule
        picked = take(False)
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subs", default=str(SUBS))
    ap.add_argument("--per-word", type=int, default=5)
    ap.add_argument("--align-floor", type=float, default=ALIGN_FLOOR)
    ap.add_argument("--score-weight", type=float, default=SCORE_WEIGHT)
    ap.add_argument("--no-align-gate", action="store_true",
                    help="Rank on structural score alone and keep sentences "
                         "with no alignment score. Lets a full-coverage deck "
                         "be built straight off a harvest with no embedding "
                         "spend; example quality is lower because a broken "
                         "translation is no longer filtered out.")
    ap.add_argument("--include-held", action="store_true",
                    help="consider sentences that failed only a taste gate")
    ap.add_argument("--label", default="", help="short name for this policy run")
    ap.add_argument("--no-render", action="store_true",
                    help="write the pick file but leave examples_raw.json alone")
    args = ap.parse_args()

    subs = Path(args.subs)
    bank = load_bank(subs / "sentence_bank.jsonl")
    candidates = json.loads((subs / "word_candidates.json").read_text(encoding="utf-8"))
    align_path = subs / "alignment.json"
    if not align_path.exists() and not args.no_align_gate:
        raise SystemExit("no alignment.json — run step_5a_embed_candidates first, "
                         "or pass --no-align-gate to build without it")
    alignment = (json.loads(align_path.read_text(encoding="utf-8"))
                 if align_path.exists() else {})

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    if args.label:
        run_id += "_" + args.label

    picks, rendered, thin, starved = {}, {}, [], []
    for word, pools in candidates.items():
        cands = list(pools.get("clean") or [])
        if args.include_held:
            cands += list(pools.get("held") or [])
        chosen = choose(cands, bank, alignment, args.per_word,
                        None if args.no_align_gate else args.align_floor,
                        args.score_weight)
        if not chosen:
            starved.append(word)
            continue
        if len(chosen) < args.per_word:
            thin.append((word, len(chosen)))
        picks[word] = [{"id": sid, "alignment": align, "rank": round(rank, 4),
                        "score": row["score"], "gate": row.get("gate"),
                        "title_id": (row.get("provenance") or {}).get("title_id")}
                       for sid, row, align, rank in chosen]
        rendered[word] = [{"id": sid, "target": row["es"], "english": row["en"],
                           "source": "opensubtitles", "alignment": align,
                           "score": row["score"],
                           "naturalness": row["naturalness"],
                           "hard_words": row["hard_words"],
                           "tokens": row["tokens"],
                           "provenance": row.get("provenance") or {}}
                          for sid, row, align, _ in chosen]

    out_dir = subs / "example_picks"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy": {"per_word": args.per_word, "align_floor": None if args.no_align_gate else args.align_floor,
                   "score_weight": args.score_weight,
                   "include_held": args.include_held},
        "words": len(picks),
        "sentences": sum(len(v) for v in picks.values()),
        "picks": picks,
    }
    (out_dir / (run_id + ".json")).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    print("run %s" % run_id)
    print("  words with examples: %d | sentences: %d"
          % (len(picks), sum(len(v) for v in picks.values())))
    print("  words below target:  %d" % len(thin))
    print("  words with none:     %d%s"
          % (len(starved), (" e.g. %s" % starved[:6]) if starved else ""))

    if not args.no_render:
        # Keep every word key so the shape matches what step_6/7/8 expect; a word
        # with no surviving candidate renders as an empty list rather than
        # vanishing from the layer.
        existing = {}
        raw_path = LAYERS / "examples_raw.json"
        if raw_path.exists():
            existing = json.loads(raw_path.read_text(encoding="utf-8"))
        for word in existing:
            existing[word] = rendered.get(word, [])
        for word, rows in rendered.items():
            existing[word] = rows
        raw_path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
        added, total = update_example_store(rendered, LAYERS / "example_store.json")
        print("  rendered -> %s (%d words)" % (raw_path, len(existing)))
        print("  example_store: +%d, %d total" % (added, total))


if __name__ == "__main__":
    main()
