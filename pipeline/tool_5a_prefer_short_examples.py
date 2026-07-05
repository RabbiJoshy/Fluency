#!/usr/bin/env python3
"""tool_5a_prefer_short_examples.py — reorder normal-mode example buckets so
short sentences display first (no data loss, order-only).

The original example picker force-included sentences containing other words
from the same study set, which biased toward long sentences at the FRONT of
each bucket even when short ones were available (~19 stored per word; 91% of
words have a <=8-word option). The front-end attaches buckets in stored order
(js/vocab.js `m.examples = ex.m[bucket]`), so a stable re-sort changes what
displays without touching content.

Stable sort key: sentences of <= SHORT_WORDS words keep their original
relative order at the front; longer ones are pushed back in length bands, so
the picker's original ranking still breaks ties.

In place, idempotent. Artist examples files are NOT touched (their order is
timestamp/song-based). Run from project root:

    .venv/bin/python3 pipeline/tool_5a_prefer_short_examples.py
"""
import json
import os

EXAMPLES = "Data/Spanish/vocabulary.examples.json"
SHORT_WORDS = 10   # <= this many words = "short enough", keep original order
BAND = 4           # longer sentences sort in bands of this many words


def band(row):
    n = len((row.get("target") or row.get("spanish") or "").split())
    if n <= SHORT_WORDS:
        return 0
    return 1 + (n - SHORT_WORDS - 1) // BAND


def main():
    if not os.path.isfile(EXAMPLES):
        raise SystemExit("not found: %s (run from project root)" % EXAMPLES)
    with open(EXAMPLES, encoding="utf-8") as f:
        data = json.load(f)

    buckets = moved = 0
    for node in data.values():
        for key in ("m", "w"):
            for group in (node.get(key) or []):
                if not isinstance(group, list) or len(group) < 2:
                    continue
                buckets += 1
                new = sorted(group, key=band)  # sorted() is stable
                if new != group:
                    moved += 1
                    group[:] = new

    print("buckets seen: %d, reordered: %d" % (buckets, moved))
    if moved:
        tmp = EXAMPLES + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, EXAMPLES)
        print("wrote %s" % EXAMPLES)
    else:
        print("no changes (already ordered)")


if __name__ == "__main__":
    main()
