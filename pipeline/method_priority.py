#!/usr/bin/env python3
"""
method_priority.py — Shared priority system for sense assignments and translations.

Both the artist pipeline and normal-mode pipeline import from here.
Higher number = higher quality. Scripts should skip words that already have
an assignment from an equal or higher-priority method.
"""

import hashlib

# ---------------------------------------------------------------------------
# Sense assignment method priority
# ---------------------------------------------------------------------------

METHOD_PRIORITY = {
    "pos-flash-lite-wiktionary": 55,  # POS-refined Gemini Flash Lite
    "flash-lite-wiktionary": 50,      # Gemini Flash Lite classifier (artist)
    "gap-fill": 50,                   # Gemini gap-fill for words not in Wiktionary
    "pos-gemini": 45,                 # POS-refined Gemini classifier
    "gemini": 40,                     # Gemini classifier (normal mode)
    "pos-biencoder": 35,              # POS-refined bi-encoder
    "biencoder": 30,                  # Bi-encoder cosine similarity
    "pos-keyword-wiktionary": 15,     # POS-refined keyword
    "pos-keyword": 15,                # POS-refined keyword
    "keyword-wiktionary": 10,         # Keyword overlap (with Wiktionary senses)
    "keyword": 10,                    # Keyword overlap (basic)
    "wiktionary-auto": 0,             # Single-sense default, always overwritable
}

# ---------------------------------------------------------------------------
# Translation source priority
# ---------------------------------------------------------------------------

TRANSLATION_PRIORITY = {
    "gemini": 50,      # LLM re-translation of bad output
    "genius": 40,      # Fan translations (good but inconsistent)
    "google": 10,      # Raw Google Translate
}


# ---------------------------------------------------------------------------
# Priority helpers
# ---------------------------------------------------------------------------

def best_method_priority(word_assignments):
    """Return the highest method priority for a word's existing assignments.

    word_assignments: the value from sense_assignments.json for one word.
    Can be a dict of {method: [assignments]} (new format) or a list (old format).
    """
    if isinstance(word_assignments, dict):
        return max((METHOD_PRIORITY.get(m, 0) for m in word_assignments), default=0)
    return 0


# ---------------------------------------------------------------------------
# Sense ID helpers
# ---------------------------------------------------------------------------

def make_sense_id(pos, translation):
    """Generate a stable content-hash ID for a sense.

    Derived from pos + translation so the same sense always gets the same ID.
    Returns 3-char hex string. Caller handles collisions by extending length.
    """
    return hashlib.md5(("%s|%s" % (pos, translation)).encode("utf-8")).hexdigest()[:3]


def assign_sense_ids(senses_list):
    """Assign stable content-hash IDs to a list of sense dicts.

    Returns dict of {sense_id: sense_dict}. Extends ID length on collision.
    """
    result = {}
    for s in senses_list:
        full_hash = hashlib.md5(
            ("%s|%s" % (s["pos"], s["translation"])).encode("utf-8")
        ).hexdigest()
        for length in range(3, len(full_hash) + 1):
            sid = full_hash[:length]
            if sid not in result:
                break
        result[sid] = s
    return result
