"""Resolve and materialize the active Artist evidence profile.

The browser-facing deck remains a compact JSON projection.  This module is the
bridge that makes that projection originate in the immutable segment,
occurrence, and claim store rather than in mutable lyric-line indices.
"""

import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from pipeline.util_evidence_store import read_jsonl, resolve_claims


VOCAL_ARTIFACT_LAYER = "vocal_artifact"


def load_profile(evidence_dir):
    path = Path(evidence_dir) / "profiles" / "current.json"
    if not path.is_file():
        raise FileNotFoundError("No active evidence profile at %s" % path)
    with open(path, encoding="utf-8") as handle:
        profile = json.load(handle)
    if not isinstance(profile, dict):
        raise ValueError("Evidence profile must be an object: %s" % path)
    return profile


def write_profile(evidence_dir, profile):
    """Atomically advance the small mutable profile pointer."""
    path = Path(evidence_dir) / "profiles" / "current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(profile, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(str(temp), str(path))


def selected_claim_run_ids(profile, layer):
    """Return the profile-selected immutable runs for one claim layer.

    ``claim_runs`` can retain one active run per method, allowing a profile to
    rank multiple classifiers.  The older single ``runs[layer]`` pointer is
    accepted as a compatibility fallback.
    """
    selected = (profile.get("claim_runs") or {}).get(layer)
    run_ids = []
    if isinstance(selected, dict):
        run_ids.extend(selected.values())
    elif isinstance(selected, list):
        run_ids.extend(selected)
    elif selected:
        run_ids.append(selected)
    if not run_ids:
        fallback = (profile.get("runs") or {}).get(layer)
        if fallback:
            run_ids.append(fallback)
    return list(dict.fromkeys(str(run_id) for run_id in run_ids if run_id))


def load_selected_claims(evidence_dir, layer, profile=None):
    evidence_dir = Path(evidence_dir)
    profile = profile or load_profile(evidence_dir)
    claims = []
    for run_id in selected_claim_run_ids(profile, layer):
        path = evidence_dir / "overlays" / layer / (run_id + ".jsonl")
        if not path.is_file():
            raise FileNotFoundError(
                "Profile selects missing %s run %s" % (layer, path))
        claims.extend(read_jsonl(path))
    return claims


def load_active_evidence(evidence_dir):
    """Load the profile-selected corpus and resolved overlay claims."""
    evidence_dir = Path(evidence_dir)
    profile = load_profile(evidence_dir)
    ledger_run = (profile.get("runs") or {}).get("ledger")
    if not ledger_run:
        raise ValueError("Evidence profile has no selected ledger run")
    run_dir = evidence_dir / "ledger" / "runs" / str(ledger_run)
    segments = read_jsonl(run_dir / "segments.jsonl")
    occurrences = read_jsonl(run_dir / "occurrences.jsonl")
    priorities = profile.get("method_priorities") or {}
    active_revisions = {
        segment.get("segment_id"): segment.get("revision_id")
        for segment in segments if segment.get("state") == "present"
    }

    winners = {}
    for layer in ("corpus_membership", "normalization", VOCAL_ARTIFACT_LAYER):
        claims = load_selected_claims(evidence_dir, layer, profile)
        # A profile may temporarily retain a classifier pointer while a new
        # source snapshot is being ingested. Never apply a claim whose explicit
        # source revision no longer matches the active segment; the subsequent
        # classifier run can refresh it without deleting history.
        claims = [claim for claim in claims if all(
            reference.get("id") not in active_revisions
            or not reference.get("revision")
            or reference.get("revision") == active_revisions[reference.get("id")]
            for reference in (claim.get("input_refs") or [])
        )]
        winners.update(resolve_claims(claims, priorities))
    return {
        "profile": profile,
        "ledger_run": str(ledger_run),
        "segments": segments,
        "occurrences": occurrences,
        "claims": winners,
    }


def artifact_labels(claim):
    value = (claim or {}).get("value") or {}
    labels = value.get("labels")
    if labels is None and value.get("label"):
        labels = [value["label"]]
    return {str(label) for label in (labels or []) if label}


def build_active_segment_rows(evidence_dir, excluded_labels=None):
    """Return active segments with their resolved, policy-filtered units.

    A vocal-artifact claim is descriptive evidence.  It affects the corpus
    only when its label appears in the profile's ``excluded_labels`` policy.
    The optional argument is used by the parity harness to materialize an
    explicitly behavior-neutral view from the same immutable runs.
    """
    active = load_active_evidence(evidence_dir)
    profile = active["profile"]
    policy = ((profile.get("policies") or {}).get(VOCAL_ARTIFACT_LAYER) or {})
    if excluded_labels is None:
        excluded_labels = policy.get("excluded_labels") or []
    excluded_labels = {str(label) for label in excluded_labels}

    claims = active["claims"]
    occurrences_by_segment = defaultdict(list)
    for occurrence in active["occurrences"]:
        occurrences_by_segment[occurrence.get("segment_id")].append(occurrence)
    for rows in occurrences_by_segment.values():
        rows.sort(key=lambda row: (int(row.get("ordinal", 0)), row.get("occurrence_id", "")))

    rows = []
    excluded_occurrences = set()
    excluded_segments = set()
    for segment in active["segments"]:
        if segment.get("state") != "present":
            continue
        segment_id = segment["segment_id"]
        membership = claims.get(("corpus_membership", "segment", segment_id))
        membership_value = (membership or {}).get("value") or {}
        if membership and not membership_value.get("included", True):
            excluded_segments.add(segment_id)
            continue

        segment_artifact = claims.get((VOCAL_ARTIFACT_LAYER, "segment", segment_id))
        if artifact_labels(segment_artifact) & excluded_labels:
            excluded_segments.add(segment_id)
            continue

        units = []
        for occurrence in occurrences_by_segment.get(segment_id, []):
            occurrence_id = occurrence["occurrence_id"]
            artifact = claims.get((VOCAL_ARTIFACT_LAYER, "occurrence", occurrence_id))
            labels = artifact_labels(artifact)
            if labels & excluded_labels:
                excluded_occurrences.add(occurrence_id)
                continue
            normalization = claims.get(("normalization", "occurrence", occurrence_id))
            value = (normalization or {}).get("value") or {}
            for unit in value.get("analysis_units") or []:
                normalized_form = str(unit.get("normalized_form") or "")
                if not normalized_form:
                    continue
                units.append({
                    "analysis_unit_id": unit.get("analysis_unit_id"),
                    "normalized_form": normalized_form,
                    "surface": str(unit.get("legacy_surface") or occurrence.get("surface") or "").lower(),
                    "slot": int(unit.get("slot", 0)),
                    "occurrence": occurrence,
                    "artifact_labels": sorted(labels),
                })
        units.sort(key=lambda row: (
            int(row["occurrence"].get("ordinal", 0)), row["slot"],
            row.get("analysis_unit_id") or "",
        ))
        rows.append({"segment": segment, "units": units})

    rows.sort(key=lambda row: (
        int((row["segment"].get("metadata") or {}).get("batch_index", -1)),
        str((row["segment"].get("source") or {}).get("document_id") or ""),
        min((row["segment"].get("source") or {}).get("positions") or [0]),
        row["segment"].get("segment_id", ""),
    ))
    return {
        **active,
        "rows": rows,
        "excluded_labels": sorted(excluded_labels),
        "excluded_occurrence_ids": excluded_occurrences,
        "excluded_segment_ids": excluded_segments,
    }


def _song_id(segment):
    source = segment.get("source") or {}
    if source.get("song_id") not in (None, ""):
        return source["song_id"]
    document_id = str(source.get("document_id") or "")
    if document_id.startswith("genius:"):
        return document_id.split(":", 1)[1]
    return None


def materialize_vocabulary_evidence(evidence_dir, max_examples=10,
                                    excluded_labels=None):
    """Materialize the legacy word evidence view from the active ledger."""
    from pipeline.artist import step_2a_count_words as count_step

    active = build_active_segment_rows(evidence_dir, excluded_labels=excluded_labels)
    counts = Counter()
    candidates = defaultdict(list)
    word_songs = defaultdict(set)
    by_document = defaultdict(list)
    for row in active["rows"]:
        segment = row["segment"]
        document_id = str((segment.get("source") or {}).get("document_id") or "")
        by_document[document_id].append(row)

    for document_rows in by_document.values():
        document_rows.sort(key=lambda row: (
            min((row["segment"].get("source") or {}).get("positions") or [0]),
            row["segment"].get("segment_id", ""),
        ))
        seen_count_lines = set()
        materialized_lines = []
        for row in document_rows:
            segment = row["segment"]
            units = row["units"]
            norm_toks = [unit["normalized_form"] for unit in units]
            if not norm_toks:
                continue
            source = segment.get("source") or {}
            metadata = segment.get("metadata") or {}
            song_id = _song_id(segment)
            line_no = min(source.get("positions") or [0])
            word_surfaces = {}
            word_occurrences = defaultdict(list)
            for unit in units:
                word = unit["normalized_form"]
                word_surfaces.setdefault(word, unit["surface"] or word)
                occurrence_id = unit["occurrence"]["occurrence_id"]
                if occurrence_id not in word_occurrences[word]:
                    word_occurrences[word].append(occurrence_id)
            materialized_lines.append({
                "segment": segment,
                "song_id": song_id,
                "line_no": line_no,
                "line_text": segment.get("text") or "",
                "song_title": source.get("title") or "",
                "batch": int(metadata.get("batch_index", -1)),
                "norm_toks": norm_toks,
                "word_surfaces": word_surfaces,
                "word_occurrences": word_occurrences,
                "vocalists": list(metadata.get("vocalists") or []),
                "sung_by_primary_artist": bool(metadata.get("sung_by_primary_artist")),
            })

            count_line_key = " ".join(norm_toks)
            if count_line_key in seen_count_lines:
                continue
            seen_count_lines.add(count_line_key)
            counts.update(norm_toks)
            if song_id is not None:
                for word in set(norm_toks):
                    word_songs[word].add(str(song_id))

        top_for_word = {}
        for line in materialized_lines:
            norm_toks = line["norm_toks"]
            if not count_step.is_good_context_line(norm_toks):
                continue
            score = count_step.score_line(norm_toks)
            # This deliberately mirrors the historical example-dedupe key.
            normalized_line = " ".join(count_step.tokenize(
                count_step.strip_adlibs(line["line_text"])))
            for word, surface in line["word_surfaces"].items():
                entry = (
                    score, line["line_no"], line["line_text"], normalized_line,
                    surface, line["vocalists"], line["sung_by_primary_artist"], line,
                )
                entries = top_for_word.setdefault(word, [])
                matching = next((index for index, old in enumerate(entries)
                                 if old[3] == normalized_line), None)
                if matching is not None:
                    if score > entries[matching][0]:
                        entries[matching] = entry
                    continue
                if len(entries) < 3:
                    entries.append(entry)
                    continue
                worst = min(range(len(entries)), key=lambda index: entries[index][0])
                if score > entries[worst][0]:
                    entries[worst] = entry

        for line in materialized_lines:
            score = count_step.score_line(line["norm_toks"])
            normalized_line = " ".join(count_step.tokenize(
                count_step.strip_adlibs(line["line_text"])))
            for word, surface in line["word_surfaces"].items():
                if word in top_for_word:
                    continue
                top_for_word[word] = [(
                    score, line["line_no"], line["line_text"], normalized_line,
                    surface, line["vocalists"], line["sung_by_primary_artist"], line,
                )]

        for word, entries in top_for_word.items():
            for score, line_no, line_text, _norm, surface, vocalists, primary, line in entries:
                candidate = {
                    "score": score,
                    "batch": line["batch"],
                    "song_id": line["song_id"],
                    "line_no": line_no,
                    "line_text": line_text,
                    "song_title": line["song_title"],
                    "surface": surface,
                    "segment_id": line["segment"]["segment_id"],
                    "occurrence_ids": list(line["word_occurrences"].get(word) or []),
                }
                if vocalists:
                    candidate["vocalists"] = vocalists
                    candidate["sung_by_primary_artist"] = primary
                candidates[word].append(candidate)

    selected = count_step.select_examples(
        counts, candidates, max_examples_per_word=max_examples)
    evidence = count_step.to_evidence_json(counts, selected, word_songs)
    return evidence, {
        "ledger_run": active["ledger_run"],
        "excluded_labels": active["excluded_labels"],
        "excluded_occurrences": len(active["excluded_occurrence_ids"]),
        "excluded_segments": len(active["excluded_segment_ids"]),
        "words": len(evidence),
        "tokens": sum(item["corpus_count"] for item in evidence),
    }


def first_difference(expected, actual):
    """Return a compact semantic parity diagnostic."""
    if expected == actual:
        return None
    expected_by_word = {row.get("word"): row for row in expected or []}
    actual_by_word = {row.get("word"): row for row in actual or []}
    for word in sorted(set(expected_by_word) | set(actual_by_word)):
        if expected_by_word.get(word) != actual_by_word.get(word):
            return {
                "word": word,
                "expected": expected_by_word.get(word),
                "actual": actual_by_word.get(word),
            }
    return {"expected_records": len(expected or []), "actual_records": len(actual or [])}
