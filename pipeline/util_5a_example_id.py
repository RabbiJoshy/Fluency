"""
util_5a_example_id.py — Stable content-addressed ID for example sentences.

An example's ID is a 12-char hex SHA-256 digest of its (target, english) pair.
Using both sides of the pair means two sentences with the same target text but
different English translations get distinct IDs. The null-byte separator prevents
cross-field hash collisions.

Import this anywhere that needs to compute or verify example IDs.
"""

import hashlib


def example_id(target: str, english: str) -> str:
    """Return a 12-char stable ID for the (target, english) sentence pair.

    The ID is derived purely from content — the same sentence pair always
    produces the same ID, regardless of source corpus, run order, or when
    it was first discovered.
    """
    key = target.lower().strip() + "\0" + english.lower().strip()
    return hashlib.sha256(key.encode()).hexdigest()[:12]
