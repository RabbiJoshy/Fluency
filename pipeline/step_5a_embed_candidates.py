#!/usr/bin/env python3
"""step_5a_embed_candidates — the billed half of example selection, done once.

Reads the harvest (sentence_bank.jsonl + word_candidates.json), embeds both
sides of every candidate sentence, and stores the Spanish/English cosine as
`alignment.json`. That score is the discriminator the picker gates on: a broken
translation is worse than no example.

Split out from step_5a_build_examples_v2 so the expensive part happens once and
the policy part stays free. Alignment is a property of the sentence pair, not of
the word it was harvested for or of the run that picked it, so it is stored per
sentence and never recomputed.

Resumable and incremental. Sentences already scored are skipped, so an
interrupted run is restarted by running the same command again. Vectors go to
the shared cache in layers/sense_vectors/, keyed by exact text, so anything
already embedded for the sense harness or an earlier run is reused.

Usage:
    python3 pipeline/step_5a_embed_candidates.py
    python3 pipeline/step_5a_embed_candidates.py --limit 50000   # one chunk
    python3 pipeline/step_5a_embed_candidates.py --include-held  # taste rejects too
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from step_5a_build_examples_v2 import embed  # noqa: E402  (path set above)

SUBS = REPO / "Data/Spanish/layers/subtitles"


def load_bank(path):
    rows = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                rows[row["id"]] = row
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subs", default=str(SUBS))
    ap.add_argument("--include-held", action="store_true",
                    help="also score sentences that failed only a taste gate")
    ap.add_argument("--top", type=int, default=0,
                    help="only score candidates of the top N inventory words, so "
                         "a full end-to-end pass can be run on a bounded slice "
                         "before paying for the whole corpus (0 = all)")
    ap.add_argument("--limit", type=int, default=0,
                    help="embed at most N new sentences this run (0 = all)")
    args = ap.parse_args()

    subs = Path(args.subs)
    bank = load_bank(subs / "sentence_bank.jsonl")
    candidates = json.loads((subs / "word_candidates.json").read_text(encoding="utf-8"))

    if args.top:
        inv = json.loads((REPO / "Data/Spanish/layers/word_inventory.json")
                         .read_text(encoding="utf-8"))
        keep = {e["word"] for e in inv[:args.top]}
        candidates = {w: v for w, v in candidates.items() if w in keep}
        print("restricted to top %d words: %d have candidates"
              % (args.top, len(candidates)))

    wanted = set()
    for pools in candidates.values():
        wanted.update(pools.get("clean") or [])
        if args.include_held:
            wanted.update(pools.get("held") or [])
    wanted &= set(bank)

    align_path = subs / "alignment.json"
    alignment = {}
    if align_path.exists():
        alignment = json.loads(align_path.read_text(encoding="utf-8"))

    todo = sorted(wanted - set(alignment))
    print("candidate sentences: %d | already scored: %d | to score: %d"
          % (len(wanted), len(wanted & set(alignment)), len(todo)))
    if args.limit:
        todo = todo[:args.limit]
        print("  limited to %d this run" % len(todo))
    if not todo:
        print("nothing to do")
        return

    # One embed() call for both sides: it de-duplicates internally and a repeated
    # subtitle line is common, so batching the whole set beats per-sentence calls.
    texts = [bank[sid]["es"] for sid in todo] + [bank[sid]["en"] for sid in todo]
    vectors = embed(texts)

    for sid in todo:
        row = bank[sid]
        es_v, en_v = vectors.get(row["es"]), vectors.get(row["en"])
        if es_v is None or en_v is None:
            continue
        alignment[sid] = round(float(np.dot(es_v, en_v)), 4)

    align_path.write_text(json.dumps(alignment, ensure_ascii=False), encoding="utf-8")

    scores = sorted(alignment.values())
    if scores:
        pick = lambda q: scores[min(len(scores) - 1, int(q * len(scores)))]
        print("\nalignment over %d sentences: p10 %.3f  median %.3f  p90 %.3f"
              % (len(scores), pick(0.10), pick(0.50), pick(0.90)))
        print("  at or above 0.90 (current floor): %d (%.1f%%)"
              % (sum(1 for s in scores if s >= 0.90),
                 100.0 * sum(1 for s in scores if s >= 0.90) / len(scores)))
    print("wrote %s" % align_path)


if __name__ == "__main__":
    main()
