#!/usr/bin/env python3
"""
tool_5a_build_example_store.py — One-off migration: build example_store.json
from an existing examples_raw.json.

Reads all examples in examples_raw.json (which must already have 'id' fields
from Phase 1) and writes an append-only flat store at the same layers path:

    example_store.json: {id: {target, english, source, easiness}, ...}

Safe to run multiple times — existing store entries are preserved; only new
IDs are added.

Run once per language / artist dir after Phase 1 (tool_5a_add_example_ids.py).
Going forward, step_5a and tool_5a_extend_examples maintain the store
automatically on every run.

Usage:
    python3 pipeline/tool_5a_build_example_store.py
    python3 pipeline/tool_5a_build_example_store.py --language french
    python3 pipeline/tool_5a_build_example_store.py --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

from util_5a_example_id import update_example_store  # noqa: E402

LANGUAGES = ["spanish", "french", "dutch"]


def _layers_dir(language: str) -> Path:
    return PROJECT_ROOT / "Data" / language.capitalize() / "layers"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--language", default="spanish", choices=LANGUAGES,
        help="Language to build store for (default: spanish)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count what would be added; write nothing."
    )
    args = parser.parse_args()

    layers = _layers_dir(args.language)
    examples_path = layers / "examples_raw.json"
    store_path = layers / "example_store.json"

    if not examples_path.exists():
        print(f"ERROR: not found: {examples_path}")
        sys.exit(1)

    with open(examples_path, encoding="utf-8") as f:
        data = json.load(f)

    # Quick check that Phase 1 has been run
    sample = next(
        (ex for exs in data.values() for ex in exs if isinstance(ex, dict)),
        None
    )
    if sample and "id" not in sample:
        print(
            "WARNING: examples lack 'id' fields. "
            "Run tool_5a_add_example_ids.py first."
        )

    total_examples = sum(len(v) for v in data.values())
    print(f"examples_raw.json: {len(data)} words, {total_examples:,} examples")

    existing = 0
    if store_path.exists():
        with open(store_path, encoding="utf-8") as f:
            existing = len(json.load(f))
        print(f"example_store.json: {existing:,} entries already present")

    if args.dry_run:
        # Count how many would be added without writing
        store = {}
        if store_path.exists():
            with open(store_path, encoding="utf-8") as f:
                store = json.load(f)
        would_add = sum(
            1 for exs in data.values()
            for ex in exs
            if isinstance(ex, dict) and ex.get("id") and ex["id"] not in store
        )
        print(f"\n[dry-run] Would add {would_add:,} entries "
              f"(total would be {existing + would_add:,})")
        return

    added, total = update_example_store(data, store_path)
    print(f"\nDone. Added {added:,} entries. Store now has {total:,} total.")


if __name__ == "__main__":
    main()
