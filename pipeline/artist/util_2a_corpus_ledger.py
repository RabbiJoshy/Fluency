"""Artist adapter for the shared corpus evidence contract.

Step 2 still emits the historical word-first files during migration.  This
collector observes the same lyric scan and writes immutable segment/occurrence
snapshots plus normalization and membership claims.  Legacy examples receive
additive ``segment_id`` / ``occurrence_ids`` references so later stages can
become ID-first one at a time without a flag-day rebuild.
"""

import json
import os
import re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

from pipeline.util_evidence_store import (
    SOURCE_SCANNER_V1,
    build_occurrence,
    build_run_manifest,
    build_segment,
    canonical_json,
    identity_normalize_text,
    make_analysis_unit_id,
    make_claim,
    read_jsonl,
    scan_source_tokens,
    semantic_fingerprint,
    stable_id,
    write_jsonl_atomic,
)


ADAPTER_VERSION = 1
PROFILE_SCHEMA = "fluency.evidence-profile/v1"
LEGACY_MIGRATION_SCHEMA = "fluency.legacy-example-map/v1"
_BRACKETED_SPAN_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)")

_LANGUAGE_ALIASES = {
    "spanish": "es",
    "french": "fr",
    "dutch": "nl",
    "english": "en",
    "italian": "it",
    "polish": "pl",
    "swedish": "sv",
}


def language_tag(value):
    """Resolve repository language names to BCP-47 tags, allowing new tags."""
    lowered = str(value or "").strip().lower().replace("_", "-")
    return _LANGUAGE_ALIASES.get(lowered, lowered)


def _write_json_atomic(path, value):
    """Write one small JSON pointer/view atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(str(tmp), str(path))


class ArtistCorpusLedger(object):
    """Collect one Artist step-2 scan into Evidence Store v1 records."""

    def __init__(self, artist_dir, language, artist_name=""):
        self.artist_dir = Path(artist_dir).resolve()
        self.language = language_tag(language)
        self.artist_name = str(artist_name or self.artist_dir.name)
        self.evidence_dir = self.artist_dir / "data" / "evidence"
        self._segments = {}
        self._occurrences = {}
        self._normalization_rows = {}
        self._membership_rows = {}
        self._analysis_occurrences = defaultdict(lambda: defaultdict(list))
        self._legacy_examples = {}
        self._source_text_counts = defaultdict(int)
        self._observed_line_segments = {}

    @staticmethod
    def _document_id(song_id, title):
        if song_id not in (None, ""):
            return "genius:%s" % song_id
        # Missing provider IDs are uncommon but must not collapse duplicate
        # anonymous inputs across artists.
        return "artist-title:%s" % identity_normalize_text(title)

    def _segment_source(self, song_id, title, line_text, line_no,
                        duplicate_ordinal=None):
        source = {
            "kind": "lyrics",
            "corpus_id": "genius",
            "document_id": self._document_id(song_id, title),
            "song_id": song_id,
            "title": str(title or ""),
            "positions": [int(line_no)],
            "text": line_text,
        }
        if duplicate_ordinal is not None:
            # Repeated chorus lines are distinct source occurrences. This key
            # is local to identical text in one document, so inserting an
            # unrelated line never renumbers later segment IDs.
            source["segment_key"] = "lyric-text:%s:%d" % (
                semantic_fingerprint(identity_normalize_text(line_text)),
                duplicate_ordinal,
            )
        return source

    def observe_line(self, song_id, title, line_no, line_text,
                     source_tokens, included=True, exclusion_reason=None,
                     vocalists=None, sung_by_primary_artist=False,
                     batch_index=-1):
        """Record a source line and its current deterministic token projection.

        ``source_tokens`` is a list of ``{surface, forms}`` rows.  Each row
        represents one token from the current counting tokenizer; ``forms`` is
        the zero-or-more normalized components it emits (e.g. ``vo'a`` may emit
        ``voy`` and ``a``).  Raw occurrence identity is independently derived
        from the frozen Unicode source scanner over the untouched lyric line.
        """
        document_id = self._document_id(song_id, title)
        text_identity = identity_normalize_text(line_text)
        duplicate_key = (document_id, text_identity)
        duplicate_ordinal = self._source_text_counts[duplicate_key]
        self._source_text_counts[duplicate_key] += 1
        source = self._segment_source(
            song_id, title, line_text, line_no,
            duplicate_ordinal=duplicate_ordinal,
        )
        metadata = {
            "artist": self.artist_name,
            "batch_index": int(batch_index),
            "vocalists": list(vocalists or []),
            "sung_by_primary_artist": bool(sung_by_primary_artist),
        }
        segment = build_segment(self.language, line_text, source, metadata=metadata)
        segment_id = segment["segment_id"]

        prior = self._segments.get(segment_id)
        if prior:
            merged = deepcopy(prior)
            positions = set(merged.get("source", {}).get("positions") or [])
            positions.add(int(line_no))
            merged["source"]["positions"] = sorted(positions)
            # Rebuild so revision identity includes the merged source positions.
            rebuilt_source = dict(merged["source"])
            rebuilt_source["text"] = line_text
            segment = build_segment(
                self.language, line_text, rebuilt_source,
                metadata=merged.get("metadata") or metadata,
            )
        self._segments[segment_id] = segment
        self._observed_line_segments[(document_id, int(line_no), text_identity)] = segment_id

        raw_rows = scan_source_tokens(line_text)
        bracketed_spans = [match.span() for match in _BRACKETED_SPAN_RE.finditer(line_text)]
        occurrence_rows = []
        normalization_candidates = []
        for raw in raw_rows:
            occurrence = build_occurrence(
                segment,
                raw["ordinal"],
                raw["span"],
                raw["surface"],
                SOURCE_SCANNER_V1,
            )
            self._occurrences[occurrence["occurrence_id"]] = occurrence
            occurrence_rows.append(occurrence)
            if any(left <= raw["span"][0] and raw["span"][1] <= right
                   for left, right in bracketed_spans):
                # Step 2's normalization source is the adlib-stripped text.
                # Retain bracketed tokens as raw evidence for artifact
                # classifiers, but never let a repeated surface inside an
                # adlib steal the normalization intended for the sung line.
                continue
            normalization_candidates.append(occurrence)

        # Match each current counting token to the next same-surface frozen raw
        # occurrence. Ad-lib tokens remain in the base ledger but receive no
        # current normalization unit, which is precisely the distinction the
        # evidence model needs.
        matched_tokens = defaultdict(list)
        raw_index = 0
        raw_offset = 0
        for token in source_tokens or []:
            surface = str(token.get("surface") or "")
            normalized_surface = identity_normalize_text(surface).strip("'")
            occurrence = None
            while normalized_surface and raw_index < len(normalization_candidates):
                candidate = normalization_candidates[raw_index]
                raw_surface = identity_normalize_text(
                    candidate.get("surface") or "").strip("'")
                if raw_offset == 0 and normalized_surface == raw_surface:
                    occurrence = candidate
                    raw_index += 1
                    break

                # The shared Unicode scanner intentionally keeps a source word
                # whole even when the historical Artist tokenizer drops an
                # unsupported internal character (Hadōken -> had + ken). Those
                # legacy pieces are multiple revisable analysis units beneath
                # one frozen raw occurrence, never new raw identities.
                found = (raw_surface.find(normalized_surface, raw_offset)
                         if len(normalized_surface) >= 2 else -1)
                if found >= 0:
                    occurrence = candidate
                    raw_offset = found + len(normalized_surface)
                    if raw_offset >= len(raw_surface):
                        raw_index += 1
                        raw_offset = 0
                    break
                raw_index += 1
                raw_offset = 0
            if occurrence is None:
                continue
            matched_tokens[occurrence["occurrence_id"]].append(token)

        normalization_facts = []
        for occurrence in occurrence_rows:
            tokens = matched_tokens.get(occurrence["occurrence_id"])
            if not tokens:
                continue
            analysis_units = []
            slot = 0
            for token in tokens:
                surface = str(token.get("surface") or "")
                forms = [str(value) for value in (token.get("forms") or []) if value]
                for normalized_form in forms:
                    analysis_unit_id = make_analysis_unit_id(
                        occurrence["occurrence_id"], slot, normalized_form,
                        "artist-count-tokenizer-v%d" % ADAPTER_VERSION,
                    )
                    analysis_units.append({
                        "analysis_unit_id": analysis_unit_id,
                        "slot": slot,
                        "normalized_form": normalized_form,
                        # Compatibility materializers must reproduce the old
                        # counting surface exactly (lowercase/canonical for
                        # leading aphesis, original fused form for pa'l-style
                        # multi-word elisions) without using array position.
                        "legacy_surface": str(
                            token.get("legacy_surface") or surface).lower(),
                    })
                    word_occurrences = self._analysis_occurrences[segment_id][
                        normalized_form.casefold()
                    ]
                    if occurrence["occurrence_id"] not in word_occurrences:
                        word_occurrences.append(occurrence["occurrence_id"])
                    slot += 1
            fact = {
                "occurrence": occurrence,
                "analysis_units": analysis_units,
            }
            normalization_facts.append(fact)

        legacy_id = "%s:%s" % (song_id, line_no)
        self._legacy_examples[legacy_id] = {
            "segment_id": segment_id,
            "occurrence_ids": [row["occurrence_id"] for row in occurrence_rows],
        }
        for fact in normalization_facts:
            self._normalization_rows[fact["occurrence"]["occurrence_id"]] = fact
        self._membership_rows[segment_id] = {
            "segment": segment,
            "included": bool(included),
            "reason": exclusion_reason,
        }
        return segment_id

    def example_refs(self, song_id, title, line_no, line_text, normalized_word):
        """Return additive stable references for one legacy word/example row."""
        lookup_key = (
            self._document_id(song_id, title),
            int(line_no),
            identity_normalize_text(line_text),
        )
        segment_id = self._observed_line_segments.get(lookup_key)
        if segment_id is None:
            # Compatibility for callers that request refs without observing the
            # line first. Normal step-2 flow always takes the persisted branch.
            source = self._segment_source(
                song_id, title, line_text, line_no, duplicate_ordinal=0)
            segment_id = build_segment(self.language, line_text, source)["segment_id"]
        occurrence_ids = list(dict.fromkeys(
            self._analysis_occurrences.get(segment_id, {}).get(
                str(normalized_word or "").casefold(), []
            )
        ))
        result = {"segment_id": segment_id}
        if occurrence_ids:
            result["occurrence_ids"] = occurrence_ids
        return result

    def _load_previous_segments(self):
        profile_path = self.evidence_dir / "profiles" / "current.json"
        if not profile_path.is_file():
            return []
        try:
            with open(profile_path, encoding="utf-8") as handle:
                profile = json.load(handle)
            run_id = (profile.get("runs") or {}).get("ledger")
            if not run_id:
                return []
            path = self.evidence_dir / "ledger" / "runs" / run_id / "segments.jsonl"
            return read_jsonl(path) if path.is_file() else []
        except (OSError, ValueError):
            return []

    def _load_profile(self):
        profile_path = self.evidence_dir / "profiles" / "current.json"
        if not profile_path.is_file():
            return {}
        try:
            with open(profile_path, encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            return {}

    def finalize(self, config=None):
        """Write immutable run shards and advance the small current profile."""
        config = dict(config or {})
        active_segments = [self._segments[key] for key in sorted(self._segments)]
        previous_segments = self._load_previous_segments()
        active_ids = set(self._segments)
        tombstones = []
        for old in previous_segments:
            if old.get("state") == "present" and old.get("segment_id") not in active_ids:
                tombstone = deepcopy(old)
                tombstone["state"] = "tombstone"
                tombstone["tombstone_reason"] = "absent_from_source_snapshot"
                tombstones.append(tombstone)

        segment_records = active_segments + sorted(
            tombstones, key=lambda row: row.get("segment_id", ""))
        occurrence_records = [
            self._occurrences[key] for key in sorted(self._occurrences)
        ]
        snapshot_projection = {
            "adapter_version": ADAPTER_VERSION,
            "language": self.language,
            "segments": segment_records,
            "occurrences": occurrence_records,
            "config": config,
        }
        run_id = stable_id("run", "artist-corpus-ledger-v1", snapshot_projection)
        method = {
            "method_id": "artist-count-tokenizer-v%d" % ADAPTER_VERSION,
            "run_id": run_id,
        }

        normalization_claims = []
        for row in self._normalization_rows.values():
            occurrence = row["occurrence"]
            normalization_claims.append(make_claim(
                "normalization", "occurrence", occurrence["occurrence_id"],
                "assert", {"analysis_units": row["analysis_units"]}, method,
                {
                    "surface": occurrence["surface"],
                    "scanner": occurrence["scanner"],
                    "adapter_version": ADAPTER_VERSION,
                },
                input_refs=[{
                    "id": occurrence["segment_id"],
                    "revision": occurrence["segment_revision_id"],
                }],
            ))

        membership_method = {
            "method_id": "artist-corpus-membership-v1",
            "run_id": run_id,
        }
        membership_claims = []
        for row in self._membership_rows.values():
            segment = row["segment"]
            membership_claims.append(make_claim(
                "corpus_membership", "segment", segment["segment_id"],
                "assert",
                {"included": row["included"], "reason": row["reason"]},
                membership_method,
                {
                    "membership": row["included"],
                    "reason": row["reason"],
                },
                input_refs=[{
                    "id": segment["segment_id"],
                    "revision": segment["revision_id"],
                }],
            ))

        run_dir = self.evidence_dir / "ledger" / "runs" / run_id
        segment_artifact = write_jsonl_atomic(
            run_dir / "segments.jsonl", segment_records)
        occurrence_artifact = write_jsonl_atomic(
            run_dir / "occurrences.jsonl", occurrence_records)
        normalization_path = (
            self.evidence_dir / "overlays" / "normalization" / (run_id + ".jsonl"))
        normalization_artifact = write_jsonl_atomic(
            normalization_path, normalization_claims)
        membership_path = (
            self.evidence_dir / "overlays" / "corpus_membership" / (run_id + ".jsonl"))
        membership_artifact = write_jsonl_atomic(
            membership_path, membership_claims)

        manifest = build_run_manifest(
            run_id,
            "corpus",
            self.language,
            {"name": "artist-step-2", "version": ADAPTER_VERSION},
            {"snapshot": semantic_fingerprint(snapshot_projection)},
            config,
            {
                "segments.jsonl": segment_artifact,
                "occurrences.jsonl": occurrence_artifact,
                "normalization.jsonl": normalization_artifact,
                "corpus_membership.jsonl": membership_artifact,
            },
            {
                row["segment_id"]: row["revision_id"]
                for row in active_segments
            },
        )
        _write_json_atomic(run_dir / "manifest.json", manifest)
        _write_json_atomic(
            normalization_path.with_suffix(".manifest.json"),
            {"run": run_id, "layer": "normalization", "artifact": normalization_artifact},
        )
        _write_json_atomic(
            membership_path.with_suffix(".manifest.json"),
            {"run": run_id, "layer": "corpus_membership", "artifact": membership_artifact},
        )
        _write_json_atomic(
            self.evidence_dir / "migrations" / "legacy_example_ids.json",
            {
                "schema": LEGACY_MIGRATION_SCHEMA,
                "run_id": run_id,
                "examples": self._legacy_examples,
            },
        )
        profile = self._load_profile()
        profile.update({
            "schema": PROFILE_SCHEMA,
            "profile_id": profile.get("profile_id") or "artist-current-v1",
            "language": self.language,
        })
        profile.setdefault("runs", {}).update({
            "ledger": run_id,
            "normalization": run_id,
            "corpus_membership": run_id,
        })
        _write_json_atomic(
            self.evidence_dir / "profiles" / "current.json", profile)
        return {
            "run_id": run_id,
            "segments": len(active_segments),
            "tombstones": len(tombstones),
            "occurrences": len(occurrence_records),
            "normalization_claims": len(normalization_claims),
        }
