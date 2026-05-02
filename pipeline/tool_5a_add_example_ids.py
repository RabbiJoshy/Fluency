#!/usr/bin/env python3
"""
tool_5a_add_example_ids.py — One-off migration: stamp stable IDs onto every
example in examples_raw.json that doesn't already have one.

Safe to run multiple times — examples that already carry an "id" field are
left untouched. Examples without one get a 12-char SHA-256 ID derived from
(target, english), the same formula used by step_5a going forward.

Run this once per examples_raw.json file (normal mode + each artist dir).

Usage:
    # Normal mode (Spanish):
    python3 pipeline/tool_5a_add_example_ids.py

    # Other languages:
    python3 pipeline/tool_5a_add_example_ids.py --language french

    # Artist mode:
    python3 pipeline/tool_5a_add_example_ids.py --artist-dir Artists/es/BadBunny

    # Dry run (report stats, write nothing):
    python3 pipeline/tool_5a_add_example_ids.py --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

from util_5a_example_id import example_id  # noqa: E402
from util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

LANGUAGES = ["spanish", "french", "dutch"]


def _examples_path(language: str, artist_dir=None) -> Path:
    if artist_dir:
        return Path(artist_dir).resolve() / "data" / "layers" / "examples_raw.json"
    lang_cap = language.capitalize()
    return PROJECT_ROOT / "Data" / lang_cap / "layers" / "examples_raw.json"


def _detect_format(data: dict) -> str:
    """Return 'normal' or 'artist' based on the example field names.

    Normal mode (Tatoeba/OpenSubtitles): {"target": ..., "english": ..., "source": ...}
    Artist mode (song lyrics):           {"spanish": ..., "title": ..., "surface": ...}
    """
    for examples in data.values():
        if examples:
            ex = examples[0]
            if "target" in ex and "english" in ex:
                return "normal"
            if "spanish" in ex or "title" in ex:
                return "artist"
    return "unknown"


def migrate(path: Path, dry_run: bool) -> dict:
    """Add 'id' to every example that lacks one. Returns stats dict.

    Artist-format files (song lyrics with their own lyric-based IDs) are
    detected and skipped — they already have a stable ID scheme.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    fmt = _detect_format(data)
    if fmt == "artist":
        return {"skipped": True, "reason": "artist format (lyrics IDs already present)"}
    if fmt == "unknown":
        return {"skipped": True, "reason": "unrecognised format — no examples found"}

    total = 0
    already_had = 0
    added = 0
    collisions = []

    seen_ids: dict[str, tuple] = {}  # id -> (target, english) for collision check

    for word, examples in data.items():
        for ex in examples:
            total += 1
            if "id" in ex:
                already_had += 1
                eid = ex["id"]
            else:
                eid = example_id(ex["target"], ex["english"])
                if not dry_run:
                    ex["id"] = eid
                added += 1

            # Collision check: same ID, different content
            key = (ex["target"].lower().strip(), ex["english"].lower().strip())
            if eid in seen_ids and seen_ids[eid] != key:
                collisions.append((eid, seen_ids[eid], key, word))
            else:
                seen_ids[eid] = key

    if not dry_run and added > 0:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        write_sidecar(path, make_meta("add_example_ids", 1))

    return {
        "skipped": False,
        "total": total,
        "already_had": already_had,
        "added": added,
        "collisions": collisions,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--language", default="spanish", choices=LANGUAGES,
        help="Language for normal-mode path (default: spanish)"
    )
    parser.add_argument(
        "--artist-dir", default=None,
        help="Path to an artist directory (e.g. Artists/es/BadBunny). "
             "When set, targets that artist's examples_raw.json."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report stats without writing anything."
    )
    args = parser.parse_args()

    path = _examples_path(args.language, args.artist_dir)

    if not path.exists():
        print(f"ERROR: not found: {path}")
        sys.exit(1)

    label = args.artist_dir or args.language
    print(f"{'[dry-run] ' if args.dry_run else ''}Migrating {path} ...")
    stats = migrate(path, dry_run=args.dry_run)

    if stats.get("skipped"):
        print(f"  Skipped: {stats['reason']}")
        return

    print(f"  {stats['total']:,} examples total")
    print(f"  {stats['already_had']:,} already had an id (untouched)")
    print(f"  {stats['added']:,} {'would be stamped' if args.dry_run else 'stamped'}")

    if stats["collisions"]:
        print(f"\n  WARNING: {len(stats['collisions'])} ID collision(s) detected:")
        for eid, existing, new, word in stats["collisions"][:5]:
            print(f"    id={eid}  word={word}")
            print(f"      existing: {existing[0][:60]!r}")
            print(f"      new:      {new[0][:60]!r}")
    else:
        print("  No collisions.")

    if not args.dry_run and stats["added"] > 0:
        print(f"\nDone. {path.name} updated.")
    elif args.dry_run:
        print("\n(dry-run: nothing written)")


if __name__ == "__main__":
    main()
