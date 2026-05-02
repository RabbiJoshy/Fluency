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
from pathlib import Path

from util_6a_method_priority import METHOD_PRIORITY


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


def stamp_example_ids(assignments_out, examples_raw):
    """Add 'example_ids' to every new assignment item that lacks it.

    Call on assignments_out just before merging into the on-disk file.
    Idempotent — items already carrying example_ids are left untouched.

    assignments_out : {word: {method: [items]}}  (legacy in-memory shape)
    examples_raw    : {word: [{id, target, english, ...}]}  — the full
                      examples_raw.json dict loaded earlier in the caller.
                      Each example must already have an 'id' field (Phase 1).
    """
    for word, methods in assignments_out.items():
        word_examples = examples_raw.get(word, [])
        idx_to_id = {i: ex.get("id") for i, ex in enumerate(word_examples)}

        items_iter = (
            methods.values() if isinstance(methods, dict) else [methods]
        )
        for item_list in items_iter:
            for item in item_list or []:
                if not isinstance(item, dict) or "example_ids" in item:
                    continue
                item["example_ids"] = [
                    idx_to_id[i] for i in item.get("examples") or []
                    if i in idx_to_id and idx_to_id[i]
                ]


def resolve_best_per_example(word_data, min_priority=0):
    """Resolve per-example winners from a word's {method: [items]} dict.

    For each example index encountered, picks the highest-priority (method,
    sense) pairing that claimed it. Lower-priority conflicting claims are
    dropped; non-conflicting claims from different methods are all kept.

    ``min_priority``: methods with priority strictly below this value are
    ignored entirely — their claims don't participate in the resolution and
    the examples they'd have covered become unclaimed (eligible for the
    remainder/orphan pool in the builder). Default 0 keeps every method.

    Returns ``{sense_id: [{"ex_idx": int, "method": str}, ...]}`` with
    example lists sorted by ex_idx. The result groups per-sense so an
    assembler can produce one meaning per sense with examples carrying
    their own winning method.

    Items without a ``sense`` field are skipped. Empty / malformed input
    returns ``{}``.
    """
    if not isinstance(word_data, dict) or not word_data:
        return {}

    # ex_idx -> (priority, method, sense_id, ex_id_or_None)
    best = {}
    for method, items in word_data.items():
        prio = METHOD_PRIORITY.get(method, 0)
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
            examples = item.get("examples") or []
            example_ids = item.get("example_ids") or []
            # Map integer index -> stable ID (positional alignment).
            idx_to_id = {
                ex: example_ids[i]
                for i, ex in enumerate(examples)
                if i < len(example_ids) and example_ids[i]
            }
            for ex_idx in examples:
                existing = best.get(ex_idx)
                if existing is None or prio > existing[0]:
                    best[ex_idx] = (prio, method, sid, idx_to_id.get(ex_idx))

    # Regroup by sense_id with ex_idx-sorted example lists.
    out = {}
    for ex_idx in sorted(best.keys()):
        _, method, sid, ex_id = best[ex_idx]
        entry = {"ex_idx": ex_idx, "method": method}
        if ex_id:
            entry["ex_id"] = ex_id
        out.setdefault(sid, []).append(entry)
    return out
