#!/usr/bin/env python3
"""tool_5c_embed_sense_glosses — pre-pay the sense side of the vector cache.

step_6d embeds glosses and sentences together, and only for words that already
have an example. This does the gloss half alone, for the whole inventory, so the
one-time spend is out of the way before the example set is settled.

Uses step_6d's own gloss() renderer, so the strings — and therefore the cache
keys — are identical to what classification will look up later. Nothing is
classified and no deck changes.

Resumable: the cache is keyed by exact text, so an interrupted run costs
nothing. Re-run the same command and it continues from where it stopped.

Note the cache is keyed on the RENDERED gloss. Changing the gloss format later
(dropping the POS tag, say) orphans every vector this writes. Settle the format
first if you intend to change it.

Usage:
    python3 pipeline/tool_5c_embed_sense_glosses.py --dry-run
    python3 pipeline/tool_5c_embed_sense_glosses.py --minutes 20
    python3 pipeline/tool_5c_embed_sense_glosses.py            # everything
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from step_6d_assign_senses_embeddings import embed, gloss  # noqa: E402

LAYERS = REPO / "Data/Spanish/layers"
CACHE = LAYERS / "sense_vectors"
RATE_PER_MIN = 2800   # the self-imposed limit inside embed()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", default=str(LAYERS / "sense_menu/spanishdict.json"))
    ap.add_argument("--minutes", type=float, default=0,
                    help="stop after roughly N minutes of budget (0 = no cap)")
    ap.add_argument("--limit", type=int, default=0,
                    help="hard cap on texts this run (0 = no cap)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = json.loads(Path(args.menu).read_text(encoding="utf-8"))
    texts, words = [], 0
    seen = set()
    for word, entries in raw.items():
        words += 1
        for entry in entries or []:
            for sense in (entry.get("senses") or {}).values():
                text = gloss(word, sense)
                if text not in seen:
                    seen.add(text)
                    texts.append(text)

    idx_path = CACHE / "vec_index.json"
    cached = set()
    if idx_path.exists():
        cached = set(json.loads(idx_path.read_text(encoding="utf-8")))
    todo = [t for t in texts if t not in cached]

    print("menu: %d words, %d distinct gloss strings" % (words, len(texts)))
    print("  already cached: %d" % (len(texts) - len(todo)))
    print("  to embed:       %d  (~%.0f min at %d/min, ~$%.2f)"
          % (len(todo), len(todo) / RATE_PER_MIN, RATE_PER_MIN,
             len(todo) * 30 / 1e6 * 0.15))

    budget = int(args.minutes * RATE_PER_MIN) if args.minutes else 0
    cap = min([n for n in (budget, args.limit) if n] or [0])
    if cap and cap < len(todo):
        todo = todo[:cap]
        print("  capped this run: %d (~%.0f min)" % (len(todo), len(todo) / RATE_PER_MIN))

    if args.dry_run:
        print("\n--dry-run: nothing embedded")
        return
    if not todo:
        print("nothing to do")
        return

    started = time.time()
    embed(todo)
    print("\ndone in %.1f min; re-run to continue if it was capped"
          % ((time.time() - started) / 60))


if __name__ == "__main__":
    main()
