#!/usr/bin/env python3
"""Shared plumbing: stable IDs, the frozen split, the menu, the judgement store."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

# The panel and its labels are DATA and live under Data/, versioned like every
# other benchmark in Intermediates/. The code lives here. Bump VERSION to freeze
# a new panel; never edit a released one.
VERSION = "2026-08-11_v1"
DATA = REPO / "Data/Spanish/Intermediates/wsd_sense_harness" / VERSION
CORPORA = DATA / "panels"
LABEL_DIR = DATA / "labels"
RUNS = DATA / "runs"
JUDGEMENTS = DATA / "judgements.jsonl"

LABELS = ("GOOD", "OK", "BAD")


def sid(corpus: str, word: str, sentence: str) -> str:
    """Stable sentence id. Same text always gets the same id, forever."""
    h = hashlib.sha1(f"{word}|{sentence}".encode()).hexdigest()[:12]
    return f"{corpus}:{h}"


def split_of(word: str) -> str:
    """Frozen dev/test assignment. A hash, not a seed, so it cannot drift."""
    h = int(hashlib.sha1(word.encode()).hexdigest()[:8], 16)
    return "dev" if h % 100 < 35 else "test"


def load_menu(artist: str | None = None) -> dict:
    p = (REPO / "Data/Spanish/layers/sense_menu/spanishdict.json" if not artist
         else REPO / f"Artists/spanish/{artist}/data/layers/sense_menu/spanishdict.json")
    raw = json.load(open(p))
    return {w: {sid_: v for e in entries for sid_, v in e.get("senses", {}).items()}
            for w, entries in raw.items()}


def gloss(word: str, m: dict) -> str:
    tr = (m.get("translation") or "").strip() or "(sin traduccion)"
    ctx = (m.get("context") or "").strip()
    return f'"{word}" ({m.get("pos","")}): {tr}' + (f" — {ctx}" if ctx else "")


def read_corpus(name: str) -> list[dict]:
    p = CORPORA / f"{name}.jsonl"
    if not p.exists():
        raise SystemExit(f"no such corpus slice: {p}\nbuild it with build_corpus.py")
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def load_judgements() -> dict:
    """(sentence_id, sense_id) -> label. Later lines win, so a correction is
    just an append."""
    out = {}
    if JUDGEMENTS.exists():
        for line in open(JUDGEMENTS, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            out[(r["sentence_id"], r["sense_id"])] = r["label"]
    return out


def append_judgements(rows: list[dict]) -> None:
    with open(JUDGEMENTS, "a", encoding="utf-8") as f:
        for r in rows:
            assert r["label"] in LABELS, r
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def deacc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


EN_STOP = {"the", "is", "are", "you", "where", "and", "of", "with", "this", "have",
           "from", "they", "what", "was", "were", "will", "been", "their", "there",
           "which", "would", "does", "his", "her", "she", "him", "your", "that"}


def looks_english(s: str) -> bool:
    return sum(t in EN_STOP for t in re.findall(r"[a-z']+", s.lower())) >= 2
