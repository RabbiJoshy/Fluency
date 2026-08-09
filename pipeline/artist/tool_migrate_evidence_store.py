#!/usr/bin/env python3
"""Archive an artist's existing mutable layers as Evidence Store baselines.

This is a non-destructive bridge for artists built before Evidence Store v1.
It does not rebuild layers or modify their JSON. Run artist step 2 separately
to create the canonical segment/occurrence ledger, then use
``pipeline/tool_6a_migrate_example_ids.py`` to backfill stable assignment refs.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.artist.util_1a_artist_config import load_artist_config  # noqa: E402
from pipeline.util_evidence_store import archive_json_artifact  # noqa: E402


STATIC_LAYERS = (
    ("data/elision_merge/vocab_evidence_merged.json", "elision_normalization"),
    ("data/known_vocab/word_routing.json", "word_routing"),
    ("data/layers/example_pos.json", "example_pos"),
)

DYNAMIC_DIRS = (
    ("data/layers/sense_menu", "sense_menu"),
    ("data/layers/sense_assignments", "sense_assignments"),
    ("data/layers/sense_assignments_lemma", "sense_assignments_lemma"),
    ("data/layers/unassigned_routing", "unassigned_routing"),
    ("data/layers/unassigned_routing_evidence", "unassigned_routing_evidence"),
)


def discover_layers(artist_dir):
    artist_dir = Path(artist_dir).resolve()
    found = []
    for relative_path, layer in STATIC_LAYERS:
        path = artist_dir / relative_path
        if path.is_file():
            found.append((path, layer))
    for relative_dir, prefix in DYNAMIC_DIRS:
        directory = artist_dir / relative_dir
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            if path.name.endswith(".meta.json"):
                continue
            found.append((path, "%s/%s" % (prefix, path.stem)))
    return found


def migrate(artist_dir, dry_run=False):
    artist_dir = Path(artist_dir).resolve()
    config = load_artist_config(artist_dir)
    language = config.get("language") or artist_dir.parent.name or "und"
    evidence_dir = artist_dir / "data" / "evidence"
    results = []
    for path, layer in discover_layers(artist_dir):
        if dry_run:
            results.append({"layer": layer, "path": str(path), "run_id": None})
            continue
        with open(path, encoding="utf-8") as file:
            payload = json.load(file)
        result = archive_json_artifact(
            evidence_dir,
            layer,
            payload,
            language=language,
            adapter={"name": "artist-evidence-baseline-migration", "version": 1},
            inputs={"legacy_path": str(path.relative_to(artist_dir))},
        )
        results.append({"layer": layer, "path": str(path), **result})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artist-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    results = migrate(args.artist_dir, dry_run=args.dry_run)
    verb = "Would archive" if args.dry_run else "Archived"
    print("%s %d layer(s):" % (verb, len(results)))
    for result in results:
        suffix = " -> %s" % result["run_id"] if result.get("run_id") else ""
        print("  %s: %s%s" % (result["layer"], result["path"], suffix))
    if not args.dry_run:
        print("Run artist step 2 to create/refresh the segment and occurrence ledger.")
        print("Then run tool_6a_migrate_example_ids.py to upgrade assignment references.")


if __name__ == "__main__":
    main()
