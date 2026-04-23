#!/usr/bin/env python3
"""Wiktionary inflection tags -> verbecc-style {mood, tense, person} triples.

Wiktionary's kaikki dump tags every form-of sense with English-language
inflection labels (``indicative``, ``present``, ``third-person``,
``singular`` ...). The front-end already speaks the verbecc dialect
(``indicativo``, ``presente``, ``3s`` ...), so we normalise tags into the
same shape on import. One shared formatter then renders both sources.

Public surface:

    tags_to_morphology(tags) -> dict | list[dict] | None
        ``dict`` for unambiguous forms, ``list[dict]`` for syncretic forms
        where one surface covers multiple person/number slots (1s/3s
        subjunctive imperfect being the classic example), ``None`` when the
        tags carry no inflection signal.
"""

# Non-finite tags trump finite ones: ``infinitive`` + an erroneous extra
# ``present`` tag should still resolve to the infinitive entry rather than
# fabricating an indicativo/presente row.
_NONFINITE = {
    "infinitive": ("infinitivo", "infinitivo"),
    "gerund": ("gerundio", "gerundio"),
    "participle": ("participo", "participo"),
}

# (verbecc mood, wiktionary tense tag) -> verbecc tense slot.
# Subjunctive imperfect splits into -ra (-1) and -se (-2) in verbecc, but
# Wiktionary doesn't disambiguate. We collapse to ``pretérito-imperfecto``
# and let the front-end render "imperf" identically either way.
_TENSE_BY_MOOD = {
    ("indicativo", "present"): "presente",
    ("indicativo", "preterite"): "pretérito-perfecto-simple",
    ("indicativo", "imperfect"): "pretérito-imperfecto",
    ("indicativo", "future"): "futuro",
    ("subjuntivo", "present"): "presente",
    ("subjuntivo", "imperfect"): "pretérito-imperfecto",
    ("subjuntivo", "future"): "futuro",
    ("subjuntivo", "preterite"): "pretérito-perfecto-simple",
}

_PERSON_DIGIT = {
    "first-person": "1",
    "second-person": "2",
    "third-person": "3",
}


def tags_to_morphology(tags):
    """Convert a Wiktionary tag list to verbecc-style morphology.

    Returns ``None`` when tags don't describe a finite/non-finite verb form.
    Returns a single ``{mood, tense, person?}`` dict when unambiguous.
    Returns a list of such dicts when the tag set encodes multiple
    person/number slots (syncretic forms).
    """
    tagset = set(tags or [])

    for nf_tag, (mood, tense) in _NONFINITE.items():
        if nf_tag in tagset:
            return {"mood": mood, "tense": tense}

    if "conditional" in tagset:
        mood, tense = "condicional", "presente"
    elif "subjunctive" in tagset:
        mood, tense = "subjuntivo", None
    elif "imperative" in tagset:
        mood = "imperativo"
        tense = "negativo" if "negative" in tagset else "afirmativo"
    elif "indicative" in tagset:
        mood, tense = "indicativo", None
    elif any(t in tagset for t in ("present", "preterite", "imperfect", "future")):
        # Tense tag without explicit mood — Wiktionary sometimes omits the
        # mood for non-conjugated forms. Default to indicative.
        mood, tense = "indicativo", None
    else:
        return None

    if tense is None:
        for tense_tag in ("present", "preterite", "imperfect", "future"):
            if tense_tag in tagset:
                tense = _TENSE_BY_MOOD.get((mood, tense_tag))
                if tense:
                    break

    if not tense:
        return None

    person_digits = [d for tag, d in _PERSON_DIGIT.items() if tag in tagset]
    numbers = []
    if "singular" in tagset:
        numbers.append("s")
    if "plural" in tagset:
        numbers.append("p")

    persons = [d + n for d in person_digits for n in numbers]

    base = {"mood": mood, "tense": tense}
    if not persons:
        return base
    if len(persons) == 1:
        return {**base, "person": persons[0]}
    return [{**base, "person": p} for p in persons]


def merge_morphology(*candidates):
    """Combine multiple morphology results, dropping ``None`` and dedup'ing.

    Used when a single surface word has multiple form-of senses with
    different tag sets (e.g. ``ha`` is both 3s indicativo presente of
    ``haber`` and an interjection — only the verb form contributes).
    """
    seen = set()
    out = []
    for cand in candidates:
        if cand is None:
            continue
        items = cand if isinstance(cand, list) else [cand]
        for item in items:
            key = (item.get("mood"), item.get("tense"), item.get("person"))
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    if not out:
        return None
    if len(out) == 1:
        return out[0]
    return out
