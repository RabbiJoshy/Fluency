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
    "pos-flash-wiktionary": 60,       # POS-refined Gemini Flash
    "flash-wiktionary": 55,           # Gemini Flash classifier (artist)
    "spanishdict-flash": 55,          # Gemini Flash classifier (artist, SpanishDict menu)
    "pos-flash-lite-wiktionary": 52,  # POS-refined Gemini Flash Lite
    "flash-lite-wiktionary": 50,      # Gemini Flash Lite classifier (artist)
    "spanishdict-flash-lite": 50,     # Gemini Flash Lite classifier (artist, SpanishDict menu)
    "gap-fill": 50,                   # Gemini gap-fill for words not in Wiktionary
    "pos-gemini": 45,                 # POS-refined Gemini classifier
    "gemini": 40,                     # Gemini classifier (normal mode)
    "pos-biencoder": 35,              # POS-refined bi-encoder
    "biencoder": 30,                  # Bi-encoder cosine similarity
    "spanishdict-biencoder": 30,      # Bi-encoder cosine similarity on SpanishDict menu
    # pos-auto: per-example POS filter narrowed the menu to exactly one
    # sense, so we assign directly without running a classifier. Priority
    # sits above keyword (lexical overlap is weaker signal than a trusted
    # POS tag) and below biencoder (a real classifier on ambiguous POS is
    # still richer signal than a single-candidate default). Stamp written
    # by step_6b (keyword + biencoder branches) and step_6c (Gemini
    # pre-filter).
    "pos-auto": 25,
    "pos-keyword-wiktionary": 15,     # POS-refined keyword
    "pos-keyword": 15,                # POS-refined keyword
    "keyword-wiktionary": 10,         # Keyword overlap (with Wiktionary senses)
    "keyword": 10,                    # Keyword overlap (basic)
    "spanishdict-keyword": 10,        # Keyword overlap on SpanishDict menu
    "wiktionary-auto": 0,             # Single-sense default, always overwritable
    "spanishdict-auto": 0,            # Single-sense default for SpanishDict menu
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
    Supports:
      - {method: [assignments]}          (in-memory dict form)
      - [{"method": ..., ...}, ...]      (on-disk flat-list form)
      - []                               (empty)
    """
    if isinstance(word_assignments, dict):
        return max((METHOD_PRIORITY.get(m, 0) for m in word_assignments), default=0)
    if isinstance(word_assignments, list):
        return max(
            (METHOD_PRIORITY.get(e.get("method"), 0)
             for e in word_assignments if isinstance(e, dict)),
            default=0,
        )
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
