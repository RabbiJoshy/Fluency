#!/usr/bin/env python3
"""Remove inert and disproven records from the shared elision curation file.

The active normalizer consumes only ``merge`` records of type
``elision_pair`` or ``elided_only``.  Historical ``same_word_dup`` and
``skip`` rows never affected output, yet made the file look like thousands of
live manual overrides.  This tool makes the consumer contract explicit and
also removes a small reviewed set of generated targets that restore the wrong
letter; those forms are subsequently handled by the conservative frequency
gate in :mod:`step_3a_merge_elisions`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = PROJECT_ROOT / "Artists" / "curations" / "elision_mapping.json"

DISPROVEN_GENERATED_TARGETS = {
    "actitu'", "ajedre'", "azúca'", "confia'", "cru'", "feli'",
    "felicida'", "gonzále'", "mai'", "mayagüe'", "oportunida'",
    "rodrígue'", "uste'",
}


def compact(records):
    kept = []
    removed = {"same_word_dup": 0, "skip": 0, "disproven_target": 0}
    for record in records:
        if record.get("merge_type") == "same_word_dup":
            removed["same_word_dup"] += 1
            continue
        if record.get("action") == "skip":
            removed["skip"] += 1
            continue
        surface = str(record.get("elided_word") or record.get("word") or "").casefold()
        if surface in DISPROVEN_GENERATED_TARGETS:
            removed["disproven_target"] += 1
            continue
        kept.append(record)
    return kept, removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = json.loads(args.path.read_text(encoding="utf-8"))
    kept, removed = compact(records)
    print(json.dumps({
        "before": len(records), "after": len(kept), "removed": removed,
        "mode": "apply" if args.apply else "dry-run",
    }, indent=2))
    if args.apply:
        args.path.write_text(
            json.dumps(kept, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
