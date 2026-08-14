#!/usr/bin/env python3
"""tool_5a_seed_bank_from_examples — put the current examples into the new shape.

The three-stage split (harvest -> embed -> pick) reads a sentence bank, a
candidate list and an alignment file. The examples already in examples_raw.json
were produced by step_5a_build_examples_v2, which computed all of that and then
threw away everything except the winners — but the winners themselves carry
their score, alignment and OpenSubtitles provenance.

So the existing examples can be lifted into the new layout with no corpus scan
and no embedding. The bank starts small (only sentences that were already
picked, so every word's candidate pool is exactly its current examples) and a
later real harvest merges into it without losing anything.

This is a migration convenience, not a pipeline step. Run it once.

Usage:
    python3 pipeline/tool_5a_seed_bank_from_examples.py
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LAYERS = REPO / "Data/Spanish/layers"
SUBS = LAYERS / "subtitles"

SEED_RUN = "seeded-from-examples_raw-v1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", default=str(LAYERS / "examples_raw.json"))
    ap.add_argument("--subs", default=str(SUBS))
    args = ap.parse_args()

    raw = json.loads(Path(args.examples).read_text(encoding="utf-8"))
    subs = Path(args.subs)
    subs.mkdir(parents=True, exist_ok=True)

    bank_path = subs / "sentence_bank.jsonl"
    existing = {}
    if bank_path.exists():
        with bank_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    row = json.loads(line)
                    existing[row["id"]] = row

    rows, candidates, alignment = {}, {}, {}
    no_align = 0
    if (subs / "alignment.json").exists():
        alignment = json.loads((subs / "alignment.json").read_text(encoding="utf-8"))

    for word, examples in raw.items():
        ids = []
        for ex in examples or []:
            sid = ex.get("id")
            if not sid:
                continue
            ids.append(sid)
            if sid not in rows:
                rows[sid] = {
                    "id": sid,
                    "es": ex.get("target", ""),
                    "en": ex.get("english", ""),
                    "score": ex.get("score", 0.0),
                    "naturalness": ex.get("naturalness"),
                    "hard_words": ex.get("hard_words"),
                    "tokens": ex.get("tokens"),
                    # These survived the v2 gates, so none is a taste reject.
                    "gate": None,
                    "provenance": ex.get("provenance") or {},
                    "harvest_run": SEED_RUN,
                }
            if ex.get("alignment") is not None:
                alignment.setdefault(sid, ex["alignment"])
            elif sid not in alignment:
                no_align += 1
        if ids:
            candidates[word] = {"clean": ids, "held": []}

    merged = dict(existing)
    for sid, row in rows.items():
        merged.setdefault(sid, row)
    with bank_path.open("w", encoding="utf-8") as f:
        for sid in sorted(merged):
            f.write(json.dumps(merged[sid], ensure_ascii=False) + "\n")

    cand_path = subs / "word_candidates.json"
    if cand_path.exists():
        prior = json.loads(cand_path.read_text(encoding="utf-8"))
        for word, pools in candidates.items():
            slot = prior.setdefault(word, {"clean": [], "held": []})
            slot["clean"] = list(dict.fromkeys(list(slot.get("clean") or []) + pools["clean"]))
        candidates = prior
    cand_path.write_text(json.dumps(candidates, ensure_ascii=False), encoding="utf-8")
    (subs / "alignment.json").write_text(
        json.dumps(alignment, ensure_ascii=False), encoding="utf-8")

    (subs / "seed_manifest.json").write_text(json.dumps({
        "seed_run": SEED_RUN,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(args.examples),
        "words_with_examples": len(candidates),
        "sentences_seeded": len(rows),
        "sentences_in_bank": len(merged),
        "alignment_scores": len(alignment),
        "missing_alignment": no_align,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print("seeded from %s" % args.examples)
    print("  words with candidates: %d" % len(candidates))
    print("  sentences into bank:   %d (bank now %d)" % (len(rows), len(merged)))
    print("  alignment scores:      %d (missing %d)" % (len(alignment), no_align))
    print("wrote %s" % subs)


if __name__ == "__main__":
    main()
