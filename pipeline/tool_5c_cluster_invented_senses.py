#!/usr/bin/env python3
"""tool_5c_cluster_invented_senses — find sense rows that say the same thing twice.

36.5% of the artist master (10,124 of 27,738 senses) is LLM-invented gap-fill
rather than dictionary content, and **100% of those carry no `context` field**.
That is why duplicates survive: `step_8a` dedupes on `(pos, translation, context)`,
so two invented NOUN senses with empty context differ only by translation and
both ship. `reales` shows both "money" and "cash" for exactly this reason — two
separate invention events, two gloss strings, two sense_id hashes, never compared.

This clusters senses within a `(word, POS)` group by gloss-vector cosine and
proposes merges. It also compares invented senses against their DICTIONARY
siblings, because an invention duplicating a dictionary sense is the same defect
and is likelier still.

    SENSE IDS ARE LOAD-BEARING. They hash gloss text and carry per-sense learner
    progress (COLLABORATION.md rule 4). This tool never rewrites them in place.
    It writes a proposal plus a migration map {retired_id: surviving_id} so a
    merge can be applied deliberately, with progress carried across.

Usage:
    python3 pipeline/tool_5c_cluster_invented_senses.py --dry-run
    python3 pipeline/tool_5c_cluster_invented_senses.py --threshold 0.93 --embed
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline"))

LAYERS = REPO / "Data/Spanish/layers"
MASTER = REPO / "Artists/spanish/vocabulary_master.json"


def gloss(word, s):
    tr = (s.get("translation") or "").strip() or "(sin traduccion)"
    ctx = (s.get("context") or "").strip()
    return f'"{word}" ({s.get("pos","")}): {tr}' + (f" — {ctx}" if ctx else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default=str(MASTER))
    ap.add_argument("--threshold", type=float, default=0.93)
    ap.add_argument("--embed", action="store_true",
                    help="embed any gloss not already cached (~$0.05 for 10k)")
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    master = json.loads(Path(args.master).read_text(encoding="utf-8"))
    idx = json.loads((LAYERS / "sense_vectors/vec_index.json").read_text())

    need, groups = set(), []
    for key, entry in master.items():
        word = entry.get("word") or ""
        by_pos = collections.defaultdict(list)
        for s in (entry.get("senses") or []):
            by_pos[s.get("pos")].append(s)
        for pos, senses in by_pos.items():
            if len(senses) < 2:
                continue
            groups.append((key, word, pos, senses))
            for s in senses:
                need.add(gloss(word, s))

    missing = sorted(need - set(idx))
    inv = sum(1 for _, _, _, ss in groups for s in ss if s.get("source") != "spanishdict")
    print(f"{len(groups):,} (word, POS) groups with >=2 senses; "
          f"{inv:,} of their senses are invented")
    print(f"glosses needing a vector: {len(missing):,} "
          f"(~${len(missing)*30/1e6*0.15:.3f})")

    if missing:
        if not args.embed:
            print("  pass --embed to embed them; proceeding with cached only")
        else:
            from step_6d_assign_senses_embeddings import embed
            embed(missing)
            idx = json.loads((LAYERS / "sense_vectors/vec_index.json").read_text())

    M = np.load(LAYERS / "sense_vectors/vec.npy", mmap_mode="r")
    proposals, migration = [], {}
    stats = collections.Counter()

    for key, word, pos, senses in groups:
        keys = [gloss(word, s) for s in senses]
        ok = [i for i, g in enumerate(keys) if g in idx]
        if len(ok) < 2:
            continue
        V = np.asarray(M[[idx[keys[i]] for i in ok]], np.float32)
        V /= np.linalg.norm(V, axis=1, keepdims=True) + 1e-9
        sim = V @ V.T
        # greedy: first sense in menu order survives, later near-duplicates retire
        retired = set()
        for a in range(len(ok)):
            if a in retired:
                continue
            for b in range(a + 1, len(ok)):
                if b in retired or sim[a, b] < args.threshold:
                    continue
                sa, sb = senses[ok[a]], senses[ok[b]]
                # never retire a dictionary sense in favour of an invention
                if sa.get("source") != "spanishdict" and sb.get("source") == "spanishdict":
                    sa, sb = sb, sa
                if not (sb.get("sense_id") and sa.get("sense_id")):
                    continue
                retired.add(b)
                kind = ("invented~invented" if sa.get("source") != "spanishdict"
                        and sb.get("source") != "spanishdict"
                        else "invented~dictionary" if sb.get("source") != "spanishdict"
                        or sa.get("source") != "spanishdict" else "dictionary~dictionary")
                stats[kind] += 1
                migration[sb["sense_id"]] = sa["sense_id"]
                proposals.append(dict(card=key, word=word, pos=pos, kind=kind,
                                      keep=sa.get("translation"), retire=sb.get("translation"),
                                      keep_id=sa["sense_id"], retire_id=sb["sense_id"],
                                      cos=round(float(sim[a, b]), 4)))

    print(f"\nmerge proposals at cos>={args.threshold}: {len(proposals):,}")
    for k, v in stats.most_common():
        print(f"   {k:<22} {v:,}")
    cards = len({p["card"] for p in proposals})
    print(f"   affecting {cards:,} cards")
    print("\n  sample:")
    for p in sorted(proposals, key=lambda x: -x["cos"])[:12]:
        print(f"    {p['word']:<14} {p['pos']:<5} keep '{p['keep']}'  retire '{p['retire']}'"
              f"  ({p['cos']}, {p['kind']})")

    if args.dry_run or not args.out:
        return print("\n--dry-run / no --out: nothing written")
    Path(args.out).write_text(json.dumps(
        {"threshold": args.threshold, "proposals": proposals, "migration": migration},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}  ({len(migration):,} id migrations)")
    print("NOT applied. Sense IDs carry learner progress; apply deliberately.")


if __name__ == "__main__":
    main()
