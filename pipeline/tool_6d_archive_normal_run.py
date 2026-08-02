#!/usr/bin/env python3
"""Freeze the active Normal Mode sense layers as an immutable run.

The normal pipeline keeps its active inputs under ``Data/<Language>/layers``.
Those paths are convenient for builders but are not a history mechanism.  This
tool copies the sense menu and both assignment layers into a named run, records
their hashes, and refuses to overwrite an existing run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def file_record(path: Path, relative_to: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def copy_required(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Required checkpoint file is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def evidence_coverage(assignments_path: Path, published_examples_path: Path) -> dict[str, Any]:
    assignments = load_json(assignments_path)
    assignment_ids = {
        example_id
        for methods in assignments.values()
        for rows in methods.values()
        for row in rows
        for example_id in row.get("example_ids", [])
    }

    published_ids: set[str] = set()
    if published_examples_path.is_file():
        published = load_json(published_examples_path)
        published_ids = {
            example["id"]
            for card in published.values()
            for meaning in card.get("m", [])
            for example in meaning
            if example.get("id")
        }

    retained = assignment_ids & published_ids
    return {
        "assignment_example_ids": len(assignment_ids),
        "retained_in_published_deck": len(retained),
        "missing_from_published_deck": len(assignment_ids - published_ids),
        "retained_percentage": round(100 * len(retained) / len(assignment_ids), 2)
        if assignment_ids
        else 100.0,
    }


def build_distributions(assignments_path: Path) -> dict[str, Any]:
    assignments = load_json(assignments_path)
    output: dict[str, Any] = {}
    for word, methods in assignments.items():
        output[word] = {}
        for method, rows in methods.items():
            counts = []
            total = 0
            for row in rows:
                count = len(row.get("example_ids") or row.get("examples") or [])
                total += count
                counts.append((row.get("sense"), count))
            output[word][method] = {
                "total": total,
                "senses": [
                    {
                        "sense": sense,
                        "count": count,
                        "share": round(count / total, 6) if total else 0.0,
                    }
                    for sense, count in counts
                ],
            }
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", default="Spanish")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--purpose", required=True)
    parser.add_argument("--status", default="frozen", choices=("frozen", "candidate"))
    parser.add_argument(
        "--evidence-note",
        default="The original examples_raw.json was not available when this run was archived.",
    )
    args = parser.parse_args()

    language_root = PROJECT_ROOT / "Data" / args.language
    layers = language_root / "layers"
    run_root = language_root / "runs" / "normal_mode" / args.run_id
    if run_root.exists():
        raise FileExistsError(f"Run already exists; refusing to overwrite: {run_root}")

    archive_map = {
        layers / "sense_menu" / "spanishdict.json": run_root / "sense_menu" / "spanishdict.json",
        layers / "sense_menu" / "spanishdict.json.meta.json": run_root / "sense_menu" / "spanishdict.json.meta.json",
        layers / "sense_assignments" / "spanishdict.json": run_root / "assignments" / "surface_spanishdict.json",
        layers / "sense_assignments" / "spanishdict.json.meta.json": run_root / "assignments" / "surface_spanishdict.json.meta.json",
        layers / "sense_assignments_lemma" / "spanishdict.json": run_root / "assignments" / "lemma_spanishdict.json",
        layers / "sense_assignments_lemma" / "spanishdict.json.meta.json": run_root / "assignments" / "lemma_spanishdict.json.meta.json",
    }
    for source, destination in archive_map.items():
        copy_required(source, destination)

    distribution_path = run_root / "distributions" / "spanishdict.json"
    distribution_path.parent.mkdir(parents=True, exist_ok=True)
    distribution_path.write_text(
        json.dumps(
            build_distributions(layers / "sense_assignments" / "spanishdict.json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    published_examples = language_root / "vocabulary.examples.json"
    cache_snapshot = language_root / "Senses" / "spanishdict_cache_snapshot.tar.gz"
    cache_manifest = cache_snapshot.with_suffix(cache_snapshot.suffix + ".manifest.json")
    references = {}
    for name, path in {
        "published_examples": published_examples,
        "spanishdict_cache_snapshot": cache_snapshot,
        "spanishdict_cache_manifest": cache_manifest,
    }.items():
        if path.is_file():
            record = file_record(path, PROJECT_ROOT)
            record["repository_path"] = record.pop("path")
            references[name] = record

    manifest = {
        "schema_version": 1,
        "run_id": args.run_id,
        "mode": "normal",
        "language": args.language,
        "status": args.status,
        "purpose": args.purpose,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "git_commit_at_archive": git_commit(),
        "immutable": True,
        "artifacts": {
            destination.relative_to(run_root).as_posix(): file_record(destination, run_root)
            for destination in archive_map.values()
        }
        | {
            distribution_path.relative_to(run_root).as_posix(): file_record(
                distribution_path, run_root
            )
        },
        "external_references": references,
        "evidence_recovery": {
            **evidence_coverage(
                layers / "sense_assignments" / "spanishdict.json", published_examples
            ),
            "note": args.evidence_note,
        },
        "provenance_notes": [
            "Assignment rows retain their original method, prompt_id, and run_ts fields.",
            "The distribution file is derived deterministically from archived surface assignments.",
            "Generated or personalised examples must never contribute to these distributions.",
        ],
    }
    (run_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Archived {args.run_id} at {run_root.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
