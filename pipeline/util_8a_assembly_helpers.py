"""Shared assembly helpers used by both normal-mode and artist-mode builders.

Functions:
    make_stable_id     — deterministic 6-char hex ID from word|lemma
    split_count_proportionally — distribute an integer total across weights
"""

import hashlib


SURFACE_ID_NAMESPACE = "surface/v2:"
SURFACE_ID_LENGTH = 8


def make_surface_id(surface, used):
    """Card ID for a surface-keyed card.

    Two deliberate differences from make_stable_id, both learned the hard way:

    * The scheme name is inside the hashed string. md5("word|lemma") and
      md5("surface|surface") otherwise draw from one namespace, so 1,162 of the
      new IDs collided with existing ones — which is what made the word|lemma
      migration unsafe to run twice. Namespacing drops that to 6; the extra two
      hex characters take it to 0.
    * Eight hex characters, not six. At six, ~10k surfaces produce real
      birthday collisions, and make_stable_id resolves them by sliding the hash
      window — which makes an ID depend on what was assigned before it. That
      order dependence silently parked `brillantes` on `laboratorio`'s card.
      At eight the collision path is effectively never taken, so an ID is a
      pure function of its surface.

    The fallback is kept anyway; an ID that depends on insertion order is still
    better than two cards sharing one.
    """
    digest = hashlib.md5(
        (SURFACE_ID_NAMESPACE + surface).encode("utf-8")).hexdigest()
    base_id = digest[:SURFACE_ID_LENGTH]
    if base_id not in used:
        return base_id
    for start in range(1, len(digest) - SURFACE_ID_LENGTH + 1):
        candidate = digest[start:start + SURFACE_ID_LENGTH]
        if candidate not in used:
            return candidate
    val = int(base_id, 16) + 1
    limit = 16 ** SURFACE_ID_LENGTH
    while True:
        candidate = format(val % limit, "0%dx" % SURFACE_ID_LENGTH)
        if candidate not in used:
            return candidate
        val += 1


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
