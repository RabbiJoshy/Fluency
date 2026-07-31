#!/usr/bin/env python3
"""Snapshot / restore the shared SpanishDict scrape cache.

`Data/Spanish/Senses/spanishdict/` is gitignored — 20 MB of derived data that
does not belong in history as loose JSON. But rederiving it means re-scraping
SpanishDict for every word in the corpus, which is slow enough to be painful and
was in fact lost once already in a machine transfer. The cache was recovered
from git history (it was tracked until commit 5d3f87e7 untracked it), and this
tool exists so that never has to be a rescue operation again.

The snapshot compresses ~20 MB to ~3.6 MB, which is committable — the repo
already tracks `kaikki-*.jsonl.gz` on the same reasoning.

    python3 pipeline/tool_5c_snapshot_spanishdict_cache.py            # save
    python3 pipeline/tool_5c_snapshot_spanishdict_cache.py --restore  # restore

Restore MERGES by default: entries already on disk win, so a restore can never
discard words fetched since the snapshot. Pass --overwrite for a clean replace.
"""

import argparse
import json
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "Senses", "spanishdict")
SNAPSHOT = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "Senses",
                        "spanishdict_cache_snapshot.tar.gz")
MANIFEST = SNAPSHOT + ".manifest.json"
# Word-keyed maps that can be merged entry-by-entry on restore.
MERGEABLE = ("surface_cache.json", "headword_cache.json", "redirects.json",
             "phrases_cache.json")


def cache_counts():
    counts = {}
    for name in sorted(os.listdir(CACHE_DIR)) if os.path.isdir(CACHE_DIR) else []:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(CACHE_DIR, name), "r", encoding="utf-8") as f:
                data = json.load(f)
            counts[name] = len(data) if hasattr(data, "__len__") else 0
        except Exception:
            counts[name] = -1
    return counts


def save():
    if not os.path.isdir(CACHE_DIR):
        sys.exit("No cache at %s — nothing to snapshot." % CACHE_DIR)
    counts = cache_counts()
    with tarfile.open(SNAPSHOT, "w:gz") as tar:
        tar.add(CACHE_DIR, arcname="spanishdict")
    manifest = {
        "created": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "bytes": os.path.getsize(SNAPSHOT),
    }
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print("Snapshot written: %s (%.1f MB)"
          % (os.path.relpath(SNAPSHOT, _PROJECT_ROOT), manifest["bytes"] / 1e6))
    for name, n in counts.items():
        print("   %-22s %d entries" % (name, n))
    print("\nCommit it so a fresh clone can restore instead of re-scraping.")


def restore(overwrite):
    if not os.path.isfile(SNAPSHOT):
        sys.exit("No snapshot at %s" % SNAPSHOT)
    before = cache_counts()
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(SNAPSHOT, "r:gz") as tar:
            tar.extractall(tmp)
        src = os.path.join(tmp, "spanishdict")
        if overwrite or not os.path.isdir(CACHE_DIR):
            if os.path.isdir(CACHE_DIR):
                shutil.rmtree(CACHE_DIR)
            shutil.copytree(src, CACHE_DIR)
        else:
            os.makedirs(CACHE_DIR, exist_ok=True)
            for name in os.listdir(src):
                target = os.path.join(CACHE_DIR, name)
                if not os.path.isfile(target):
                    shutil.copy(os.path.join(src, name), target)
                    continue
                if name not in MERGEABLE:
                    continue  # leave status.json and anything unknown alone
                with open(os.path.join(src, name), "r", encoding="utf-8") as f:
                    snap = json.load(f)
                with open(target, "r", encoding="utf-8") as f:
                    live = json.load(f)
                if isinstance(snap, dict) and isinstance(live, dict):
                    merged = dict(snap)
                    merged.update(live)  # anything fetched since the snapshot wins
                    with open(target, "w", encoding="utf-8") as f:
                        json.dump(merged, f, ensure_ascii=False)
    after = cache_counts()
    print("Restored from %s (%s)"
          % (os.path.relpath(SNAPSHOT, _PROJECT_ROOT),
             "overwrite" if overwrite else "merge, live entries win"))
    for name in sorted(set(before) | set(after)):
        print("   %-22s %s -> %s" % (name, before.get(name, 0), after.get(name, 0)))


def main():
    parser = argparse.ArgumentParser(description="Snapshot or restore the SpanishDict cache")
    parser.add_argument("--restore", action="store_true", help="Restore instead of saving")
    parser.add_argument("--overwrite", action="store_true",
                        help="With --restore: replace the cache instead of merging into it")
    args = parser.parse_args()
    restore(args.overwrite) if args.restore else save()


if __name__ == "__main__":
    main()
