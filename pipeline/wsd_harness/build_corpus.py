#!/usr/bin/env python3
"""Freeze a corpus slice. Run once per slice; the output is append-only thereafter.

  python build_corpus.py spanishdict
  python build_corpus.py opensubtitles
  python build_corpus.py badbunny

Each line of the output is one candidate:
  {id, corpus, word, sentence, split, gold?}

`gold` is present only for spanishdict, where the dictionary filed the example under
a sense itself. The other slices have no gold by design — they are judged by pooling.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from collections import defaultdict

from common import (CORPORA, REPO, load_menu, looks_english, sid, split_of)

# A panel, not a corpus. The binding constraint is human judging time, so keep it
# small and spend the budget on WORD DIVERSITY: one sentence per word.
PANEL_SIZE = 150
WORDS_PER_SLICE = 600           # candidate words, taken by corpus frequency
SENTS_PER_WORD = 3              # sampled from, then cut to one
MIN_W, MAX_W = 5, 26
OPENSUB_MAX_LINES = 400_000     # never stream the whole 2 GB file


def target_words(menu, n=WORDS_PER_SLICE, min_senses=2, max_senses=20):
    inv = json.load(open(REPO / "Data/Spanish/layers/word_inventory.json"))
    out = []
    for rec in inv:
        w = rec["word"]
        m = menu.get(w)
        if m and min_senses <= len(m) <= max_senses:
            out.append(w)
        if len(out) >= n:
            break
    return out


def build_spanishdict(menu):
    rows = []
    for word in target_words(menu):
        seen, dupe = {}, set()
        for s_id, meta in menu[word].items():
            for ex in (meta.get("examples") or []):
                t = (ex.get("original") or "").strip()
                if not t or not (MIN_W <= len(t.split()) <= MAX_W) or looks_english(t):
                    continue
                if t in seen and seen[t] != s_id:
                    dupe.add(t)
                seen.setdefault(t, s_id)
        for t, s_id in seen.items():
            if t in dupe:
                continue
            rows.append({"id": sid("spanishdict", word, t), "corpus": "spanishdict",
                         "word": word, "sentence": t, "split": split_of(word),
                         "gold": s_id})
    return rows


def build_opensubtitles(menu, max_lines=OPENSUB_MAX_LINES):
    """Stream the Spanish side and collect candidate sentences per target word."""
    words = set(target_words(menu))
    got = defaultdict(list)
    path = REPO / "Data/Spanish/corpora/opensubtitles/OpenSubtitles.en-es.es"
    tok = re.compile(r"[a-záéíóúüñ]+")
    with open(path, encoding="utf-8", errors="ignore") as f:
        for n, line in enumerate(f):
            if n >= max_lines:
                break
            t = line.strip()
            if not (MIN_W <= t.count(" ") + 1 <= MAX_W):
                continue
            if looks_english(t):
                continue
            for w in set(tok.findall(t.lower())) & words:
                if len(got[w]) < SENTS_PER_WORD:
                    got[w].append(t)
            if n % 1_000_000 == 0 and n:
                done = sum(1 for w in words if len(got[w]) >= SENTS_PER_WORD)
                print(f"  {n:,} lines, {done}/{len(words)} words filled", flush=True)
                if done == len(words):
                    break
    rows = []
    for w, sents in got.items():
        for t in sents:
            rows.append({"id": sid("opensubtitles", w, t), "corpus": "opensubtitles",
                         "word": w, "sentence": t, "split": split_of(w)})
    return rows


def build_badbunny(menu):
    art = REPO / "Artists/spanish/Bad Bunny/data/layers"
    amenu = load_menu("Bad Bunny")
    ex = json.load(open(art / "examples_raw.json"))
    rows = []
    for w, recs in ex.items():
        m = amenu.get(w)
        if not m or not (2 <= len(m) <= 20):
            continue
        for r in recs[:SENTS_PER_WORD]:
            t = (r.get("spanish") or "").strip()
            if t and MIN_W <= len(t.split()) <= MAX_W:
                rows.append({"id": sid("badbunny", w, t), "corpus": "badbunny",
                             "word": w, "sentence": t, "split": split_of(w),
                             "document": r.get("title")})
    return rows


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "spanishdict"
    menu = load_menu()
    fn = {"spanishdict": build_spanishdict, "opensubtitles": build_opensubtitles,
          "badbunny": build_badbunny}[which]
    rows = fn(menu)
    # cut to the panel: one sentence per word, so 150 judgements buy 150 words
    import random
    by_word = {}
    for r in sorted(rows, key=lambda r: r["id"]):
        by_word.setdefault(r["word"], r)
    picked = sorted(by_word.values(), key=lambda r: r["id"])
    random.Random(0).shuffle(picked)
    rows = sorted(picked[:PANEL_SIZE], key=lambda r: r["word"])
    CORPORA.mkdir(parents=True, exist_ok=True)
    out = CORPORA / f"{which}.jsonl"
    if out.exists():
        raise SystemExit(f"{out} already exists — slices are frozen. Delete it "
                         f"deliberately if you really mean to rebuild.")
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    words = {r["word"] for r in rows}
    dev = {r["word"] for r in rows if r["split"] == "dev"}
    print(f"wrote {out}")
    print(f"  {len(rows):,} candidates over {len(words)} words "
          f"({len(dev)} dev / {len(words)-len(dev)} test)")


if __name__ == "__main__":
    main()
