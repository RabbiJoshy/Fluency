"""Serialization helpers for sense assignment files.

On-disk format (new):
    {
      "word": [
        {"sense": "abc", "examples": [0, 1], "method": "biencoder", "bucket": "classifiable"},
        {"sense": "def", "examples": [2],    "method": "gap-fill",  "bucket": "needs_sense_discovery",
         "pos": "NOUN", "translation": "...", "lemma": "...", "source": "gap-fill"},
        ...
      ],
      ...
    }

In-memory format (legacy, used by classifiers and consumers):
    {"word": {"method": [{"sense": ..., "examples": ..., ...}, ...], ...}}

This module handles conversion at the filesystem boundary. Callers continue
to manipulate the legacy dict-of-methods shape in Python; the helper flattens
on dump and unflattens on load (auto-detecting legacy files).

Buckets:
  - "classifiable":            the sense lives in the menu (wiktionary, spanishdict).
  - "needs_sense_discovery":   the word has no menu entry; method invented
                               senses inline (gap-fill*).
"""

import json
import re
from pathlib import Path

try:  # Package import in tests/tools; script import in pipeline entry points.
    from .util_6a_method_priority import METHOD_PRIORITY
    from .util_6a_prompt_registry import capability_tier, load_registry
    from .util_evidence_store import archive_json_artifact
except ImportError:  # pragma: no cover - exercised by direct script execution
    from util_6a_method_priority import METHOD_PRIORITY
    from util_6a_prompt_registry import capability_tier, load_registry
    from util_evidence_store import archive_json_artifact


# A proposed gloss is a proper-noun *label* — not a translation — when Gemini
# recognises the word is a name/place/brand but has no tag slot to say so, and
# writes the category into the translation field ("proper noun", "proper name",
# "proper noun (name of soccer player)", "Name of a social media app"). These
# should route to Extra as proper nouns, not render as main-deck translations.
# Deliberately narrow: a real gloss that merely CONTAINS "name" (nombre→"name")
# must NOT match, so we anchor on the "proper …" prefix and the "name of …" lead.
_PROPER_NOUN_GLOSS_RE = re.compile(
    r"^\s*(?:a |an |the )?proper[\s-]*(?:noun|name)\b"
    r"|^\s*(?:the )?name of\b",
    re.I,
)


def is_proper_noun_gloss(translation):
    """True if a proposed translation is really a proper-noun label.

    Catches the ``proper noun`` / ``proper name`` / ``Name of …`` family that
    Gemini emits for names it can't translate. A ``type == "proper_noun"`` stamp
    (from the next-run prompt) is a separate, stronger signal the caller may also
    check; this handles the legacy translation-field form.
    """
    if not translation or not isinstance(translation, str):
        return False
    return bool(_PROPER_NOUN_GLOSS_RE.match(translation.strip()))


# Gemini answers PROPN, but has also been observed returning the spelled-out
# PROPER_NOUN. Both mean the same thing; PROPN is the canonical UD tag used
# everywhere else in the pipeline and by the front end's POS colouring.
_POS_ALIASES = {"PROPER_NOUN": "PROPN", "PROPERNOUN": "PROPN"}
PROPER_NOUN_POS = frozenset({"PROPN"})


def normalize_pos(pos):
    """Canonicalise a POS tag coming from a model proposal."""
    if not pos or not isinstance(pos, str):
        return pos
    cleaned = pos.strip()
    return _POS_ALIASES.get(cleaned.upper(), cleaned)


# The classify-or-propose prompt stamps a `type` on off-menu proposals
# (slang|regional|figurative|vulgar|loanword|proper_noun|other) and may carry a
# `construction`. These are bonus metadata: the word should normally have been
# excluded by word routing, so a tag here is the backstop telling us routing
# missed one, plus useful register information for the card.
_SENSE_TAG_FIELDS = ("type", "construction")


def carry_sense_tags(target, sense):
    """Copy a sense's model-assigned tags onto an outgoing meaning dict.

    Mirrors ``carry_sense_identity``: assembly rebuilds meanings as fresh dicts
    of ``pos``/``translation``, so anything not explicitly carried is dropped.
    """
    if not isinstance(target, dict) or not isinstance(sense, dict):
        return target
    for key in _SENSE_TAG_FIELDS:
        value = sense.get(key)
        if value:
            target[key] = value
    return target


def is_proper_noun_sense(sense):
    """True if a sense denotes a proper noun, by tag, POS, or gloss shape.

    Order matters. The ``type`` stamp and the PROPN part of speech are what the
    model actually asserts, so they are checked first; the gloss regex is only a
    fallback for the legacy form where the category was written into the
    translation. Checking the regex first would perversely recognise a *useless*
    gloss ("proper noun") while missing a *good* one ("The Beatles (band)").
    """
    if not isinstance(sense, dict):
        return False
    if sense.get("type") == "proper_noun":
        return True
    if normalize_pos(sense.get("pos")) in PROPER_NOUN_POS:
        return True
    return is_proper_noun_gloss(sense.get("translation"))


# Methods that discover senses absent from the menu. Items written by these
# methods carry the inline sense definition (pos, translation, lemma, source)
# alongside the {sense, examples} fields.
_DISCOVERY_METHODS = {"gap-fill", "gap-fill-batch"}


def method_to_bucket(method):
    """Return the assignment bucket ('classifiable' or 'needs_sense_discovery')."""
    return "needs_sense_discovery" if method in _DISCOVERY_METHODS else "classifiable"


def flatten_word_data(word_data):
    """Convert {method: [items]} to a flat list with method + bucket stamps.

    Preserves any extra fields already on each item (translation, pos, lemma,
    source, ...). Skips malformed items that are not dicts.
    """
    out = []
    if not isinstance(word_data, dict):
        return out
    for method, items in word_data.items():
        bucket = method_to_bucket(method)
        for item in items or []:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            entry["method"] = method
            entry["bucket"] = bucket
            out.append(entry)
    return out


def unflatten_word_entries(entries, default_method="legacy"):
    """Convert a flat list back to {method: [items]}.

    Strips the method/bucket markers from each item. Entries without a method
    field are grouped under default_method.
    """
    out = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        method = entry.get("method") or default_method
        item = {k: v for k, v in entry.items() if k not in ("method", "bucket")}
        out.setdefault(method, []).append(item)
    return out


def load_assignments(path):
    """Load an assignments file and return the legacy {word: {method: [items]}} form.

    Auto-detects on-disk format so old files still read cleanly:
      - new:    payload is a list of entries.
      - legacy: payload is a {method: [items]} dict.
    Empty / malformed payloads become {}.
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for word, payload in raw.items():
        if isinstance(payload, list):
            out[word] = unflatten_word_entries(payload)
        elif isinstance(payload, dict):
            out[word] = {m: list(items or []) for m, items in payload.items()}
        else:
            out[word] = {}
    return out


def dump_assignments(word_dict, path):
    """Serialize ``{word: {method: [items]}}`` to disk in the same shape.

    Items keep only ``sense``/``examples`` (and any sense-definition fields
    used by discovery methods). The per-item ``method`` and ``bucket``
    stamps are omitted — method is the dict key; bucket is derivable from
    method via ``method_to_bucket`` when needed.

    ``load_assignments`` still auto-detects this dict form AND the legacy
    flat-list form, so older files keep loading.
    """
    serialized = {}
    for word, data in word_dict.items():
        if isinstance(data, list):
            # Legacy in-memory form passed in as flat list — normalise.
            data = unflatten_word_entries(data)
        if not isinstance(data, dict):
            continue
        methods = {}
        for method, items in data.items():
            clean = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                clean.append({k: v for k, v in item.items()
                              if k not in ("method", "bucket")})
            if clean:
                methods[method] = clean
        if methods:
            serialized[word] = methods
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serialized, f, ensure_ascii=False, indent=2)
    path_obj = Path(path).resolve()
    if (path_obj.parent.name in ("sense_assignments", "sense_assignments_lemma")
            and path_obj.parent.parent.name == "layers"):
        evidence_dir = path_obj.parents[2] / "evidence"
        language = "und"
        if len(path_obj.parents) > 4 and path_obj.parents[2].name == "data":
            language = path_obj.parents[4].name
        elif len(path_obj.parents) > 2:
            language = path_obj.parents[2].name
        archive_json_artifact(
            evidence_dir,
            "%s/%s" % (path_obj.parent.name, path_obj.stem),
            serialized,
            language=language,
            adapter={"name": "dump_assignments", "version": 1},
        )


def example_identity(example):
    """Primary identity for a teaching example, with legacy compatibility."""
    if not isinstance(example, dict):
        return None
    return example.get("segment_id") or example.get("id")


def index_examples_by_identity(examples):
    """Index both ledger and legacy IDs during the additive migration."""
    result = {}
    for example in examples or []:
        if not isinstance(example, dict):
            continue
        for identity in (example.get("segment_id"), example.get("id")):
            if identity:
                result.setdefault(identity, example)
    return result


def resolve_example_reference(entry, examples, identity_index=None):
    """Resolve an assignment row without silently trusting a stale index.

    Once a stable ID is present it is authoritative: if that source segment no
    longer exists, return ``None`` rather than falling back to a numeric index
    which may now name a different lyric. Index-only legacy rows continue to
    work until migrated.
    """
    if isinstance(entry, dict):
        stable_identity = entry.get("ex_id") or entry.get("example_id")
        ex_idx = entry.get("ex_idx")
    else:
        stable_identity = None
        ex_idx = entry
    if stable_identity:
        identity_index = identity_index or index_examples_by_identity(examples)
        return identity_index.get(stable_identity)
    if isinstance(ex_idx, int) and 0 <= ex_idx < len(examples):
        return examples[ex_idx]
    return None


def resolve_routing_references(entries, examples):
    """Materialize stable unassigned-routing rows as current legacy indices."""
    identity_index = {
        identity: index
        for index, example in enumerate(examples or [])
        if isinstance(example, dict)
        for identity in (example.get("segment_id"), example.get("id"))
        if identity
    }
    resolved = []
    for entry in entries or []:
        if isinstance(entry, dict):
            stable_identity = entry.get("example_id") or entry.get("segment_id")
            if stable_identity:
                index = identity_index.get(stable_identity)
                if index is not None:
                    resolved.append(index)
                continue
            index = entry.get("example_index")
        else:
            index = entry
        if isinstance(index, int) and 0 <= index < len(examples):
            resolved.append(index)
    return list(dict.fromkeys(resolved))


def stamp_example_ids(assignments_out, examples_raw):
    """Add stable example/occurrence references to new assignment items.

    Call on assignments_out just before merging into the on-disk file.
    Idempotent — items already carrying example_ids are left untouched.

    assignments_out : {word: {method: [items]}}  (legacy in-memory shape)
    examples_raw    : {word: [{id, target, english, ...}]}  — the full
                      examples_raw.json dict loaded earlier in the caller.
                      Each example must already have an 'id' field (Phase 1).
                      Artist evidence may additionally carry ``occurrence_ids``.
    """
    for word, methods in assignments_out.items():
        word_examples = examples_raw.get(word, [])
        idx_to_id = {i: example_identity(ex) for i, ex in enumerate(word_examples)}

        items_iter = (
            methods.values() if isinstance(methods, dict) else [methods]
        )
        for item_list in items_iter:
            for item in item_list or []:
                if not isinstance(item, dict):
                    continue
                example_indices = [
                    i for i in (item.get("examples") or []) if isinstance(i, int)
                ]
                if "example_ids" not in item:
                    # Preserve positional alignment even for malformed legacy
                    # examples. A missing ID must not shift every later ID onto
                    # the wrong integer index.
                    item["example_ids"] = [idx_to_id.get(i) for i in example_indices]

                if "occurrence_refs" not in item:
                    refs = []
                    for ex_idx in example_indices:
                        if not (0 <= ex_idx < len(word_examples)):
                            continue
                        example = word_examples[ex_idx]
                        for occurrence_id in example.get("occurrence_ids") or []:
                            if not occurrence_id:
                                continue
                            refs.append({
                                "occurrence_id": occurrence_id,
                                "example_id": example_identity(example),
                                "example_index": ex_idx,
                            })
                    if refs:
                        # The flat field is convenient for audits/adapters; the
                        # structured refs retain the compatibility example join.
                        item["occurrence_refs"] = refs
                        item["occurrence_ids"] = list(dict.fromkeys(
                            ref["occurrence_id"] for ref in refs
                        ))


def stamp_provenance(assignments_out, prompt_id, run_ts, methods=None):
    """Stamp ``prompt_id`` + ``run_ts`` onto every item that lacks a ``prompt_id``.

    Records which prompt/model run produced each assignment so the display
    resolver and the card UI can trace it. Idempotent — items already carrying a
    ``prompt_id`` are left untouched, so re-running never relabels prior runs.

    assignments_out : {word: {method: [items]}}  (legacy in-memory shape)
    prompt_id       : the registry join key for THIS run (e.g. "sd-cop-v2")
    run_ts          : ISO-8601 timestamp string for this run
    """
    if not prompt_id:
        return
    selected_methods = None if methods is None else set(methods)
    for _word, method_map in assignments_out.items():
        items_iter = (
            ((items for method, items in method_map.items()
              if selected_methods is None or method in selected_methods)
             if isinstance(method_map, dict) else [method_map])
        )
        for item_list in items_iter:
            for item in item_list or []:
                if not isinstance(item, dict) or item.get("prompt_id"):
                    continue
                item["prompt_id"] = prompt_id
                if run_ts:
                    item["run_ts"] = run_ts


def resolve_best_per_example(word_data, min_priority=0, method_priority=None,
                             min_prompt_tier=0, prompt_registry=None,
                             accepted_model_prompt_ids=None):
    """Resolve per-example winners from a word's {method: [items]} dict.

    For each occurrence (or stable example ID, then legacy index) encountered,
    picks the highest-priority method/sense pairing that claimed it.

    ``min_priority``: methods with priority strictly below this value are
    ignored entirely — their claims don't participate in the resolution and
    the examples they'd have covered become unclaimed (eligible for the
    remainder/orphan pool in the builder). Default 0 keeps every method.

    ``method_priority`` optionally overlays the built-in priorities, allowing
    an active evidence profile to rank arbitrary adapter method IDs.

    Returns ``{sense_id: [{"ex_idx": int, "method": str}, ...]}`` with
    example lists sorted by ex_idx. The result groups per-sense so an
    assembler can produce one meaning per sense with examples carrying
    their own winning method.

    Items without a ``sense`` field are skipped. Empty / malformed input
    returns ``{}``.
    """
    if not isinstance(word_data, dict) or not word_data:
        return {}

    # Stable evidence identity ->
    # (priority, method, sense_id, ex_idx, ex_id, occurrence_id, prompt_id, run_ts)
    priority_map = dict(METHOD_PRIORITY)
    priority_map.update(method_priority or {})
    registry = prompt_registry if prompt_registry is not None else load_registry()
    best = {}
    for method, items in word_data.items():
        prio = priority_map.get(method, 0)
        # Auto-assignments (single-sense words) are exempt from the
        # min-priority filter: they're "trivially correct" (only one
        # sense exists) rather than "low-quality classification", so
        # filtering them out produces empty cards for no good reason.
        # A real classifier's claim still wins over an auto claim at
        # per-example resolution because prio=0 < any real priority.
        is_auto = method.endswith("-auto")
        if prio < min_priority and not is_auto:
            continue
        for item in items or []:
            if not isinstance(item, dict):
                continue
            sid = item.get("sense")
            if not sid:
                continue
            # Model admission is an explicit prompt-id allowlist. Numeric tiers
            # survive only as an opt-in compatibility fallback for old callers.
            # Deterministic and explicitly retained evidence is exempt because
            # no model prompt authored those decisions.
            is_retained = method.startswith("legacy-") and method.endswith("-v1")
            if (accepted_model_prompt_ids is not None
                    and not is_auto and not is_retained):
                if item.get("prompt_id") not in accepted_model_prompt_ids:
                    continue
            elif min_prompt_tier and not is_auto and not is_retained:
                if capability_tier(item.get("prompt_id"), registry) < min_prompt_tier:
                    continue
            # Provenance join keys (may be absent on pre-backfill data). Carried
            # through additively — they do NOT participate in winner selection
            # here; the winner is still highest method priority.
            # Historical writers stamped the surrounding Gemini run onto
            # deterministic auto claims. Do not surface that as model
            # authorship; retained adapters are likewise non-prompt evidence.
            prompt_id = None if (is_auto or is_retained) else item.get("prompt_id")
            run_ts = None if (is_auto or is_retained) else item.get("run_ts")
            examples = item.get("examples") or []
            example_ids = item.get("example_ids") or []
            # Map integer index -> stable ID (positional alignment).
            idx_to_id = {
                ex: example_ids[i]
                for i, ex in enumerate(examples)
                if i < len(example_ids) and example_ids[i]
            }
            occurrence_refs = item.get("occurrence_refs") or []
            evidence_rows = []
            if occurrence_refs:
                for ref in occurrence_refs:
                    if not isinstance(ref, dict) or not ref.get("occurrence_id"):
                        continue
                    evidence_rows.append((
                        ("occurrence", ref["occurrence_id"]),
                        ref.get("example_index"),
                        ref.get("example_id"),
                        ref["occurrence_id"],
                    ))
            else:
                for ex_idx in examples:
                    ex_id = idx_to_id.get(ex_idx)
                    evidence_rows.append((
                        (("example", ex_id) if ex_id else ("index", ex_idx)),
                        ex_idx,
                        ex_id,
                        None,
                    ))

            for evidence_key, ex_idx, ex_id, occurrence_id in evidence_rows:
                existing = best.get(evidence_key)
                if existing is None or prio > existing[0]:
                    best[evidence_key] = (
                        prio, method, sid, ex_idx, ex_id, occurrence_id,
                        prompt_id, run_ts,
                    )

    # Regroup by sense_id with ex_idx-sorted example lists.
    out = {}
    grouped = {}
    for evidence_key in sorted(best.keys(), key=lambda value: canonical_evidence_key(value)):
        (_, method, sid, ex_idx, ex_id, occurrence_id,
         prompt_id, run_ts) = best[evidence_key]
        display_key = (sid, ex_id if ex_id else ("index", ex_idx), method,
                       prompt_id, run_ts)
        entry = grouped.get(display_key)
        if entry is None:
            entry = {"ex_idx": ex_idx, "method": method}
            grouped[display_key] = entry
        if ex_id:
            entry["ex_id"] = ex_id
        if occurrence_id:
            entry.setdefault("occurrence_ids", []).append(occurrence_id)
        if prompt_id:
            entry["prompt_id"] = prompt_id
        if run_ts:
            entry["run_ts"] = run_ts
    for (sid, _display, _method, _prompt, _run), entry in grouped.items():
        if entry.get("occurrence_ids"):
            entry["occurrence_ids"] = sorted(set(entry["occurrence_ids"]))
        out.setdefault(sid, []).append(entry)
    for entries in out.values():
        entries.sort(key=lambda entry: (
            str(entry.get("ex_id") or ""),
            entry.get("ex_idx") if isinstance(entry.get("ex_idx"), int) else -1,
        ))
    return out


def canonical_evidence_key(value):
    """Stable cross-type sort key for an internal evidence identity tuple."""
    if isinstance(value, tuple):
        return "%s:%s" % (value[0], value[1])
    return str(value)
