#!/usr/bin/env python3
"""Backfill ``step_version`` on pre-versioning status rows.

Context
-------
``tool_5c_build_spanishdict_cache.py`` uses ``STEP_VERSION`` to mark old
cache entries stale when the scraper's extraction logic changes. The
check is ``entry_version < STEP_VERSION``. Entries written before the
versioning mechanism was added carry no ``step_version`` field, which
evaluates as 0 — so they're treated as stale and get re-fetched on the
next cache run even when their data is still valid.

After ``tool_5c_invalidate_backwards_entries.py`` surgically removes
the small subset of entries that need refetching, it's counterproductive
to also refetch ~13k unversioned-but-correct entries just because their
status row lacks the field. This tool stamps those rows with the
current ``STEP_VERSION``, so the cache builder only refetches truly
missing entries on the next run.

Usage (from repo root):

    # Dry run — prints what would change
    .venv/bin/python3 pipeline/tool_5c_backfill_status_version.py

    # Apply
    .venv/bin/python3 pipeline/tool_5c_backfill_status_version.py --execute

The tool backs up ``status.json`` to ``status.json.bak`` before editing.
Run this AFTER a scraper change when you're confident the existing
cache data is still valid under the new scraper logic. If the scraper
change genuinely invalidates old data, bump STEP_VERSION instead.
"""

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

# Import STEP_VERSION from the cache builder so the two stay in sync.
_SCRIPT_DIR = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(_SCRIPT_DIR))
from tool_5c_build_spanishdict_cache import STEP_VERSION  # noqa: E402
from util_5c_spanishdict import SPANISHDICT_STATUS


def main():
    parser = argparse.ArgumentParser(description="Backfill step_version on status.json")
    parser.add_argument("--execute", action="store_true",
                        help="Actually update status.json. Without this flag "
                             "the tool prints what would change.")
    parser.add_argument("--target-version", type=int, default=STEP_VERSION,
                        help=f"Version to stamp on unversioned rows "
                             f"(default: current STEP_VERSION = {STEP_VERSION}).")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip writing status.json.bak before editing.")
    args = parser.parse_args()

    if not SPANISHDICT_STATUS.exists():
        print(f"ERROR: status file not found at {SPANISHDICT_STATUS}")
        return

    with open(SPANISHDICT_STATUS, encoding="utf-8") as f:
        status = json.load(f)

    # Backfill BOTH the ``surface`` and ``headwords`` status sections.
    # The cache builder's stale-version check applies equally to both;
    # a backfill that only covered surface still left ~4k unversioned
    # headword rows driving a spurious ~24 min of headword re-fetches.
    sections = [
        ("surface", status.get("surface", {})),
        ("headwords", status.get("headwords", {})),
    ]
    total_missing = []
    for name, section in sections:
        counts_before = Counter()
        missing = []
        for k, s in section.items():
            if not isinstance(s, dict):
                continue
            v = s.get("step_version", "missing")
            counts_before[v] += 1
            if v == "missing":
                missing.append(k)
        print(f"\n[{name}] {len(section)} rows; step_version distribution (before):")
        for v, n in sorted(counts_before.items(), key=lambda kv: (str(kv[0]))):
            print(f"  {v!r}: {n}")
        total_missing.append((name, section, missing))

    any_missing = any(missing for _, _, missing in total_missing)
    if not any_missing:
        print("\nNothing to backfill.")
        return

    for name, _, missing in total_missing:
        if not missing:
            continue
        print(f"\n[{name}] Would stamp {len(missing)} rows with step_version={args.target_version}")
        print(f"  Sample: {missing[:10]}")

    if not args.execute:
        print("\nDry run — no changes made.")
        print("Re-run with --execute to apply.")
        return

    if not args.no_backup:
        bak = SPANISHDICT_STATUS.with_suffix(SPANISHDICT_STATUS.suffix + ".bak")
        shutil.copy2(SPANISHDICT_STATUS, bak)
        print(f"\nBacked up → {bak}")

    total_stamped = 0
    for name, section, missing in total_missing:
        for k in missing:
            section[k]["step_version"] = args.target_version
        total_stamped += len(missing)

    with open(SPANISHDICT_STATUS, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    print(f"Stamped {total_stamped} rows (surface + headwords) with "
          f"step_version={args.target_version}.")


if __name__ == "__main__":
    main()
