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


def _is_phrase_only_self_analysis(word, analysis):
    """True if analysis's headword equals the surface word AND all its senses are PHRASE.

    SpanishDict publishes a "phrasebook" analysis for common conjugated forms
    (e.g. ``está`` with senses "he's", "she's" all tagged POS=PHRASE) alongside
    the real verb analysis (headword=``estar``). The phrasebook headword is the
    surface form itself, which is not a true lemma.
    """
    headword = (analysis.get("headword") or "").strip().lower()
    if not headword or headword != word.lower():
        return False
    senses = analysis.get("senses", {})
    if not isinstance(senses, dict) or not senses:
        return False
    return all(
        isinstance(s, dict) and s.get("pos") == "PHRASE"
        for s in senses.values()
    )


def analysis_key(word, analysis, known_lemmas=None):
    """Build a word|lemma key from a word and an analysis dict.

    If the analysis is a phrasebook self-analysis (headword == surface word,
    all senses POS=PHRASE) and the inventory's ``known_lemmas`` contain a real
    lemma distinct from the surface word, the phrase senses are routed under
    that lemma instead (so e.g. ``está`` phrase senses merge into ``está|estar``
    rather than creating a dead ``está|está`` entry).
    """
    headword = analysis.get("headword")
    default_lemma = headword if isinstance(headword, str) and headword.strip() else word

    if known_lemmas:
        lemmas_lower = {kl.lower() for kl in known_lemmas if isinstance(kl, str) and kl.strip()}
        if (default_lemma.lower() not in lemmas_lower
                and _is_phrase_only_self_analysis(word, analysis)):
            # Use the first real lemma from the inventory (corpus-derived,
            # so it reflects how this surface word is actually used).
            for kl in known_lemmas:
                if isinstance(kl, str) and kl.strip():
                    return "%s|%s" % (word, kl)

    return "%s|%s" % (word, default_lemma)


def split_word_assignments(word, analyses, raw_value, known_lemmas=None):
    """Split a surface-word assignment into per-analysis (word|lemma) keys.

    Uses sense IDs to determine which analysis owns each assignment item.
    Falls back to word|word (or word|inline_lemma) if no analyses are provided.

    Args:
        word: surface word string
        analyses: list of analysis dicts, each with {headword, senses: {id: ...}}
        raw_value: raw assignment value (dict or list)
        known_lemmas: optional list of corpus-derived lemmas for the surface
            word (from word_inventory.json). When provided, phrasebook
            self-analyses are folded into the first known lemma instead of
            creating a ``word|word`` entry.

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
        analysis_maps.append((analysis_key(word, a, known_lemmas=known_lemmas), sense_ids))

    # Collapse reflexive/pronominal analyses into base form when both exist.
    # E.g. fumar|fumarse -> fumar|fumar when fumar is also a lemma in this set.
    all_lemmas = {key.split('|', 1)[1] for key, _ in analysis_maps}
    redirects = {lem: lem[:-2] for lem in all_lemmas if lem.endswith('se') and lem[:-2] in all_lemmas}
    if redirects:
        analysis_maps = [
            ('%s|%s' % (word, redirects.get(key.split('|', 1)[1], key.split('|', 1)[1])), sids)
            for key, sids in analysis_maps
        ]

    # Collapse PHRASE self-analyses (word|word) into the first real lemma when
    # other lemmas exist — handles cases where known_lemmas is absent.
    self_key = '%s|%s' % (word, word)
    other_lemmas = [key.split('|', 1)[1] for key, _ in analysis_maps if key != self_key]
    if self_key in {k for k, _ in analysis_maps} and other_lemmas:
        analysis_maps = [
            ('%s|%s' % (word, other_lemmas[0]) if key == self_key else key, sids)
            for key, sids in analysis_maps
        ]

    # Split assignments by sense ID ownership. Multiple analyses can resolve
    # to the same key (e.g. a phrasebook analysis folded into its verb lemma's
    # key), so merge rather than overwrite on collision.
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
            if target_key in split:
                split[target_key] = merge_method_maps(split[target_key], target_methods)
            else:
                split[target_key] = target_methods

    if split:
        return split

    # No sense IDs matched any analysis — fall back
    fallback_key = "%s|%s" % (word, inline_lemma or word)
    return {fallback_key: deepcopy(methods)}
