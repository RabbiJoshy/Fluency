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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serialized, f, ensure_ascii=False, indent=2)


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

    # ex_idx -> (priority, method, sense_id)
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
            for ex_idx in item.get("examples", []) or []:
                existing = best.get(ex_idx)
                if existing is None or prio > existing[0]:
                    best[ex_idx] = (prio, method, sid)

    # Regroup by sense_id with ex_idx-sorted example lists.
    out = {}
    for ex_idx in sorted(best.keys()):
        _, method, sid = best[ex_idx]
        out.setdefault(sid, []).append({"ex_idx": ex_idx, "method": method})
    return out
