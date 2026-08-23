#!/usr/bin/env python3
"""Score WSD variants on the hard_200 panel. See README.md.

Four configurations, one variable apart, so the strata table is readable:

    prior       take the first menu entry (the commonest sense)
    prior+pos   ...after the UD/SpanishDict POS filter
    proto       nearest leaf prototype (mean BETO vector of assigned occurrences)
    proto+pos   ...after the same POS filter

The baseline here is the menu prior, NOT the shipped v5 stack -- v5 also scores
Gemini gloss cosines, and those are not cached for these sentences.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "pipeline"))

from util_5c_token_prototypes import (  # noqa: E402
    DEFAULT_LAYERS, encode_spans, find_span, load_encoder)
import util_6a_pos_menu_filter as F  # noqa: E402

HERE = Path(__file__).resolve().parent
LAYERS = ROOT / "Data" / "Spanish" / "layers"
MIN_OCCURRENCES = 2


def meaning_groups(menu, word):
    """Menu leaves collapsed to distinct (pos, gloss, headword) meanings."""
    g = collections.OrderedDict()
    for analysis in menu.get(word, []):
        for sid, s in analysis.get("senses", {}).items():
            key = (s.get("pos", ""),
                   s.get("translation") or "<EMPTY>",
                   (s.get("headword") or "").lower())
            g.setdefault(key, []).append(sid)
    return g


def build_leaf_prototypes():
    """Mean token vector per sense id, from the deck's own assignments."""
    index = json.loads((LAYERS / "token_vec_cache/index.json").read_text())
    vecs = np.load(LAYERS / "token_vec_cache/vecs.npy").astype(np.float32)
    deck = json.loads((ROOT / "Data/Spanish/vocabulary.json").read_text())
    examples = json.loads((ROOT / "Data/Spanish/vocabulary.examples.json").read_text())
    by_id = {e["id"]: e for e in deck}

    rows = collections.defaultdict(list)
    for card_id, payload in examples.items():
        entry = by_id.get(card_id)
        if not entry:
            continue
        for meaning, block in zip(entry["meanings"], payload.get("m", [])):
            for sent in block:
                if sent.get("source") == "spanishdict":
                    continue            # dictionary example, not a corpus assignment
                key = f"{sent.get('target', '')}\t{entry['word']}"
                if key in index:
                    rows[meaning["sense_id"]].append(index[key])

    protos = {}
    for sid, idxs in rows.items():
        if len(idxs) < MIN_OCCURRENCES:
            continue
        v = vecs[idxs].mean(0)
        n = float(np.linalg.norm(v))
        if n > 0:
            protos[sid] = v / n
    return protos


def main():
    panel = [json.loads(l) for l in (HERE / "panel.jsonl").read_text().splitlines() if l.strip()]
    menu = json.loads((LAYERS / "sense_menu/spanishdict.json").read_text())
    protos = build_leaf_prototypes()
    print(f"leaf prototypes: {len(protos):,}")

    spans = {}
    for item in panel:
        span = find_span(item["sentence"], item["word"], item["word"], None)
        if span:
            spans.setdefault(item["sentence"], {})[item["word"]] = span
    tok, model = load_encoder(device="mps")
    vectors = encode_spans(list(spans), spans, tok, model,
                           device="mps", layers=DEFAULT_LAYERS)

    import spacy
    nlp = spacy.load("es_dep_news_trf")
    tags = {}
    for item in panel:
        doc = nlp(item["sentence"])
        low = item["word"].lower()
        tags[item["id"]] = next((t.pos_ for t in doc if t.text.lower() == low), None)

    stats = collections.defaultdict(collections.Counter)
    for item in panel:
        if item["no_answer"]:
            continue
        acceptable = {tuple(a) for a in item["acceptable"]}
        groups = meaning_groups(menu, item["word"])
        keys = list(groups)
        sid_to_key = {sid: k for k, sids in groups.items() for sid in sids}

        query = vectors.get((item["sentence"], item["word"]))
        tag = tags.get(item["id"])
        allowed = None
        if tag:
            allowed = {k for k in keys if F.sense_compatible_bridged(k[0], tag)}
            if not allowed:
                allowed = None          # empty keep-set -> caller falls back

        def nearest(restrict):
            cand = [(sid, k) for sid, k in sid_to_key.items()
                    if sid in protos and (restrict is None or k in restrict)]
            if not cand or query is None:
                return keys[0]
            return sid_to_key[max(cand, key=lambda t: float(query @ protos[t[0]]))[0]]

        picks = {
            "prior": keys[0],
            "prior+pos": next((k for k in keys if allowed is None or k in allowed), keys[0]),
            "proto": nearest(None),
            "proto+pos": nearest(allowed),
        }
        for name, key in picks.items():
            stats[item["cls"]][f"{name}_ok"] += key in acceptable
            stats["ALL"][f"{name}_ok"] += key in acceptable
        stats[item["cls"]]["n"] += 1
        stats["ALL"]["n"] += 1

    cols = ["prior", "prior+pos", "proto", "proto+pos"]
    print(f"\n{'stratum':<8}{'n':>5}" + "".join(f"{c:>13}" for c in cols))
    for cls in ["AUX", "REFL", "POLY", "ALL"]:
        row = stats[cls]
        if not row["n"]:
            continue
        line = f"{cls:<8}{row['n']:>5}"
        for c in cols:
            line += f"{100 * row[f'{c}_ok'] / row['n']:>12.1f}%"
        print(line)


if __name__ == "__main__":
    main()
