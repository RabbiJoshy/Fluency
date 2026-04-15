"""Shared utilities for splitting surface-word assignments onto word|lemma keys.

Extracted from artist/step_7a_map_senses_to_lemmas.py so both normal-mode and
artist-mode pipelines can share the same split logic.
"""

from copy import deepcopy


def normalize_assignment_methods(raw_value):
    """Normalise a raw assignment value to {method: [items]} dict."""
    if isinstance(raw_value, dict):
        return {method: list(items or []) for method, items in raw_value.items()}
    if isinstance(raw_value, list):
        return {"legacy": list(raw_value)}
    return {}


def merge_items(existing, incoming):
    """Merge two lists of {sense, examples} items, deduplicating by sense ID."""
    merged = {}
    order = []
    for item in list(existing) + list(incoming):
        sense = item.get("sense")
        if not sense:
            continue
        examples = sorted(set(item.get("examples", [])))
        if sense not in merged:
            merged[sense] = {"sense": sense, "examples": examples}
            order.append(sense)
        else:
            merged[sense]["examples"] = sorted(set(merged[sense]["examples"]) | set(examples))
    return [merged[sense] for sense in order]


def merge_method_maps(existing, incoming):
    """Merge two method-keyed assignment dicts."""
    out = {method: list(items) for method, items in existing.items()}
    for method, items in incoming.items():
        if method not in out:
            out[method] = list(items)
        else:
            out[method] = merge_items(out[method], items)
    return out


def analysis_key(word, analysis):
    """Build a word|lemma key from a word and an analysis dict."""
    headword = analysis.get("headword")
    lemma = headword if isinstance(headword, str) and headword.strip() else word
    return "%s|%s" % (word, lemma)


def split_word_assignments(word, analyses, raw_value):
    """Split a surface-word assignment into per-analysis (word|lemma) keys.

    Uses sense IDs to determine which analysis owns each assignment item.
    Falls back to word|word (or word|inline_lemma) if no analyses are provided.

    Args:
        word: surface word string
        analyses: list of analysis dicts, each with {headword, senses: {id: ...}}
        raw_value: raw assignment value (dict or list)

    Returns:
        dict mapping word|lemma keys to method-keyed assignments
    """
    methods = normalize_assignment_methods(raw_value)
    if not methods:
        return {}

    # Check for inline lemma hint from assignment items
    inline_lemma = None
    for items in methods.values():
        for item in items:
            lemma = item.get("lemma")
            if isinstance(lemma, str) and lemma.strip():
                inline_lemma = lemma.strip()
                break
        if inline_lemma:
            break

    if not analyses:
        fallback_lemma = inline_lemma or word
        return {"%s|%s" % (word, fallback_lemma): deepcopy(methods)}

    # Build mapping: analysis_key -> set of sense IDs owned by that analysis
    analysis_maps = []
    for a in analyses:
        sense_map = a.get("senses", {})
        sense_ids = set(sense_map.keys()) if isinstance(sense_map, dict) else set()
        analysis_maps.append((analysis_key(word, a), sense_ids))

    # Split assignments by sense ID ownership
    split = {}
    for target_key, sense_ids in analysis_maps:
        target_methods = {}
        for method, items in methods.items():
            kept = []
            for item in items:
                sid = item.get("sense")
                if sid and sid in sense_ids:
                    kept.append({
                        "sense": sid,
                        "examples": sorted(set(item.get("examples", []))),
                    })
            if kept:
                target_methods[method] = kept
        if target_methods:
            split[target_key] = target_methods

    if split:
        return split

    # No sense IDs matched any analysis — fall back
    fallback_key = "%s|%s" % (word, inline_lemma or word)
    return {fallback_key: deepcopy(methods)}
