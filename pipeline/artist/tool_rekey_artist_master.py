#!/usr/bin/env python3
"""tool_rekey_artist_master — move vocabulary_master.json onto surface IDs.

The master is keyed by card ID. Migrating the identity registry alone is not
enough: step_8b then sees cards whose IDs are absent from the master, treats
every one as new, and appends 10,373 fresh entries beside the 17,451 originals
instead of re-keying them. The old entries become orphans that nothing reads and
the deck doubles.

So the master has to be re-keyed in the same pass as the registry. Entries whose
cards collapsed onto one surface are merged here, not left as duplicates:

  senses      unioned, de-duplicated on (pos, translation, context, sense_id)
  lemma       kept from the entry contributing the most senses, so the display
              headword is the one with the most behind it
  everything  else taken from that same entry

Idempotent: an already-8-hex master is left alone rather than re-keyed twice.

Usage:
    python3 pipeline/artist/tool_rekey_artist_master.py --dry-run
    python3 pipeline/artist/tool_rekey_artist_master.py
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MASTER = REPO / "Artists/spanish/vocabulary_master.json"
MAPPING = REPO / "Artists/spanish/evidence/artist_surface_id_migration.json"


def sense_key(sense):
    return (sense.get("pos"), sense.get("translation"),
            sense.get("context"), sense.get("sense_id"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default=str(MASTER))
    ap.add_argument("--mapping", default=str(MAPPING))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    master = json.loads(Path(args.master).read_text(encoding="utf-8"))
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))["mapping"]

    lengths = Counter(len(k) for k in master)
    print("master: %d entries, id lengths %s" % (len(master), dict(lengths)))
    if set(lengths) == {8}:
        print("already re-keyed — nothing to do")
        return

    # Cards retired by an EARLIER migration are not in this migration's mapping,
    # because it only walked active records. They still hold learner progress, so
    # follow superseded_by to whichever card is live now rather than stranding
    # them under a dead key.
    records = json.loads(
        (REPO / "Artists/spanish/evidence/registries/cards.json").read_text(
            encoding="utf-8"))["records"]

    def final_destination(card_id, limit=10):
        """Walk superseded_by until a live card, not until a mapping key.

        A destination is not a key in the mapping — the mapping is old -> new —
        so stopping only on `in mapping` walks straight past an already-active
        successor and returns None. 794249 -> ed5cdf2c is exactly that: the
        successor is live and already carries an 8-hex surface ID.
        """
        seen = set()
        while limit > 0 and card_id not in seen:
            seen.add(card_id)
            if card_id in mapping:
                return mapping[card_id]
            record = records.get(card_id) or {}
            if (record.get("status") or "active") == "active":
                return card_id
            successor = record.get("superseded_by")
            if not successor:
                return None
            card_id = successor
            limit -= 1
        return None

    grouped = defaultdict(list)
    unmapped = []
    followed = 0
    for old_id, entry in master.items():
        new_id = mapping.get(old_id)
        if new_id is None:
            new_id = final_destination(old_id)
            if new_id is None:
                unmapped.append(old_id)
                continue
            followed += 1
            mapping[old_id] = new_id
        grouped[new_id].append((old_id, entry))
    if followed:
        print("  resolved via superseded_by: %d" % followed)

    print("  mapped to %d surface IDs" % len(grouped))
    print("  entries with no mapping: %d%s"
          % (len(unmapped), (" e.g. %s" % unmapped[:5]) if unmapped else ""))
    collapsing = {k: v for k, v in grouped.items() if len(v) > 1}
    print("  surface IDs receiving >1 entry: %d (merging %d entries)"
          % (len(collapsing), sum(len(v) for v in collapsing.values())))

    rekeyed = {}
    for new_id, members in grouped.items():
        # Most senses wins: that entry supplies lemma and the scalar fields.
        members.sort(key=lambda pair: -len(pair[1].get("senses") or []))
        _, primary = members[0]
        merged = dict(primary)
        if len(members) > 1:
            senses, seen = [], set()
            for _, entry in members:
                for sense in entry.get("senses") or []:
                    key = sense_key(sense)
                    if key not in seen:
                        seen.add(key)
                        senses.append(sense)
            merged["senses"] = senses
            merged["merged_from"] = sorted(old for old, _ in members)
        rekeyed[new_id] = merged

    # Entries the registry never saw keep their old key rather than vanishing.
    for old_id in unmapped:
        rekeyed[old_id] = master[old_id]

    total_senses_before = sum(len(e.get("senses") or []) for e in master.values())
    total_senses_after = sum(len(e.get("senses") or []) for e in rekeyed.values())
    print("  entries: %d -> %d" % (len(master), len(rekeyed)))
    print("  senses:  %d -> %d (dedup removed %d)"
          % (total_senses_before, total_senses_after,
             total_senses_before - total_senses_after))

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    backup = Path(args.master).with_suffix(".pre_surface_rekey.%s.json" % stamp)
    shutil.copy2(args.master, backup)
    Path(args.master).write_text(json.dumps(rekeyed, ensure_ascii=False),
                                 encoding="utf-8")
    print("\nbacked up -> %s" % backup)
    print("wrote     -> %s" % args.master)


if __name__ == "__main__":
    main()
