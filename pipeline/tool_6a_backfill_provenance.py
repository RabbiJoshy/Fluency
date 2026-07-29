#!/usr/bin/env python3
"""tool_6a_backfill_provenance.py — Stamp provenance onto historical sense assignments.

Existing ``sense_assignments/*.json`` (and their lemma-mapped twins) predate the
provenance system: items carry no ``prompt_id``/``run_ts``. This one-shot backfill
adds those fields best-effort so the structure is there and every FUTURE stamped
run supersedes cleanly.

Backfill rule (see docs/design/sense_provenance.md):
  - Items under the ``gap-fill`` method key are provably the 3.1 classify-or-propose
    run's off-menu proposals  -> prompt_id ``sd-cop-v2``.
  - Everything else is unrecoverable (bare menu-picks look identical across 2.5 and
    3.1) -> prompt_id ``legacy-unknown`` (lowest tier; any real run supersedes it).
  - run_ts is taken from the sibling ``*.meta.json`` ``generated_at`` when present
    (best-effort; the exact per-item run time was never recorded).

Idempotent: items already carrying a ``prompt_id`` are left untouched.

Usage:
    .venv/bin/python3 pipeline/tool_6a_backfill_provenance.py [--root DIR] [--dry-run]

Walks every ``sense_assignments`` and ``sense_assignments_lemma`` directory under
``--root`` (default: repo root), covering both normal-mode (Data/) and artist-mode
(Artists/) layers.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util_6a_prompt_registry import (backfill_prompt_id_for_method,  # noqa: E402
                                     BACKFILL_DEFAULT_PROMPT_ID)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_DIRS = ("sense_assignments", "sense_assignments_lemma")


def _meta_generated_at(json_path):
    """Best-effort run_ts (UTC ISO-8601) from the sibling .meta.json, or None.

    ``generated_at`` is stored as a Unix epoch (int/float) in most meta files;
    some may carry an ISO string. Normalize both to ``YYYY-MM-DDTHH:MMZ`` so the
    card renders a real timestamp and stamps sort lexicographically.
    """
    meta_path = json_path + ".meta.json"
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    ts = meta.get("generated_at") if isinstance(meta, dict) else None
    if isinstance(ts, bool):
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        except (OSError, ValueError, OverflowError):
            return None
    return ts if isinstance(ts, str) and ts else None


def backfill_file(json_path, dry_run=False):
    """Stamp provenance into one assignments file. Returns (stamped, skipped)."""
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return (0, 0)
    if not isinstance(data, dict):
        return (0, 0)

    # The `gap-fill` -> sd-cop-v2 (3.1 classify-or-propose) mapping only holds
    # where that rerun actually happened: the ARTIST decks. Standard mode
    # (Data/) was never re-run on 3.1, so its gap-fill items are an older method
    # and must stay legacy-unknown. Scope by path.
    norm = os.path.normpath(json_path)
    is_artist = ("%sArtists%s" % (os.sep, os.sep)) in norm or norm.startswith("Artists%s" % os.sep)

    run_ts = _meta_generated_at(json_path)
    stamped = skipped = 0
    for _word, payload in data.items():
        # On-disk shape is {method: [items]}; tolerate the legacy flat list too.
        method_items = payload.items() if isinstance(payload, dict) else [
            ("legacy", payload if isinstance(payload, list) else [])]
        for method, items in method_items:
            prompt_id = (backfill_prompt_id_for_method(method) if is_artist
                         else BACKFILL_DEFAULT_PROMPT_ID)
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                if item.get("prompt_id"):
                    skipped += 1
                    continue
                item["prompt_id"] = prompt_id
                if run_ts:
                    item["run_ts"] = run_ts
                stamped += 1

    if stamped and not dry_run:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return (stamped, skipped)


def find_assignment_files(root):
    """Yield every *.json (not *.meta.json) inside any target assignments dir."""
    for dirpath, _dirnames, filenames in os.walk(root):
        if os.path.basename(dirpath) not in TARGET_DIRS:
            continue
        for name in filenames:
            if name.endswith(".json") and not name.endswith(".meta.json"):
                yield os.path.join(dirpath, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=REPO_ROOT,
                        help="Directory to walk (default: repo root).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing.")
    args = parser.parse_args()

    files = sorted(find_assignment_files(args.root))
    total_stamped = total_skipped = 0
    touched = 0
    for path in files:
        stamped, skipped = backfill_file(path, dry_run=args.dry_run)
        total_stamped += stamped
        total_skipped += skipped
        if stamped:
            touched += 1
            rel = os.path.relpath(path, args.root)
            print("  %-70s +%d stamped, %d already-labeled" % (rel, stamped, skipped))

    verb = "Would stamp" if args.dry_run else "Stamped"
    print("\n%s %d items across %d files (%d files scanned, %d items already labeled)."
          % (verb, total_stamped, touched, len(files), total_skipped))


if __name__ == "__main__":
    main()
