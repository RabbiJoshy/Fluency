#!/usr/bin/env python3
"""tool_5c_build_token_prototypes — the offline token-prototype asset.

For every `(lookup word, headword, POS)` tuple that ships at least
--min-examples dictionary examples, encode the target token in each example with
BETO and store the mean vector. This is inventory-derived, so it is built ONCE
and reused by every deck, every artist, every run — the same asymmetry that makes
the gloss vectors worth paying for.

The expensive half of the work lives here on purpose: locating the target token
is hard offline (68% of dictionary examples do not contain the lookup form — the
`una` menu carries `unir` examples reading "Unió los cables") and trivial online
(a harvested candidate sentence always contains the form). `conjugation_reverse`
does the offline resolution.

Scoring rule this asset must preserve: a menu is only scoreable by prototypes if
EVERY tuple in it has one. Falling back to a gloss vector for the thin tuples
mixes two score families in one argmax, and the offset between families dwarfs
the signal. `scoreable_words` in the manifest records which menus qualify.

Usage:
    python3 pipeline/tool_5c_build_token_prototypes.py --dry-run
    python3 pipeline/tool_5c_build_token_prototypes.py
    python3 pipeline/tool_5c_build_token_prototypes.py --artist-dir "Artists/spanish/SpanishTestPlaylist"
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.util_5c_token_prototypes import (  # noqa: E402
    DEFAULT_LAYERS, DEFAULT_MIN_EXAMPLES, DEFAULT_MODEL,
    encode_spans, find_span, load_encoder, proto_key, tuple_of)

LAYERS_DIR = REPO / "Data/Spanish/layers"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artist-dir", default="",
                    help="build from an artist's sense menu instead of normal mode")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--layers", type=int, default=DEFAULT_LAYERS)
    ap.add_argument("--min-examples", type=int, default=DEFAULT_MIN_EXAMPLES)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    base = (REPO / args.artist_dir / "data/layers") if args.artist_dir else LAYERS_DIR
    menu_path = base / "sense_menu/spanishdict.json"
    if not menu_path.exists():
        raise SystemExit(f"no sense menu at {menu_path}")
    out_dir = Path(args.out) if args.out else base / "token_prototypes"

    raw = json.loads(menu_path.read_text(encoding="utf-8"))
    menus = {w: {sid: v for e in entries for sid, v in e.get("senses", {}).items()}
             for w, entries in raw.items()}

    revconj_path = LAYERS_DIR / "conjugation_reverse.json"
    revconj = (json.loads(revconj_path.read_text(encoding="utf-8"))
               if revconj_path.exists() else {})
    print(f"menu {menu_path.relative_to(REPO)}: {len(menus):,} words; "
          f"{len(revconj):,} conjugated forms", flush=True)

    # ---- gather every (word, tuple) and its example sentences
    sources: dict[tuple, list[str]] = collections.defaultdict(list)
    per_word: dict[str, set] = collections.defaultdict(set)
    for w, m in menus.items():
        for sense in m.values():
            t = tuple_of(w, sense)
            per_word[w].add(t)
            for ex in (sense.get("examples") or []):
                o = (ex.get("original") or "").strip()
                if o:
                    sources[(w, t)].append(o)

    kept = {k: v for k, v in sources.items() if len(v) >= args.min_examples}
    # a menu is scoreable only if EVERY one of its tuples has a prototype
    scoreable = sorted(w for w, ts in per_word.items()
                       if len(ts) > 1 and all((w, t) in kept for t in ts))
    print(f"tuples with >={args.min_examples} examples: {len(kept):,} of {len(sources):,}")
    print(f"menus fully scoreable by prototypes: {len(scoreable):,} of "
          f"{sum(1 for ts in per_word.values() if len(ts) > 1):,} ambiguous")

    # ---- align
    spans: dict[str, dict] = collections.defaultdict(dict)
    missed = 0
    for (w, t), sents in kept.items():
        for o in sents:
            sp = find_span(o, w, t[0], revconj)
            if sp:
                spans[o][(w, t)] = sp
            else:
                missed += 1
    n_pairs = sum(len(v) for v in spans.values())
    print(f"aligned {n_pairs:,} (sentence, tuple) pairs across {len(spans):,} "
          f"sentences; {missed:,} could not be located")

    if args.dry_run:
        print("\n--dry-run: nothing encoded or written")
        return

    # ---- encode
    print(f"encoding with {args.model} on {args.device} "
          f"(mean of last {args.layers} layers)", flush=True)
    t0 = time.time()
    tok, model = load_encoder(args.model, args.device)
    sent_list = sorted(spans)
    vecs = encode_spans(sent_list, spans, tok, model, args.device, args.layers,
                        args.batch,
                        progress=lambda d, n: print(f"    {d:,}/{n:,}", flush=True))
    print(f"  {len(vecs):,} token vectors in {time.time()-t0:.0f}s")

    # ---- average into prototypes
    keys, rows, counts = [], [], []
    for (w, t), sents in sorted(kept.items()):
        pool = [vecs[(o, (w, t))] for o in sents if (o, (w, t)) in vecs]
        if len(pool) < args.min_examples:
            continue
        v = np.mean(pool, 0)
        n = float(np.linalg.norm(v))
        if n <= 0:
            continue
        keys.append(proto_key(w, t))
        rows.append((v / n).astype(np.float32))
        counts.append(len(pool))

    # recompute scoreability against what actually survived encoding
    have = {tuple(k.split("\t")) for k in keys}
    scoreable = sorted(w for w, ts in per_word.items()
                       if len(ts) > 1 and all((w, t[0], t[1]) in have for t in ts))

    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "proto.npy", np.stack(rows))
    (out_dir / "proto_index.json").write_text(
        json.dumps({k: i for i, k in enumerate(keys)}, ensure_ascii=False))
    (out_dir / "manifest.json").write_text(json.dumps({
        "model": args.model, "layers": args.layers,
        "min_examples": args.min_examples,
        "prototypes": len(keys),
        "examples_per_prototype_mean": round(sum(counts) / max(len(counts), 1), 2),
        "scoreable_words": scoreable,
        "menu_source": str(menu_path.relative_to(REPO)),
        "built": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()),
    }, ensure_ascii=False, indent=2))
    (out_dir / "proto_counts.json").write_text(
        json.dumps(dict(zip(keys, counts)), ensure_ascii=False))

    print(f"\nwrote {len(keys):,} prototypes -> {out_dir.relative_to(REPO)}")
    print(f"  mean {sum(counts)/max(len(counts),1):.1f} examples each")
    print(f"  {len(scoreable):,} menus fully scoreable")


if __name__ == "__main__":
    main()
