#!/usr/bin/env python3
"""Materialize the active evidence profile into the legacy Artist corpus view.

The parity pass always resolves the same ledger with vocal-artifact exclusions
disabled and compares it to step_2a's historical output.  Only after that
check succeeds is the selected policy allowed to advance ``vocab_evidence``.
"""

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pipeline.artist.util_2b_evidence_view import (  # noqa: E402
    corpus_profile_fingerprint,
    first_difference,
    load_profile,
    materialize_vocabulary_evidence,
)
from pipeline.util_evidence_store import archive_json_artifact  # noqa: E402
from pipeline.util_pipeline_meta import make_meta, write_sidecar  # noqa: E402


STEP_VERSION = 2
STEP_VERSION_NOTES = {
    1: "materialize a selected Evidence Store corpus profile with strict neutral parity",
    2: "+ stamp the semantic corpus-profile fingerprint for downstream build contracts",
}


def _load_immutable_baseline(evidence_dir, profile):
    run_id = (profile.get("materialized_runs") or {}).get(
        "vocab_evidence_baseline")
    if not run_id:
        return None
    path = (Path(evidence_dir) / "snapshots" / "vocab_evidence_baseline" /
            "runs" / str(run_id) / "artifact.json")
    if not path.is_file():
        raise FileNotFoundError(
            "Profile selects missing behavior-neutral baseline %s" % path)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def materialize_artist(artist_dir, output_path=None, max_examples=None,
                       require_parity=True):
    artist_dir = Path(artist_dir).resolve()
    evidence_dir = artist_dir / "data" / "evidence"
    output_path = Path(output_path) if output_path else (
        artist_dir / "data" / "word_counts" / "vocab_evidence.json")
    profile = load_profile(evidence_dir)
    ledger_run = (profile.get("runs") or {}).get("ledger")

    manifest_path = evidence_dir / "ledger" / "runs" / str(ledger_run) / "manifest.json"
    ledger_config = {}
    if manifest_path.is_file():
        with open(manifest_path, encoding="utf-8") as handle:
            ledger_config = (json.load(handle).get("config") or {})
    if max_examples is None:
        max_examples = int(ledger_config.get("max_examples", 10))

    baseline = _load_immutable_baseline(evidence_dir, profile)
    # Migration fallback for ledgers created before step_2a began archiving a
    # dedicated neutral baseline. A fresh orchestrated run always takes the
    # immutable branch, so rerunning only classification/materialization never
    # compares against an already-filtered live view.
    if baseline is None and output_path.is_file():
        with open(output_path, encoding="utf-8") as handle:
            baseline = json.load(handle)

    neutral, neutral_summary = materialize_vocabulary_evidence(
        evidence_dir, max_examples=max_examples, excluded_labels=[])
    difference = first_difference(baseline, neutral) if baseline is not None else None
    if difference and require_parity:
        raise ValueError(
            "Behavior-neutral evidence materialization differs from step_2a "
            "baseline. First difference: %s" % json.dumps(
                difference, ensure_ascii=False, sort_keys=True))

    materialized, summary = materialize_vocabulary_evidence(
        evidence_dir, max_examples=max_examples)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(materialized, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(str(temp_path), str(output_path))
    write_sidecar(str(output_path), make_meta(
        "materialize_artist_corpus", STEP_VERSION,
        extra={
            "ledger_run": ledger_run,
            "corpus_profile_hash": corpus_profile_fingerprint(profile),
            "excluded_labels": summary["excluded_labels"],
        },
    ))
    archived = archive_json_artifact(
        evidence_dir,
        "vocab_evidence_materialized",
        materialized,
        language=profile.get("language") or "und",
        adapter={"name": "artist-evidence-materializer", "version": STEP_VERSION},
        inputs={
            "ledger_run": ledger_run,
            "normalization_runs": (profile.get("claim_runs") or {}).get("normalization")
                                  or (profile.get("runs") or {}).get("normalization"),
            "membership_runs": (profile.get("claim_runs") or {}).get("corpus_membership")
                               or (profile.get("runs") or {}).get("corpus_membership"),
            "vocal_artifact_runs": (profile.get("claim_runs") or {}).get("vocal_artifact")
                                   or (profile.get("runs") or {}).get("vocal_artifact"),
        },
        config={
            "max_examples": max_examples,
            "excluded_labels": summary["excluded_labels"],
        },
    )
    return {
        **summary,
        "neutral_parity": difference is None,
        "neutral_words": neutral_summary["words"],
        "output": str(output_path),
        "snapshot_run": archived["run_id"],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Materialize active Artist evidence profile")
    parser.add_argument("--artist-dir", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--max-examples", type=int, default=None)
    parser.add_argument("--allow-parity-drift", action="store_true",
                        help="Diagnostic escape hatch; never use for a live cutover")
    args = parser.parse_args()
    summary = materialize_artist(
        args.artist_dir,
        output_path=args.out,
        max_examples=args.max_examples,
        require_parity=not args.allow_parity_drift,
    )
    print("Evidence materialization: %(words)d words / %(tokens)d tokens" % summary)
    print("  neutral parity: %(neutral_parity)s" % summary)
    print("  excluded: %(excluded_occurrences)d occurrences, %(excluded_segments)d segments" % summary)
    print("  labels: %(excluded_labels)s" % summary)
    print("  output: %(output)s" % summary)


if __name__ == "__main__":
    main()
