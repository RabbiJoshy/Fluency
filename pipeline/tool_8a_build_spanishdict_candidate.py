#!/usr/bin/env python3
"""Build a reversible Spanish Normal Mode deck from SpanishDict examples.

The existing index remains the provisional sense-selection/distribution proxy.
For every displayed ``sense_id``, this tool attaches the example authored for
that exact SpanishDict leaf.  A small, separately audited template bank can add
personalised variants; those variants are selected by the app only when their
reinforcement word was recently answered incorrectly.
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

from lingua import Language, LanguageDetectorBuilder


ROOT = Path(__file__).resolve().parents[1]
SPANISH = ROOT / "Data" / "Spanish"
DEFAULT_RUN_ID = "2026-08-03_spanishdict_examples_v2"
DEFAULT_FRAME_BANK = SPANISH / "personalised_example_frames.json"
EXPERIMENT = SPANISH / "Intermediates" / "example_methodology_v2" / "automatic_frame_test"
LANGUAGE_DETECTOR = LanguageDetectorBuilder.from_languages(
    Language.SPANISH, Language.ENGLISH
).build()


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=None if compact else 2)
        handle.write("\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, relative_to: Path = ROOT) -> dict[str, Any]:
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def materialize_or_reference(source: Path, destination: Path,
                             resource_path: Path | None) -> dict[str, Any]:
    """Copy a run artifact unless an immutable prior run has identical bytes."""
    if resource_path and resource_path.is_file() and sha256(resource_path) == sha256(source):
        record = file_record(resource_path)
        record["storage"] = "reference"
        return record
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    record = file_record(destination, destination.parent.parent if destination.parent.name == "sense_menu" else destination.parent)
    record["path"] = destination.name if destination.parent.name != "sense_menu" else "sense_menu/" + destination.name
    record["storage"] = "local"
    return record


def content_id(spanish: str, english: str) -> str:
    material = f"{spanish.strip()}\n{english.strip()}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:12]


def current_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def extract_consensus_frames(output: Path) -> dict[str, Any]:
    panel_path = EXPERIMENT / "panel.json"
    proposals_path = EXPERIMENT / "iteration_2" / "proposals.jsonl"
    audit_a_path = EXPERIMENT / "iteration_3" / "audit_a.json"
    audit_b_path = EXPERIMENT / "iteration_3" / "audit_b.json"
    required = [panel_path, proposals_path, audit_a_path, audit_b_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Cannot extract audited frames; missing: " + ", ".join(missing))

    accepted = {"pass", "pass_with_soft_flags", "accept", "accept_with_soft_flags"}
    audit_a = read_json(audit_a_path)
    audit_b = read_json(audit_b_path)
    a_decisions = {
        row["variant_id"]: row["overall"] for row in audit_a["variant_audits"]
    }
    b_decisions = {
        row["variant_id"]: row["audit_overall"] for row in audit_b["decisions"]
    }
    consensus = {
        variant_id
        for variant_id, decision in a_decisions.items()
        if decision in accepted and b_decisions.get(variant_id) in accepted
    }

    panel = read_json(panel_path)
    targets = {item["panel_item_id"]: item for item in panel["items"]}
    variants = {}
    with proposals_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            proposal = record["proposal"]
            panel_id = proposal["panel_item_id"]
            frame = proposal.get("frame") or {}
            for candidate in frame.get("candidate_replacements") or []:
                variant_id = f"{panel_id}/{candidate['vocabulary_id']}"
                variants[variant_id] = (record, candidate)

    frames = []
    for variant_id in sorted(consensus):
        record, candidate = variants[variant_id]
        panel_id = record["proposal"]["panel_item_id"]
        item = targets[panel_id]
        target = item["target"]
        frames.append({
            "frame_id": variant_id,
            "target_card_id": target["vocabulary_id"],
            "target_word": target["surface_form"],
            "target_lemma": target["lemma"],
            "target_sense_id": target["sense_id"],
            "target_translation": target["translation"],
            "target_context": target.get("context"),
            "reinforcement_card_id": candidate["vocabulary_id"],
            "reinforcement_word": candidate["vocabulary_word"],
            "spanish": candidate["generated_spanish"],
            "english": candidate["generated_english"],
            "base_source_id": item["base"]["source_id"],
            "model": record.get("_meta", {}).get("model"),
            "prompt_id": record.get("_meta", {}).get("prompt_id"),
            "audit": {
                "a": a_decisions[variant_id],
                "b": b_decisions[variant_id],
                "rule": "retained only when both independent audits accepted the variant",
            },
        })

    payload = {
        "schema_version": 1,
        "status": "beta_consensus_only",
        "purpose": "Offline personalised examples for recently incorrect Spanish words.",
        "selection_rule": "Both Iteration 3 independent audits accepted every included variant.",
        "excluded_note": "Gate-only approvals and every disputed/rejected variant are excluded.",
        "source_hashes": {
            path.relative_to(ROOT).as_posix(): sha256(path) for path in required
        },
        "frames": frames,
    }
    write_json(output, payload)
    return payload


def index_menu_senses(menu_entry: Any) -> dict[str, dict[str, Any]]:
    indexed = {}
    analyses = menu_entry if isinstance(menu_entry, list) else []
    for analysis in analyses:
        for sense_id, sense in (analysis.get("senses") or {}).items():
            indexed.setdefault(sense_id, sense)
    return indexed


def canonical_example_records(sense_id: str, sense: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    records = []
    repaired_directions = 0
    for example in sense.get("examples") or []:
        spanish = (example.get("original") or "").strip()
        english = (example.get("translated") or "").strip()
        if not spanish or not english:
            continue
        original_language = LANGUAGE_DETECTOR.detect_language_of(spanish)
        translated_language = LANGUAGE_DETECTOR.detect_language_of(english)
        repaired = (
            original_language == Language.ENGLISH
            and translated_language == Language.SPANISH
        )
        if repaired:
            spanish, english = english, spanish
            repaired_directions += 1
        record = {
            "id": content_id(spanish, english),
            "target": spanish,
            "english": english,
            "source": "spanishdict",
            "assignment_method": "spanishdict-canonical",
            "sense_id": sense_id,
            "dictionary_headword": sense.get("headword"),
        }
        if repaired:
            record["direction_repaired"] = True
        records.append(record)
    return records, repaired_directions


def personalised_record(frame: dict[str, Any]) -> dict[str, Any]:
    spanish = frame["spanish"]
    english = frame["english"]
    return {
        "id": content_id(spanish, english),
        "target": spanish,
        "english": english,
        "source": "personalised-template",
        "assignment_method": (
            "human-reviewed-template"
            if frame.get("validation_tier") == "deterministic_model_gate_human_review_v1"
            else "audited-template"
        ),
        "sense_id": frame["target_sense_id"],
        "personalised": True,
        "reinforcement_word": frame["reinforcement_word"],
        "reinforcement_id": frame["reinforcement_card_id"],
        "frame_id": frame["frame_id"],
    }


def build_candidate(index: list[dict[str, Any]], menu: dict[str, Any],
                    previous_examples: dict[str, Any], frame_bank: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    frames_by_target: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for frame in frame_bank.get("frames") or []:
        key = (frame["target_card_id"], frame["target_sense_id"])
        frames_by_target.setdefault(key, []).append(frame)

    output = {}
    stats = {
        "cards": len(index),
        "displayed_meanings": 0,
        "exact_sense_matches": 0,
        "meanings_with_spanishdict_examples": 0,
        "meanings_without_spanishdict_examples": 0,
        "spanishdict_examples": 0,
        "direction_repaired_examples": 0,
        "personalised_frames": 0,
        "preserved_nonmeaning_buckets": 0,
    }
    for entry in index:
        card_id = entry["id"]
        senses = index_menu_senses(menu.get(str(entry.get("word", "")).lower()))
        meaning_buckets = []
        for meaning in entry.get("meanings") or []:
            stats["displayed_meanings"] += 1
            sense_id = meaning.get("sense_id") or meaning.get("id")
            sense = senses.get(sense_id)
            if sense:
                examples, repaired = canonical_example_records(sense_id, sense)
                stats["direction_repaired_examples"] += repaired
            else:
                examples = []
            if sense:
                stats["exact_sense_matches"] += 1
            if examples:
                stats["meanings_with_spanishdict_examples"] += 1
                stats["spanishdict_examples"] += len(examples)
            else:
                stats["meanings_without_spanishdict_examples"] += 1
            for frame in frames_by_target.get((card_id, sense_id), []):
                examples.append(personalised_record(frame))
                stats["personalised_frames"] += 1
            meaning_buckets.append(examples)

        prior = previous_examples.get(card_id) or {}
        card_output = {key: value for key, value in prior.items() if key != "m"}
        stats["preserved_nonmeaning_buckets"] += len(card_output)
        if any(meaning_buckets):
            card_output["m"] = meaning_buckets
        if card_output:
            output[card_id] = card_output
    return output, stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--frame-bank", type=Path, default=DEFAULT_FRAME_BANK)
    parser.add_argument("--extract-audited-frames", action="store_true")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument(
        "--resource-run",
        help="Prior immutable run whose byte-identical menu/frame assets may be referenced",
    )
    args = parser.parse_args()

    if args.extract_audited_frames:
        frame_bank = extract_consensus_frames(args.frame_bank)
        print(f"Extracted {len(frame_bank['frames'])} consensus frames -> {args.frame_bank}")
    else:
        frame_bank = read_json(args.frame_bank)

    run_root = SPANISH / "runs" / "normal_mode" / args.run_id
    if run_root.exists():
        raise FileExistsError(f"Candidate run already exists; refusing to overwrite: {run_root}")

    index_path = SPANISH / "vocabulary.index.json"
    examples_path = SPANISH / "vocabulary.examples.json"
    menu_path = SPANISH / "layers" / "sense_menu" / "spanishdict.json"
    legacy_manifest_path = (
        SPANISH / "runs" / "normal_mode" / "2026-05-02_legacy_gemini" / "manifest.json"
    )
    for path in (index_path, examples_path, menu_path, legacy_manifest_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    index = read_json(index_path)
    previous_examples = read_json(examples_path)
    menu = read_json(menu_path)
    candidate, stats = build_candidate(index, menu, previous_examples, frame_bank)

    run_index = run_root / "vocabulary.index.json"
    run_examples = run_root / "vocabulary.examples.json"
    run_menu = run_root / "sense_menu" / "spanishdict.json"
    run_frames = run_root / "personalised_example_frames.json"
    run_root.mkdir(parents=True)
    shutil.copy2(index_path, run_index)
    write_json(run_examples, candidate, compact=True)

    resource_root = (
        SPANISH / "runs" / "normal_mode" / args.resource_run
        if args.resource_run else None
    )
    menu_record = materialize_or_reference(
        menu_path,
        run_menu,
        resource_root / "sense_menu" / "spanishdict.json" if resource_root else None,
    )
    frames_record = materialize_or_reference(
        args.frame_bank,
        run_frames,
        resource_root / "personalised_example_frames.json" if resource_root else None,
    )

    manifest = {
        "schema_version": 1,
        "run_id": args.run_id,
        "mode": "normal",
        "language": "Spanish",
        "status": "candidate" if not args.activate else "active_candidate",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit_at_build": current_commit(),
        "method": {
            "sense_selection": "Existing displayed SpanishDict sense IDs",
            "sense_distribution": "Inherited provisional frequencies from 2026-05-02_legacy_gemini",
            "examples": "Exact SpanishDict examples attached to each displayed sense ID",
            "personalisation": "Reviewed offline templates selected by recent learner mistakes",
        },
        "parent_run": "2026-05-02_legacy_gemini",
        "parent_manifest_sha256": sha256(legacy_manifest_path),
        "artifacts": {
            "vocabulary.index.json": {
                **file_record(run_index, run_root), "storage": "local"},
            "vocabulary.examples.json": {
                **file_record(run_examples, run_root), "storage": "local"},
            "sense_menu/spanishdict.json": menu_record,
            "personalised_example_frames.json": frames_record,
        },
        "metrics": stats,
        "invariants": [
            "Every canonical example is attached through its exact SpanishDict sense ID.",
            "Generated examples do not contribute to sense distributions.",
            "The original templates require both Iteration 3 audits; scale-pilot templates also require deterministic checks, a high-confidence semantic gate, and explicit human acceptance.",
            "The app makes no live model call while studying.",
        ],
    }
    write_json(run_root / "manifest.json", manifest)

    if args.activate:
        shutil.copy2(run_examples, examples_path)
        write_json(
            examples_path.with_suffix(examples_path.suffix + ".meta.json"),
            {
                "step_name": "build_spanishdict_example_candidate",
                "step_version": 1,
                "run_id": args.run_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        write_json(
            SPANISH / "active_normal_run.json",
            {
                "schema_version": 1,
                "run_id": args.run_id,
                "role": "active_candidate",
                "parent_run": "2026-05-02_legacy_gemini",
                "note": "SpanishDict exact-sense examples plus reviewed offline personalisation, with provisional legacy sense weights.",
            },
        )
        print(f"Activated {args.run_id} -> Data/Spanish/vocabulary.examples.json")

    print(json.dumps(stats, indent=2))
    print(f"Candidate run: {run_root.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
