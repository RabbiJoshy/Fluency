#!/usr/bin/env python3
"""bench_wikt_sense_coverage.py — Phase 0 of the artist Wiktionary sense port.

Read-only diff report: for every VISIBLE Bad Bunny card (front-end default
filters, mirroring bench_deck_quality), look the word up in the English
Wiktionary layer (step_5c's load_wiktionary + lookup_senses) and compare the
resulting sense menu with the card's current (Gemini/SpanishDict) senses.

Answers, with numbers, the open questions in
docs/design/artist_sense_pipeline.md before any Gemini call:
  - coverage: how many visible words get Wiktionary senses at all
  - gloss overlap: does the current PRIMARY gloss appear in the wikt menu
    (fuzzy word-overlap) — i.e. how disruptive is the switch
  - menu_bloat: how many of the repeated-gloss menus dissolve
  - curated overrides: for each tool_8c-curated word, does the wikt menu
    contain the curated gloss (regression risk list)
  - gap list: visible words with NO wikt senses (the gap-fill workload)

Run from project root (first run parses the kaikki cache, ~fast):

    .venv/bin/python3 pipeline/bench_wikt_sense_coverage.py
"""
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

from step_5c_build_senses import WIKT_FILE, load_wiktionary, lookup_senses  # noqa: E402

MASTER = PROJECT_ROOT / "Artists/spanish/vocabulary_master.json"
BB_INDEX = PROJECT_ROOT / "Artists/spanish/Bad Bunny/BadBunnyvocabulary.index.json"


def norm(t):
    return (t or "").strip()


def keywords(t):
    """Lowercased content words of a gloss, for fuzzy overlap."""
    stop = {"to", "a", "an", "the", "of", "or", "in", "for", "on", "at", "sth",
            "sb", "something", "someone", "be", "with", "and", "one's", "up"}
    t = "".join(c for c in unicodedata.normalize("NFD", (t or "").lower())
                if unicodedata.category(c) != "Mn")
    return {w for w in re.findall(r"[a-z']+", t) if w not in stop}


def visible(mst, idx):
    if not mst:
        return False
    for f in ("is_english", "is_noise", "is_interjection", "is_english_loanword",
              "is_propernoun", "is_propernoun_corpus"):
        if mst.get(f):
            return False
    senses = [s for s in mst.get("senses", []) if norm(s.get("translation"))]
    if not senses or all(s.get("pos") == "PROPN" for s in senses):
        return False
    cs = idx.get("cognate_score", mst.get("cognate_score",
                 1 if mst.get("is_transparent_cognate") else 0))
    if cs is not None and cs >= 0.85:
        return False
    if (idx.get("corpus_count", 0) or 0) <= 1:
        return False
    return True


def main():
    master = json.load(open(MASTER))
    bb = json.load(open(BB_INDEX))
    wikt_index, redirects = load_wiktionary(WIKT_FILE)

    cards = []
    seen = set()
    for i in bb:
        m = master.get(i["id"])
        if m and i["id"] not in seen and visible(m, i):
            seen.add(i["id"])
            cards.append((i, m))
    print(f"\nVisible Bad Bunny cards: {len(cards)}\n" + "=" * 64)

    covered = 0
    primary_hits = 0
    primary_misses = []
    gaps = []
    sense_counts = []
    for i, m in cards:
        word = (m.get("word") or "").lower()
        lemma = (m.get("lemma") or "").lower()
        wsenses = lookup_senses(word, lemma, wikt_index, redirects)
        if not wsenses:
            gaps.append((word, lemma, norm(m["senses"][0].get("translation"))[:40]))
            continue
        covered += 1
        sense_counts.append(len(wsenses))
        # Current primary gloss = top-frequency sense per the artist index.
        freqs = i.get("sense_frequencies") or []
        senses = m.get("senses", [])
        top = max(range(len(senses)),
                  key=lambda j: (freqs[j] if j < len(freqs) else 0)) if senses else 0
        cur = norm(senses[top].get("translation"))
        cur_kw = keywords(cur)
        if not cur_kw:
            # Gloss is all function words ("to", "the", "of") — not comparable
            # by keyword overlap; wikt trivially covers these.
            primary_hits += 1
            continue
        if any(cur_kw & keywords(ws.get("translation")) for ws in wsenses):
            primary_hits += 1
        else:
            primary_misses.append((word, lemma, cur[:36],
                                   " | ".join(norm(ws.get("translation"))[:28]
                                              for ws in wsenses[:3])))

    print(f"Wiktionary coverage : {covered}/{len(cards)} ({100*covered/len(cards):.1f}%)")
    print(f"Menu size           : mean {sum(sense_counts)/len(sense_counts):.1f}, "
          f"max {max(sense_counts)} (capped at 8 by lookup)")
    print(f"Primary-gloss match : {primary_hits}/{covered} "
          f"({100*primary_hits/covered:.1f}%) — current top gloss found in wikt menu")

    print(f"\n### GAPS — no Wiktionary senses ({len(gaps)}) -> gap-fill workload")
    for g in gaps[:40]:
        print("   %-16s lemma=%-14s cur='%s'" % g)
    if len(gaps) > 40:
        print(f"   ... ({len(gaps)-40} more)")

    print(f"\n### PRIMARY-GLOSS MISSES ({len(primary_misses)}) — current top gloss "
          "absent from wikt menu (either wikt wins or curation needed)")
    for pm in primary_misses[:40]:
        print("   %-14s %-12s cur='%s'  wikt: %s" % pm)
    if len(primary_misses) > 40:
        print(f"   ... ({len(primary_misses)-40} more)")

    # menu_bloat resolution: same repeated-gloss check on wikt menus.
    print("\n### MENU BLOAT (gloss repeated >=4x in current menu) — wikt comparison")
    bloat_fixed = bloat_kept = 0
    for i, m in cards:
        senses = [s for s in m.get("senses", []) if norm(s.get("translation"))]
        gl = collections.Counter(norm(s.get("translation")).lower() for s in senses)
        if not any(c >= 4 for c in gl.values()):
            continue
        word = (m.get("word") or "").lower()
        lemma = (m.get("lemma") or "").lower()
        wsenses = lookup_senses(word, lemma, wikt_index, redirects)
        wgl = collections.Counter(norm(ws.get("translation")).lower() for ws in wsenses)
        still = any(c >= 4 for c in wgl.values())
        bloat_kept += still
        bloat_fixed += not still
        print("   %-12s current %d senses -> wikt %d senses %s"
              % (m["word"], len(senses), len(wsenses), "(still bloated)" if still else ""))
    print(f"   -> {bloat_fixed} dissolve, {bloat_kept} remain")

    # Curated-override regression risk: does the wikt menu contain each
    # curated gloss (from the live master, which tool_8c already patched)?
    print("\n### CURATED-GLOSS REGRESSION CHECK (tool_8c-patched words)")
    sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
    import tool_8c_patch_master_curated as t8c
    at_risk = ok = hidden = 0
    for ov in t8c.OVERRIDES:
        m = master.get(ov["key"])
        if not m:
            continue
        if any(m.get(f) for f in ("is_english", "is_noise", "is_interjection",
                                  "is_english_loanword", "is_propernoun")):
            hidden += 1
            continue
        word = (m.get("word") or "").lower()
        lemma = (m.get("lemma") or "").lower()
        wsenses = lookup_senses(word, lemma, wikt_index, redirects)
        curated = [norm(m["senses"][j].get("translation"))
                   for j in ov.get("senses", {})
                   if j < len(m["senses"]) and norm(m["senses"][j].get("translation"))]
        misses = [c for c in curated
                  if not any(keywords(c) & keywords(ws.get("translation"))
                             for ws in wsenses)]
        if misses:
            at_risk += 1
            print("   %-14s needs curation: %s  (wikt: %s)"
                  % (m["word"], "; ".join(x[:30] for x in misses),
                     " | ".join(norm(ws.get("translation"))[:24] for ws in wsenses[:3]) or "NO SENSES"))
        else:
            ok += 1
    print(f"   -> {ok} covered by wikt, {at_risk} need curated overrides carried over, "
          f"{hidden} hidden anyway (flags carry over unchanged)")


if __name__ == "__main__":
    main()
