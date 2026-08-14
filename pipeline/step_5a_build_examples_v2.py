#!/usr/bin/env python3
"""step_5a_build_examples_v2 — pick example sentences on quality alone.

Replaces the neighbour-coverage selection in step_5a_build_examples.py. That one
sorted by "tier" (how much nearby co-study vocabulary a sentence contained) and
then *discarded everything with tier == 0*, so a perfectly good sentence with no
neighbour words was thrown away and the survivors were chosen for word overlap
rather than for being good sentences. That is why the shipped examples read oddly.

Here there is no level matching and no neighbour logic. A sentence is judged on
whether it is a clear, ordinary, well-translated sentence, full stop.

  gates      length, real sentence, clean text, sane translation, 1-2 clauses
  score      naturalness, hard-word count, structure, length, source prior
  alignment  multilingual cosine between the two sides — the discriminator, and
             a hard floor, because a broken translation is worse than no example

Provenance is carried per sentence: OpenSubtitles ships an .ids file aligned
line-for-line with the text, giving the title and subtitle each line came from.

Usage:
    python3 pipeline/step_5a_build_examples_v2.py --top 500 --per-word 5
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from util_5a_example_id import example_id

REPO = Path(__file__).resolve().parents[1]
CORP = REPO / "Data/Spanish/corpora/opensubtitles"
LAYERS = REPO / "Data/Spanish/layers"
CACHE = LAYERS / "sense_vectors"

MIN_LEN, MAX_LEN = 5, 11
BAND = 5000                 # "ordinary speech" frequency band
MAX_CLAUSES = 2
ALIGN_FLOOR = 0.90
SHORTLIST = 30              # structural survivors per word sent for embedding

TOK = re.compile(r"[a-záéíóúüñ]+", re.I)
WORDCHARS = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
SUB = {"que", "cuando", "aunque", "porque", "si", "mientras", "quien", "cual",
       "donde"}
FINITE = {"indicativo", "subjuntivo", "imperativo"}
QUOTES = re.compile(r'["«»“”]')


def load_key():
    for line in (REPO / ".env").open(encoding="utf-8"):
        k, _, v = line.partition("=")
        if k.strip() == "GEMINI_API_KEY":
            return v.strip().strip('"').strip("'")
    raise SystemExit("no GEMINI_API_KEY")


class Scorer:
    def __init__(self):
        inv = json.load((LAYERS / "word_inventory.json").open(encoding="utf-8"))
        self.rank = {r["word"]: i for i, r in enumerate(inv)}
        self.inv = inv
        self.conj = json.load(
            (LAYERS / "conjugation_reverse.json").open(encoding="utf-8"))

    def clauses(self, es):
        return sum(1 for w in TOK.findall(es.lower())
                   if any(e.get("mood") in FINITE for e in self.conj.get(w, [])))

    def gate(self, es, en, word):
        raw = WORDCHARS.findall(es)
        t = [w.lower() for w in raw]
        if not (MIN_LEN <= len(t) <= MAX_LEN):              return "length"
        if word not in t:                                   return "target absent"
        occ = [i for i, w in enumerate(t) if w == word]
        if occ and all(raw[i][0].isupper() and i > 0 for i in occ):
            return "proper noun"
        s = es.rstrip()
        if s.endswith(("...", "…", "..")):                  return "trailing ellipsis"
        if not s.endswith((".", "!", "?", '"', "»")):       return "no terminal punct"
        if es.lstrip().startswith(("-", "–", "—")):       return "dialogue dash"
        if es == es.upper() and len(es) > 8:                return "all caps"
        # Two subtitle lines merged into one. The tell is a capitalised COMMON
        # word mid-sentence with no preceding punctuation ("...hasta Tengo mi
        # lugar..."). Checking the word is in the inventory keeps real proper
        # nouns, which are not ranked, from being rejected.
        for m in re.finditer(r"(?<=[a-záéíóúüñ]) +([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+)", es):
            if m.group(1).lower() in self.rank:
                return "merged lines"
        if "(" in es or ")" in es:                          return "parenthetical"
        if re.search(r"[♪<>{}]|https?://|\d{3,}", es):      return "junk chars"
        if not en or not en.strip():                        return "no english"
        if en.rstrip().endswith(("...", "…")):              return "english fragment"
        if not (0.5 <= len(en.split()) / max(1, len(es.split())) <= 2.0):
            return "length ratio"
        if en.strip().lower() == es.strip().lower():        return "identical sides"
        c = self.clauses(es)
        if c == 0:                                          return "no finite verb"
        if c > MAX_CLAUSES:                                 return "3+ clauses"
        return None

    def structural(self, es):
        t = TOK.findall(es.lower())
        ranks = [self.rank.get(w) for w in t]
        hard = sum(1 for r in ranks if r is None or r >= BAND)
        nat = sum(1 for r in ranks if r is not None and r < BAND) / len(t)
        hard_pen = {0: 0.0, 1: 0.0, 2: 0.15}.get(hard, 0.15 + 0.25 * (hard - 2))
        struct = (0.10 * min(es.count(","), 2)
                  + 0.06 * max(0, sum(1 for w in t if w in SUB) - 1))
        quote_pen = 0.12 if QUOTES.search(es) else 0.0
        finite = 0.08
        ideal = (MIN_LEN + MAX_LEN) / 2
        length_bonus = 0.10 * (1 - abs(len(t) - ideal) / ideal)
        return dict(score=nat - hard_pen - struct - quote_pen + finite + length_bonus,
                    naturalness=round(nat, 3), hard_words=hard, tokens=len(t))


def stream_pairs(scorer, targets, limit):
    """Walk .es/.en/.ids in lockstep. They are aligned line-for-line, which is the
    only way to attach provenance — cached_pairs.json.gz has none."""
    pool = defaultdict(list)
    rejects = defaultdict(int)
    es_f = (CORP / "OpenSubtitles.en-es.es").open(encoding="utf-8", errors="ignore")
    en_f = (CORP / "OpenSubtitles.en-es.en").open(encoding="utf-8", errors="ignore")
    id_f = (CORP / "OpenSubtitles.en-es.ids").open(encoding="utf-8", errors="ignore")
    n = 0
    with es_f, en_f, id_f:
        for es, en, ids in zip(es_f, en_f, id_f):
            n += 1
            if n > limit:
                break
            # cheap pre-filters first: a per-line loop over 500 targets is
            # O(lines x targets) and dominates everything else. Tokenise once and
            # intersect instead.
            if not (24 <= len(es) <= 110):
                continue
            es, en = es.strip(), en.strip()
            hits = targets & set(TOK.findall(es.lower()))
            if not hits:
                continue
            for w in hits:
                r = scorer.gate(es, en, w)
                if r:
                    rejects[r] += 1
                    continue
                parts = ids.rstrip("\n").split("\t")
                prov = {"corpus": "opensubtitles"}
                if len(parts) >= 4:
                    seg = parts[1].split("/")          # es/0/1084944/4103721.xml.gz
                    if len(seg) >= 4:
                        prov["title_id"] = seg[2]
                        prov["subtitle_id"] = seg[3].split(".")[0]
                    prov["line"] = parts[3]
                m = scorer.structural(es)
                # keep the legacy fields the rest of the pipeline reads:
                # `id` is a content hash so a sentence keeps its identity across
                # runs, and example_ids must stay positionally aligned.
                m.update(id=example_id(es, en), target=es, english=en,
                         source="opensubtitles", provenance=prov)
                pool[w].append(m)
            if n % 2_000_000 == 0:
                filled = sum(1 for w in targets if len(pool[w]) >= 200)
                print(f"  {n:,} lines — {filled}/{len(targets)} words have 200+ "
                      f"candidates", flush=True)
    return pool, rejects, n


def embed(texts):
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
                        st["done"] += len(ch)
                        # Time-based, not count-based: at the rate limit a
                        # every-5000 print is one line every ~2 minutes, which
                        # reads as a hang.
                        now = time.time()
                        if now - st["last"] >= 10 or st["done"] == len(todo):
                            st["last"] = now
                            el = now - st["t0"]
                            rate = st["done"] / max(el, 1e-9)
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

        print(f"  embedding {len(todo):,} texts "
              f"(~${len(todo)*30/1e6*0.15:.2f}, ~{len(todo)/2800:.0f} min)")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=500)
    ap.add_argument("--per-word", type=int, default=5)
    ap.add_argument("--max-lines", type=int, default=8_000_000)
    ap.add_argument("--out", default=str(LAYERS / "examples_raw.json"))
    a = ap.parse_args()

    sc = Scorer()
    targets = {r["word"] for r in sc.inv[:a.top]}
    print(f"top {a.top} words, streaming up to {a.max_lines:,} subtitle lines")
    pool, rejects, seen = stream_pairs(sc, targets, a.max_lines)
    print(f"scanned {seen:,} lines")
    print(f"  rejects: {dict(sorted(rejects.items(), key=lambda x: -x[1])[:6])}")
    empty = [w for w in targets if not pool.get(w)]
    print(f"  words with no candidate at all: {len(empty)}"
          + (f" e.g. {empty[:8]}" if empty else ""))

    short = {w: sorted(v, key=lambda x: -x["score"])[:SHORTLIST]
             for w, v in pool.items()}
    V = embed([c["target"] for v in short.values() for c in v]
              + [c["english"] for v in short.values() for c in v])

    out, thin = {}, []
    for w, cands in short.items():
        keep = []
        for c in cands:
            c["alignment"] = round(float(V[c["target"]] @ V[c["english"]]), 4)
            if c["alignment"] >= ALIGN_FLOOR:
                keep.append(c)
        keep.sort(key=lambda c: -(c["alignment"] + 0.15 * c["score"]))

        def take(cands, one_per_title):
            """Prefer one sentence per film. Without this a frequent word draws
            all five from whichever subtitle file happened to be dense in it."""
            out, titles = [], set()
            for c in cands:
                if any(c["target"][:25] == q["target"][:25] for q in out):
                    continue                   # crude near-duplicate guard
                t = c["provenance"].get("title_id")
                if one_per_title and t and t in titles:
                    continue
                titles.add(t)
                out.append(c)
                if len(out) == a.per_word:
                    break
            return out

        picked = take(keep, True)
        if len(picked) < a.per_word:           # not enough distinct films: relax
            picked = take(keep, False)
        for c in picked:
            c["score"] = round(c["score"], 3)
        if len(picked) < a.per_word:
            thin.append((w, len(picked)))
        if picked:
            out[w] = picked

    n = sum(len(v) for v in out.values())
    print(f"\nselected {n:,} sentences for {len(out)} words "
          f"(target {a.per_word}/word)")
    if thin:
        print(f"  {len(thin)} words got fewer than {a.per_word}: "
              f"{sorted(thin, key=lambda x: x[1])[:10]}")
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
