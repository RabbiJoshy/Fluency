"""Shared assembly helpers used by both normal-mode and artist-mode builders.

Functions:
    make_stable_id     — deterministic 6-char hex ID from word|lemma
    split_count_proportionally — distribute an integer total across weights
"""

import hashlib


def make_stable_id(word, lemma, used):
    """6-char hex ID from md5(word|lemma). On collision, slide the hash window."""
    h = hashlib.md5((word + "|" + lemma).encode("utf-8")).hexdigest()
    base_id = h[:6]

    if base_id not in used:
        return base_id

    for start in range(1, len(h) - 5):
        candidate = h[start:start + 6]
        if candidate not in used:
            return candidate

    val = int(base_id, 16) + 1
    while True:
        candidate = format(val % 0xFFFFFF, "06x")
        if candidate not in used:
            return candidate
        val += 1


def split_count_proportionally(total, weights):
    """Split an integer total across weights using largest remainder method."""
    if not weights:
        return []
    if total <= 0:
        return [0 for _ in weights]
    weight_sum = sum(weights)
    if weight_sum <= 0:
        base = total // len(weights)
        out = [base] * len(weights)
        for i in range(total - sum(out)):
            out[i] += 1
        return out
    raw = [total * w / weight_sum for w in weights]
    floors = [int(x) for x in raw]
    remainder = total - sum(floors)
    order = sorted(range(len(weights)),
                   key=lambda i: (raw[i] - floors[i], weights[i]),
                   reverse=True)
    for i in order[:remainder]:
        floors[i] += 1
    return floors
