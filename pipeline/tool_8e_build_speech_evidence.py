#!/usr/bin/env python3
"""Build an experimental Spanish Speech Mode evidence run.

The v0.1 architecture has three deliberately separate phases:

* ``prepare``: snapshot a SpanishDict inventory and reservoir-sample real,
  provenance-bearing bilingual corpus occurrences.
* ``classify``: assign each occurrence directly to an allowed SpanishDict
  sense ID (or abstain) with a replaceable offline classifier.
* ``summarize``: derive conservative prominence bands and a high-confidence
  example bank without changing the inventory or source records.

The tool writes only to an explicit experimental run directory. It never
changes active layers, an immutable Normal Mode run, or the shipped app.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SPANISH = ROOT / "Data" / "Spanish"
DEFAULT_MENU = SPANISH / "layers" / "sense_menu" / "spanishdict.json"
DEFAULT_CORPUS = SPANISH / "corpora" / "opensubtitles"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
SCHEMA_VERSION = 1
PROMPT_VERSION = "speech_sd_closed_v1"
OTHER = "OTHER_OR_UNCLEAR"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, relative_to: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def relative_or_absolute(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def target_id(target: dict[str, Any]) -> str:
    supplied = str(target.get("target_id") or "").strip()
    if supplied:
        return supplied
    return "|".join([
        str(target["surface"]).casefold(),
        str(target["headword"]).casefold(),
        str(target["pos"]).upper(),
    ])


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Expected config schema_version {SCHEMA_VERSION}")
    if not config.get("run_id"):
        raise ValueError("Config requires run_id")
    sample_size = config.get("sample_size_per_target")
    if not isinstance(sample_size, int) or sample_size < 1:
        raise ValueError("sample_size_per_target must be a positive integer")
    targets = config.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("Config requires a non-empty targets list")
    seen = set()
    normalized_targets = []
    for raw in targets:
        target = dict(raw)
        for field in ("surface", "headword", "pos", "forms"):
            if not target.get(field):
                raise ValueError(f"Target is missing {field}: {raw}")
        if not isinstance(target["forms"], list):
            raise ValueError(f"Target forms must be a list: {raw}")
        target["forms"] = list(dict.fromkeys(
            str(form).strip() for form in target["forms"] if str(form).strip()
        ))
        if not target["forms"]:
            raise ValueError(f"Target has no usable forms: {raw}")
        target["pos"] = str(target["pos"]).upper()
        target["target_id"] = target_id(target)
        if target["target_id"] in seen:
            raise ValueError(f"Duplicate target_id: {target['target_id']}")
        seen.add(target["target_id"])
        normalized_targets.append(target)
    return {**config, "targets": normalized_targets}


def inventory_for(config: dict[str, Any], menu: dict[str, Any]) -> dict[str, Any]:
    inventory_targets = []
    for target in config["targets"]:
        analyses = menu.get(target["surface"]) or []
        matching = [
            analysis for analysis in analyses
            if analysis.get("headword") == target["headword"]
        ]
        if not matching:
            raise ValueError(
                f"No SpanishDict analysis for {target['surface']} -> {target['headword']}"
            )
        senses: dict[str, Any] = {}
        for analysis in matching:
            for sense_id, sense in (analysis.get("senses") or {}).items():
                if str(sense.get("pos") or "").upper() != target["pos"]:
                    continue
                senses[sense_id] = {
                    "sense_id": sense_id,
                    "pos": sense.get("pos"),
                    "translation": sense.get("translation"),
                    "context": sense.get("context"),
                    "regions": sense.get("regions") or [],
                    "spanishdict_examples": [
                        {
                            "spanish": example.get("original"),
                            "english": example.get("translated"),
                        }
                        for example in (sense.get("examples") or [])
                        if example.get("original") and example.get("translated")
                    ],
                }
        if not senses:
            raise ValueError(
                f"No {target['pos']} SpanishDict senses for {target['target_id']}"
            )
        inventory_targets.append({
            "target_id": target["target_id"],
            "surface": target["surface"],
            "headword": target["headword"],
            "pos": target["pos"],
            "forms": target["forms"],
            "senses": list(senses.values()),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "inventory": "spanishdict",
        "authority": "SpanishDict sense menu and stable leaf IDs",
        "generated_at": utc_now(),
        "targets": inventory_targets,
    }


def compile_forms(inventory: dict[str, Any]) -> dict[str, re.Pattern[str]]:
    return {
        target["target_id"]: re.compile(
            r"(?<!\w)(" + "|".join(
                sorted(map(re.escape, target["forms"]), key=len, reverse=True)
            ) + r")(?!\w)",
            re.IGNORECASE,
        )
        for target in inventory["targets"]
    }


def occurrence_id(source: str, target: str, line_number: int) -> str:
    material = f"{source}|{target}|{line_number}"
    return "occ-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def source_record(source_ids: str) -> dict[str, Any]:
    fields = source_ids.split("\t")
    return {
        "alignment_ids": source_ids,
        "english_document": fields[0] if len(fields) > 0 else None,
        "spanish_document": fields[1] if len(fields) > 1 else None,
        "english_segment": fields[2] if len(fields) > 2 else None,
        "spanish_segment": fields[3] if len(fields) > 3 else None,
    }


def sample_occurrences(
    inventory: dict[str, Any], corpus_dir: Path, sample_size: int, seed: int
) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    patterns = compile_forms(inventory)
    reservoirs: dict[str, list[dict[str, Any]]] = {
        target_id: [] for target_id in patterns
    }
    seen: Counter[str] = Counter()
    rng = random.Random(seed)
    paths = {
        "spanish": corpus_dir / "OpenSubtitles.en-es.es",
        "english": corpus_dir / "OpenSubtitles.en-es.en",
        "ids": corpus_dir / "OpenSubtitles.en-es.ids",
    }
    for name, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing {name} corpus file: {path}")
    with (
        paths["spanish"].open(encoding="utf-8", errors="replace") as spanish_handle,
        paths["english"].open(encoding="utf-8", errors="replace") as english_handle,
        paths["ids"].open(encoding="utf-8", errors="replace") as ids_handle,
    ):
        lines_scanned = 0
        for lines_scanned, (spanish, english, ids) in enumerate(
            zip(spanish_handle, english_handle, ids_handle), 1
        ):
            spanish = spanish.rstrip("\n")
            english = english.rstrip("\n")
            ids = ids.rstrip("\n")
            for current_target_id, pattern in patterns.items():
                match = pattern.search(spanish)
                if not match:
                    continue
                seen[current_target_id] += 1
                record = {
                    "schema_version": SCHEMA_VERSION,
                    "occurrence_id": occurrence_id(
                        "opensubtitles-en-es", current_target_id, lines_scanned
                    ),
                    "target_id": current_target_id,
                    "matched_form": match.group(1),
                    "spanish": spanish,
                    "english": english,
                    "source": {
                        "corpus": "OpenSubtitles en-es",
                        "corpus_line": lines_scanned,
                        **source_record(ids),
                    },
                    "sampling": {
                        "method": "seeded_reservoir",
                        "seed": seed,
                        "stratum": current_target_id,
                    },
                }
                reservoir = reservoirs[current_target_id]
                if len(reservoir) < sample_size:
                    reservoir.append(record)
                else:
                    replacement = rng.randrange(seen[current_target_id])
                    if replacement < sample_size:
                        reservoir[replacement] = record
            if lines_scanned % 10_000_000 == 0:
                print(f"scanned {lines_scanned:,} aligned lines", flush=True)
    records = [record for rows in reservoirs.values() for record in rows]
    records.sort(key=lambda row: (row["target_id"], row["source"]["corpus_line"]))
    return records, dict(seen), lines_scanned


def load_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if api_key:
        return api_key
    env_path = ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError("GEMINI_API_KEY is not configured")


def classification_prompt(
    target: dict[str, Any], occurrences: list[dict[str, Any]]
) -> str:
    senses = []
    for sense in target["senses"]:
        examples = "; ".join(
            f"ES: {example['spanish']} / EN: {example['english']}"
            for example in sense["spanishdict_examples"][:2]
        ) or "none"
        senses.append(
            f"{sense['sense_id']} | {sense['pos']} | {sense['translation']} | "
            f"context={sense.get('context') or 'none'} | "
            f"regions={','.join(sense.get('regions') or []) or 'none'} | "
            f"examples={examples}"
        )
    rows = [
        f"{row['occurrence_id']} | ES: {row['spanish']} | EN: {row['english']}"
        for row in occurrences
    ]
    schema = [{
        "occurrence_id": "occ-example",
        "status": "assigned",
        "sense_ids": [target["senses"][0]["sense_id"]],
        "confidence": "high",
        "reason": "short reason",
    }]
    return "\n".join([
        f"Classify the use of Spanish {target['surface']} with headword "
        f"{target['headword']} and POS {target['pos']}.",
        "SpanishDict is the sole sense inventory. Select only listed IDs or abstain.",
        "The Spanish sentence is authoritative; English is supporting translation evidence.",
        "Use status=abstain, sense_ids=[], and confidence=low when the token is a proper name, different lemma/POS, unlisted meaning, idiom not covered by a listed context, bad alignment, or genuinely unclear.",
        "Dictionary contexts are strict boundaries. Never force the nearest gloss.",
        "Use multiple sense_ids only when the occurrence genuinely cannot distinguish translation-equivalent listed leaves; such rows will not be auto-published.",
        "Confidence must be high, medium, or low. Keep reason under 12 words.",
        "",
        "ALLOWED SPANISHDICT SENSES",
        "\n".join(senses),
        "",
        "OCCURRENCES",
        "\n".join(rows),
        "",
        "Return one JSON-array row per occurrence in this shape:",
        json.dumps(schema, ensure_ascii=False),
    ])


def call_gemini(model: str, prompt: str) -> list[dict[str, Any]]:
    from google import genai

    client = genai.Client(api_key=load_api_key())
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={"temperature": 0.0, "response_mime_type": "application/json"},
    )
    parsed = json.loads(response.text)
    if isinstance(parsed, dict) and isinstance(parsed.get("assignments"), list):
        parsed = parsed["assignments"]
    if not isinstance(parsed, list):
        raise ValueError("Classifier did not return a JSON array")
    return parsed


def normalize_decisions(
    target: dict[str, Any],
    occurrences: list[dict[str, Any]],
    raw: list[dict[str, Any]],
    model: str,
) -> list[dict[str, Any]]:
    expected = {row["occurrence_id"] for row in occurrences}
    by_id = {str(row.get("occurrence_id")): row for row in raw}
    if set(by_id) != expected:
        raise ValueError(
            f"Classifier ID mismatch; missing={sorted(expected - set(by_id))}; "
            f"extra={sorted(set(by_id) - expected)}"
        )
    allowed_ids = {sense["sense_id"] for sense in target["senses"]}
    normalized = []
    for occurrence in occurrences:
        row = by_id[occurrence["occurrence_id"]]
        status = str(row.get("status") or "").lower()
        confidence = str(row.get("confidence") or "").lower()
        sense_ids = row.get("sense_ids")
        if sense_ids is None and row.get("sense_id"):
            sense_ids = [row["sense_id"]]
        sense_ids = list(dict.fromkeys(str(value) for value in (sense_ids or [])))
        if confidence not in {"high", "medium", "low"}:
            raise ValueError(f"Invalid confidence for {occurrence['occurrence_id']}")
        if status not in {"assigned", "abstain"}:
            raise ValueError(f"Invalid status for {occurrence['occurrence_id']}: {status}")
        invalid = set(sense_ids) - allowed_ids
        if invalid:
            raise ValueError(
                f"Invalid sense IDs for {occurrence['occurrence_id']}: {sorted(invalid)}"
            )
        if status == "abstain" and sense_ids:
            raise ValueError(f"Abstention has sense IDs: {occurrence['occurrence_id']}")
        if status == "assigned" and not sense_ids:
            raise ValueError(f"Assignment has no sense IDs: {occurrence['occurrence_id']}")
        normalized.append({
            "schema_version": SCHEMA_VERSION,
            "occurrence_id": occurrence["occurrence_id"],
            "target_id": target["target_id"],
            "decision": {
                "status": status,
                "sense_ids": sense_ids,
                "confidence": confidence,
                "reason": str(row.get("reason") or "")[:240],
            },
            "classifier": {
                "method": "direct_spanishdict_closed_set_llm",
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "classified_at": utc_now(),
            },
        })
    return normalized


def batches(records: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(records), size):
        yield records[start:start + size]


def prominence_band(share_of_all: float) -> str:
    if share_of_all >= 0.50:
        return "dominant"
    if share_of_all >= 0.15:
        return "common"
    if share_of_all >= 0.03:
        return "occasional"
    return "uncommon_or_unseen"


def summarize_records(
    inventory: dict[str, Any],
    occurrences: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    assignment_by_id = {row["occurrence_id"]: row for row in assignments}
    target_by_id = {target["target_id"]: target for target in inventory["targets"]}
    occurrences_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for occurrence in occurrences:
        occurrences_by_target[occurrence["target_id"]].append(occurrence)
    example_bank = []
    target_summaries = []
    review_rows = []
    for current_target_id, target in target_by_id.items():
        rows = occurrences_by_target[current_target_id]
        counts: Counter[str] = Counter()
        accepted = 0
        ambiguous = 0
        explicit_abstentions = 0
        pending = 0
        categorized_rows = []
        for occurrence in rows:
            assignment = assignment_by_id.get(occurrence["occurrence_id"])
            category = "pending"
            if assignment is None:
                pending += 1
            else:
                decision = assignment["decision"]
                if decision["status"] == "abstain":
                    explicit_abstentions += 1
                    category = "abstain"
                elif decision["confidence"] == "high" and len(decision["sense_ids"]) == 1:
                    sense_id = decision["sense_ids"][0]
                    counts[sense_id] += 1
                    accepted += 1
                    category = "accepted"
                    example_bank.append({
                        "schema_version": SCHEMA_VERSION,
                        "example_id": occurrence["occurrence_id"],
                        "target_id": current_target_id,
                        "sense_id": sense_id,
                        "spanish": occurrence["spanish"],
                        "english": occurrence["english"],
                        "source": occurrence["source"],
                        "assignment": assignment,
                        "publication_status": "candidate_requires_human_audit",
                    })
                else:
                    ambiguous += 1
                    category = "ambiguous_or_below_gate"
            categorized_rows.append((category, occurrence, assignment))
        total = len(rows)
        coverage = accepted / total if total else 0.0
        senses = []
        for sense in target["senses"]:
            count = counts[sense["sense_id"]]
            share_all = count / total if total else 0.0
            senses.append({
                **sense,
                "accepted_random_occurrences": count,
                "share_of_all_sampled_occurrences": round(share_all, 6),
                "share_of_accepted_occurrences": round(count / accepted, 6)
                if accepted else 0.0,
                "provisional_prominence": prominence_band(share_all),
            })
        senses.sort(key=lambda row: (
            -row["accepted_random_occurrences"], row["sense_id"]
        ))
        target_summaries.append({
            "target_id": current_target_id,
            "surface": target["surface"],
            "headword": target["headword"],
            "pos": target["pos"],
            "sampled_occurrences": total,
            "accepted_unique_high": accepted,
            "accepted_coverage": round(coverage, 6),
            "explicit_abstentions": explicit_abstentions,
            "ambiguous_or_below_gate": ambiguous,
            "pending": pending,
            "prominence_status": "usable_first_pass" if coverage >= 0.70
            else "insufficient_assignment_coverage",
            "senses": senses,
        })
        for category in ("accepted", "abstain", "ambiguous_or_below_gate"):
            candidates = [row for row in categorized_rows if row[0] == category]
            candidates.sort(key=lambda row: hashlib.sha256(
                row[1]["occurrence_id"].encode("utf-8")
            ).hexdigest())
            for _, occurrence, assignment in candidates[:5]:
                review_rows.append({
                    "occurrence_id": occurrence["occurrence_id"],
                    "target_id": current_target_id,
                    "category": category,
                    "spanish": occurrence["spanish"],
                    "english": occurrence["english"],
                    "model_decision": assignment["decision"] if assignment else None,
                    "human_decision": None,
                    "human_sense_id": None,
                    "notes": "",
                })
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "method": {
            "prominence_denominator": "all random sampled surface occurrences",
            "publication_gate": "assigned + high confidence + exactly one SpanishDict ID",
            "bands": {
                "dominant": ">=50% of all sampled occurrences",
                "common": "15-49.99%",
                "occasional": "3-14.99%",
                "uncommon_or_unseen": "<3%",
            },
            "warning": "Bands are provisional and corpus-domain-specific; low assignment coverage blocks use.",
        },
        "targets": target_summaries,
    }
    example_bank.sort(key=lambda row: (
        row["target_id"], row["sense_id"], row["source"]["corpus_line"]
    ))
    review_rows.sort(key=lambda row: (row["target_id"], row["category"], row["occurrence_id"]))
    return summary, example_bank, review_rows


def artifact_manifest(run_dir: Path) -> dict[str, Any]:
    names = [
        "config.json", "inventory.json", "occurrences.jsonl", "assignments.jsonl",
        "summary.json", "example_bank.jsonl", "human_review_template.jsonl",
    ]
    return {
        name: file_record(run_dir / name, run_dir)
        for name in names if (run_dir / name).is_file()
    }


def update_manifest(run_dir: Path, **updates: Any) -> None:
    path = run_dir / "manifest.json"
    manifest = read_json(path) if path.is_file() else {}
    manifest.update(updates)
    manifest["updated_at"] = utc_now()
    manifest["artifacts"] = artifact_manifest(run_dir)
    write_json(path, manifest)


def ensure_mutable_run(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Run manifest is missing: {manifest_path}")
    manifest = read_json(manifest_path)
    if manifest.get("immutable"):
        raise RuntimeError(f"Run is immutable: {run_dir}")
    return manifest


def prepare(args: argparse.Namespace) -> None:
    if args.run_dir.exists():
        raise FileExistsError(f"Refusing to overwrite existing run: {args.run_dir}")
    config = validate_config(read_json(args.config))
    args.run_dir.mkdir(parents=True)
    try:
        config_snapshot = {
            **config,
            "sense_menu": relative_or_absolute(args.menu),
            "corpus_dir": relative_or_absolute(args.corpus_dir),
        }
        write_json(args.run_dir / "config.json", config_snapshot)
        inventory = inventory_for(config, read_json(args.menu))
        write_json(args.run_dir / "inventory.json", inventory)
        occurrences, matches, lines_scanned = sample_occurrences(
            inventory,
            args.corpus_dir,
            config["sample_size_per_target"],
            int(config.get("seed", 20260803)),
        )
        write_jsonl(args.run_dir / "occurrences.jsonl", occurrences)
        update_manifest(
            args.run_dir,
            schema_version=SCHEMA_VERSION,
            run_id=config["run_id"],
            purpose="Spanish Speech Mode evidence architecture v0.1",
            status="prepared",
            immutable=False,
            not_for_app=True,
            created_at=utc_now(),
            git_commit_at_prepare=git_commit(),
            source_inputs={
                "sense_menu": {
                    "path": relative_or_absolute(args.menu),
                    "sha256": sha256(args.menu),
                },
                "corpus": {
                    "path": relative_or_absolute(args.corpus_dir),
                    "aligned_lines_scanned": lines_scanned,
                },
            },
            matching_occurrences=matches,
            sampled_occurrences=len(occurrences),
        )
    except Exception:
        # Leave partial files for diagnosis, but make their incomplete status explicit.
        update_manifest(
            args.run_dir,
            schema_version=SCHEMA_VERSION,
            run_id=config.get("run_id"),
            status="prepare_failed",
            immutable=False,
            not_for_app=True,
        )
        raise
    print(f"prepared {args.run_dir}")


def classify(args: argparse.Namespace) -> None:
    ensure_mutable_run(args.run_dir)
    inventory = read_json(args.run_dir / "inventory.json")
    occurrences = read_jsonl(args.run_dir / "occurrences.jsonl")
    existing = read_jsonl(args.run_dir / "assignments.jsonl")
    completed = {row["occurrence_id"] for row in existing}
    target_by_id = {target["target_id"]: target for target in inventory["targets"]}
    pending_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for occurrence in occurrences:
        if occurrence["occurrence_id"] not in completed:
            pending_by_target[occurrence["target_id"]].append(occurrence)
    total_pending = sum(map(len, pending_by_target.values()))
    if not args.apply:
        print(
            f"dry run: {total_pending} pending occurrences; pass --apply to call {args.model}"
        )
        for current_target_id, rows in pending_by_target.items():
            if rows:
                preview = classification_prompt(
                    target_by_id[current_target_id], rows[:args.batch_size]
                )
                (args.run_dir / "prompt_preview.txt").write_text(preview, encoding="utf-8")
                print(f"wrote {args.run_dir / 'prompt_preview.txt'}")
                break
        return
    batches_run = 0
    for current_target_id, rows in pending_by_target.items():
        target = target_by_id[current_target_id]
        for batch in batches(rows, args.batch_size):
            raw = call_gemini(args.model, classification_prompt(target, batch))
            normalized = normalize_decisions(target, batch, raw, args.model)
            append_jsonl(args.run_dir / "assignments.jsonl", normalized)
            batches_run += 1
            print(
                f"classified {len(normalized)} occurrences for {current_target_id}",
                flush=True,
            )
            if args.max_batches and batches_run >= args.max_batches:
                break
        if args.max_batches and batches_run >= args.max_batches:
            break
    assignment_count = len(read_jsonl(args.run_dir / "assignments.jsonl"))
    update_manifest(
        args.run_dir,
        status="classified" if assignment_count == len(occurrences) else "partially_classified",
        classifier={
            "method": "direct_spanishdict_closed_set_llm",
            "model": args.model,
            "prompt_version": PROMPT_VERSION,
        },
        assignment_count=assignment_count,
        occurrence_count=len(occurrences),
    )
    print(f"assignments: {assignment_count}/{len(occurrences)}")


def summarize(args: argparse.Namespace) -> None:
    ensure_mutable_run(args.run_dir)
    inventory = read_json(args.run_dir / "inventory.json")
    occurrences = read_jsonl(args.run_dir / "occurrences.jsonl")
    assignments = read_jsonl(args.run_dir / "assignments.jsonl")
    summary, example_bank, review_rows = summarize_records(
        inventory, occurrences, assignments
    )
    write_json(args.run_dir / "summary.json", summary)
    write_jsonl(args.run_dir / "example_bank.jsonl", example_bank)
    write_jsonl(args.run_dir / "human_review_template.jsonl", review_rows)
    update_manifest(
        args.run_dir,
        status="summarized_candidate",
        immutable=False,
        not_for_app=True,
        summary_counts={
            "targets": len(summary["targets"]),
            "sampled_occurrences": len(occurrences),
            "assignments": len(assignments),
            "candidate_examples": len(example_bank),
            "human_review_rows": len(review_rows),
        },
    )
    print(f"candidate examples: {len(example_bank)}")
    print(f"wrote {args.run_dir / 'summary.json'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--config", type=Path, required=True)
    prepare_parser.add_argument("--run-dir", type=Path, required=True)
    prepare_parser.add_argument("--menu", type=Path, default=DEFAULT_MENU)
    prepare_parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    prepare_parser.set_defaults(handler=prepare)

    classify_parser = subparsers.add_parser("classify")
    classify_parser.add_argument("--run-dir", type=Path, required=True)
    classify_parser.add_argument("--model", default=DEFAULT_MODEL)
    classify_parser.add_argument("--batch-size", type=int, default=20)
    classify_parser.add_argument("--max-batches", type=int, default=0)
    classify_parser.add_argument("--apply", action="store_true")
    classify_parser.set_defaults(handler=classify)

    summarize_parser = subparsers.add_parser("summarize")
    summarize_parser.add_argument("--run-dir", type=Path, required=True)
    summarize_parser.set_defaults(handler=summarize)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
