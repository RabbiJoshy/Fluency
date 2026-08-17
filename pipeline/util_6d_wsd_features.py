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

FEATURE_VERSION = 4

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
          pred_empty, token, companion, menu_pos=0):
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
    ] + list(companion)
