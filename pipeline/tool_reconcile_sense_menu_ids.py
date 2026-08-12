#!/usr/bin/env python3
"""Reattach stable sense IDs from a reference menu by exact sense content."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

from util_5c_sense_menu_format import carry_sense_ids_by_content  # noqa: E402
from util_evidence_store import archive_json_artifact  # noqa: E402
from util_pipeline_meta import make_meta, write_sidecar  # noqa: E402


def load(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def digest(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def id_payload(menu, word):
    return [
        {sense_id: sense for sense_id, sense in (analysis.get("senses") or {}).items()}
        for analysis in menu.get(word, [])
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--menu", type=Path, required=True)
    parser.add_argument("--reference-menu", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    menu = load(args.menu)
    reference = load(args.reference_menu)
    before_hash = digest(menu)
    changed_words = []
    for word in sorted(menu.keys() & reference.keys()):
        before = id_payload(menu, word)
        menu[word] = carry_sense_ids_by_content(menu[word], reference[word])
        if before != id_payload(menu, word):
            changed_words.append(word)

    with args.menu.open("w", encoding="utf-8") as handle:
        json.dump(menu, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    after_hash = digest(menu)
    write_sidecar(
        args.menu,
        make_meta(
            "reconcile_sense_menu_ids",
            1,
            extra={
                "reference_menu": str(args.reference_menu),
                "reference_sha256": digest(reference),
                "input_sha256": before_hash,
                "output_sha256": after_hash,
            },
        ),
    )
    if args.evidence_dir:
        archive_json_artifact(
            args.evidence_dir,
            "sense_menu/spanishdict",
            menu,
            adapter={"name": "reconcile-sense-menu-ids", "version": 1},
            inputs={"reference_menu": "sha256:" + digest(reference), "menu": "sha256:" + before_hash},
            config={"match": "exact-sense-content"},
        )
    report = {
        "schema": "fluency.sense-menu-id-reconciliation/v1",
        "menu": str(args.menu),
        "reference_menu": str(args.reference_menu),
        "changed_word_count": len(changed_words),
        "changed_words": changed_words,
        "input_sha256": before_hash,
        "output_sha256": after_hash,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"changed_word_count": len(changed_words)}, indent=2))


if __name__ == "__main__":
    main()
