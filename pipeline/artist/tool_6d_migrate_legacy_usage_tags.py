#!/usr/bin/env python3
"""Migrate non-WSD side judgments from legacy Gemini assignments.

Older sense-assignment prompts also returned ``type``, ``construction``, ``pos``
and ``pos_verdict`` fields.  They are useful evidence, but they are not sense
assignments and must not remain coupled to whichever WSD run happens to win.

This one-time/re-runnable adapter records them as occurrence-scoped immutable
``usage_tag`` claims.  It never edits the legacy assignment file and never
promotes model output into human-curated overrides.
"""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.artist.util_1a_artist_config import load_artist_config  # noqa: E402
from pipeline.artist.util_2a_corpus_ledger import language_tag  # noqa: E402
from pipeline.artist.util_2b_evidence_view import (  # noqa: E402
    USAGE_TAG_LAYER,
    load_active_evidence,
    write_profile,
)
from pipeline.util_evidence_store import (  # noqa: E402
    build_run_manifest,
    identity_normalize_text,
    make_claim,
    semantic_fingerprint,
    stable_id,
    write_jsonl_atomic,
)


STEP_VERSION = 1
METHOD_ID = "legacy-gemini-usage-tags-v1"
STANDARD_TAGS = (
    "slang", "regional", "figurative", "vulgar", "idiom", "loanword",
    "proper_noun", "interjection", "onomatopoeia",
)
TAG_ALIASES = {
    "slang": "slang",
    "regional": "regional",
    "figurative": "figurative",
    "vulgar": "vulgar",
    "idiom": "idiom",
    "idiomatic": "idiom",
    "loanword": "loanword",
    "proper_noun": "proper_noun",
    "proper noun": "proper_noun",
    "intj": "interjection",
    "interjection": "interjection",
    "onomatopoeia": "onomatopoeia",
}


def _load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(path, manifest):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.is_file():
        with open(path, encoding="utf-8") as handle:
            if json.load(handle) != manifest:
                raise ValueError("Immutable migration manifest differs: %s" % path)
        return
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(payload)
    os.replace(str(temp), str(path))


def iter_tagged_assignment_records(assignments):
    """Yield tagged records with their legacy word and classifier bucket."""
    for word, methods in (assignments or {}).items():
        if not isinstance(methods, dict):
            continue
        for assignment_method, records in methods.items():
            if not isinstance(records, list):
                continue
            for record_index, record in enumerate(records):
                if not isinstance(record, dict):
                    continue
                if not any(record.get(field) not in (None, "", [])
                           for field in ("type", "construction", "pos", "pos_verdict")):
                    continue
                yield str(word), str(assignment_method), record_index, record


def canonical_tag(raw_type):
    value = identity_normalize_text(raw_type).replace("-", "_")
    return TAG_ALIASES.get(value)


def load_elision_aliases(path):
    """Return historical elided form -> canonical word/lemma lookup."""
    aliases = defaultdict(set)
    if not Path(path).is_file():
        return aliases
    for record in _load_json(path):
        source = record.get("elided_word") or record.get("word")
        if not source:
            continue
        source = identity_normalize_text(source)
        forms = {source, source.rstrip("'")}
        for field in ("target_word", "full_word", "target_lemma"):
            value = identity_normalize_text(record.get(field))
            if value:
                forms.add(value)
        # Historical tokenizers disagreed about retaining a final apostrophe,
        # and successive normalization stages could record either an
        # intermediate or final form. Treat one curation row as an undirected
        # alias family, but use it only inside an already matched exact line.
        forms.discard("")
        for form in forms:
            aliases[form].update(forms - {form})
    return aliases


def _normalization_candidates(active, elision_aliases=None):
    elision_aliases = elision_aliases or {}
    candidates = defaultdict(set)
    for occurrence in active["occurrences"]:
        occurrence_id = occurrence["occurrence_id"]
        candidates[occurrence_id].add(
            identity_normalize_text(occurrence.get("surface")))
    for (layer, subject_kind, subject_id), claim in active["claims"].items():
        if layer != "normalization" or subject_kind != "occurrence":
            continue
        for unit in ((claim.get("value") or {}).get("analysis_units") or []):
            candidates[subject_id].add(identity_normalize_text(
                unit.get("normalized_form")))
    for occurrence_id, values in list(candidates.items()):
        expanded = set(values)
        for value in values:
            expanded.update(elision_aliases.get(value, ()))
        candidates[occurrence_id] = expanded
    return candidates


def _example_target_occurrences(example_id, word, legacy_examples,
                                occurrence_by_id, occurrence_ids_by_segment,
                                candidates):
    """Resolve one legacy example to occurrences of its target word."""
    mapped = legacy_examples.get(str(example_id)) or {}
    segment_id = mapped.get("segment_id")
    if str(example_id).startswith("seg_"):
        segment_id = str(example_id)
    possible = list(mapped.get("occurrence_ids") or [])
    if not possible and segment_id:
        possible = occurrence_ids_by_segment.get(segment_id, [])
    target = identity_normalize_text(word)

    def matches(candidate):
        if target == candidate:
            return True
        # Common lyric spelling drops a final plural ``s`` or infinitive ``r``
        # and leaves an apostrophe. Restrict this fallback to the exact legacy
        # line and one-character restoration; it is evidence reconciliation,
        # not a general lemmatiser.
        return bool(
            target.endswith(("s", "r"))
            and (candidate.rstrip("'") == target[:-1])
        )

    return [
        occurrence_id for occurrence_id in possible
        if occurrence_id in occurrence_by_id
        and any(matches(candidate) for candidate in candidates[occurrence_id])
    ]


def collect_occurrence_assertions(assignments, active, legacy_map,
                                  elision_aliases=None):
    """Return occurrence assertions plus a loss/accounting report."""
    occurrence_by_id = {
        row["occurrence_id"]: row for row in active["occurrences"]
        if row.get("state") == "present"
    }
    occurrence_ids_by_segment = defaultdict(list)
    for occurrence in occurrence_by_id.values():
        occurrence_ids_by_segment[occurrence.get("segment_id")].append(
            occurrence["occurrence_id"])
    candidates = _normalization_candidates(active, elision_aliases)
    legacy_examples = (legacy_map or {}).get("examples") or {}
    assertions = defaultdict(list)
    report = Counter()
    unresolved = []

    for word, assignment_method, record_index, record in (
            iter_tagged_assignment_records(assignments)):
        report["source_records"] += 1
        raw_type = str(record.get("type") or "").strip()
        tag = canonical_tag(raw_type)
        if raw_type:
            report["raw_type_records"] += 1
            report["standardized_tag_records" if tag else "unstandardized_type_records"] += 1

        example_ids = [str(value) for value in (record.get("example_ids") or [])]
        explicit_by_example = defaultdict(list)
        for reference in record.get("occurrence_refs") or []:
            occurrence_id = str(reference.get("occurrence_id") or "")
            if occurrence_id in occurrence_by_id:
                explicit_by_example[str(reference.get("example_id") or "")].append(
                    occurrence_id)
        if not example_ids and record.get("occurrence_ids"):
            example_ids = [""]
            explicit_by_example[""] = [
                str(value) for value in record.get("occurrence_ids") or []
                if str(value) in occurrence_by_id
            ]

        resolved_for_record = set()
        resolution_methods = set()
        matched_examples = defaultdict(list)
        for example_id in example_ids:
            occurrence_ids = explicit_by_example.get(example_id, [])
            resolution = "exact_occurrence_ref"
            if not occurrence_ids:
                occurrence_ids = _example_target_occurrences(
                    example_id, word, legacy_examples, occurrence_by_id,
                    occurrence_ids_by_segment, candidates)
                resolution = "legacy_line_target_match"
            for occurrence_id in occurrence_ids:
                resolved_for_record.add(occurrence_id)
                resolution_methods.add(resolution)
                matched_examples[occurrence_id].append(example_id)

        if not resolved_for_record:
            report["unresolved_records"] += 1
            unresolved.append({
                "word": word,
                "assignment_method": assignment_method,
                "record_index": record_index,
                "example_ids": example_ids,
                "prompt_id": record.get("prompt_id"),
                "raw_type": raw_type or None,
                "construction": record.get("construction"),
            })
            continue

        report["resolved_records"] += 1
        for occurrence_id in sorted(resolved_for_record):
            assertion = {
                "word": word,
                "assignment_method": assignment_method,
                "record_index": record_index,
                "prompt_id": record.get("prompt_id") or "legacy-unknown",
                "run_ts": record.get("run_ts"),
                "raw_type": raw_type or None,
                "tag": tag,
                "construction": record.get("construction"),
                "pos": record.get("pos"),
                "pos_verdict": record.get("pos_verdict"),
                "sense_ref": record.get("sense"),
                "example_ids": sorted(set(matched_examples[occurrence_id])),
                "resolution": (
                    "exact_occurrence_ref" if occurrence_id in sum(
                        explicit_by_example.values(), [])
                    else "legacy_line_target_match"),
            }
            assertions[occurrence_id].append(assertion)
            report["occurrence_assertions"] += 1

    return assertions, {
        "source_records": report["source_records"],
        "resolved_records": report["resolved_records"],
        "unresolved_records": report["unresolved_records"],
        "raw_type_records": report["raw_type_records"],
        "standardized_tag_records": report["standardized_tag_records"],
        "unstandardized_type_records": report["unstandardized_type_records"],
        "occurrence_assertions": report["occurrence_assertions"],
        **dict(report),
        "unresolved": unresolved,
    }


def build_usage_tag_claims(assertions, active, run_id, assignment_hash):
    occurrence_by_id = {row["occurrence_id"]: row for row in active["occurrences"]}
    claims = []
    for occurrence_id in sorted(assertions):
        occurrence = occurrence_by_id[occurrence_id]
        source_assertions = sorted(assertions[occurrence_id], key=lambda row: (
            str(row.get("prompt_id") or ""), str(row.get("run_ts") or ""),
            row["word"], row["assignment_method"], row["record_index"],
        ))
        labels = sorted({row["tag"] for row in source_assertions if row.get("tag")})
        raw_types = sorted({row["raw_type"] for row in source_assertions
                            if row.get("raw_type")})
        constructions = sorted({str(row["construction"]) for row in source_assertions
                                if row.get("construction")})
        value = {
            "labels": labels,
            "raw_types": raw_types,
            "constructions": constructions,
            "source_assertions": source_assertions,
            "source_kind": "legacy_gemini_sense_prompt_side_fields",
            "historical_model_evidence": True,
        }
        segment_id = occurrence["segment_id"]
        claims.append(make_claim(
            USAGE_TAG_LAYER,
            "occurrence",
            occurrence_id,
            "assert",
            value,
            {"method_id": METHOD_ID, "run_id": run_id},
            {
                "ledger_run": active["ledger_run"],
                "segment_revision": occurrence.get("segment_revision_id"),
                "assignment_sha256": assignment_hash,
                "source_assertions": source_assertions,
                "taxonomy_version": STEP_VERSION,
            },
            confidence=(
                0.85 if all(row["resolution"] == "exact_occurrence_ref"
                            for row in source_assertions) else 0.70),
            input_refs=[{
                "id": segment_id,
                "revision": occurrence.get("segment_revision_id"),
            }],
        ))
    return claims


def migrate_artist(artist_dir, assignments_path=None):
    artist_dir = Path(artist_dir)
    config = load_artist_config(str(artist_dir))
    language = language_tag(config.get("language") or "und")
    evidence_dir = artist_dir / "data" / "evidence"
    active = load_active_evidence(evidence_dir)
    assignments_path = Path(assignments_path or (
        artist_dir / "data" / "layers" / "sense_assignments" / "spanishdict.json"))
    legacy_map_path = evidence_dir / "migrations" / "legacy_example_ids.json"
    if not assignments_path.is_file():
        raise FileNotFoundError("No legacy assignments at %s" % assignments_path)
    if not legacy_map_path.is_file():
        raise FileNotFoundError("No legacy example map at %s" % legacy_map_path)

    assignment_hash = _file_sha256(assignments_path)
    legacy_map_hash = _file_sha256(legacy_map_path)
    assignments = _load_json(assignments_path)
    legacy_map = _load_json(legacy_map_path)
    elision_path = PROJECT_ROOT / "Artists" / "curations" / "elision_mapping.json"
    elision_aliases = load_elision_aliases(elision_path)
    assertions, report = collect_occurrence_assertions(
        assignments, active, legacy_map, elision_aliases=elision_aliases)
    input_projection = {
        "ledger_run": active["ledger_run"],
        "assignment_sha256": assignment_hash,
        "legacy_example_map_sha256": legacy_map_hash,
        "elision_mapping_sha256": (
            _file_sha256(elision_path) if elision_path.is_file() else None),
        "step_version": STEP_VERSION,
        "taxonomy": list(STANDARD_TAGS),
    }
    run_id = stable_id(
        "run", METHOD_ID, language, input_projection,
        semantic_fingerprint(assertions))
    claims = build_usage_tag_claims(
        assertions, active, run_id, assignment_hash)
    overlay_path = evidence_dir / "overlays" / USAGE_TAG_LAYER / (run_id + ".jsonl")
    artifact = write_jsonl_atomic(overlay_path, claims)
    manifest = build_run_manifest(
        run_id,
        USAGE_TAG_LAYER,
        language,
        {"name": METHOD_ID, "version": STEP_VERSION},
        input_projection,
        {"standard_tags": list(STANDARD_TAGS), "other_policy": "retain_raw_only"},
        {"claims.jsonl": artifact},
        {claim["subject"]["id"]: claim["input_fingerprint"] for claim in claims},
    )
    _write_manifest(overlay_path.with_suffix(".manifest.json"), manifest)

    profile = active["profile"]
    profile.setdefault("claim_runs", {}).setdefault(
        USAGE_TAG_LAYER, {})[METHOD_ID] = run_id
    profile.setdefault("runs", {})[USAGE_TAG_LAYER] = run_id
    profile.setdefault("method_priorities", {}).setdefault(METHOD_ID, 5)
    write_profile(evidence_dir, profile)

    label_counts = Counter(
        label for claim in claims for label in claim["value"]["labels"])
    summary = {
        "artist": config.get("name") or artist_dir.name,
        "run_id": run_id,
        "claims": len(claims),
        "labels": dict(sorted(label_counts.items())),
        **{key: value for key, value in report.items() if key != "unresolved"},
        "unresolved": report.get("unresolved") or [],
    }
    report_path = artist_dir / "data" / "reports" / "legacy_usage_tag_migration.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temp = report_path.with_suffix(report_path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(str(temp), str(report_path))
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Migrate legacy Gemini side tags into occurrence evidence")
    parser.add_argument("--artist-dir", required=True)
    parser.add_argument("--assignments", default=None)
    args = parser.parse_args()
    summary = migrate_artist(args.artist_dir, assignments_path=args.assignments)
    print("%(artist)s: %(claims)d occurrence claims in %(run_id)s" % summary)
    print("  source records: %(source_records)d total; %(resolved_records)d resolved, "
          "%(unresolved_records)d unresolved"
          % summary)
    print("  labels: %s" % summary["labels"])


if __name__ == "__main__":
    main()
