#!/usr/bin/env python3
"""Materialise human global/context usage-tag curations as immutable claims."""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.artist.tool_6d_migrate_legacy_usage_tags import (  # noqa: E402
    STANDARD_TAGS,
    _file_sha256,
    _write_manifest,
)
from pipeline.artist.util_1a_artist_config import load_artist_config  # noqa: E402
from pipeline.artist.util_2a_corpus_ledger import language_tag  # noqa: E402
from pipeline.artist.util_2b_evidence_view import (  # noqa: E402
    USAGE_TAG_OVERRIDE_LAYER,
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
METHOD_ID = "human-usage-tag-curation-v1"
DEFAULT_CURATIONS = PROJECT_ROOT / "Artists" / "curations" / "usage_tag_overrides.json"


def _validated_operations(entry, scope, override_index):
    action = str(entry.get("action") or "")
    if action not in ("add", "remove"):
        raise ValueError("%s override %d requires action=add|remove" % (
            scope, override_index))
    tags = [str(tag) for tag in entry.get("tags") or []]
    unknown = sorted(set(tags) - set(STANDARD_TAGS))
    if unknown:
        raise ValueError("Unknown standardized usage tags: %s" % unknown)
    if not tags:
        raise ValueError("%s override %d has no tags" % (scope, override_index))
    if not entry.get("reason") or not entry.get("reviewed_by"):
        raise ValueError("Curated overrides require reason and reviewed_by")
    override_id = entry.get("override_id") or stable_id(
        "cur", "usage-tag-override-v1", scope, override_index, entry)
    return [{
        "action": action,
        "tag": tag,
        "scope": scope,
        "override_id": override_id,
        "reason": entry["reason"],
        "reviewed_by": entry["reviewed_by"],
    } for tag in tags]


def collect_override_operations(curations, active, artist_name, language):
    occurrence_by_id = {row["occurrence_id"]: row for row in active["occurrences"]
                        if row.get("state") == "present"}
    candidates = defaultdict(set)
    for occurrence_id, occurrence in occurrence_by_id.items():
        candidates[occurrence_id].add(
            identity_normalize_text(occurrence.get("surface")))
    for (layer, kind, occurrence_id), claim in active["claims"].items():
        if layer == "normalization" and kind == "occurrence":
            for unit in ((claim.get("value") or {}).get("analysis_units") or []):
                candidates[occurrence_id].add(
                    identity_normalize_text(unit.get("normalized_form")))

    operations = defaultdict(list)
    matched_overrides = set()
    for index, entry in enumerate(curations.get("global") or []):
        entry_language = str(entry.get("language") or "").lower()
        if entry_language and entry_language not in (language, "spanish" if language == "es" else language):
            continue
        target = identity_normalize_text(
            entry.get("normalized_form") or entry.get("surface"))
        if not target:
            raise ValueError("global override %d requires surface or normalized_form" % index)
        for occurrence_id, forms in candidates.items():
            if target in forms:
                operations[occurrence_id].extend(
                    _validated_operations(entry, "global", index))
                matched_overrides.add(("global", index))

    for index, entry in enumerate(curations.get("occurrences") or []):
        entry_artist = str(entry.get("artist") or "")
        if entry_artist and entry_artist.casefold() != artist_name.casefold():
            continue
        occurrence_id = str(entry.get("occurrence_id") or "")
        if occurrence_id not in occurrence_by_id:
            raise ValueError("Curated occurrence is absent from active ledger: %s" % occurrence_id)
        revision = entry.get("segment_revision_id")
        if revision and revision != occurrence_by_id[occurrence_id].get("segment_revision_id"):
            raise ValueError("Curated occurrence revision is stale: %s" % occurrence_id)
        operations[occurrence_id].extend(
            _validated_operations(entry, "occurrence", index))
        matched_overrides.add(("occurrence", index))
    return operations, matched_overrides


def apply_artist_curations(artist_dir, curations_path=DEFAULT_CURATIONS):
    artist_dir = Path(artist_dir)
    curations_path = Path(curations_path)
    config = load_artist_config(str(artist_dir))
    artist_name = config.get("name") or artist_dir.name
    language = language_tag(config.get("language") or "und")
    with open(curations_path, encoding="utf-8") as handle:
        curations = json.load(handle)
    if curations.get("schema") != "fluency.usage-tag-curations/v1":
        raise ValueError("Unsupported usage-tag curation schema")
    evidence_dir = artist_dir / "data" / "evidence"
    active = load_active_evidence(evidence_dir)
    operations, matched = collect_override_operations(
        curations, active, artist_name, language)
    curation_hash = _file_sha256(curations_path)
    input_projection = {
        "ledger_run": active["ledger_run"],
        "curation_sha256": curation_hash,
        "artist": artist_name,
        "step_version": STEP_VERSION,
    }
    run_id = stable_id(
        "run", METHOD_ID, language, input_projection,
        semantic_fingerprint(operations))
    occurrence_by_id = {row["occurrence_id"]: row for row in active["occurrences"]}
    claims = []
    for occurrence_id in sorted(operations):
        occurrence = occurrence_by_id[occurrence_id]
        claims.append(make_claim(
            USAGE_TAG_OVERRIDE_LAYER, "occurrence", occurrence_id, "assert",
            {"operations": operations[occurrence_id], "human_curated": True},
            {"method_id": METHOD_ID, "run_id": run_id},
            {**input_projection, "operations": operations[occurrence_id],
             "segment_revision": occurrence.get("segment_revision_id")},
            confidence=1.0,
            input_refs=[{"id": occurrence["segment_id"],
                         "revision": occurrence.get("segment_revision_id")}],
        ))
    overlay_path = evidence_dir / "overlays" / USAGE_TAG_OVERRIDE_LAYER / (run_id + ".jsonl")
    artifact = write_jsonl_atomic(overlay_path, claims)
    manifest = build_run_manifest(
        run_id, USAGE_TAG_OVERRIDE_LAYER, language,
        {"name": METHOD_ID, "version": STEP_VERSION}, input_projection,
        {"standard_tags": list(STANDARD_TAGS), "precedence": ["global", "occurrence"]},
        {"claims.jsonl": artifact},
        {claim["subject"]["id"]: claim["input_fingerprint"] for claim in claims})
    _write_manifest(overlay_path.with_suffix(".manifest.json"), manifest)
    profile = active["profile"]
    profile.setdefault("claim_runs", {}).setdefault(
        USAGE_TAG_OVERRIDE_LAYER, {})[METHOD_ID] = run_id
    profile.setdefault("runs", {})[USAGE_TAG_OVERRIDE_LAYER] = run_id
    profile.setdefault("method_priorities", {})[METHOD_ID] = 100
    write_profile(evidence_dir, profile)
    return {
        "artist": artist_name,
        "run_id": run_id,
        "claims": len(claims),
        "matched_overrides": len(matched),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Apply human global/context usage-tag curations")
    parser.add_argument("--artist-dir", required=True)
    parser.add_argument("--curations", default=str(DEFAULT_CURATIONS))
    args = parser.parse_args()
    summary = apply_artist_curations(args.artist_dir, args.curations)
    print("%(artist)s: %(claims)d curated occurrence claims in %(run_id)s" % summary)
    print("  matched curation entries: %(matched_overrides)d" % summary)


if __name__ == "__main__":
    main()
