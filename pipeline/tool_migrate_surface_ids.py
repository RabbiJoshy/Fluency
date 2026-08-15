#!/usr/bin/env python3
"""tool_migrate_surface_ids — move speech-mode cards from word|lemma to surface.

Emits three things:

  Data/{Lang}/id_migration.json      old 6-char hex -> new 6-char hex, for EVERY
                                     old card. Deliberately includes surfaces the
                                     current deck does not carry: the mapping is a
                                     pure function of the surface, so filing old
                                     progress under the right key now means it is
                                     already correct when coverage grows back.

  backend/local/surface_migration_progress.json
                                     the Sheets payload. Card rows re-keyed under
                                     the merge rule, plus one lemma item per old
                                     card so the pre-migration lemma mapping stays
                                     live rather than only existing in a backup.

  backend/local/surface_migration_report.json
                                     what merged, what collided, what was dropped.

Merge rule for cards collapsing onto one surface: strongest wins — highest
srsStage, then most correct answers, then most recent sighting. Counts are summed.
Resetting to the weakest would re-teach a word the learner already knows, and the
lemma items below retain the per-lemma detail either way.

The lemma items are a snapshot for rollback, not a durable record. Lemma credit is
a view over card history plus the current attribution: when WSD improves and a
sense moves headword, that credit is meant to be recomputed, not preserved.

Usage:
    python3 pipeline/tool_migrate_surface_ids.py --dry-run
    python3 pipeline/tool_migrate_surface_ids.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from util_8a_assembly_helpers import (SURFACE_ID_LENGTH,
                                     SURFACE_ID_NAMESPACE,
                                     make_surface_id)  # noqa: E402

SNAPSHOT = REPO / "Data/Spanish/Intermediates/snapshots/2026-08-12_pre_slice/tree"
OLD_INDEX = SNAPSHOT / "Data/Spanish/vocabulary.index.json"
OUT_MIGRATION = REPO / "Data/Spanish/id_migration.json"
LOCAL = REPO / "backend/local"

KNOWLEDGE_SCHEMA_VERSION = 1


def normalize_knowledge_text(value):
    """Mirror normalizeKnowledgeText in js/knowledge.js."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return " ".join(text.split())


def hash_knowledge_signature(value):
    """Mirror hashKnowledgeSignature in js/knowledge.js (FNV-1a, 32-bit).

    JS reads UTF-16 code units via charCodeAt and multiplies with Math.imul.
    Spanish is entirely BMP, so ord() per character matches; the mask reproduces
    imul's 32-bit wrap.
    """
    h = 0x811C9DC5
    for ch in str(value or ""):
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return format(h, "08x")


def lemma_item_id(full_id, headword):
    signature = "lemma|%s" % normalize_knowledge_text(headword)
    return "%s~k%d:lemma:%s" % (full_id, KNOWLEDGE_SCHEMA_VERSION,
                                hash_knowledge_signature(signature))


def surface_id_map(old_cards):
    """surface -> new 6-char id, assigned over the FULL surface set.

    make_stable_id slides the hash window on collision, so the result depends on
    what is already taken. Assigning over every surface in sorted order — not just
    the surfaces in today's deck — keeps the map stable as coverage changes.
    """
    surfaces = sorted({c["word"].lower() for c in old_cards})
    used, mapping = set(), {}
    for surface in surfaces:
        new_id = make_surface_id(surface, used)
        used.add(new_id)
        mapping[surface] = new_id
    collisions = [s for s in surfaces
                  if mapping[s] != hashlib.md5(
                      (SURFACE_ID_NAMESPACE + s).encode("utf-8")
                  ).hexdigest()[:SURFACE_ID_LENGTH]]
    return mapping, collisions


def strength(row):
    """Sort key for 'strongest wins'."""
    return (int(row.get("srsStage") or 0),
            int(row.get("correct") or 0),
            str(row.get("lastSeen") or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-index", default=str(OLD_INDEX))
    ap.add_argument("--progress", default=str(LOCAL / "Progress.json"))
    ap.add_argument("--prefix", default="es0",
                    help="language+mode prefix on a fullId (es0 = Spanish, normal)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    old_cards = json.loads(Path(args.old_index).read_text(encoding="utf-8"))
    by_old_id = {c["id"]: c for c in old_cards}
    mapping, collisions = surface_id_map(old_cards)

    id_migration = {}
    fanin = defaultdict(list)
    for card in old_cards:
        surface = card["word"].lower()
        new_id = mapping[surface]
        if card["id"] != new_id:
            id_migration[card["id"]] = new_id
        fanin[new_id].append(card["id"])

    # Compose with any existing map rather than replacing it. The file already
    # carries earlier hops (the clitic merges step_8a emitted); a learner who has
    # not run those yet needs old -> clitic -> surface to resolve in one lookup,
    # because the app applies the map exactly once.
    prior = {}
    if OUT_MIGRATION.exists():
        prior = json.loads(OUT_MIGRATION.read_text(encoding="utf-8"))
    composed = dict(id_migration)
    rewired = skipped = 0
    for old_id, mid_id in prior.items():
        # The surface map wins. A prior hop whose key is itself a live card id
        # must not overwrite that card's own destination: brillantes (id f7bfce)
        # had a prior entry f7bfce -> 7bfce0, and 7bfce0 maps to f7bfce, so
        # composing blindly produced f7bfce -> f7bfce and silently parked
        # brillantes on laboratorio's surface.
        if old_id in id_migration:
            skipped += 1
            continue
        # Follow the chain to a fixed point. One hop is not enough when a
        # prior entry points at another prior entry's key: 6aedef -> 794249
        # -> ed5cdf2c would otherwise stop at 794249 and need a second pass.
        final = id_migration.get(mid_id, mid_id)
        if composed.get(old_id) != final:
            rewired += 1
        composed[old_id] = final
    # Collapse any remaining chains to a fixed point. A prior hop can point at
    # another prior hop's key (6aedef -> 794249 -> ed5cdf2c), and the app applies
    # the map exactly once, so every value must already be a final destination.
    for _ in range(10):
        moved = 0
        for old_id, target in list(composed.items()):
            final = composed.get(target)
            if final is not None and final != target:
                composed[old_id] = final
                moved += 1
        if not moved:
            break
    id_migration = {k: v for k, v in composed.items() if k != v}

    # ---- progress
    payload = json.loads(Path(args.progress).read_text(encoding="utf-8"))
    rows = payload["rows"] if isinstance(payload, dict) and "rows" in payload else payload
    speech_rows = [r for r in rows
                   if r.get("mode") == "normal" and r.get("itemType") == "word"]

    grouped = defaultdict(list)
    unmatched = []
    for row in speech_rows:
        full = str(row.get("itemId") or "")
        if not full.startswith(args.prefix):
            unmatched.append(full)
            continue
        card = by_old_id.get(full[len(args.prefix):])
        if card is None:
            unmatched.append(full)
            continue
        grouped[mapping[card["word"].lower()]].append((row, card))

    card_rows, lemma_rows, merged_surfaces = [], [], []
    for new_id, members in grouped.items():
        members.sort(key=lambda rc: strength(rc[0]), reverse=True)
        best, best_card = members[0]
        new_full = args.prefix + new_id
        card_rows.append({
            **{k: v for k, v in best.items() if k not in ("itemId",)},
            "itemId": new_full,
            "itemType": "word",
            "word": best_card["word"],
            "correct": sum(int(r.get("correct") or 0) for r, _ in members),
            "wrong": sum(int(r.get("wrong") or 0) for r, _ in members),
            "srsStage": max(int(r.get("srsStage") or 0) for r, _ in members),
            "lastSeen": max((str(r.get("lastSeen") or "") for r, _ in members)),
        })
        if len(members) > 1:
            merged_surfaces.append({
                "surface": best_card["word"],
                "new_id": new_id,
                "from": [{"old_id": c["id"], "lemma": c.get("lemma"),
                          "srsStage": r.get("srsStage"), "correct": r.get("correct")}
                         for r, c in members],
                "kept": best_card.get("lemma"),
            })
        # One lemma item per contributing card: the old word|lemma record, re-keyed.
        for row, card in members:
            headword = card.get("lemma") or card["word"]
            lemma_rows.append({
                # `user` is not optional: bulkSave drops any row without one,
                # silently and before it looks at the type. These rows are built
                # from scratch rather than copied, so it has to be carried over
                # explicitly.
                "user": row.get("user"),
                "itemId": lemma_item_id(new_full, headword),
                "itemType": "lemma",
                "mode": row.get("mode", "normal"),
                "source": row.get("source", ""),
                "parentWordId": new_full,
                "label": headword,
                "word": card["word"],
                "language": row.get("language", "Spanish"),
                "correct": int(row.get("correct") or 0),
                "wrong": int(row.get("wrong") or 0),
                "srsStage": int(row.get("srsStage") or 0),
                "lastSeen": row.get("lastSeen", ""),
                "lastCorrect": row.get("lastCorrect", ""),
                "lastWrong": row.get("lastWrong", ""),
                "schemaVersion": row.get("schemaVersion", 4),
                "_migrated_from": args.prefix + card["id"],
            })

    report = {
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "old_cards": len(old_cards),
        "distinct_surfaces": len(mapping),
        "id_migration_entries": len(id_migration),
        "prior_entries_composed": len(prior),
        "prior_entries_rewired": rewired,
        "hash_collisions_resolved": collisions,
        "surfaces_receiving_multiple_cards": sum(1 for v in fanin.values() if len(v) > 1),
        "speech_word_rows": len(speech_rows),
        "rows_matched_to_a_card": sum(len(v) for v in grouped.values()),
        "rows_unmatched": len(unmatched),
        "card_rows_out": len(card_rows),
        "lemma_rows_out": len(lemma_rows),
        "merges_affecting_progress": merged_surfaces,
    }

    print("old cards %d -> %d surfaces" % (len(old_cards), len(mapping)))
    print("  id_migration entries: %d (composed %d prior, rewired %d)"
          % (len(id_migration), len(prior), rewired))
    print("  hash collisions resolved: %s" % (collisions or "none"))
    print("  speech word rows: %d (matched %d, unmatched %d)"
          % (len(speech_rows), report["rows_matched_to_a_card"], len(unmatched)))
    print("  card rows out: %d | lemma items out: %d" % (len(card_rows), len(lemma_rows)))
    print("  progressed cards merging: %d" % len(merged_surfaces))
    for m in merged_surfaces:
        print("     %-10s keeps %-10s from %s" % (
            m["surface"], m["kept"],
            [(f["lemma"], f["srsStage"], f["correct"]) for f in m["from"]]))

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return

    OUT_MIGRATION.write_text(json.dumps(id_migration, ensure_ascii=False),
                             encoding="utf-8")
    LOCAL.mkdir(parents=True, exist_ok=True)
    (LOCAL / "surface_migration_progress.json").write_text(json.dumps(
        {"cards": card_rows, "lemmaItems": lemma_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (LOCAL / "surface_migration_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nwrote %s" % OUT_MIGRATION)
    print("wrote %s" % (LOCAL / "surface_migration_progress.json"))
    print("wrote %s" % (LOCAL / "surface_migration_report.json"))


if __name__ == "__main__":
    main()
