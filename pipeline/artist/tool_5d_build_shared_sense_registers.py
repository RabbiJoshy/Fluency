#!/usr/bin/env python3
"""Build configured cross-artist sense registers and apply them to one menu."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

from util_1a_artist_config import add_artist_arg
from util_5d_shared_sense_register import (
    apply_registers_to_menu, build_configured_registers,
    exact_register_assignments,
)
from util_6a_assignment_format import (
    dump_assignments, load_assignments, stamp_example_ids,
)
from util_evidence_store import archive_json_artifact
from util_pipeline_meta import make_meta, write_sidecar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_artist_arg(parser)
    args = parser.parse_args()
    artist_dir = Path(args.artist_dir).resolve()
    language_dir = artist_dir.parent

    built = build_configured_registers(language_dir)
    for path, payload in built:
        count = sum(len(items) for items in (payload.get("senses") or {}).values())
        print("Built %s: %d words / %d senses / %d members" % (
            path, len(payload.get("senses") or {}), count,
            len(payload.get("members") or [])))

    layers = artist_dir / "data/layers"
    menu_path = layers / "sense_menu/spanishdict.json"
    inventory_path = layers / "word_inventory.json"
    menu = json.loads(menu_path.read_text(encoding="utf-8")) if menu_path.exists() else {}
    inventory = json.loads(inventory_path.read_text(encoding="utf-8")) if inventory_path.exists() else []
    words = [entry.get("word") for entry in inventory if isinstance(entry, dict) and entry.get("word")]
    merged, added = apply_registers_to_menu(artist_dir, menu, words)
    menu_path.parent.mkdir(parents=True, exist_ok=True)
    menu_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    register_names = json.loads(
        (artist_dir / "artist.json").read_text(encoding="utf-8")
    ).get("sense_registers") or []
    write_sidecar(menu_path, make_meta(
        "apply_shared_sense_registers", 1,
        extra={"source": "spanishdict", "sense_registers": register_names},
    ))
    archive_json_artifact(
        layers.parent / "evidence", "sense_menu/spanishdict", merged,
        language=language_dir.name,
        adapter={"name": "shared-sense-registers", "version": 1},
        config={"source": "spanishdict", "sense_registers": register_names},
    )
    print("Applied %d shared-register senses to %s" % (added, menu_path))

    assignments_path = layers / "sense_assignments/spanishdict.json"
    existing_assignments = (load_assignments(assignments_path)
                            if assignments_path.exists() else {})
    for word_data in existing_assignments.values():
        if isinstance(word_data, dict):
            word_data.pop("shared-register-auto", None)
    exact = exact_register_assignments(artist_dir)
    for word, methods in exact.items():
        existing_assignments.setdefault(word, {}).update(methods)
    examples_path = layers / "examples_raw.json"
    examples_raw = (json.loads(examples_path.read_text(encoding="utf-8"))
                    if examples_path.exists() else {})
    stamp_example_ids(existing_assignments, examples_raw)
    assignments_path.parent.mkdir(parents=True, exist_ok=True)
    dump_assignments(existing_assignments, assignments_path)
    exact_count = sum(len(item.get("examples") or [])
                      for methods in exact.values()
                      for item in methods.get("shared-register-auto", []))
    print("Reused %d exact cross-artist example(s) across %d word(s)" % (
        exact_count, len(exact)))


if __name__ == "__main__":
    main()
