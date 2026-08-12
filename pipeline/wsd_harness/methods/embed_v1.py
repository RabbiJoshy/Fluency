#!/usr/bin/env python3
"""embed_v1 — the current best method, registered so it can be beaten.

Gemini gemini-embedding-001. Sense vector from the English gloss, sentence embedded
once, nearest sense by cosine. Two additions that survived the audit in RESULTS.md:

  * class gap    — confidence is the gap between the top two MEANINGS, not the top
                   two leaves, so a near-tie between synonymous leaves is not read
                   as uncertainty
  * offline hub  — a per-sense constant measured once against a fixed background
                   corpus and subtracted. Per-SENSE calibration. Must be offline:
                   estimating it from the batch being scored is an artifact of pool
                   composition and hurts on realistic (Zipfian) inputs.

Embeddings are cached under .cache/ keyed by text, so re-runs are free.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

import numpy as np

from common import HERE, REPO, gloss, load_menu, read_corpus

MODEL = "gemini-embedding-001"
RATE = 2800          # the quota counts TEXTS, not requests
WORKERS = 4
CACHE = REPO / "Data/Spanish/layers/sense_vectors"   # shared, persists
BG_N, BG_K = 1200, 40


def _key():
    for line in open(REPO / ".env", encoding="utf-8"):
        k, _, v = line.partition("=")
        if k.strip() == "GEMINI_API_KEY":
            return v.strip().strip('"').strip("'")
    raise SystemExit("no GEMINI_API_KEY in .env")


def embed(texts: list[str]) -> np.ndarray:
    """Cached, paced, L2-normalised."""
    CACHE.mkdir(parents=True, exist_ok=True)
    store = CACHE / "vec.npy"
    index = CACHE / "vec_index.json"
    idx = json.load(open(index)) if index.exists() else {}
    M = np.load(store) if store.exists() else np.zeros((0, 3072), dtype=np.float16)

    todo = [t for t in dict.fromkeys(texts) if t not in idx]
    if todo:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=_key())
        out = [None] * ((len(todo) + 99) // 100)
        lock = threading.Lock()
        st = {"issued": 0, "t0": time.time(), "done": 0}

        def take(k):
            while True:
                with lock:
                    allowed = RATE / 60.0 * (time.time() - st["t0"])
                    if st["issued"] + k <= allowed:
                        st["issued"] += k
                        return
                    wait = (st["issued"] + k - allowed) / (RATE / 60.0)
                time.sleep(min(wait, 5))

        def work(job):
            i, chunk = job
            for attempt in range(7):
                take(len(chunk))
                try:
                    r = client.models.embed_content(
                        model=MODEL, contents=chunk,
                        config=types.EmbedContentConfig(
                            task_type="SEMANTIC_SIMILARITY"))
                    out[i] = np.asarray([e.values for e in r.embeddings],
                                        dtype=np.float32)
                    break
                except Exception:
                    if attempt == 6:
                        raise
                    with lock:
                        st["t0"] = time.time() + 35
                        st["issued"] = 0
                    time.sleep(min(40, 5 * 2 ** attempt))
            with lock:
                st["done"] += len(chunk)
                if st["done"] % 5000 < 100:
                    print(f"    embedded {st['done']:,}/{len(todo):,}", flush=True)

        from concurrent.futures import ThreadPoolExecutor
        jobs = [(i // 100, todo[i:i + 100]) for i in range(0, len(todo), 100)]
        print(f"  embedding {len(todo):,} new texts "
              f"(~${len(todo)*30/1e6*0.15:.3f}, ~{len(todo)/RATE:.0f} min)")
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(work, jobs))
        new = np.vstack(out)
        new /= np.linalg.norm(new, axis=1, keepdims=True) + 1e-9
        for t in todo:
            idx[t] = len(idx)
        M = np.vstack([M, new.astype(np.float16)])
        np.save(store, M)
        json.dump(idx, open(index, "w"))

    return M[[idx[t] for t in texts]].astype(np.float32)


def run(corpus: str, split: str):
    rows = read_corpus(corpus)
    if split != "all":
        rows = [r for r in rows if r["split"] == split]
    menu = load_menu("Bad Bunny" if corpus == "badbunny" else None)

    words = sorted({r["word"] for r in rows if r["word"] in menu})
    sense_texts, sense_keys = [], []
    for w in words:
        for s_id, m in menu[w].items():
            sense_keys.append((w, s_id))
            sense_texts.append(gloss(w, m))

    S = embed(sense_texts)
    Q = embed([r["sentence"] for r in rows])
    srow = {k: i for i, k in enumerate(sense_keys)}
    qrow = {r["id"]: i for i, r in enumerate(rows)}

    rng = np.random.default_rng(0)
    BG = Q[rng.choice(Q.shape[0], min(BG_N, Q.shape[0]), replace=False)]

    def norm_tr(t):
        t = (t or "").lower().strip()
        t = re.sub(r"^(to |a |an |the )", "", t)
        return re.sub(r"[^a-z0-9 ]", "", t).strip()

    preds = []
    for w in words:
        sids = list(menu[w])
        Sw = S[[srow[(w, s)] for s in sids]]
        wr = [r for r in rows if r["word"] == w]
        if not wr:
            continue
        Qw = Q[[qrow[r["id"]] for r in wr]]
        hub = np.sort(BG @ Sw.T, axis=0)[-min(BG_K, BG.shape[0]):].mean(0)
        C = Qw @ Sw.T - hub[None, :]

        cls, cid = {}, []
        for s in sids:
            m = menu[w][s]
            cid.append(cls.setdefault((m.get("pos", ""),
                                       norm_tr(m.get("translation"))), len(cls)))
        cid = np.array(cid)
        n_cls = int(cid.max()) + 1

        for j, r in enumerate(wr):
            row = C[j]
            best = np.full(n_cls, -np.inf)
            np.maximum.at(best, cid, row)
            o = np.argsort(-best)
            conf = float(best[o[0]] - best[o[1]]) if n_cls > 1 else 1.0
            preds.append((r["id"], sids[int(np.argmax(row))], conf))
    return preds
