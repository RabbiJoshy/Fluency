#!/usr/bin/env python3
"""util_6d_wsd_features — the calibrator's feature contract, in one place.

The trainer and the runtime MUST build identical vectors. Keeping two copies in
sync by hand has already failed twice in this project (the reflexive gate, the
prompt_id rename), so there is exactly one implementation and both import it.

FEATURES is the order. Appending is safe; reordering or removing invalidates any
model trained against the old order, so bump FEATURE_VERSION when that happens
and refuse to load a mismatched model.
"""
from __future__ import annotations

import re

FEATURE_VERSION = 5

FEATURES = [
    # --- gloss path
    "tuple_gap", "class_gap", "class_gap_collapsed",
    # --- menu shape
    "n_tup", "n_leaf", "leaf_split_ratio", "sent_len",
    # --- what was predicted
    "pred_is_se", "pred_is_verb", "pred_is_nounadj", "pred_empty_gloss",
    # --- token-prototype path
    "token_available", "token_gap", "token_agrees",
    # --- SpanishDict construction metadata ("used with X")
    "companion_in_menu", "companion_on_pred", "companion_present",
    "companion_adjacent", "companion_discriminates",
    # --- SpanishDict construction metadata, GRAMMATICAL form ("used with a
    # gerund", "before past participle", "used in progressive constructions").
    # Distinct from the companion block above, which only ever sees a literal
    # token: `companion_of` reads "used with a gerund" and returns the string
    # "a", so the correct periphrastic leaf scores as companion-ABSENT. These
    # five test the construction morphologically instead.
    "struct_in_menu", "struct_on_pred", "struct_satisfied",
    "struct_discriminates", "struct_alt_satisfied",
]

# "used with 'de'" / "used with que". SpanishDict is not consistent about quoting.
_COMPANION = re.compile(r'used with\s+"([^"]+)"|used with\s+([a-záéíóúüñ]+)', re.I)
_TOKEN = re.compile(r"[a-záéíóúüñ0-9']+")


def companion_of(sense: dict) -> str | None:
    """The literal companion a sense's context note names, if any.

    Only ~6% of senses carry one, but they cluster on function words where the
    gloss signal is weakest, and they touch 19% of gold items. Note the context
    field is ALREADY embedded into the sense vector as prose by gloss(); this
    extracts it as a structured signal to test whether structure beats prose.
    """
    m = _COMPANION.search((sense.get("context") or ""))
    if not m:
        return None
    c = (m.group(1) or m.group(2) or "").strip().lower()
    return c or None


def companion_features(word, sentence, menu, pred_sense_id, tuple_of):
    """Five features describing the construction evidence for the prediction.

    Deliberately literal. A staged same-sentence < clause < dependency ladder was
    proposed; the cheap literal test is measured first, because the clitic gate
    showed a regex can capture the whole of a headroom that looked like it needed
    parsing. `companion_adjacent` is the one concession to attachment: the
    companion sitting within two tokens of the target is weak evidence that it
    actually attaches, without needing a parser.
    """
    toks = _TOKEN.findall((sentence or "").lower())
    tokset = set(toks)

    comps = {}
    for sid, s in (menu or {}).items():
        c = companion_of(s)
        if c:
            comps[sid] = c
    if not comps:
        return [0.0, 0.0, 0.0, 0.0, 0.0]

    pred_comp = comps.get(pred_sense_id)
    # does the note distinguish tuples at all, or does every tuple carry one?
    with_c = {tuple_of(word, menu[sid]) for sid in comps}
    all_t = {tuple_of(word, s) for s in menu.values()}
    discriminates = float(bool(with_c) and with_c != all_t)

    present = adjacent = 0.0
    if pred_comp:
        parts = pred_comp.split()
        present = float(all(p in tokset for p in parts))
        if present and word.lower() in toks:
            wi = toks.index(word.lower())
            ci = [i for i, t in enumerate(toks) if t == parts[0]]
            adjacent = float(any(abs(i - wi) <= 2 for i in ci))
    return [1.0, float(pred_comp is not None), present, adjacent, discriminates]


def build(*, tuple_gap, class_gap, n_tup, n_leaf, sent_len, pred_tuple,
          pred_empty, token, companion, structural=(0.0,) * 5, menu_pos=0):
    """Assemble one feature vector in FEATURES order.

    `menu_pos` is accepted and DELIBERATELY UNUSED. SpanishDict orders leaves by
    frequency and accuracy really does fall with position (86.3% at leaves 0-2,
    66.3% at 15+), but adding it as a feature dropped held-out yield at 99% from
    45.8% to 41.3%. It was already rejected in 2026-08 as a standalone prior
    (43.7% vs 53.6%); it is now also rejected in combination. The correlation is
    real and the feature still does not generalise across the word-level split,
    because menu shape differs per word. Kept in the signature so the next person
    does not spend an afternoon rediscovering this.
    """
    hw, pos = pred_tuple
    tok_avail, tok_gap, tok_agree = token
    return [
        float(tuple_gap), float(class_gap), float(class_gap >= 0.999),
        float(n_tup), float(n_leaf), n_leaf / max(n_tup, 1), float(sent_len),
        float(str(hw).endswith("se")), float(pos == "VERB"),
        float(pos in ("NOUN", "ADJ")), float(pred_empty),
        float(tok_avail), float(tok_gap), float(tok_agree),
    ] + list(companion) + list(structural)


# ---------------------------------------------------------------------------
# Grammatical construction notes
# ---------------------------------------------------------------------------
# SpanishDict states a construction requirement in at least five wordings, and
# only one of them is a literal token the companion block can test:
#
#   used with a gerund / a participle / an infinitive      90 leaves
#   used with "por" and infinitive  (companion sees "por"  46 leaves
#     and silently drops the infinitive half)
#   used in progressive constructions / with the passive    70 leaves
#     voice / before past participle / before the gerund
#     -- no "used with" at all, so companion_of returns None
#
# `companion_of` takes the first bare word after "used with", so those parse to
# the literal "a" or "an" and are then tested for presence in a Spanish
# sentence. The correct leaf is therefore scored as construction-VIOLATING on
# nearly every occurrence -- the clue is not merely unused, it is inverted.
#
# Only morphologically decidable predicates are implemented. "used with
# adjectives", "used with quantities" and "used with verbs of perception" need a
# parser or a lexicon to test, and a predicate that cannot be checked is worse
# than no predicate: it would emit struct_on_pred=1 with struct_satisfied=0 on
# every occurrence and teach the model that construction leaves are always wrong.

_STRUCT_PATTERNS = (
    ("gerund", re.compile(r"\bgerund\b|\bprogressive construction", re.I)),
    ("participle", re.compile(r"\bparticiple\b|\bpassive voice\b", re.I)),
    ("infinitive", re.compile(r"\binfinitive\b", re.I)),
)

# -ando/-iendo/-yendo is exceptionless for Spanish gerunds.
_GERUND = re.compile(r"\w+(?:ando|iendo|yendo)$", re.I)
_INFINITIVE = re.compile(r"\w{3,}(?:ar|er|ir)$", re.I)
_PARTICIPLE = re.compile(r"\w+(?:ado|ada|ados|adas|ido|ida|idos|idas)$", re.I)
# The irregular participles are a closed class and all of them are common.
_IRREG_PART = {"hecho", "dicho", "visto", "puesto", "escrito", "roto", "vuelto",
               "muerto", "abierto", "cubierto", "resuelto", "impreso", "frito"}


def structural_of(sense):
    """The construction a sense's note requires, or None.

    Returns one of "gerund" / "participle" / "infinitive". Checked in that
    order because "used with a participle to describe a state" must not be read
    as an infinitive by the -ir suffix of some other word in the note.
    """
    ctx = (sense.get("context") or "")
    for name, pat in _STRUCT_PATTERNS:
        if pat.search(ctx):
            return name
    return None


def structural_satisfied(kind, word, sentence):
    """Is the required construction actually present after the target?

    Windowed to the three tokens after the target, not the whole sentence: a
    lyric line usually holds several verbs, and "somewhere in this line there is
    a gerund" is satisfied so often that it carries no information. Falls back
    to the whole line when the target form is not locatable (elided surfaces
    like `'Taba` do not match the lookup key).
    """
    if not kind:
        return True
    toks = _TOKEN.findall((sentence or "").lower())
    if not toks:
        return False
    try:
        i = toks.index(word.lower())
        window = toks[i + 1:i + 4]
    except ValueError:
        window = toks
    if kind == "gerund":
        return any(_GERUND.match(t) for t in window)
    if kind == "participle":
        return any(_PARTICIPLE.match(t) or t in _IRREG_PART for t in window)
    if kind == "infinitive":
        return any(_INFINITIVE.match(t) for t in window)
    return True


def structural_features(word, sentence, menu, pred_sense_id, tuple_of):
    """Five features describing the CONSTRUCTION evidence for the prediction.

    `struct_alt_satisfied` is the one that carries the periphrastic case: the
    pick is a plain lexical leaf, and a sibling in the SAME tuple demands a
    gerund which the line supplies. That is the shape of `Nos fuimos calentando`
    carded as "ir: to go (to exit a place)" while "to be (used in progressive
    constructions)" sits unpicked one row away.
    """
    kinds = {sid: structural_of(s) for sid, s in (menu or {}).items()}
    if not any(kinds.values()):
        return [0.0, 0.0, 0.0, 0.0, 0.0]

    pred_kind = kinds.get(pred_sense_id)
    with_k = {tuple_of(word, menu[sid]) for sid, k in kinds.items() if k}
    all_t = {tuple_of(word, s) for s in menu.values()}
    discriminates = float(bool(with_k) and with_k != all_t)

    satisfied = float(bool(pred_kind) and structural_satisfied(pred_kind, word, sentence))

    alt = 0.0
    if pred_sense_id in menu:
        pred_tup = tuple_of(word, menu[pred_sense_id])
        for sid, k in kinds.items():
            if not k or sid == pred_sense_id:
                continue
            if tuple_of(word, menu[sid]) != pred_tup:
                continue
            if structural_satisfied(k, word, sentence) and not satisfied:
                alt = 1.0
                break
    return [1.0, float(pred_kind is not None), satisfied, discriminates, alt]
