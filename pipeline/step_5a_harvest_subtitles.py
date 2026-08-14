#!/usr/bin/env python3
"""step_5a_harvest_subtitles — scan OpenSubtitles once, keep what it found.

step_5a_build_examples_v2 fuses three jobs into one process: scan the corpus,
embed the survivors, pick five per word. So the 4 GB scan is repeated for every
change, and it is repeated per *batch of target words* — running --top 500 and
later --top 10000 scans the corpus twice and discards the first result. Only the
five picked sentences per word survive; the candidates, the scores and the
reject reasons are gone.

This script does the scan alone, for every inventory word at once, and keeps the
result. Nothing downstream needs the corpus again.

Two facts make that cheap:

  * Only 2 of the 15 gate checks depend on which word you are looking for
    ("target absent", "proper noun"). The other 13, and the whole structural
    score, are properties of the sentence pair. Today a line containing eight
    target words runs all fifteen checks eight times.
  * The score is therefore a property of the sentence, so it is stored on the
    sentence rather than on each (word, sentence) pair.

Outputs, all under Data/Spanish/layers/subtitles/:

  sentence_bank.jsonl    One row per surviving sentence: content id, both sides,
                         score parts, and the OpenSubtitles title/subtitle/line
                         it came from. Merged with any existing bank on re-run;
                         rows are never rewritten or dropped.
  word_candidates.json   word -> sentence ids, best first. A view over the bank,
                         rebuildable without touching the corpus.
  harvest_manifest.json  Run id, arguments, counts, and the reject histogram.

Embedding, alignment and the final pick are separate steps. This one is pure
CPU and disk — no API key needed.

Usage:
    python3 pipeline/step_5a_harvest_subtitles.py                    # all words
    python3 pipeline/step_5a_harvest_subtitles.py --top 500 --max-lines 2000000
"""

from __future__ import annotations

import argparse
import heapq
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from step_5a_build_examples_v2 import (  # noqa: E402  (path set above)
    MAX_CLAUSES,
    MAX_LEN,
    MIN_LEN,
    TOK,
    WORDCHARS,
    Scorer,
)
from util_5a_example_id import example_id  # noqa: E402

CORP = REPO / "Data/Spanish/corpora/opensubtitles"
OUT = REPO / "Data/Spanish/layers/subtitles"

HARVEST_VERSION = "harvest-v1"
MERGED_LINES = re.compile(r"(?<=[a-záéíóúüñ]) +([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+)")
JUNK = re.compile(r"[♪<>{}]|https?://|\d{3,}")


# ---------------------------------------------------------------- gates
# Split verbatim out of Scorer.gate. Same checks, same order, same reject
# strings — only regrouped by what they actually depend on.

def gate_broken(sc, es, en):
    """Checks that mean the data is unusable however the algorithm changes.

    A line failing one of these can never be rescued by a different selection
    policy, so it is dropped and not banked.
    """
    if es == es.upper() and len(es) > 8:
        return "all caps"
    for m in MERGED_LINES.finditer(es):
        if m.group(1).lower() in sc.rank:
            return "merged lines"
    if "(" in es or ")" in es:
        return "parenthetical"
    if JUNK.search(es):
        return "junk chars"
    if not en or not en.strip():
        return "no english"
    if en.rstrip().endswith(("...", "…")):
        return "english fragment"
    if not (0.5 <= len(en.split()) / max(1, len(es.split())) <= 2.0):
        return "length ratio"
    if en.strip().lower() == es.strip().lower():
        return "identical sides"
    return None


def gate_taste(sc, es, t):
    """Checks that are this run's policy rather than facts about the data.

    A line failing one of these is still a real, well-translated sentence — it
    just isn't what the current selection policy wants. These are banked with
    the reason recorded, so changing the policy later is a re-filter over the
    bank instead of another pass over 4 GB of corpus.

    Run after gate_broken, so a reason returned here also means the line passed
    every brokenness check.
    """
    if not (MIN_LEN <= len(t) <= MAX_LEN):
        return "length"
    s = es.rstrip()
    if s.endswith(("...", "…", "..")):
        return "trailing ellipsis"
    if not s.endswith((".", "!", "?", '"', "»")):
        return "no terminal punct"
    if es.lstrip().startswith(("-", "–", "—")):
        return "dialogue dash"
    c = sc.clauses(es)
    if c == 0:
        return "no finite verb"
    if c > MAX_CLAUSES:
        return "3+ clauses"
    return None


def gate_word(raw, t, word):
    """The 2 checks that depend on which word you are looking for."""
    if word not in t:
        return "target absent"
    occ = [i for i, w in enumerate(t) if w == word]
    if occ and all(raw[i][0].isupper() and i > 0 for i in occ):
        return "proper noun"
    return None


def provenance(ids):
    """OpenSubtitles ships .ids aligned line-for-line: es/0/<title>/<subtitle>.xml.gz"""
    parts = ids.rstrip("\n").split("\t")
    prov = {"corpus": "opensubtitles"}
    if len(parts) >= 4:
        seg = parts[1].split("/")
        if len(seg) >= 4:
            prov["title_id"] = seg[2]
            prov["subtitle_id"] = seg[3].split(".")[0]
        prov["line"] = parts[3]
    return prov


# ---------------------------------------------------------------- harvest

def harvest(sc, targets, max_lines, cap, taste_cap, compact_every, run_id):
    """Stream the corpus once, keeping the best sentences per target word.

    Two pools per word. `heaps` holds sentences the current policy wants.
    `held` holds sentences that are perfectly good but fail a taste gate, under
    a smaller cap, so they cannot crowd out the clean ones. Changing the policy
    later re-filters both instead of re-reading the corpus.

    Memory is bounded by keeping only (score, sentence id) per word and sweeping
    the sentence table of anything no word still points at. Without the sweep a
    full-corpus run over 10k targets would hold every surviving line in RAM.
    """
    heaps = defaultdict(list)   # word -> bounded min-heap of (score, sentence id)
    held = defaultdict(list)    # word -> same, for taste-rejected sentences
    rows = {}                   # sentence id -> bank row, periodically swept
    rejects = Counter()        # per line, dropped as broken
    word_rejects = Counter()   # per (line, word) pair
    banked = Counter()
    n = 0
    t0 = time.time()

    es_p = CORP / "OpenSubtitles.en-es.es"
    en_p = CORP / "OpenSubtitles.en-es.en"
    id_p = CORP / "OpenSubtitles.en-es.ids"
    for p in (es_p, en_p, id_p):
        if not p.exists():
            raise SystemExit("missing corpus file: %s" % p)

    with es_p.open(encoding="utf-8", errors="ignore") as es_f, \
         en_p.open(encoding="utf-8", errors="ignore") as en_f, \
         id_p.open(encoding="utf-8", errors="ignore") as id_f:
        for es, en, ids in zip(es_f, en_f, id_f):
            n += 1
            if max_lines and n > max_lines:
                break

            # Sweep before the filters below, not after: most lines `continue`
            # out, so a check placed further down almost never runs and the
            # sentence table grows without bound.
            if n % compact_every == 0:
                live = {s for p in (heaps, held) for h in p.values() for _, s in h}
                rows = {k: v for k, v in rows.items() if k in live}
                filled = sum(1 for h in heaps.values() if len(h) >= cap)
                rate = int(n / max(1e-9, time.time() - t0))
                print(f"  {n:,} lines | {filled}/{len(targets)} words full | "
                      f"{len(rows):,} sentences held | {rate:,} lines/s",
                      flush=True)

            # Cheap byte-length prefilter before any tokenisation, as in v2.
            if not (24 <= len(es) <= 110):
                continue
            es, en = es.strip(), en.strip()
            hits = targets & set(TOK.findall(es.lower()))
            if not hits:
                continue

            raw = WORDCHARS.findall(es)
            t = [w.lower() for w in raw]
            broken = gate_broken(sc, es, en)
            if broken:
                rejects[broken] += 1
                continue
            taste = gate_taste(sc, es, t)
            banked["clean" if taste is None else taste] += 1

            metrics = sc.structural(es)
            score = metrics["score"]
            pool, limit = (heaps, cap) if taste is None else (held, taste_cap)
            sid = None
            for w in hits:
                word_why = gate_word(raw, t, w)
                if word_why:
                    # Counted separately: this is one (line, word) pair, not a
                    # line, so it cannot be added to the per-line tallies.
                    word_rejects[word_why] += 1
                    continue
                h = pool[w]
                # This word's pool is already full and this sentence cannot beat
                # its worst survivor, so there is nothing to store.
                if len(h) >= limit and score <= h[0][0]:
                    continue
                if sid is None:
                    sid = example_id(es, en)
                    if sid not in rows:
                        rows[sid] = {"id": sid, "es": es, "en": en,
                                     "score": round(score, 4),
                                     "naturalness": metrics["naturalness"],
                                     "hard_words": metrics["hard_words"],
                                     "tokens": metrics["tokens"],
                                     "gate": taste,
                                     "provenance": provenance(ids),
                                     "harvest_run": run_id}
                heapq.heappush(h, (score, sid))
                if len(h) > limit:
                    heapq.heappop(h)

    live = {s for p in (heaps, held) for h in p.values() for _, s in h}
    rows = {k: v for k, v in rows.items() if k in live}
    return heaps, held, rows, rejects, word_rejects, banked, n


# ---------------------------------------------------------------- output

def merge_bank(path, rows):
    """Sentence ids are content hashes, so an existing row is already correct.

    Re-running with different arguments adds sentences; it never rewrites or
    removes one, which is what makes a later run cheap to compare against.
    """
    merged = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                merged[row["id"]] = row
    before = len(merged)
    for sid, row in rows.items():
        merged.setdefault(sid, row)
    return merged, before


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0,
                    help="target the top N inventory words (0 = all)")
    ap.add_argument("--max-lines", type=int, default=0,
                    help="stop after N corpus lines (0 = whole corpus)")
    ap.add_argument("--per-word-cap", type=int, default=60,
                    help="clean candidates retained per word; the pick step "
                         "needs headroom because alignment rejects afterwards")
    ap.add_argument("--taste-cap", type=int, default=20,
                    help="per word, how many sentences that fail only a taste "
                         "gate to bank anyway, so a later policy change is a "
                         "re-filter rather than another corpus scan")
    ap.add_argument("--compact-every", type=int, default=1_000_000)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    run_id = "%s_%s" % (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ"),
                        HARVEST_VERSION)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    sc = Scorer()
    inv = sc.inv if not args.top else sc.inv[:args.top]
    targets = {r["word"] for r in inv}
    print("harvest %s" % run_id)
    print("  targets: %d words | cap %d clean + %d held per word | lines: %s"
          % (len(targets), args.per_word_cap, args.taste_cap,
             "all" if not args.max_lines else "{:,}".format(args.max_lines)))

    heaps, held, rows, rejects, word_rejects, banked, scanned = harvest(
        sc, targets, args.max_lines, args.per_word_cap, args.taste_cap,
        args.compact_every, run_id)

    def ordered_ids(heap):
        """Best first, deduped: a repeated subtitle line hashes to one id."""
        seen, out = set(), []
        for _, sid in sorted(heap, key=lambda x: -x[0]):
            if sid not in seen:
                seen.add(sid)
                out.append(sid)
        return out

    candidates = {}
    for word in set(heaps) | set(held):
        clean = ordered_ids(heaps.get(word, []))
        spare = ordered_ids(held.get(word, []))
        if clean or spare:
            candidates[word] = {"clean": clean, "held": spare}

    bank_path = out_dir / "sentence_bank.jsonl"
    merged, before = merge_bank(bank_path, rows)
    with bank_path.open("w", encoding="utf-8") as f:
        for sid in sorted(merged):
            f.write(json.dumps(merged[sid], ensure_ascii=False) + "\n")

    (out_dir / "word_candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False), encoding="utf-8")

    with_clean = {w for w, v in candidates.items() if v["clean"]}
    empty = sorted(targets - with_clean)
    thin = sorted(((w, len(candidates[w]["clean"])) for w in with_clean
                   if len(candidates[w]["clean"]) < 10), key=lambda x: x[1])
    manifest = {
        "run_id": run_id,
        "harvest_version": HARVEST_VERSION,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "args": {"top": args.top, "max_lines": args.max_lines,
                 "per_word_cap": args.per_word_cap,
                 "taste_cap": args.taste_cap},
        "lines_scanned": scanned,
        "targets": len(targets),
        "words_with_clean": len(with_clean),
        "words_with_none": len(empty),
        "sentences_new": len(merged) - before,
        "sentences_total": len(merged),
        "banked_by_gate": dict(banked.most_common()),
        "dropped_as_broken": dict(rejects.most_common()),
        "word_level_rejects": dict(word_rejects.most_common()),
    }
    (out_dir / "harvest_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nscanned {:,} lines".format(scanned))
    print("  sentences in bank: {:,} ({:,} new)".format(len(merged), len(merged) - before))
    print("  words with clean candidates: %d of %d" % (len(with_clean), len(targets)))
    if empty:
        print("  words with none: %d e.g. %s" % (len(empty), empty[:8]))
    if thin:
        print("  words under 10 clean: %d e.g. %s" % (len(thin), thin[:8]))
    print("  banked by gate: %s" % dict(banked.most_common(6)))
    print("  dropped as broken: %s" % dict(rejects.most_common(5)))
    print("\nwrote %s" % out_dir)


if __name__ == "__main__":
    main()
