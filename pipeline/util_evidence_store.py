"""Language-agnostic identity and evidence helpers for corpus pipelines.

The evidence store is deliberately a small file contract, not a database.  A
corpus importer writes immutable segment/occurrence snapshots, analysis tools
write immutable claim runs, and a build profile chooses which compatible claims
to materialise into the legacy layer files consumed by the app.

Nothing in this module assumes lyrics, Spanish, a dictionary, or even that a
sense inventory exists.  Artist lyrics and Speech/parallel-corpus records share
the same segment and occurrence envelopes.
"""

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from copy import deepcopy
from pathlib import Path


SEGMENT_SCHEMA = "fluency.segment/v1"
OCCURRENCE_SCHEMA = "fluency.occurrence/v1"
CLAIM_SCHEMA = "fluency.claim/v1"
RUN_MANIFEST_SCHEMA = "fluency.evidence-run/v1"
WSD_INPUT_SCHEMA = "fluency.wsd-input/v1"
WSD_OUTPUT_SCHEMA = "fluency.wsd-output/v1"
SOURCE_SCANNER_V1 = "unicode-source-token-v1"

_WS_RE = re.compile(r"\s+")
_APOSTROPHE_TABLE = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u02bc": "'", "`": "'",
})


def canonical_json(value):
    """Return deterministic compact JSON for hashing and JSONL output."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def semantic_fingerprint(value):
    """Return a namespaced SHA-256 fingerprint for a semantic projection."""
    payload = canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def stable_id(prefix, *parts, length=24):
    """Mint a deterministic opaque ID from an explicitly versioned namespace."""
    payload = canonical_json(list(parts)).encode("utf-8")
    return "%s_%s" % (prefix, hashlib.sha256(payload).hexdigest()[:length])


def normalize_language(language):
    """Normalize a BCP-47-ish language tag without imposing a fixed language list."""
    value = str(language or "").strip().replace("_", "-").lower()
    if not value:
        raise ValueError("language is required")
    return value


def identity_normalize_text(text):
    """Conservatively normalize source text for stable segment identity.

    This intentionally knows nothing about tokenization, elision, morphology,
    or a language's orthography.  Those are revisable evidence layers and must
    never participate in raw segment identity.
    """
    value = unicodedata.normalize("NFC", str(text or ""))
    value = value.translate(_APOSTROPHE_TABLE)
    return _WS_RE.sub(" ", value).strip().casefold()


def _is_word_character(char):
    return bool(char) and unicodedata.category(char)[0] in ("L", "M")


def scan_source_tokens(text):
    """Return frozen, language-agnostic source-token spans.

    The scanner recognizes Unicode letters/combining marks and keeps a leading
    or internal apostrophe when it is attached to a word.  It deliberately does
    not expand contractions, restore elisions, infer lemmas, or know any
    language.  Those revisable decisions belong in normalization claims.
    """
    text = str(text or "")
    apostrophes = frozenset(("'", "\u2018", "\u2019", "\u02bc", "`"))
    rows = []
    index = 0
    while index < len(text):
        start = index
        if text[index] in apostrophes and index + 1 < len(text) \
                and _is_word_character(text[index + 1]):
            index += 1
        elif not _is_word_character(text[index]):
            index += 1
            continue

        saw_letter = False
        while index < len(text):
            char = text[index]
            if _is_word_character(char):
                saw_letter = True
                index += 1
                continue
            if char in apostrophes and index + 1 < len(text) \
                    and _is_word_character(text[index + 1]):
                index += 1
                continue
            break
        if saw_letter:
            rows.append({
                "ordinal": len(rows),
                "span": [start, index],
                "surface": text[start:index],
            })
        elif index == start:
            index += 1
    return rows


def make_segment_id(language, source):
    """Return a stable ID for one source segment.

    ``source`` must identify its corpus/document and carry either a stable
    ``segment_key`` supplied by that corpus or the source text.  Lyrics usually
    use document ID + conservatively normalized text so inserting an earlier
    line cannot renumber every later line.  Parallel corpora should supply their
    native segment key when available.
    """
    language = normalize_language(language)
    source = dict(source or {})
    kind = str(source.get("kind") or "corpus")
    corpus_id = str(source.get("corpus_id") or "unknown")
    document_id = str(source.get("document_id") or "")
    segment_key = source.get("segment_key")
    if segment_key is None:
        text_key = identity_normalize_text(source.get("text") or "")
        if not text_key:
            raise ValueError("source requires segment_key or text")
        segment_key = "text:" + semantic_fingerprint(text_key)
    return stable_id(
        "seg", "segment-id-v1", language, kind, corpus_id, document_id,
        str(segment_key),
    )


def make_revision_id(segment_id, text, metadata=None, aligned_texts=None):
    """Return a revision ID that changes for content/metadata, not identity."""
    return stable_id(
        "rev", "segment-revision-v1", segment_id,
        unicodedata.normalize("NFC", str(text or "")),
        metadata or {}, aligned_texts or [],
    )


def make_occurrence_id(segment_id, ordinal):
    """Return the stable identity of a frozen raw-scanner token occurrence."""
    if not isinstance(ordinal, int) or ordinal < 0:
        raise ValueError("occurrence ordinal must be a non-negative integer")
    return stable_id("occ", "occurrence-id-v1", segment_id, ordinal)


def make_analysis_unit_id(occurrence_id, slot, normalized_form, method_id):
    """Identify one derived token emitted by a revisable normalization method."""
    return stable_id(
        "unit", "analysis-unit-id-v1", occurrence_id, int(slot),
        str(normalized_form or "").casefold(), str(method_id or ""),
    )


def build_segment(language, text, source, metadata=None, aligned_texts=None,
                  state="present"):
    """Build a validated segment envelope usable by lyrics or parallel corpora."""
    language = normalize_language(language)
    source = dict(source or {})
    source.setdefault("text", text)
    segment_id = make_segment_id(language, source)
    aligned_texts = list(aligned_texts or [])
    metadata = dict(metadata or {})
    stored_source = {k: v for k, v in source.items() if k != "text"}
    return {
        "schema": SEGMENT_SCHEMA,
        "segment_id": segment_id,
        "revision_id": make_revision_id(
            segment_id, text,
            metadata={"metadata": metadata, "source": stored_source},
            aligned_texts=aligned_texts,
        ),
        "language": language,
        "text": str(text or ""),
        "source": stored_source,
        "metadata": metadata,
        "aligned_texts": aligned_texts,
        "state": state,
    }


def build_occurrence(segment, ordinal, span, surface, scanner,
                     state="present"):
    """Build one immutable raw occurrence beneath ``segment``."""
    if not isinstance(segment, dict) or not segment.get("segment_id"):
        raise ValueError("segment with segment_id is required")
    start, end = list(span or [None, None])[:2]
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
        raise ValueError("span must be [start, end] character offsets")
    return {
        "schema": OCCURRENCE_SCHEMA,
        "occurrence_id": make_occurrence_id(segment["segment_id"], ordinal),
        "segment_id": segment["segment_id"],
        "segment_revision_id": segment["revision_id"],
        "language": segment["language"],
        "ordinal": ordinal,
        "span": [start, end],
        "surface": str(surface or ""),
        "scanner": str(scanner or ""),
        "state": state,
    }


def make_claim(layer, subject_kind, subject_id, operation, value, method,
               input_projection, confidence=None, input_refs=None,
               supersedes=None):
    """Build a versioned evidence claim.

    Competing methods coexist.  ``supersedes`` is only for a newer run in the
    same method lineage; a resolver/profile decides between different methods.
    """
    if operation not in ("assert", "abstain", "retract"):
        raise ValueError("unsupported claim operation: %s" % operation)
    method = dict(method or {})
    if not method.get("method_id") or not method.get("run_id"):
        raise ValueError("method requires method_id and run_id")
    input_fingerprint = semantic_fingerprint(input_projection)
    identity = {
        "layer": layer,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "operation": operation,
        "value": value,
        "method_id": method["method_id"],
        "run_id": method["run_id"],
        "input_fingerprint": input_fingerprint,
    }
    claim = {
        "schema": CLAIM_SCHEMA,
        "claim_id": stable_id("clm", "claim-id-v1", identity),
        "layer": str(layer),
        "subject": {"kind": str(subject_kind), "id": str(subject_id)},
        "operation": operation,
        "value": deepcopy(value),
        "method": method,
        "input_fingerprint": input_fingerprint,
        "input_refs": list(input_refs or []),
    }
    if confidence is not None:
        claim["confidence"] = float(confidence)
    if supersedes:
        claim["supersedes"] = sorted(set(supersedes))
    return claim


def claim_is_current(claim, input_projection):
    """Return whether a stored claim still matches its semantic inputs."""
    return claim.get("input_fingerprint") == semantic_fingerprint(input_projection)


def resolve_claims(claims, method_priority=None, minimum_confidence=0.0):
    """Resolve active claims per ``(layer, subject)`` without deleting history.

    Explicit retractions suppress claims they supersede.  Different methods are
    ranked by the caller's profile; run ID and claim ID provide deterministic
    tie-breaks.  A newer weak method therefore cannot silently overwrite an
    older trusted one.
    """
    method_priority = dict(method_priority or {})
    retracted = set()
    for claim in claims or []:
        if claim.get("operation") == "retract":
            retracted.update(claim.get("supersedes") or [])

    winners = {}
    for claim in claims or []:
        if claim.get("operation") != "assert":
            continue
        if claim.get("claim_id") in retracted:
            continue
        if float(claim.get("confidence", 1.0)) < minimum_confidence:
            continue
        subject = claim.get("subject") or {}
        key = (claim.get("layer"), subject.get("kind"), subject.get("id"))
        method = claim.get("method") or {}
        score = (
            int(method_priority.get(method.get("method_id"), 0)),
            str(method.get("run_id") or ""),
            str(claim.get("claim_id") or ""),
        )
        current = winners.get(key)
        if current is None or score > current[0]:
            winners[key] = (score, claim)
    return {key: value[1] for key, value in winners.items()}


def validate_wsd_input(record):
    """Validate the replaceable WSD input contract, including menu-free input."""
    if not isinstance(record, dict):
        raise ValueError("WSD input must be an object")
    if record.get("schema") != WSD_INPUT_SCHEMA:
        raise ValueError("unsupported WSD input schema")
    for key in ("analysis_unit_id", "occurrence_id", "language", "context"):
        if not record.get(key):
            raise ValueError("WSD input missing %s" % key)
    normalize_language(record["language"])
    inventory = record.get("inventory")
    if inventory is not None:
        if not isinstance(inventory, dict):
            raise ValueError("inventory must be an object or null")
        if not isinstance(inventory.get("candidates", []), list):
            raise ValueError("inventory candidates must be a list")
    return True


def validate_wsd_output(record):
    """Validate model-neutral assigned/abstain/proposed WSD output."""
    if not isinstance(record, dict):
        raise ValueError("WSD output must be an object")
    if record.get("schema") != WSD_OUTPUT_SCHEMA:
        raise ValueError("unsupported WSD output schema")
    for key in ("analysis_unit_id", "occurrence_id", "method_id", "decision"):
        if not record.get(key):
            raise ValueError("WSD output missing %s" % key)
    decision = record["decision"]
    if decision == "assigned":
        if not record.get("sense_id"):
            raise ValueError("assigned WSD output requires sense_id")
    elif decision == "proposed":
        proposed = record.get("proposed_sense")
        if not isinstance(proposed, dict):
            raise ValueError("proposed WSD output requires proposed_sense")
        for key in ("lemma", "pos", "translation"):
            if not proposed.get(key):
                raise ValueError("proposed sense missing %s" % key)
    elif decision != "abstain":
        raise ValueError("unsupported WSD decision: %s" % decision)
    return True


def write_jsonl_atomic(path, records):
    """Atomically write deterministic JSONL.  Returns record count + hash."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [canonical_json(record) for record in records]
    payload = ("\n".join(rows) + ("\n" if rows else "")).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return {"records": len(rows), "sha256": hashlib.sha256(payload).hexdigest()}


def read_jsonl(path):
    """Read a JSONL artifact, rejecting malformed or duplicate identities."""
    records = []
    seen = {}
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ValueError("invalid JSONL at %s:%d" % (path, line_no)) from exc
            identity = (
                # Most record types also carry their parent IDs. Prefer the
                # record's own identity so multiple occurrences beneath one
                # segment are not mistaken for divergent duplicate segments.
                record.get("claim_id") or record.get("occurrence_id")
                or record.get("segment_id")
            )
            if identity:
                prior = seen.get(identity)
                if prior is not None and prior != record:
                    raise ValueError("duplicate ID with divergent records: %s" % identity)
                seen[identity] = record
            records.append(record)
    return records


def build_run_manifest(run_id, layer, language, adapter, inputs, config,
                       artifacts, subject_fingerprints=None):
    """Build an immutable run manifest with explicit dependency fingerprints."""
    return {
        "schema": RUN_MANIFEST_SCHEMA,
        "run_id": str(run_id),
        "layer": str(layer),
        "language": normalize_language(language),
        "adapter": dict(adapter or {}),
        "inputs": dict(inputs or {}),
        "input_selection_hash": semantic_fingerprint(inputs or {}),
        "config_hash": semantic_fingerprint(config or {}),
        "artifacts": dict(artifacts or {}),
        "subject_fingerprints": dict(subject_fingerprints or {}),
        "immutable": True,
    }


def archive_json_artifact(evidence_dir, layer, payload, language="und",
                          adapter=None, inputs=None, config=None):
    """Archive a content-addressed compatibility layer and advance its pointer.

    This is the bridge for legacy JSON producers that have not yet been
    rewritten as granular claim writers. Re-running or forcing one of those
    tools no longer destroys its prior output: every distinct payload gets an
    immutable run while the small profile points at the selected snapshot.
    """
    evidence_dir = Path(evidence_dir)
    profile_path = evidence_dir / "profiles" / "current.json"
    profile = {}
    if profile_path.is_file():
        with open(profile_path, encoding="utf-8") as file:
            profile = json.load(file)
        if not isinstance(profile, dict):
            profile = {}
    effective_language = profile.get("language") or normalize_language(language)
    archived_payload = deepcopy(payload)
    if isinstance(archived_payload, dict) and isinstance(
            archived_payload.get("_meta"), dict):
        # Generation time is audit metadata, not semantic layer content. The
        # method/version remains in the snapshot and run manifest.
        archived_payload["_meta"].pop("generated_at", None)
    layer = str(layer)
    layer_dir = re.sub(r"[^A-Za-z0-9_.-]+", "__", layer).strip("_") or "layer"
    snapshot_hash = semantic_fingerprint(archived_payload)
    run_id = stable_id(
        "run", "compatibility-artifact-v1", layer, effective_language,
        snapshot_hash, adapter or {}, config or {},
    )
    run_dir = evidence_dir / "snapshots" / layer_dir / "runs" / run_id
    artifact_path = run_dir / "artifact.json"
    artifact_bytes = (canonical_json(archived_payload) + "\n").encode("utf-8")
    if artifact_path.is_file():
        if artifact_path.read_bytes() != artifact_bytes:
            raise ValueError("immutable artifact differs for run %s" % run_id)
    else:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=artifact_path.name + ".", dir=str(artifact_path.parent))
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(artifact_bytes)
            os.replace(temp_name, artifact_path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    artifact = {
        "records": (len(archived_payload)
                    if hasattr(archived_payload, "__len__") else None),
        "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
    }
    manifest = build_run_manifest(
        run_id,
        layer,
        effective_language,
        adapter or {"name": "legacy-json-bridge", "version": 1},
        inputs or {"payload": snapshot_hash},
        config or {},
        {"artifact.json": artifact},
    )
    manifest_path = run_dir / "manifest.json"
    manifest_bytes = (canonical_json(manifest) + "\n").encode("utf-8")
    if manifest_path.is_file() and manifest_path.read_bytes() != manifest_bytes:
        raise ValueError("immutable manifest differs for run %s" % run_id)
    if not manifest_path.exists():
        manifest_path.write_bytes(manifest_bytes)

    profile.update({
        "schema": profile.get("schema") or "fluency.evidence-profile/v1",
        "profile_id": profile.get("profile_id") or "current",
        "language": effective_language,
    })
    profile.setdefault("materialized_runs", {})[layer] = run_id
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_temp = profile_path.with_suffix(profile_path.suffix + ".tmp")
    profile_temp.write_text(canonical_json(profile) + "\n", encoding="utf-8")
    os.replace(profile_temp, profile_path)
    return {"run_id": run_id, "artifact": artifact, "path": str(run_dir)}
