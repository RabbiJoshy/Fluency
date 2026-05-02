"""
util_5a_example_id.py — Stable content-addressed ID for example sentences,
and the append-only example store that makes those IDs permanent.

An example's ID is a 12-char hex SHA-256 digest of its (target, english) pair.
Using both sides of the pair means two sentences with the same target text but
different English translations get distinct IDs. The null-byte separator prevents
cross-field hash collisions.

The example store (example_store.json) is a flat {id: example} dict that only
ever grows. step_5a and tool_5a_extend_examples both call update_example_store
after writing examples_raw.json. This means a --force rebuild can pick entirely
different examples without losing any previously-classified ones — they remain
findable by ID in the store regardless of which sentences are in the current
per-word list.

Import this anywhere that needs to compute IDs or maintain the store.
"""

import hashlib
import json
from pathlib import Path


def example_id(target: str, english: str) -> str:
    """Return a 12-char stable ID for the (target, english) sentence pair.

    The ID is derived purely from content — the same sentence pair always
    produces the same ID, regardless of source corpus, run order, or when
    it was first discovered.
    """
    key = target.lower().strip() + "\0" + english.lower().strip()
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def update_example_store(examples_by_word: dict, store_path: Path) -> tuple:
    """Merge examples into the append-only store at store_path.

    Reads the existing store (or starts empty), adds any example whose ID
    isn't already present, and writes back. Never removes entries.

    examples_by_word: the same dict written to examples_raw.json —
        {word: [{id, target, english, source, easiness}, ...]}

    Returns (added, total) — examples newly added, total entries in store.
    """
    store = {}
    if store_path.exists():
        with open(store_path, encoding="utf-8") as f:
            store = json.load(f)

    added = 0
    for examples in examples_by_word.values():
        for ex in examples:
            eid = ex.get("id")
            if not eid:
                continue
            # Only store corpus examples (target + english format).
            # Lyric examples (spanish / title format) have their own lyric ID
            # scheme and don't belong in the content-addressed store.
            target = ex.get("target")
            english = ex.get("english")
            if not target or not english:
                continue
            if eid not in store:
                store[eid] = {
                    "target": target,
                    "english": english,
                    "source": ex.get("source", ""),
                    "easiness": ex.get("easiness", 0),
                }
                added += 1

    store_path.parent.mkdir(parents=True, exist_ok=True)
    with open(store_path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)

    return added, len(store)
