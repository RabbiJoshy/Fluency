#!/usr/bin/env python3
"""
tool_6a_migrate_example_ids.py — Add stable example and occurrence references
alongside each sense assignment's legacy integer ``examples`` list.

Reads examples_raw.json (which already has 'id' fields after Phase 1), then
walks every sense_assignments/*.json and sense_assignments_lemma/*.json file.
For each assignment item:

    {"sense": "abc", "examples": [0, 1, 5]}

it adds:

    {"sense": "abc", "examples": [0, 1, 5], "example_ids": ["a1b2c3", "d4e5f6", "f7a8b9"]}

Integer indices are preserved unchanged — nothing downstream breaks. The IDs
are just recorded alongside so future steps can migrate to referencing them.

Idempotent: stable references already present are left untouched.

Works for normal mode (--language) and artist mode (--artist-dir). Artist mode
prefers the persisted evidence-ledger ``segment_id`` and records target
``occurrence_ids`` when available. Existing lyric IDs remain migration aliases.

Usage:
    python3 pipeline/tool_6a_migrate_example_ids.py
    python3 pipeline/tool_6a_migrate_example_ids.py --language french
    python3 pipeline/tool_6a_migrate_example_ids.py --artist-dir Artists/es/BadBunny
    python3 pipeline/tool_6a_migrate_example_ids.py --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

from util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

LANGUAGES = ["spanish", "french", "dutch"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _layers_dir(language: str, artist_dir=None) -> Path:
    if artist_dir:
        return Path(artist_dir).resolve() / "data" / "layers"
    return PROJECT_ROOT / "Data" / language.capitalize() / "layers"


def _build_id_lookup(examples_raw: dict) -> dict:
    """Return identity/occurrence records aligned to each word's examples.

    Both segment and legacy IDs are aliases, allowing existing claims to be
    upgraded without trusting their possibly stale numeric index.
    """
    lookup = {}
    for word, examples in examples_raw.items():
        lookup[word.lower()] = [{
            "identity": ex.get("segment_id") or ex.get("id"),
            "aliases": [value for value in (ex.get("segment_id"), ex.get("id")) if value],
            "occurrence_ids": list(ex.get("occurrence_ids") or []),
            "example_index": index,
        } for index, ex in enumerate(examples)]
    return lookup


def _surface_word(key: str) -> str:
    """Extract surface word from a plain word key or a 'word|lemma' key."""
    return key.split("|", 1)[0]


def _migrate_items(items, word_refs: list, stats: dict) -> None:
    """Add or upgrade aligned example and occurrence refs in-place."""
    by_alias = {
        alias: ref
        for ref in word_refs
        for alias in ref.get("aliases", [])
    }
    for item in items or []:
        if not isinstance(item, dict):
            continue
        stats["total"] += 1
        if "example_ids" in item:
            stats["already_had"] += 1
        indices = item.get("examples") or []
        old_ids = item.get("example_ids") or []
        eids = []
        resolved_refs = []
        for position, index in enumerate(indices):
            old_id = old_ids[position] if position < len(old_ids) else None
            ref = by_alias.get(old_id) if old_id else None
            if ref is None and not old_id and isinstance(index, int) and 0 <= index < len(word_refs):
                ref = word_refs[index]
            if ref is not None and ref.get("identity"):
                eids.append(ref["identity"])
                resolved_refs.append(ref)
            else:
                # Keep alignment and never retarget an unresolved stable ID by
                # falling back to a potentially stale numeric position.
                eids.append(old_id)
                resolved_refs.append(None)
                stats["missing"] += 1
        changed = item.get("example_ids") != eids
        item["example_ids"] = eids

        if "occurrence_refs" not in item:
            occurrence_refs = []
            for index, example_id, ref in zip(indices, eids, resolved_refs):
                if ref is None:
                    continue
                for occurrence_id in ref.get("occurrence_ids") or []:
                    occurrence_refs.append({
                        "occurrence_id": occurrence_id,
                        "example_id": example_id,
                        "example_index": ref.get("example_index", index),
                    })
            if occurrence_refs:
                item["occurrence_refs"] = occurrence_refs
                item["occurrence_ids"] = list(dict.fromkeys(
                    row["occurrence_id"] for row in occurrence_refs
                ))
                stats["occurrence_migrated"] += 1
                changed = True
        if changed:
            stats["migrated"] += 1


def migrate_file(path: Path, id_lookup: dict, dry_run: bool) -> dict:
    """Migrate one assignments file. Returns stats dict."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    stats = {
        "total": 0,
        "already_had": 0,
        "migrated": 0,
        "occurrence_migrated": 0,
        "missing": 0,
    }

    for key, value in data.items():
        # key is "word" in sense_assignments, "word|lemma" in sense_assignments_lemma
        word = _surface_word(key)
        word_refs = id_lookup.get(word.lower(), [])

        if isinstance(value, dict):
            # Modern format: {method: [items]}
            for method, items in value.items():
                _migrate_items(items, word_refs, stats)
        elif isinstance(value, list):
            # Legacy flat-list format: [items]
            _migrate_items(value, word_refs, stats)

    if not dry_run and stats["migrated"] > 0:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        write_sidecar(path, make_meta("migrate_example_ids", 2))

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--language", default="spanish", choices=LANGUAGES,
        help="Language for normal-mode paths (default: spanish)"
    )
    parser.add_argument(
        "--artist-dir", default=None,
        help="Path to an artist directory (e.g. Artists/es/BadBunny)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be migrated; write nothing."
    )
    args = parser.parse_args()

    layers = _layers_dir(args.language, args.artist_dir)
    examples_path = layers / "examples_raw.json"

    if not examples_path.exists():
        print(f"ERROR: examples_raw.json not found: {examples_path}")
        sys.exit(1)

    with open(examples_path, encoding="utf-8") as f:
        examples_raw = json.load(f)

    # Check examples have IDs (Phase 1 must have run first)
    sample = next(
        (ex for exs in examples_raw.values() for ex in exs if isinstance(ex, dict)),
        None
    )
    if sample and "id" not in sample and "segment_id" not in sample:
        print(
            "WARNING: examples_raw.json examples lack 'id' fields.\n"
            "Run tool_5a_add_example_ids.py first (Phase 1) to stamp IDs."
        )

    id_lookup = _build_id_lookup(examples_raw)
    print(f"ID lookup built: {len(id_lookup)} words")

    # Collect all assignment files to migrate
    targets = []
    for subdir in ("sense_assignments", "sense_assignments_lemma"):
        d = layers / subdir
        if d.is_dir():
            for p in sorted(d.glob("*.json")):
                if p.suffix == ".json" and not p.name.endswith(".meta.json") \
                        and not p.name.endswith(".bak"):
                    targets.append((subdir, p))

    if not targets:
        print("No assignment files found.")
        sys.exit(0)

    print(f"Found {len(targets)} assignment file(s) to migrate:\n")

    grand = {
        "total": 0,
        "already_had": 0,
        "migrated": 0,
        "occurrence_migrated": 0,
        "missing": 0,
    }

    for subdir, path in targets:
        stats = migrate_file(path, id_lookup, dry_run=args.dry_run)
        tag = "[dry-run] " if args.dry_run else ""
        print(f"  {tag}{subdir}/{path.name}")
        print(f"    {stats['total']} items  |  "
              f"{stats['already_had']} already had ids  |  "
              f"{stats['migrated']} {'would migrate' if args.dry_run else 'migrated'}  |  "
              f"{stats['occurrence_migrated']} occurrence-linked  |  "
              f"{stats['missing']} missing")
        for k in grand:
            grand[k] += stats[k]

    print(f"\nTotal: {grand['total']} items, "
          f"{grand['migrated']} {'would migrate' if args.dry_run else 'migrated'}, "
          f"{grand['occurrence_migrated']} occurrence-linked, "
          f"{grand['already_had']} already done, "
          f"{grand['missing']} missing lookups")

    if args.dry_run:
        print("\n(dry-run: nothing written)")
    elif grand["migrated"] > 0:
        print("\nDone.")


if __name__ == "__main__":
    main()
