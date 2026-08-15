#!/usr/bin/env python3
"""tool_migrate_artist_surface_ids — move artist cards onto surface identity.

Speech mode already keys cards on the surface form. Artist mode still keys on
``word|lemma``, and because getCrossModeId() shares progress between modes by
flipping es0/es1 and reusing the hex, the two schemes no longer line up: 479 of
491 speech surfaces also exist in the artist master, and none of them credit
each other any more. Migrating artist restores that by construction — both modes
mint the same ID from the same surface, so the coordination that
``load_artist_master_ids`` used to provide stops being necessary at all.

The work happens in the identity registry rather than by renumbering files.
For each surface it seeds a record under the new surface ID and merges every
active card for that surface into it. ``CardIdentityRegistry.merge`` retires the
source, rebinds its ``(surface, lemma)`` aliases onto the target, unions the
evidence, and appends a migration entry — which is also what makes the learner
progress remap derivable afterwards rather than guessed.

Nothing here is destroyed: merged records stay in the registry with
``status: merged`` and ``superseded_by``, so the pre-migration mapping is still
readable if the decision is ever reversed.

Run this, then rebuild each artist deck with step_8b --surface-cards, then
migrate progress using the emitted mapping.

Usage:
    python3 pipeline/artist/tool_migrate_artist_surface_ids.py --dry-run
    python3 pipeline/artist/tool_migrate_artist_surface_ids.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "pipeline"))

from pipeline.util_identity_registry import CardIdentityRegistry  # noqa: E402
from util_8a_assembly_helpers import make_surface_id  # noqa: E402

REGISTRY = REPO / "Artists/spanish/evidence/registries/cards.json"
OUT_DIR = REPO / "Artists/spanish/evidence"


def active_records(registry):
    return {cid: rec for cid, rec in registry.records.items()
            if (rec.get("status") or "active") == "active"}


def surfaces_of(record):
    return {str(a.get("surface") or "").strip().lower()
            for a in (record.get("aliases") or []) if a.get("surface")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=str(REGISTRY))
    ap.add_argument("--language", default="spanish")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    registry = CardIdentityRegistry.load(Path(args.registry), args.language)
    actives = active_records(registry)
    print("registry: %d records (%d active, %d migrations)"
          % (len(registry.records), len(actives), len(registry.migrations)))

    # A card can carry aliases for more than one surface. Those are historical
    # spellings of one learner identity, so the card belongs to whichever
    # surface most of its aliases name; ties break alphabetically for
    # determinism rather than dict order.
    owner_surface = {}
    multi_surface = 0
    for cid, rec in actives.items():
        surfaces = surfaces_of(rec)
        if not surfaces:
            continue
        if len(surfaces) > 1:
            multi_surface += 1
        counts = Counter(str(a.get("surface") or "").strip().lower()
                         for a in (rec.get("aliases") or []) if a.get("surface"))
        owner_surface[cid] = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    by_surface = defaultdict(list)
    for cid, surface in owner_surface.items():
        by_surface[surface].append(cid)

    # Mint over every surface in sorted order so the collision fallback inside
    # make_surface_id cannot make an ID depend on iteration order.
    reserved = set(registry.records)
    new_id_for = {}
    for surface in sorted(by_surface):
        new_id = make_surface_id(surface, reserved)
        reserved.add(new_id)
        new_id_for[surface] = new_id

    collapsing = {s: c for s, c in by_surface.items() if len(c) > 1}
    print("  cards with an owning surface: %d" % len(owner_surface))
    print("  cards whose aliases span >1 surface: %d" % multi_surface)
    print("  surfaces: %d  (of which absorbing >1 card: %d, collapsing %d cards)"
          % (len(by_surface), len(collapsing),
             sum(len(c) for c in collapsing.values())))
    already = sum(1 for s, cids in by_surface.items()
                  if len(cids) == 1 and cids[0] == new_id_for[s])
    print("  already on their surface ID: %d" % already)

    mapping = {}
    for surface, cids in by_surface.items():
        target = new_id_for[surface]
        for cid in cids:
            if cid != target:
                mapping[cid] = target

    print("  old ID -> surface ID entries: %d" % len(mapping))
    sample = list(mapping.items())[:5]
    print("  sample:", [(a, b, [s for s, c in by_surface.items() if a in c][0])
                        for a, b in sample])

    if args.dry_run:
        print("\n--dry-run: registry untouched, nothing written")
        return

    merged = seeded = 0
    for surface in sorted(by_surface):
        target = new_id_for[surface]
        sources = [c for c in by_surface[surface] if c != target]
        if not sources:
            continue
        if target not in registry.records:
            # Seed the target from the first source's alias so the new record
            # owns a real (surface, lemma) pair before anything merges into it.
            first = registry.records[sources[0]]
            alias = (first.get("aliases") or [{}])[0]
            registry.seed(target, surface, alias.get("lemma") or surface)
            seeded += 1
        for source in sources:
            registry.merge(source, target,
                           "surface identity migration: %s" % surface)
            merged += 1

    registry.save(Path(args.registry))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "artist_surface_id_migration.json"
    out.write_text(json.dumps({
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "language": args.language,
        "surfaces": len(by_surface),
        "cards_merged": merged,
        "targets_seeded": seeded,
        "mapping": mapping,
    }, ensure_ascii=False), encoding="utf-8")

    print("\nseeded %d new surface records, merged %d cards" % (seeded, merged))
    print("registry -> %s" % args.registry)
    print("mapping  -> %s" % out)
    print("\nNext: rebuild each artist deck with step_8b --surface-cards")


if __name__ == "__main__":
    main()
