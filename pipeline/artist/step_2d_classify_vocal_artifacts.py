#!/usr/bin/env python3
"""Write a conservative occurrence-level vocal-artifact claim run.

This first adapter is intentionally rules-only and high precision.  It proves
the replaceable classifier boundary without coupling the Evidence Store to a
specific model provider.  A later local model or API adapter can write the same
claim schema under a different ``method_id`` and the active profile can rank or
disable it without deleting this run.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pipeline.artist.util_1a_artist_config import load_artist_config  # noqa: E402
from pipeline.artist.util_2a_corpus_ledger import language_tag  # noqa: E402
from pipeline.artist.util_2b_evidence_view import (  # noqa: E402
    VOCAL_ARTIFACT_LAYER,
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
METHOD_ID = "artist-vocal-artifact-rules-v1"
BASIC_EXCLUDED_LABELS = ["adlib", "echo", "stutter"]
_BRACKET_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)")
_HYPHEN_GAP_RE = re.compile(r"^\s*-\s*$")
_ECHO_GAP_RE = re.compile(r"^\s*(?:,\s*)?-\s*$|^\s*,\s*$")


def _letters_only(value):
    return "".join(char for char in identity_normalize_text(value)
                   if char.isalpha())


def default_known_forms_path(language):
    language = language_tag(language)
    names = {"es": "Spanish", "fr": "French", "nl": "Dutch"}
    name = names.get(language)
    if not name:
        return None
    path = Path(PROJECT_ROOT) / "Data" / name / "layers" / (
        "%s_forms.json" % name.lower())
    return path if path.is_file() else None


def load_known_forms(path):
    if not path:
        return set()
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        payload = payload.get("forms") or payload.get("entries") or payload.keys()
    return {identity_normalize_text(value) for value in payload or [] if value}


def classify_occurrences(segments, occurrences, known_forms=None):
    """Return ``occurrence_id -> {labels, reasons}`` for conservative rules."""
    known_forms = set(known_forms or [])
    segments_by_id = {segment["segment_id"]: segment for segment in segments
                      if segment.get("state") == "present"}
    by_segment = defaultdict(list)
    for occurrence in occurrences:
        if occurrence.get("state") == "present":
            by_segment[occurrence.get("segment_id")].append(occurrence)
    for rows in by_segment.values():
        rows.sort(key=lambda row: int(row.get("ordinal", 0)))

    classified = defaultdict(lambda: {"labels": set(), "reasons": []})
    for segment_id, rows in by_segment.items():
        segment = segments_by_id.get(segment_id)
        if not segment:
            continue
        text = str(segment.get("text") or "")

        bracket_spans = [match.span() for match in _BRACKET_RE.finditer(text)]
        for occurrence in rows:
            start, end = occurrence.get("span") or [0, 0]
            if any(left <= start and end <= right for left, right in bracket_spans):
                result = classified[occurrence["occurrence_id"]]
                result["labels"].add("adlib")
                result["reasons"].append("inside bracketed or parenthetical vocal")

        # Short hyphen chains (ah-na-na, ca-ca-ca) are stutters/onomatopoeia.
        short_runs = []
        short_run = []
        for occurrence in rows:
            surface = _letters_only(occurrence.get("surface"))
            if len(surface) > 3 or not surface:
                if len(short_run) >= 2:
                    short_runs.append(short_run)
                short_run = []
                continue
            if short_run:
                previous = short_run[-1]
                gap = text[previous["span"][1]:occurrence["span"][0]]
                if not _HYPHEN_GAP_RE.match(gap):
                    if len(short_run) >= 2:
                        short_runs.append(short_run)
                    short_run = []
            short_run.append(occurrence)
        if len(short_run) >= 2:
            short_runs.append(short_run)
        for run in short_runs:
            forms = [identity_normalize_text(member.get("surface")) for member in run]
            # Protect ordinary short-word reduplication (no-no, sol-sol) when
            # a language lexicon is available. Two-part runs need to repeat an
            # unknown fragment; longer chains remain the familiar high-signal
            # lyric stutter pattern even when their syllables differ.
            if len(run) == 2 and (
                    forms[0] != forms[1]
                    or (known_forms and forms[0] in known_forms)):
                continue
            for member in run:
                result = classified[member["occurrence_id"]]
                result["labels"].add("stutter")
                reason = "member of short hyphenated vocal chain"
                if reason not in result["reasons"]:
                    result["reasons"].append(reason)

        # A longer known word followed by its unknown tail is an echo at that
        # exact occurrence only: mover, -over. Legitimate uses elsewhere stay.
        if known_forms:
            for previous, occurrence in zip(rows, rows[1:]):
                source = identity_normalize_text(previous.get("surface"))
                echo = identity_normalize_text(occurrence.get("surface"))
                source_letters = _letters_only(source)
                echo_letters = _letters_only(echo)
                gap = text[previous["span"][1]:occurrence["span"][0]]
                if not _ECHO_GAP_RE.match(gap):
                    continue
                if len(echo_letters) < 3 or len(source_letters) <= len(echo_letters):
                    continue
                if not source_letters.endswith(echo_letters):
                    continue
                if source not in known_forms or echo in known_forms:
                    continue
                result = classified[occurrence["occurrence_id"]]
                result["labels"].add("echo")
                result["reasons"].append(
                    "unknown tail repeated immediately after known form '%s'" % source)

    return {
        occurrence_id: {
            "labels": sorted(value["labels"]),
            "reasons": value["reasons"],
        }
        for occurrence_id, value in classified.items()
        if value["labels"]
    }


def write_classifier_run(artist_dir, policy="basic", known_forms_path=None,
                         method_id=METHOD_ID):
    artist_dir = Path(artist_dir).resolve()
    evidence_dir = artist_dir / "data" / "evidence"
    config = load_artist_config(str(artist_dir))
    language = language_tag(config.get("language") or "und")
    active = load_active_evidence(evidence_dir)
    path = Path(known_forms_path) if known_forms_path else default_known_forms_path(language)
    known_forms = load_known_forms(path)
    classifications = classify_occurrences(
        active["segments"], active["occurrences"], known_forms=known_forms)

    input_projection = {
        "ledger_run": active["ledger_run"],
        "segment_revisions": {
            row["segment_id"]: row.get("revision_id")
            for row in active["segments"] if row.get("state") == "present"
        },
        "known_forms": semantic_fingerprint(sorted(known_forms)),
        "step_version": STEP_VERSION,
    }
    run_id = stable_id(
        "run", "vocal-artifact-rules-v1", method_id, language,
        input_projection, classifications)
    method = {"method_id": method_id, "run_id": run_id}
    occurrence_by_id = {row["occurrence_id"]: row for row in active["occurrences"]}
    claims = []
    for occurrence_id in sorted(classifications):
        occurrence = occurrence_by_id[occurrence_id]
        segment_id = occurrence["segment_id"]
        claims.append(make_claim(
            VOCAL_ARTIFACT_LAYER,
            "occurrence",
            occurrence_id,
            "assert",
            classifications[occurrence_id],
            method,
            {
                "surface": occurrence.get("surface"),
                "span": occurrence.get("span"),
                "segment_revision": occurrence.get("segment_revision_id"),
                "rules_version": STEP_VERSION,
                "known_forms_hash": input_projection["known_forms"],
            },
            confidence=0.99,
            input_refs=[{
                "id": segment_id,
                "revision": occurrence.get("segment_revision_id"),
            }],
        ))

    overlay_path = evidence_dir / "overlays" / VOCAL_ARTIFACT_LAYER / (run_id + ".jsonl")
    artifact = write_jsonl_atomic(overlay_path, claims)
    manifest = build_run_manifest(
        run_id,
        VOCAL_ARTIFACT_LAYER,
        language,
        {"name": method_id, "version": STEP_VERSION},
        input_projection,
        {
            "rules_version": STEP_VERSION,
            "known_forms_hash": input_projection["known_forms"],
        },
        {"claims.jsonl": artifact},
        {claim["subject"]["id"]: claim["input_fingerprint"] for claim in claims},
    )
    manifest_path = overlay_path.with_suffix(".manifest.json")
    if manifest_path.is_file():
        with open(manifest_path, encoding="utf-8") as handle:
            if json.load(handle) != manifest:
                raise ValueError("Immutable classifier manifest differs for %s" % run_id)
    else:
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")

    profile = active["profile"]
    profile.setdefault("claim_runs", {}).setdefault(
        VOCAL_ARTIFACT_LAYER, {})[method_id] = run_id
    profile.setdefault("runs", {})[VOCAL_ARTIFACT_LAYER] = run_id
    profile.setdefault("method_priorities", {}).setdefault(method_id, 10)
    profile.setdefault("policies", {})[VOCAL_ARTIFACT_LAYER] = {
        "policy_id": policy,
        "excluded_labels": BASIC_EXCLUDED_LABELS if policy == "basic" else [],
    }
    write_profile(evidence_dir, profile)
    counts = Counter(
        label for value in classifications.values() for label in value["labels"])
    return {
        "run_id": run_id,
        "claims": len(claims),
        "labels": dict(sorted(counts.items())),
        "policy": policy,
        "known_forms": len(known_forms),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Classify conservative occurrence-level lyric vocal artifacts")
    parser.add_argument("--artist-dir", required=True)
    parser.add_argument("--policy", choices=["off", "basic"], default="basic",
                        help="Profile policy to select after recording claims")
    parser.add_argument("--known-forms", default=None,
                        help="Optional language lexicon JSON for suffix-echo validation")
    args = parser.parse_args()
    summary = write_classifier_run(
        args.artist_dir, policy=args.policy, known_forms_path=args.known_forms)
    print("Vocal-artifact run: %(run_id)s" % summary)
    print("  claims: %(claims)d; labels: %(labels)s" % summary)
    print("  policy: %(policy)s; known forms: %(known_forms)d" % summary)


if __name__ == "__main__":
    main()
