#!/usr/bin/env python3
"""tool_5d_stamp_mwe_ids — give every multi-word expression a durable identity.

js/knowledge.js keys an Expression's learner progress on ``mwe.id`` and falls
back to hashing the rendered expression text. No MWE in the layer carries an id,
so the fallback is the only path in use today: correcting a phrase's wording,
normalising an apostrophe, or fixing spacing silently orphans whatever progress
was recorded against it. Senses already avoid this by carrying ``sense_id``.

The id is minted once from the expression and then **persisted**. That is the
whole point — a recomputed hash would move with the text and fix nothing. Once
stamped, an expression can be re-worded freely and keeps its identity, exactly
as a card keeps its identity when its lemma is revised.

Idempotent: an expression that already has an id is left alone, so this can be
re-run after the MWE builder adds new phrases.

Usage:
    python3 pipeline/tool_5d_stamp_mwe_ids.py --dry-run
    python3 pipeline/tool_5d_stamp_mwe_ids.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MWE_PATH = REPO / "Data/Spanish/layers/mwe_phrases.json"

MWE_ID_NAMESPACE = "mwe/v1:"
MWE_ID_LENGTH = 8


def normalize_expression(text):
    """Fold only what can never distinguish two expressions.

    Case and whitespace are safe to ignore when minting. Accents are NOT — in
    Spanish they carry meaning, so `de` and `dé` must not collide.
    """
    value = unicodedata.normalize("NFC", str(text or "")).strip().lower()
    return " ".join(value.split())


def mint_id(expression):
    digest = hashlib.md5(
        (MWE_ID_NAMESPACE + normalize_expression(expression)).encode("utf-8")
    ).hexdigest()
    return "mwe_" + digest[:MWE_ID_LENGTH]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=str(MWE_PATH))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = Path(args.path)
    data = json.loads(path.read_text(encoding="utf-8"))

    stamped = kept = 0
    minted = {}
    collisions = Counter()
    for word, phrases in data.items():
        for phrase in phrases or []:
            if phrase.get("id"):
                kept += 1
                continue
            expression = phrase.get("expression") or ""
            if not expression.strip():
                continue
            new_id = mint_id(expression)
            norm = normalize_expression(expression)
            if new_id in minted and minted[new_id] != norm:
                collisions[new_id] += 1
            minted[new_id] = norm
            phrase["id"] = new_id
            stamped += 1

    total = sum(len(v or []) for v in data.values())
    print("expressions: %d across %d words" % (total, len(data)))
    print("  already had an id: %d" % kept)
    print("  stamped this run:  %d" % stamped)
    print("  distinct ids:      %d" % len(minted))
    print("  hash collisions between DIFFERENT expressions: %d %s"
          % (len(collisions), dict(collisions) if collisions else ""))
    shared = total - len(minted) - kept
    print("  expressions sharing an id with an identical phrase on another "
          "word: %d (correct — one expression, one identity)" % max(0, shared))

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print("\nwrote %s" % path)


if __name__ == "__main__":
    main()
