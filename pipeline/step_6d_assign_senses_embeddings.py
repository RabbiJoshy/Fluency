#!/usr/bin/env python3
"""step_6d_assign_senses_embeddings — sense assignment by Gemini embeddings.

The method that survived the 2026-08-11 audit, recorded in
Data/Spanish/Intermediates/wsd_sense_harness/README.md:

  * sense vector from the English gloss: '"word" (POS): translation — context'
  * the sentence embedded once; nearest sense by cosine
  * confidence is the gap between the top two (headword, POS) TUPLES — the
    level learner knowledge is recorded at. A near-tie between synonymous
    leaves is not read as uncertainty, and neither is the hacer/hacerse
    distinction read as certainty just because both glosses say "to make"
  * a per-sense hubness offset, measured OFFLINE against a fixed background
    sample, is subtracted first. Some senses sit near everything and win by
    default; the gap cannot see that because it only compares scores within one
    sentence's row. Estimating the offset from the word's own candidate pool was
    measured and is an artifact — it helps on a balanced pool and hurts on a
    realistic Zipfian one, so the background sample is fixed and shared.

Every example is assigned; none are dropped. Each carries its confidence and a
band, so a low-confidence assignment is visible in the app rather than silently
equal to a high-confidence one. Both gaps are written: `confidence` is the tuple
gap (which lemma+POS) and `class_confidence` the older class gap (which gloss).

    high    gap >= 0.043   measured 99% lemma+POS accurate at this cut
    medium  gap >= 0.020   measured 95% lemma+POS accurate
    low     below          82% overall; assigned anyway so no card is starved

The cuts are ABSOLUTE values derived from 16,016 dictionary-gold sentences that
contain the target form (the production-shaped slice), not quantiles of the
current run. They replace cuts transferred from the 150-sentence hand-labelled
panel, which were calibrated on leaf-level acceptability and on a confidence
signal that could not see the lemma distinction at all.

Cutting on a run's own quantiles instead would make "high" mean "top 10% of
whatever this run happened to contain", which is circular and hides exactly the
thing worth seeing: subtitle sentences score lower than dictionary examples, so a
faithful banding returns fewer highs on real text than on gold.

Usage:
    python3 pipeline/step_6d_assign_senses_embeddings.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import threading
import time
from pathlib import Path

import sys

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from util_6a_assignment_format import stamp_example_ids  # noqa: E402

LAYERS = REPO / "Data/Spanish/layers"
CACHE = LAYERS / "sense_vectors"
METHOD = "spanishdict-embed-v1"
# bumped 2026-08-16: same picks, but `confidence` now means the tuple gap, so
# claims either side of this id are not comparable on confidence
PROMPT_ID = "embed-gloss-tuplegap-hub-v1"
BG_N, BG_K = 1200, 40
# absolute, measured on dictionary gold — see the module docstring
HIGH_CUT, MEDIUM_CUT = 0.043, 0.020


def load_key():
    for line in (REPO / ".env").open(encoding="utf-8"):
        k, _, v = line.partition("=")
        if k.strip() == "GEMINI_API_KEY":
            return v.strip().strip('"').strip("'")
    raise SystemExit("no GEMINI_API_KEY")


def embed(texts):
    """Cached, paced. The quota counts TEXTS in a batch, not requests."""
    idx_p, vec_p = CACHE / "vec_index.json", CACHE / "vec.npy"
    CACHE.mkdir(parents=True, exist_ok=True)
    idx = json.loads(idx_p.read_text()) if idx_p.exists() else {}
    M = np.load(vec_p) if vec_p.exists() else np.zeros((0, 3072), np.float16)
    todo = [t for t in dict.fromkeys(texts) if t not in idx]
    if todo:
        from concurrent.futures import ThreadPoolExecutor
        from google import genai
        from google.genai import types
        cl = genai.Client(api_key=load_key())
        out = [None] * ((len(todo) + 99) // 100)
        st, lock = ({"i": 0, "t0": time.time(), "done": 0, "last": 0.0},
                    threading.Lock())

        def take(k):
            while True:
                with lock:
                    if st["i"] + k <= 2800 / 60 * (time.time() - st["t0"]):
                        st["i"] += k
                        return
                time.sleep(0.4)

        def work(job):
            i, ch = job
            for a in range(6):
                take(len(ch))
                try:
                    r = cl.models.embed_content(
                        model="gemini-embedding-001", contents=ch,
                        config=types.EmbedContentConfig(
                            task_type="SEMANTIC_SIMILARITY"))
                    out[i] = np.asarray([e.values for e in r.embeddings], np.float32)
                    with lock:
                        # Time-based, not count-based. At the pacing limit a
                        # per-N-texts print is minutes apart, which reads as a
                        # hang on a job this long.
                        st["done"] += len(ch)
                        now = time.time()
                        if now - st["last"] >= 10 or st["done"] == len(todo):
                            st["last"] = now
                            rate = st["done"] / max(now - st["t0"], 1e-9)
                            left = (len(todo) - st["done"]) / max(rate, 1e-9)
                            print(f"    {st['done']:,}/{len(todo):,} "
                                  f"({st['done']/len(todo):.0%})  "
                                  f"{rate*60:,.0f}/min  eta {left/60:.1f} min",
                                  flush=True)
                    return
                except Exception:
                    if a == 5:
                        raise
                    time.sleep(8 * (a + 1))

        print(f"  embedding {len(todo):,} new texts "
              f"(~${len(todo)*30/1e6*0.15:.3f})")
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(work, [(i // 100, todo[i:i + 100])
                               for i in range(0, len(todo), 100)]))
        new = np.vstack(out)
        new /= np.linalg.norm(new, axis=1, keepdims=True) + 1e-9
        for t in todo:
            idx[t] = len(idx)
        M = np.vstack([M, new.astype(np.float16)])
        np.save(vec_p, M)
        idx_p.write_text(json.dumps(idx, ensure_ascii=False))
    return {t: M[idx[t]].astype(np.float32) for t in texts}


def gloss(word, m):
    tr = (m.get("translation") or "").strip() or "(sin traduccion)"
    ctx = (m.get("context") or "").strip()
    return f'"{word}" ({m.get("pos","")}): {tr}' + (f" — {ctx}" if ctx else "")


def norm_tr(t):
    t = (t or "").lower().strip()
    t = re.sub(r"^(to |a |an |the )", "", t)
    return re.sub(r"[^a-z0-9 ]", "", t).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", default=str(LAYERS / "examples_raw.json"))
    ap.add_argument("--out", default=str(LAYERS / "sense_assignments/spanishdict.json"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    examples = json.loads(Path(a.examples).read_text(encoding="utf-8"))
    raw = json.loads((LAYERS / "sense_menu/spanishdict.json").read_text(encoding="utf-8"))
    menus = {w: {sid: v for e in entries for sid, v in e.get("senses", {}).items()}
             for w, entries in raw.items()}

    # examples_raw.json keeps a key for every inventory word, most with an empty
    # list. Those words have no sentence to classify, so embedding their menus
    # is pure cost — it was inflating the job roughly twentyfold.
    with_examples = [w for w in examples if examples[w]]
    words = [w for w in with_examples if menus.get(w)]
    no_menu = [w for w in with_examples if not menus.get(w)]
    print(f"{len(examples)} words in the layer; {len(with_examples)} have at least "
          f"one example")
    print(f"  classifying {len(words)} of those ({len(no_menu)} have no sense menu); "
          f"{len(examples) - len(with_examples)} skipped as example-free")

    sent_texts, sense_texts = [], []
    for w in words:
        sent_texts += [c["target"] for c in examples[w]]
        sense_texts += [gloss(w, m) for m in menus[w].values()]
    V = embed(sent_texts + sense_texts)

    # fixed background sample for the hubness offset — shared by every word, so
    # it never reflects any one word's candidate pool
    rng = np.random.default_rng(0)
    uniq = list(dict.fromkeys(sent_texts))
    BG = np.stack([V[t] for t in
                   (uniq if len(uniq) <= BG_N
                    else [uniq[i] for i in rng.choice(len(uniq), BG_N, False)])])

    out, bands, gaps, singles = {}, {"high": 0, "medium": 0, "low": 0}, [], 0
    per_word = {}
    for w in words:
        sids = list(menus[w])
        S = np.stack([V[gloss(w, menus[w][s])] for s in sids])
        Q = np.stack([V[c["target"]] for c in examples[w]])
        hub = np.sort(BG @ S.T, axis=0)[-min(BG_K, BG.shape[0]):].mean(0)
        C = Q @ S.T - hub[None, :]

        # Confidence is the gap between the top two (headword, POS) TUPLES.
        # Until 2026-08-16 it was measured between (POS, translation) classes,
        # a key with no headword in it — so leaves of `hacer` and `hacerse`
        # sharing a translation collapsed into ONE bucket and the gap skipped
        # past the real contest to some unrelated third meaning. That returned
        # maximum confidence on a coin flip: `olvide` in "Me olvidé que era
        # nuestro aniversario" scored 1.0000 (all five leaves read "to forget",
        # so there was only one class) while the actual olvidar/olvidarse
        # decision was a dead tie.
        #
        # Measured over 84,174 dictionary-gold sentences, yield at 99% lemma+POS
        # accuracy goes from 6 items to 13,224 (15.7%). The PICK is untouched:
        # argmax over per-tuple maxima is always the tuple holding the global
        # argmax leaf, so this reorders confidence without changing a single
        # assignment. Both gaps are emitted; the class gap is still the right
        # signal for "which gloss", it is just the wrong one for "which lemma".
        # See Data/Spanish/Intermediates/wsd_sense_harness/README.md section 4.
        cls, cid, tls, tid = {}, [], {}, []
        for s in sids:
            m = menus[w][s]
            cid.append(cls.setdefault(
                (m.get("pos", ""), norm_tr(m.get("translation"))), len(cls)))
            tid.append(tls.setdefault(
                ((m.get("headword") or w).strip().lower(),
                 (m.get("pos") or "").strip()), len(tls)))
        cid, tid = np.array(cid), np.array(tid)
        n_cls, n_tup = len(cls), len(tls)
        if n_tup == 1:
            singles += 1

        picks = []
        for j in range(len(examples[w])):
            row = C[j]
            k = int(np.argmax(row))
            # signed against the pick, so the two gaps stay comparable
            tbest = np.full(n_tup, -np.inf)
            np.maximum.at(tbest, tid, row)
            gap = (float(tbest[tid[k]] - np.delete(tbest, tid[k]).max())
                   if n_tup > 1 else 1.0)
            cbest = np.full(n_cls, -np.inf)
            np.maximum.at(cbest, cid, row)
            cgap = (float(cbest[cid[k]] - np.delete(cbest, cid[k]).max())
                    if n_cls > 1 else 1.0)
            picks.append((sids[k], gap, cgap))
            gaps.append(gap)
        per_word[w] = picks

    hi_cut, md_cut = HIGH_CUT, MEDIUM_CUT
    q = np.quantile(gaps, [0.5, 0.75, 0.9])
    print(f"absolute cuts from the panel — high >= {hi_cut}, medium >= {md_cut}")
    print(f"this run's own gap distribution — median {q[0]:.4f}, "
          f"p75 {q[1]:.4f}, p90 {q[2]:.4f}")

    for w, picks in per_word.items():
        by_sense = {}
        for j, (sid, gap, cgap) in enumerate(picks):
            band = "high" if gap >= hi_cut else "medium" if gap >= md_cut else "low"
            bands[band] += 1
            e = by_sense.setdefault(sid, {"sense": sid, "examples": [],
                                          "confidence": [], "band": [],
                                          "class_confidence": [],
                                          "method": METHOD,
                                          "prompt_id": PROMPT_ID,
                                          "run_ts": dt.datetime.now(
                                              dt.timezone.utc).strftime(
                                              "%Y-%m-%dT%H:%MZ")})
            e["examples"].append(j)
            e["confidence"].append(round(gap, 4))
            e["class_confidence"].append(round(cgap, 4))
            e["band"].append(band)
        out[w] = {METHOD: list(by_sense.values())}

    # A list position is not a reference: rebuilding examples_raw.json puts
    # different sentences at the same offsets and silently re-points every
    # claim. Stamp the content hash alongside, as step_6b and step_6c do — the
    # resolver prefers it and falls back to the index only for older claims.
    stamp_example_ids(out, examples)
    stamped = sum(1 for m in out.values() for items in m.values()
                  for it in items for x in (it.get("example_ids") or []) if x)

    n = sum(len(v) for v in per_word.values())
    print(f"\nassigned {n:,} examples across {len(out)} words")
    print(f"  stable example IDs stamped: {stamped:,} of {n:,}")
    print(f"  senses used: {len({(w, i['sense']) for w, m in out.items() for i in m[METHOD]}):,}")
    print(f"  words whose menu collapses to one lemma+POS: {singles}")
    for b in ("high", "medium", "low"):
        print(f"  {b:<7} {bands[b]:>5} ({bands[b]/n:.0%})")

    if a.dry_run:
        return print("\n--dry-run: nothing written")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
