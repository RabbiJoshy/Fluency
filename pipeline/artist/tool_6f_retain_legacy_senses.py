#!/usr/bin/env python3
"""Retain only defensible legacy WSD evidence.

Two deliberately narrow adapters are supported:

1. ``legacy-deterministic-single-v1``: the active menu + occurrence POS leave
   exactly one compatible stable sense.
2. ``legacy-independent-consensus-v1``: at least two independent historical
   method families selected the same still-present stable sense for the exact
   occurrence, and it remains compatible with current POS/normalization.

Source assignments are never deleted. The tool writes immutable occurrence
claims and a compatibility projection into the legacy assignment layer so the
current deck builder and the next incremental Gemini run can consume them.
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
    SENSE_RETENTION_LAYER, artifact_labels, load_active_evidence, write_profile,
)
from pipeline.util_6a_assignment_format import (  # noqa: E402
    dump_assignments, load_assignments,
)
from pipeline.util_6a_pos_menu_filter import (  # noqa: E402
    sense_compatible_with_example_pos,
)
from pipeline.util_6a_prompt_registry import capability_tier, load_registry  # noqa: E402
from pipeline.util_7a_lemma_split import merge_method_maps  # noqa: E402
from pipeline.util_evidence_store import (  # noqa: E402
    build_run_manifest, identity_normalize_text, make_claim,
    semantic_fingerprint, stable_id, write_jsonl_atomic,
)


STEP_VERSION = 1
DETERMINISTIC_METHOD = "legacy-deterministic-single-v1"
CONSENSUS_METHOD = "legacy-independent-consensus-v1"
MIN_TRUSTED_PROMPT_TIER = 20
METHOD_FAMILIES = {
    "spanishdict-flash-lite": "gemini",
    "spanishdict-flash": "gemini",
    "gemini": "gemini",
    "pos-gemini": "gemini",
    "spanishdict-biencoder": "biencoder",
    "biencoder": "biencoder",
    "pos-biencoder": "biencoder",
    "spanishdict-keyword": "keyword",
    "keyword": "keyword",
    "pos-keyword": "keyword",
}


def _load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(str(temp), str(path))


def _menu_senses(menu, word):
    result = {}
    for analysis in menu.get(word, []) or []:
        headword = analysis.get("headword") or analysis.get("lemma") or word
        senses = analysis.get("senses") or {}
        for sense_id, sense in senses.items():
            if isinstance(sense, dict):
                result[str(sense_id)] = {**sense, "headword": headword}
    return result


def _claim_refs(record):
    refs = []
    for ref in record.get("occurrence_refs") or []:
        if not isinstance(ref, dict) or not ref.get("occurrence_id"):
            continue
        refs.append({
            "occurrence_id": str(ref["occurrence_id"]),
            "example_id": ref.get("example_id"),
            "example_index": ref.get("example_index"),
        })
    return refs


def _normalization_forms(active):
    forms = defaultdict(set)
    for occurrence in active["occurrences"]:
        forms[occurrence["occurrence_id"]].add(
            identity_normalize_text(occurrence.get("surface")))
    for (layer, kind, subject_id), claim in active["claims"].items():
        if layer != "normalization" or kind != "occurrence":
            continue
        for unit in ((claim.get("value") or {}).get("analysis_units") or []):
            value = identity_normalize_text(unit.get("normalized_form"))
            if value:
                forms[subject_id].add(value)
    return forms


def build_retention(artist_dir):
    artist_dir = Path(artist_dir)
    layers = artist_dir / "data" / "layers"
    evidence_dir = artist_dir / "data" / "evidence"
    assignments_path = layers / "sense_assignments" / "spanishdict.json"
    menu_path = layers / "sense_menu" / "spanishdict.json"
    pos_path = layers / "example_pos.json"
    examples_path = layers / "examples_raw.json"
    required = (assignments_path, menu_path, pos_path, examples_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing retention input(s): %s" % ", ".join(missing))

    config = load_artist_config(str(artist_dir))
    active = load_active_evidence(evidence_dir)
    assignments = load_assignments(assignments_path)
    source_assignments = {
        word: {
            method: rows for method, rows in methods.items()
            if method not in (DETERMINISTIC_METHOD, CONSENSUS_METHOD)
        }
        for word, methods in assignments.items()
    }
    menu = _load_json(menu_path)
    example_pos = _load_json(pos_path)
    examples = _load_json(examples_path)
    registry = load_registry()
    occurrence_by_id = {
        row["occurrence_id"]: row for row in active["occurrences"]
        if row.get("state") == "present"
    }
    forms = _normalization_forms(active)
    excluded_labels = set((((active["profile"].get("policies") or {})
                            .get("vocal_artifact") or {})
                           .get("excluded_labels") or []))
    excluded_occurrences = {
        subject_id
        for (layer, kind, subject_id), claim in active["claims"].items()
        if layer == "vocal_artifact" and kind == "occurrence"
        and artifact_labels(claim) & excluded_labels
    }

    # Exact-occurrence claims. New trusted prompts make an occurrence
    # ineligible for legacy retention; they already have stronger evidence.
    old_claims = defaultdict(list)
    trusted_occurrences = set()
    for word, methods in source_assignments.items():
        current_senses = _menu_senses(menu, word)
        for method, rows in (methods or {}).items():
            family = METHOD_FAMILIES.get(method)
            for record in rows or []:
                if not isinstance(record, dict):
                    continue
                prompt_tier = capability_tier(record.get("prompt_id"), registry)
                for ref in _claim_refs(record):
                    occurrence_id = ref["occurrence_id"]
                    if prompt_tier >= MIN_TRUSTED_PROMPT_TIER:
                        trusted_occurrences.add(occurrence_id)
                    elif family and record.get("sense") in current_senses:
                        old_claims[(word, occurrence_id)].append({
                            "family": family,
                            "method": method,
                            "sense": str(record["sense"]),
                            "ref": ref,
                            "prompt_id": record.get("prompt_id") or "legacy-unknown",
                        })

    retained = []
    counts = Counter()
    for (word, occurrence_id), claims in sorted(old_claims.items()):
        if occurrence_id in trusted_occurrences:
            counts["already_trusted"] += 1
            continue
        occurrence = occurrence_by_id.get(occurrence_id)
        if not occurrence or occurrence_id in excluded_occurrences:
            counts["inactive_or_excluded"] += 1
            continue
        if identity_normalize_text(word) not in forms.get(occurrence_id, set()):
            counts["normalization_mismatch"] += 1
            continue
        ref = claims[0]["ref"]
        ex_idx = ref.get("example_index")
        if not isinstance(ex_idx, int) or ex_idx >= len(examples.get(word, [])):
            counts["missing_example"] += 1
            continue
        pos = (example_pos.get(word) or {}).get(str(ex_idx))
        current_senses = _menu_senses(menu, word)
        compatible = {
            sid for sid, sense in current_senses.items()
            if not pos or sense_compatible_with_example_pos(sense.get("pos"), pos)
        }
        if pos and not compatible:
            # A tagger/menu disagreement is ambiguous, not deterministic.
            compatible = set(current_senses)

        method = None
        sense_id = None
        source = []
        if len(compatible) == 1:
            method = DETERMINISTIC_METHOD
            sense_id = next(iter(compatible))
            source = claims
        else:
            votes = defaultdict(set)
            by_sense = defaultdict(list)
            for claim in claims:
                if claim["sense"] in compatible:
                    votes[claim["sense"]].add(claim["family"])
                    by_sense[claim["sense"]].append(claim)
            agreed = [sid for sid, families in votes.items() if len(families) >= 2]
            if len(agreed) == 1:
                method = CONSENSUS_METHOD
                sense_id = agreed[0]
                source = by_sense[sense_id]
        if not method:
            counts["still_needs_gemini"] += 1
            continue

        sense = current_senses[sense_id]
        retained.append({
            "word": word,
            "occurrence_id": occurrence_id,
            "segment_id": occurrence["segment_id"],
            "segment_revision": occurrence.get("segment_revision_id"),
            "example_index": ex_idx,
            "example_id": ref.get("example_id"),
            "sense": sense_id,
            "headword": sense.get("headword"),
            "pos": pos,
            "method": method,
            "source_claims": source,
        })
        counts[method] += 1

    inputs = {
        "ledger_run": active["ledger_run"],
        "assignments_fingerprint": semantic_fingerprint(source_assignments),
        "menu_sha256": _sha256(menu_path),
        "example_pos_sha256": _sha256(pos_path),
        "examples_sha256": _sha256(examples_path),
        "minimum_trusted_prompt_tier": MIN_TRUSTED_PROMPT_TIER,
        "step_version": STEP_VERSION,
    }
    run_id = stable_id("run", "legacy-sense-retention-v1", language_tag(
        config.get("language") or "und"), inputs, semantic_fingerprint(retained))
    claims_out = []
    for row in retained:
        claims_out.append(make_claim(
            SENSE_RETENTION_LAYER, "occurrence", row["occurrence_id"], "assert",
            {"sense": row["sense"], "word": row["word"],
             "headword": row["headword"], "retention_rule": row["method"],
             "source_claims": row["source_claims"],
             "dependency_validation": "current_stable_ids_pos_and_normalization"},
            {"method_id": row["method"], "run_id": run_id},
            {"ledger_run": active["ledger_run"],
             "segment_revision": row["segment_revision"],
             "sense": row["sense"], "pos": row["pos"],
             "normalized_word": row["word"], "inputs": inputs},
            confidence=1.0 if row["method"] == DETERMINISTIC_METHOD else 0.70,
            input_refs=[{"id": row["segment_id"],
                         "revision": row["segment_revision"]}],
        ))
    overlay = evidence_dir / "overlays" / SENSE_RETENTION_LAYER / (run_id + ".jsonl")
    artifact = write_jsonl_atomic(overlay, claims_out)
    manifest = build_run_manifest(
        run_id, SENSE_RETENTION_LAYER, language_tag(config.get("language") or "und"),
        {"name": "legacy-sense-retention-v1", "version": STEP_VERSION},
        inputs, {"rules": [DETERMINISTIC_METHOD, CONSENSUS_METHOD]},
        {"claims.jsonl": artifact},
        {claim["subject"]["id"]: claim["input_fingerprint"] for claim in claims_out},
    )
    _write_json_atomic(overlay.with_suffix(".manifest.json"), manifest)

    # Compatibility projection for the current classifier/deck. Keep the old
    # methods untouched; prompt-tier filtering archives them at resolution.
    projected = defaultdict(lambda: defaultdict(list))
    for row in retained:
        projected[(row["word"], row["method"], row["sense"])]["rows"].append(row)
    incoming = defaultdict(dict)
    for (word, method, sense_id), bucket in projected.items():
        rows = bucket["rows"]
        example_identity = {}
        for row in sorted(rows, key=lambda item: item["example_index"]):
            example_identity.setdefault(row["example_index"], row["example_id"])
        incoming[word].setdefault(method, []).append({
            "sense": sense_id,
            "examples": list(example_identity),
            "example_ids": list(example_identity.values()),
            "occurrence_refs": [{
                "occurrence_id": row["occurrence_id"],
                "example_id": row["example_id"],
                "example_index": row["example_index"],
            } for row in rows],
            "occurrence_ids": [row["occurrence_id"] for row in rows],
            "retention_run_id": run_id,
        })
    # Rebuild this adapter's compatibility projection rather than recursively
    # treating a previous projection as a new source.
    for word in list(assignments):
        assignments[word].pop(DETERMINISTIC_METHOD, None)
        assignments[word].pop(CONSENSUS_METHOD, None)
    for word, methods in incoming.items():
        assignments[word] = merge_method_maps(assignments.get(word, {}), methods)
    dump_assignments(assignments, assignments_path)

    profile = active["profile"]
    profile.setdefault("claim_runs", {}).setdefault(
        SENSE_RETENTION_LAYER, {})["legacy-sense-retention-v1"] = run_id
    profile.setdefault("runs", {})[SENSE_RETENTION_LAYER] = run_id
    profile.setdefault("method_priorities", {})[DETERMINISTIC_METHOD] = 60
    profile.setdefault("method_priorities", {})[CONSENSUS_METHOD] = 55
    write_profile(evidence_dir, profile)

    summary = {
        "artist": config.get("name") or artist_dir.name,
        "run_id": run_id,
        "retained_occurrences": len(retained),
        "retained_words": len({row["word"] for row in retained}),
        "counts": dict(sorted(counts.items())),
        "retained": retained,
    }
    report = artist_dir / "data" / "reports" / "legacy_sense_retention.json"
    _write_json_atomic(report, summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artist-dir", required=True)
    args = parser.parse_args()
    summary = build_retention(args.artist_dir)
    print("%(artist)s: retained %(retained_occurrences)d occurrences across "
          "%(retained_words)d words (%(run_id)s)" % summary)
    print(json.dumps(summary["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
