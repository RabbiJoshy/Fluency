#!/usr/bin/env python3
"""Token-level WSD by tuple prototypes — no API, no training, entirely offline.

Instead of representing a sense by its English gloss and the query by the whole
sentence, represent a (headword, POS) TUPLE by the average contextual vector of
the target token across that tuple's example sentences, and the query by the
target token's own contextual vector. Spanish to Spanish, one model, one space.

Why tuple level and not leaf level: 95.6% of leaves ship exactly ONE example, so
holding it out to test on leaves nothing to build a prototype from. Pooled at
tuple level the median is 4 examples and 81.8% of tuples have >=2, which is what
makes leave-one-out possible at all.

Two rules this design exists to respect, both learned the hard way (see
Data/Spanish/Intermediates/wsd_sense_harness/README.md):

  * never mix score families in one argmax. Every tuple in a scored menu must
    have a real prototype — no falling back to a gloss vector for the ones that
    are short of examples, because the offset between families dwarfs the signal
    and manufactures a fake win. Hence --min-examples, applied to EVERY tuple in
    the menu and not just the gold one.
  * TEST items must be target-present. In the dictionary gold a sense's example
    illustrates its HEADWORD, so the `una` menu holds `unir` examples reading
    "Unió los cables". Picking the token to align by asking which tuple is
    correct would leak the label. On target-present items the token is the
    lookup surface form regardless of the answer, which is also exactly what
    production sees. Prototype SOURCES may be target-absent: they are labelled
    data, so aligning them via the headword is legitimate.

Usage:
    python3 pipeline/wsd_harness/bench_token_prototypes.py --limit 2000
    python3 pipeline/wsd_harness/bench_token_prototypes.py
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np

REPO = Path("/Users/joshuathomasamar/PycharmProjects/Fluency")
LAYERS = REPO / "Data/Spanish/layers"
TOKEN = re.compile(r"[a-z0-9áéíóúüñ]+")


def deacc(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


def tup(word, s):
    return ((s.get("headword") or word).strip().lower(), (s.get("pos") or "").strip())


def load_menus():
    raw = json.loads((LAYERS / "sense_menu/spanishdict.json").read_text(encoding="utf-8"))
    return {w: {sid: v for e in entries for sid, v in e.get("senses", {}).items()}
            for w, entries in raw.items()}


# ---------------------------------------------------------------- alignment
def find_span(sentence, word, headword, revconj):
    """Character span of the token realising `headword` in `sentence`.

    Order matters: the surface form is used when present because that is the
    occurrence production actually disambiguates. Otherwise the conjugation
    layer resolves an inflected verb back to its lemma (`Unió` -> `unir`), which
    covers the 61k of 96k leaves that are verbs. A stem test mops up nouns and
    adjectives, where Spanish inflection is suffixing.
    """
    low = sentence.lower()
    dl = deacc(sentence)
    spans = [(m.start(), m.end()) for m in re.finditer(r"[a-záéíóúüñ0-9]+", low)]

    w = deacc(word)
    for a, b in spans:                                   # 1. exact surface form
        if deacc(sentence[a:b]) == w:
            return a, b

    hw = headword[:-2] if headword.endswith("se") and len(headword) > 3 else headword
    hwd = deacc(hw)
    for a, b in spans:                                   # 2. conjugation layer
        t = sentence[a:b].lower()
        for entry in revconj.get(t, ()) or ():
            if entry.get("lemma", "").lower() in (hw, headword):
                return a, b

    best = None                                          # 3. stem prefix
    stem = hwd[:-2] if len(hwd) > 4 else hwd
    if len(stem) >= 4:
        for a, b in spans:
            t = dl[a:b]
            if t.startswith(stem) and (best is None or len(t) < best[2]):
                best = (a, b, len(t))
    return (best[0], best[1]) if best else None


# ---------------------------------------------------------------- encoding
def encode(sentences, spans_by_sent, model_name, device, layers, batch):
    """One forward pass per sentence; pull out every span we need from it."""
    import torch
    from transformers import AutoTokenizer, AutoModel

    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name, output_hidden_states=True)
    model.eval().to(device)

    out = {}
    with torch.no_grad():
        for i in range(0, len(sentences), batch):
            chunk = sentences[i:i + batch]
            enc = tok(chunk, return_tensors="pt", padding=True, truncation=True,
                      max_length=96, return_offsets_mapping=True)
            offsets = enc.pop("offset_mapping")
            enc = {k: v.to(device) for k, v in enc.items()}
            hs = model(**enc).hidden_states
            reps = torch.stack(hs[-layers:]).mean(0).cpu().numpy()   # (B, T, H)
            for bi, sent in enumerate(chunk):
                om = offsets[bi].numpy()
                for key, (a, b) in spans_by_sent.get(sent, {}).items():
                    sel = [ti for ti in range(len(om))
                           if om[ti][1] > om[ti][0] and om[ti][0] < b and om[ti][1] > a]
                    if not sel:
                        continue
                    v = reps[bi][sel].mean(0)
                    n = np.linalg.norm(v)
                    if n > 0:
                        out[(sent, key)] = (v / n).astype(np.float32)
            if (i // batch) % 25 == 0:
                print(f"    encoded {min(i+batch, len(sentences)):,}/{len(sentences):,}",
                      flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="bert-base-multilingual-cased")
    ap.add_argument("--layers", type=int, default=4, help="mean of last N layers")
    ap.add_argument("--min-examples", type=int, default=2,
                    help="every tuple in a scored menu needs at least this many")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--limit", type=int, default=0, help="cap test items (smoke test)")
    ap.add_argument("--baseline", default="", help="rows json from bench_tuple_accuracy")
    ap.add_argument("--out", default="", help="write per-item predictions")
    args = ap.parse_args()

    menus = load_menus()
    revconj = json.loads((LAYERS / "conjugation_reverse.json").read_text(encoding="utf-8"))
    print(f"menus {len(menus):,}  conjugation forms {len(revconj):,}", flush=True)

    # ---- population: menus with >1 tuple where EVERY tuple clears --min-examples
    #      (the score-family rule: no tuple may fall back to a different family)
    items = []            # test candidates
    sources = collections.defaultdict(list)   # (word, tuple) -> [sentence]
    for w, m in menus.items():
        by_t = collections.defaultdict(list)
        for sid, s in m.items():
            for e in (s.get("examples") or []):
                o = (e.get("original") or "").strip()
                if o:
                    by_t[tup(w, s)].append(o)
        if len(by_t) < 2 or any(len(v) < args.min_examples for v in by_t.values()):
            continue
        for t, sents in by_t.items():
            sources[(w, t)] = sents
            for o in sents:
                if deacc(w) in set(TOKEN.findall(deacc(o))):     # target-present only
                    items.append((w, o, t))
    print(f"scoreable menus give {len(items):,} test items "
          f"across {len({(w,) for w, _, _ in items}):,} words", flush=True)
    if args.limit:
        items = items[:args.limit]
        print(f"  capped to {len(items):,}")

    # ---- what needs a vector, and where in each sentence
    # index by word once; scanning `sources` per item is O(items x sources)
    by_word = collections.defaultdict(list)
    for (w, t) in sources:
        by_word[w].append(t)
    keep = {(w, t) for w, _, _t in items for t in by_word[w]}
    spans = collections.defaultdict(dict)
    unaligned = 0
    for (w, t), sents in sources.items():
        if (w, t) not in keep:
            continue
        for o in sents:
            sp = find_span(o, w, t[0], revconj)
            if sp:
                spans[o][(w, t)] = sp
            else:
                unaligned += 1
    # test items align on the SURFACE FORM, never on the gold tuple
    test_spans = {}
    for w, o, t in items:
        sp = find_span(o, w, w, revconj)
        if sp:
            spans[o][(w, "__TEST__")] = sp
            test_spans[(w, o)] = sp
    aligned_tests = sum(1 for w, o, _ in items if (w, o) in test_spans)
    print(f"alignment: {aligned_tests:,}/{len(items):,} test items "
          f"({aligned_tests/max(len(items),1):.1%}); {unaligned:,} prototype sources missed",
          flush=True)

    sent_list = sorted(spans)
    print(f"encoding {len(sent_list):,} distinct sentences with {args.model} "
          f"on {args.device}", flush=True)
    vecs = encode(sent_list, spans, args.model, args.device, args.layers, args.batch)
    print(f"  got {len(vecs):,} token vectors", flush=True)

    # ---- leave-one-out scoring
    base = {}
    if args.baseline:
        for r in json.loads(Path(args.baseline).read_text()):
            base[(r["word"], r["sent"])] = r["ok_tup"]

    preds = []
    n = ok = skipped = 0
    ok_base = n_base = 0
    per_size = collections.defaultdict(lambda: [0, 0])
    for w, o, gold_t in items:
        q = vecs.get((o, (w, "__TEST__")))
        if q is None:
            skipped += 1
            continue
        cands, protos = [], []
        bad = False
        for t in by_word[w]:
            sents = sources[(w, t)]
            pool = [vecs[(s, (w, t))] for s in sents
                    if s != o and (s, (w, t)) in vecs]
            if not pool:
                bad = True
                break
            cands.append(t)
            protos.append(np.mean(pool, 0))
        if bad or len(cands) < 2:
            skipped += 1
            continue
        P = np.stack(protos)
        P /= np.linalg.norm(P, axis=1, keepdims=True) + 1e-9
        sims = P @ q
        order = np.argsort(-sims)
        pred = cands[int(order[0])]
        gap = float(sims[order[0]] - sims[order[1]])
        preds.append(dict(word=w, sent=o, gold=list(gold_t), pred=list(pred),
                          ok=pred == gold_t, gap=gap, n_tup=len(cands),
                          base_ok=base.get((w, o))))
        n += 1
        ok += (pred == gold_t)
        per_size[min(len(cands), 5)][0] += 1
        per_size[min(len(cands), 5)][1] += (pred == gold_t)
        if (w, o) in base:
            n_base += 1
            ok_base += base[(w, o)]

    print(f"\n{'='*70}\nTOKEN PROTOTYPE WSD — {n:,} scored, {skipped:,} skipped\n{'='*70}")
    print(f"  tuple accuracy            {ok/max(n,1):.2%}")
    if n_base:
        print(f"  gloss-embedding baseline  {ok_base/n_base:.2%}  (same {n_base:,} items)")
    if args.out:
        Path(args.out).write_text(json.dumps(preds, ensure_ascii=False))
        print(f"  wrote {args.out}")
    print(f"\n  by tuples in menu:")
    for k in sorted(per_size):
        a, b = per_size[k]
        lab = f"{k}" if k < 5 else "5+"
        print(f"    {lab:>3} tuples  n={a:>7,}  {b/a:.2%}")


if __name__ == "__main__":
    main()
