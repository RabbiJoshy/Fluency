#!/usr/bin/env python3
"""Lemma+POS accuracy of the embedding classifier, measured on dictionary gold.

Gold: every SpanishDict menu sense ships its own example sentence. That sentence
is a labelled instance of that sense, authored by the dictionary. The sense
vector is built from the sense's ENGLISH GLOSS, never from its example, so
scoring the example against the gloss is not leakage.

Metric: did the predicted leaf carry the same (headword, pos) as the gold leaf.
Leaf-splitting mostly vanishes at tuple level, so exact match is meaningful here
in a way it never was at leaf level.

Reports overall, on non-trivial menus (>1 tuple), by menu size, and as an
accuracy/coverage curve so "yield at 99%" has a number.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

import numpy as np

REPO = Path("/Users/joshuathomasamar/PycharmProjects/Fluency")
LAYERS = REPO / "Data/Spanish/layers"
CACHE = LAYERS / "sense_vectors"
BG_N, BG_K = 1200, 40
HIGH_CUT, MEDIUM_CUT = 0.035, 0.021


def gloss(word, m):
    tr = (m.get("translation") or "").strip() or "(sin traduccion)"
    ctx = (m.get("context") or "").strip()
    return f'"{word}" ({m.get("pos","")}): {tr}' + (f" — {ctx}" if ctx else "")


def norm_tr(t):
    t = (t or "").lower().strip()
    t = re.sub(r"^(to |a |an |the )", "", t)
    return re.sub(r"[^a-z0-9 ]", "", t).strip()


def tup(word, m):
    return ((m.get("headword") or word).strip().lower(), (m.get("pos") or "").strip())


def deacc(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


# The reflexive gate lives in pipeline/util_5c_token_prototypes so the bench
# and step_6e can never drift on it.
sys.path.insert(0, str(REPO))
from pipeline.util_5c_token_prototypes import reflexive_evidence  # noqa: E402


def has_target(word, sent):
    """Does the sentence actually contain the surface form being disambiguated?

    68% of the dictionary gold does NOT: the menu is keyed by surface form but a
    sense's example illustrates its HEADWORD, so the `una` menu carries `unir`
    senses whose examples read "Unió los cables". Production only ever classifies
    sentences that do contain the form, so the two slices are different tasks and
    only the target-present one transfers.
    """
    w, s = deacc(word), deacc(sent)
    if " " in w:
        return w in s
    # token membership only — a substring test counts `toma` as present in
    # "tiene que tomar", which is a different word and a different task
    return w in set(re.findall(r"[a-z0-9áéíóúüñ']+", s))


_WORDS = re.compile(r"[\w\u00c0-\u017f']+")


def render_query(word, sent, mode):
    """The query text handed to the embedder.

    'plain' is what ships: the bare sentence, which is IDENTICAL for every target
    word in it. A sentence carrying three menu words produces one vector serving
    all three disambiguations — the model is never told which token it is being
    asked about. The marked variants name the target so the vector can be about
    the word rather than about the topic.
    """
    if mode == "plain":
        return sent
    if mode == "mark_prefix":
        return f'"{word}" en: {sent}'
    if mode == "mark_suffix":
        return f'{sent} — "{word}"'
    if mode in ("window", "window_marked"):
        # Locality, not topic. The shipped query is the whole line, so a line
        # carrying three menu words yields ONE vector for all three -- the score
        # is dominated by what the line is ABOUT. Nearly every wrong-POS pick in
        # the graded lyric sample is decidable from the immediate neighbours and
        # indecidable from the topic: `como una obra de arte` (una as a verb),
        # `el ex novio fue un desastre` (fue as a noun), `las puerta' bajan`
        # (las as a pronoun). This keeps the target plus three tokens each side.
        toks = _WORDS.findall(sent)
        low = [t.lower() for t in toks]
        try:
            i = low.index(word.lower())
        except ValueError:
            return sent                     # target not locatable: no window to take
        frag = " ".join(toks[max(0, i - 3):i + 4])
        return f'"{word}" en: {frag}' if mode == "window_marked" else frag
    raise ValueError(mode)


def load_menus():
    raw = json.loads((LAYERS / "sense_menu/spanishdict.json").read_text(encoding="utf-8"))
    return {w: {s: v for e in entries for s, v in e.get("senses", {}).items()}
            for w, entries in raw.items()}


def build_gold(menus):
    """(word, sentence) -> set of gold sense ids. Same sentence filed under two
    leaves means either is gold."""
    gold = collections.defaultdict(set)
    for w, m in menus.items():
        for sid, s in m.items():
            for e in (s.get("examples") or []):
                o = (e.get("original") or "").strip()
                if o:
                    gold[(w, o)].add(sid)
    return gold


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="plain",
                    choices=["plain", "mark_prefix", "mark_suffix",
                             "window", "window_marked"],
                    help="how the sentence is rendered before embedding")
    ap.add_argument("--target-present-only", action="store_true",
                    help="restrict gold to sentences containing the lookup form")
    ap.add_argument("--allow-embed", action="store_true",
                    help="embed any query strings not already cached")
    ap.add_argument("--reflexive-gate", default="off",
                    choices=["off", "permissive", "se-only", "oracle"],
                    help="prune the wrong half of an X/Xse pair before argmax")
    ap.add_argument("--no-hub", action="store_true",
                    help="disable the hubness offset")
    ap.add_argument("--drop-empty", action="store_true",
                    help="remove empty-translation leaves from the candidate pool")
    ap.add_argument("--out", default="")
    ap.add_argument("--failures", default="")
    args = ap.parse_args()

    menus = load_menus()
    gold = build_gold(menus)
    if args.target_present_only:
        gold = {k: v for k, v in gold.items() if has_target(k[0], k[1])}
    qtext = {k: render_query(k[0], k[1], args.query) for k in gold}
    print(f"menus {len(menus):,}  gold items {len(gold):,}  query={args.query}", flush=True)

    idx = json.loads((CACHE / "vec_index.json").read_text())
    M = np.load(CACHE / "vec.npy", mmap_mode="r")

    # ---- candidate pool per word, optionally minus empty-translation leaves
    pool = {}
    dropped_empty = 0
    for w, m in menus.items():
        sids = list(m)
        if args.drop_empty:
            keep = [s for s in sids if (m[s].get("translation") or "").strip()]
            dropped_empty += len(sids) - len(keep)
            sids = keep or sids          # never empty a menu entirely
        pool[w] = sids
    if args.drop_empty:
        print(f"dropped {dropped_empty:,} empty-translation leaves from pools")

    # ---- everything we need a vector for
    need = set()
    for k in gold:
        need.add(qtext[k])
    for w, sids in pool.items():
        for s in sids:
            need.add(gloss(w, menus[w][s]))
    missing = [t for t in need if t not in idx]
    if missing and args.allow_embed:
        sys.path.insert(0, str(REPO / "pipeline"))
        from step_6d_assign_senses_embeddings import embed as _embed
        print(f"embedding {len(missing):,} new query strings", flush=True)
        _embed(missing)
        idx = json.loads((CACHE / "vec_index.json").read_text())
        M = np.load(CACHE / "vec.npy", mmap_mode="r")
        missing = [t for t in need if t not in idx]
    if missing:
        print(f"MISSING {len(missing):,} vectors — pass --allow-embed")
        print("  e.g. " + repr(missing[0])[:120])
        sys.exit(1)

    # ---- fixed background sample, mirroring step_6d (drawn from the run's own
    # sentences, but never from the word's own pool, and identical for all words)
    sents_in_order = []
    seen = set()
    for k in gold:
        t = qtext[k]
        if t not in seen:
            seen.add(t)
            sents_in_order.append(t)
    rng = np.random.default_rng(0)
    bg_texts = (sents_in_order if len(sents_in_order) <= BG_N else
                [sents_in_order[i] for i in rng.choice(len(sents_in_order), BG_N, False)])
    BG = np.asarray(M[[idx[t] for t in bg_texts]], np.float32)

    # ---- group gold by word
    by_word = collections.defaultdict(list)
    for k, gsids in gold.items():
        by_word[k[0]].append((k[1], gsids, qtext[k]))

    rows = []          # one per gold item
    for w, items in by_word.items():
        sids = pool[w]
        m = menus[w]
        S = np.asarray(M[[idx[gloss(w, m[s])] for s in sids]], np.float32)
        Q = np.asarray(M[[idx[q] for _, _, q in items]], np.float32)
        hub = (np.zeros(S.shape[0], np.float32) if args.no_hub
               else np.sort(BG @ S.T, axis=0)[-min(BG_K, BG.shape[0]):].mean(0))
        C = Q @ S.T - hub[None, :]

        # class ids for the SHIPPED gap: (pos, normalised translation)
        cls, cid = {}, []
        for s in sids:
            cid.append(cls.setdefault((m[s].get("pos", ""), norm_tr(m[s].get("translation"))),
                                      len(cls)))
        cid = np.array(cid)
        n_cls = len(cls)

        # tuple ids: (headword, pos) — the level knowledge is recorded at
        tls, tid = {}, []
        for s in sids:
            tid.append(tls.setdefault(tup(w, m[s]), len(tls)))
        tid = np.array(tid)
        n_tup = len(tls)
        tup_list = list(tls)

        # which leaves are -se lemmas, and does this menu offer both members of a
        # reflexive pair at all (the only place the gate can change anything)
        is_se = np.array([tup(w, m[s])[0].endswith("se") for s in sids])
        lems = {tup(w, m[s])[0] for s in sids}
        refl_ambiguous = any(L + "se" in lems for L in lems)

        for j, (sent, gsids, _q) in enumerate(items):
            row = C[j]
            gold_tups = {tup(w, m[s]) for s in gsids}

            gate_fired = gate_right = False
            grow = row
            if args.reflexive_gate != "off" and refl_ambiguous:
                truth = any(g[0].endswith("se") for g in gold_tups)
                ev = (truth if args.reflexive_gate == "oracle"
                      else reflexive_evidence(w, sent, args.reflexive_gate))
                if ev is not None and (is_se == ev).any():
                    # a finite floor, not -inf: excluded leaves must stay ordered
                    # so the gap stays a real number
                    grow = np.where(is_se == ev, row, row.min() - 1.0)
                    gate_fired, gate_right = True, (ev == truth)

            # -- shipped: argmax over leaves, tuple falls out of the winner
            k = int(np.argmax(grow))
            pred_leaf = sids[k]
            pred_tup = tup(w, m[pred_leaf])

            # Gaps are measured on the UNGATED scores, signed against whatever the
            # pick was. Scoring them on the gated row lets the gate manufacture a
            # huge gap by deleting the runner-up, which sorts its own mistakes to
            # the top of the confidence ranking — measured, and it wiped out the
            # 99% operating point entirely. A gate-flipped pick now earns a
            # NEGATIVE gap and sinks, which is the honest reading.
            cbest = np.full(n_cls, -np.inf)
            np.maximum.at(cbest, cid, row)
            cgap = (float(cbest[cid[k]] - np.delete(cbest, cid[k]).max())
                    if n_cls > 1 else 1.0)

            # -- tuple-level MAX aggregation (identical pick to leaf argmax) and
            #    its own gap, which is the confidence that matches the metric
            tbest = np.full(n_tup, -np.inf)
            np.maximum.at(tbest, tid, row)
            tgap = (float(tbest[tid[k]] - np.delete(tbest, tid[k]).max())
                    if n_tup > 1 else 1.0)

            # -- tuple-level SUM aggregation over a softmax (vote pooling)
            sums = {}
            for T in (0.01, 0.02, 0.05):
                p = np.exp((row - row.max()) / T)
                p /= p.sum()
                agg = np.zeros(n_tup)
                np.add.at(agg, tid, p)
                o = np.argsort(-agg)
                sums[T] = (tup_list[int(o[0])],
                           float(agg[o[0]] - agg[o[1]]) if n_tup > 1 else 1.0)

            # -- tuple-level MEAN aggregation
            cnt = np.bincount(tid, minlength=n_tup)
            tot = np.bincount(tid, weights=row, minlength=n_tup)
            mean = tot / np.maximum(cnt, 1)
            mo = np.argsort(-mean)
            mean_tup = tup_list[int(mo[0])]

            # -- model-free baselines, scored under the identical weighting
            counts = collections.Counter(tid)
            big_tup = tup_list[counts.most_common(1)[0][0]]
            first_tup = tup(w, m[sids[0]])

            rows.append(dict(
                word=w, sent=sent, n_leaf=len(sids), n_tup=n_tup,
                gold_tups=sorted(gold_tups), pred_tup=list(pred_tup),
                pred_leaf=pred_leaf,
                pred_tr=(m[pred_leaf].get("translation") or ""),
                gold_leaves=sorted(gsids),
                ok_leaf=pred_leaf in gsids,
                ok_tup=pred_tup in gold_tups,
                ok_sum={str(T): sums[T][0] in gold_tups for T in sums},
                ok_mean=mean_tup in gold_tups,
                ok_big=big_tup in gold_tups,
                ok_first=first_tup in gold_tups,
                cgap=cgap, tgap=tgap,
                sum_gap={str(T): sums[T][1] for T in sums},
                empty_pred=not (m[pred_leaf].get("translation") or "").strip(),
                # grouping key for the macro average: one vote per (word, gold
                # tuple), so a tuple holding 24 leaves does not outvote one
                # holding 1. The dictionary emits gold in proportion to LEAVES,
                # which is not the proportion real text emits senses in.
                grp=(w, tuple(map(tuple, sorted(gold_tups)))),
                has_target=has_target(w, sent),
                gate_fired=gate_fired, gate_right=gate_right,
                refl_amb=refl_ambiguous,
            ))

    report(rows)
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False))
        print(f"\nwrote {args.out}")
    if args.failures:
        write_failures(rows, args.failures)


def pct(a, b):
    return f"{a/b:.2%}" if b else "n/a"


def macro(pop, key, sub=None):
    """One vote per (word, gold tuple), then average. Removes the dictionary's
    leaf-count weighting, which no real corpus shares."""
    g = collections.defaultdict(list)
    for r in pop:
        g[r["grp"]].append(r[key][sub] if sub else r[key])
    return sum(sum(v) / len(v) for v in g.values()) / len(g) if g else 0.0


def report(rows):
    n = len(rows)
    nt = [r for r in rows if r["n_tup"] > 1]
    ngrp = len({r["grp"] for r in nt})
    print(f"\n{'='*86}\nLEMMA+POS TUPLE ACCURACY — {n:,} dictionary-gold sentences\n{'='*86}")
    print("micro = per sentence.  macro = per (word, gold tuple), which strips the")
    print("dictionary's leaf-count weighting. Real text is not distributed by leaf count.\n")
    # the production-shaped slice: sentence actually contains the target form
    tgt = [r for r in nt if r["has_target"]]
    print(f"{'':36}{'micro all':>12}{'micro >1tup':>13}{'MACRO >1tup':>13}"
          f"{'TARGET-PRESENT':>16}")
    print(f"{'n':36}{n:>12,}{len(nt):>13,}{ngrp:>13,}{len(tgt):>16,}")

    def line(label, key, sub=None):
        a = sum((r[key][sub] if sub else r[key]) for r in rows)
        b = sum((r[key][sub] if sub else r[key]) for r in nt)
        c = sum((r[key][sub] if sub else r[key]) for r in tgt)
        print(f"{label:36}{pct(a,n):>12}{pct(b,len(nt)):>13}{macro(nt,key,sub):>13.2%}"
              f"{pct(c,len(tgt)):>16}")

    line("leaf argmax -> tuple  (SHIPPED)", "ok_tup")
    line("tuple sum, softmax T=0.01", "ok_sum", "0.01")
    line("tuple sum, softmax T=0.02", "ok_sum", "0.02")
    line("tuple sum, softmax T=0.05", "ok_sum", "0.05")
    line("tuple mean", "ok_mean")
    print(f"{'-'*86}")
    line("BASELINE largest tuple (no model)", "ok_big")
    line("BASELINE first leaf in menu order", "ok_first")
    print(f"{'-'*86}")
    line("exact leaf match (for contrast)", "ok_leaf")

    # by menu size
    print(f"\nby distinct (headword,pos) tuples in the menu:")
    buckets = collections.defaultdict(list)
    for r in rows:
        buckets[min(r["n_tup"], 6)].append(r)
    for k in sorted(buckets):
        b = buckets[k]
        lab = f"{k}" if k < 6 else "6+"
        print(f"  {lab:>3} tuples  n={len(b):>7,}   shipped {pct(sum(r['ok_tup'] for r in b), len(b)):>8}"
              f"   sum@0.02 {pct(sum(r['ok_sum']['0.02'] for r in b), len(b)):>8}")

    # reflexive gate
    amb = [r for r in nt if r["refl_amb"]]
    fired = [r for r in amb if r["gate_fired"]]
    if fired:
        print(f"\nreflexive gate: {len(amb):,} of {len(nt):,} items sit in a menu offering "
              f"both X and Xse ({len(amb)/len(nt):.1%})")
        print(f"  gate fired on {len(fired):,} of them ({len(fired)/len(amb):.1%}); "
              f"its reflexive/plain call was right {sum(r['gate_right'] for r in fired)/len(fired):.2%}")
        print(f"  tuple accuracy on the ambiguous subset: {sum(r['ok_tup'] for r in amb)/len(amb):.2%}")
    # by gold POS — a whole-sentence vector carries topic, which says a lot about
    # a NOUN and nothing about the role of a preposition
    print(f"\nby gold POS (menus >1 tuple):")
    bypos = collections.defaultdict(list)
    for r in nt:
        bypos[r["gold_tups"][0][1]].append(r)
    for p, b in sorted(bypos.items(), key=lambda kv: -len(kv[1])):
        if len(b) >= 50:
            print(f"  {p:<12} n={len(b):>7,}  shipped {pct(sum(r['ok_tup'] for r in b), len(b)):>8}"
                  f"   baseline-largest {pct(sum(r['ok_big'] for r in b), len(b)):>8}")

    # by sentence length — if topic is doing the work, longer sentences dilute the
    # target word's contribution to a single averaged vector
    print(f"\nby sentence length in tokens (menus >1 tuple):")
    bylen = collections.defaultdict(list)
    for r in nt:
        L = len(r["sent"].split())
        bylen[min(L // 5 * 5, 25)].append(r)
    for k in sorted(bylen):
        b = bylen[k]
        lab = f"{k}-{k+4}" if k < 25 else "25+"
        print(f"  {lab:>7} tok  n={len(b):>7,}  shipped {pct(sum(r['ok_tup'] for r in b), len(b)):>8}"
              f"   mean menu {sum(r['n_tup'] for r in b)/len(b):.2f} tuples")

    # coverage curve on the non-trivial subset, by each confidence signal
    print(f"\naccuracy at top-K%% by confidence (menus >1 tuple, n={len(nt):,}):")
    print(f"  {'K':>5} {'class gap (shipped)':>22} {'tuple gap':>12} {'sum gap T=.02':>15}")
    for K in (5, 10, 25, 50, 75, 100):
        k = max(1, int(len(nt) * K / 100))
        out = [f"  {K:>4}%"]
        for conf, ok, sub in (("cgap", "ok_tup", None), ("tgap", "ok_tup", None),
                              ("sum_gap", "ok_sum", "0.02")):
            s = sorted(nt, key=lambda r: -(r[conf][sub] if sub else r[conf]))[:k]
            acc = sum((r[ok][sub] if sub else r[ok]) for r in s) / k
            out.append(f"{acc:>21.2%}" if conf == "cgap" else f"{acc:>11.2%}" if conf == "tgap" else f"{acc:>14.2%}")
        print(" ".join(out))

    # yield at 99% — the number the product actually needs
    for pop, plab in ((nt, "menus >1 tuple"), (tgt, "target-present only")):
        print(f"\nyield at 99% tuple accuracy ({plab}, n={len(pop):,}):")
        for conf, ok, sub, lab in (("cgap", "ok_tup", None, "class gap (shipped)"),
                                   ("tgap", "ok_tup", None, "tuple gap"),
                                   ("sum_gap", "ok_sum", "0.02", "sum gap T=.02")):
            s = sorted(pop, key=lambda r: -(r[conf][sub] if sub else r[conf]))
            good = best = 0
            for i, r in enumerate(s, 1):
                good += (r[ok][sub] if sub else r[ok])
                if good / i >= 0.99:
                    best = i
            print(f"  {lab:22} {best:>7,} of {len(s):,}  ({best/len(s):.1%})")

    # shipped bands
    print(f"\nshipped bands (absolute cuts on the class gap), tuple accuracy:")
    for lab, lo, hi in (("high  >=0.035", HIGH_CUT, 9e9),
                        ("medium>=0.021", MEDIUM_CUT, HIGH_CUT),
                        ("low   < 0.021", -9e9, MEDIUM_CUT)):
        b = [r for r in rows if lo <= r["cgap"] < hi]
        if b:
            print(f"  {lab}  n={len(b):>7,} ({len(b)/n:>5.1%})  tuple {pct(sum(r['ok_tup'] for r in b), len(b)):>8}"
                  f"  leaf {pct(sum(r['ok_leaf'] for r in b), len(b)):>8}")

    # empty-translation contribution
    err = [r for r in rows if not r["ok_tup"]]
    ee = [r for r in err if r["empty_pred"]]
    allempty = [r for r in rows if r["empty_pred"]]
    print(f"\nempty-translation leaves:")
    print(f"  predicted at all      {len(allempty):>7,} ({len(allempty)/n:.2%} of items)")
    print(f"  and wrong at tuple    {len(ee):>7,} ({pct(len(ee), len(err))} of all {len(err):,} errors)")
    if allempty:
        print(f"  accuracy when predicted {pct(sum(r['ok_tup'] for r in allempty), len(allempty))}")


def write_failures(rows, path):
    err = sorted([r for r in rows if not r["ok_tup"]], key=lambda r: -r["cgap"])
    with open(path, "w", encoding="utf-8") as f:
        f.write("cgap\ttgap\ttarget_present\tn_leaf\tn_tup\tword\tgold_tuple\tpred_tuple\t"
                "pred_translation\tsentence\n")
        for r in err:
            g = " | ".join(f"{a}/{b}" for a, b in r["gold_tups"])
            f.write(f"{r['cgap']:.4f}\t{r['tgap']:.4f}\t{int(r['has_target'])}\t{r['n_leaf']}\t"
                    f"{r['n_tup']}\t{r['word']}\t{g}\t{r['pred_tup'][0]}/{r['pred_tup'][1]}\t"
                    f"{r['pred_tr']}\t{r['sent']}\n")
    print(f"wrote {len(err):,} failures -> {path}")

    # which confusions repeat — a systematic (gold -> pred) pair is a fixable
    # inventory or rendering defect; a long tail of singletons is not
    conf = collections.Counter(
        (f"{r['gold_tups'][0][0]}/{r['gold_tups'][0][1]}",
         f"{r['pred_tup'][0]}/{r['pred_tup'][1]}") for r in err)
    print(f"\ntop repeated (gold -> predicted) tuple confusions:")
    for (g, p), c in conf.most_common(20):
        print(f"  {c:>5}  {g:<24} -> {p}")
    top = collections.Counter(r["word"] for r in err)
    print(f"\nwords contributing the most errors:")
    for w, c in top.most_common(15):
        tot = sum(1 for r in rows if r["word"] == w)
        print(f"  {c:>5} / {tot:<5} {w}")


if __name__ == "__main__":
    main()
