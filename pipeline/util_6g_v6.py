#!/usr/bin/env python3
"""v6 — three roles instead of seven stages.

v5 grew as a pile of stages (prior, POS filter, clitic gate, gloss argmax, BETO
vote, leaf repair, calibrator) with no shared contract, so nobody could say what
any of them was for. Everything in it does exactly one of three jobs, and this
module is that reorganisation rather than a new algorithm:

  1. CONSTRAIN  remove candidates that cannot be right       -> `apply_vetoes`
  2. RANK       one score over whatever survives             -> `rank`
  3. COMMIT     decide HOW SPECIFIC an answer to emit        -> `commit`

Role 3 is the only genuinely new idea. v5 always emits a leaf, so an uncertain
pick is a *wrong* card. v6 can emit a leaf, a glosskey (gloss without context),
or a tuple (headword+POS only) — an uncertain pick becomes a *less specific*
card instead. Declining to over-claim is always available and never wrong, which
is more than can be said for any of the mechanisms measured so far.

The shipped deck format already supports this: 7.1% of current meanings carry no
context, so a glosskey-level answer renders today with no schema change.

## Terminology (see "Vocabulary" in docs/reference/wsd_design.md)

    leaf        (pos, headword, gloss, context)   one SpanishDict sense id
    glosskey    (pos, headword, gloss)            leaf with context stripped
    tuple       (pos, headword)                   what learner progress keys on

## What is measured and what is not

MEASURED on the 200-item hard panel unless noted:

  - POS filter with the AUX bridge: +14 items over the menu prior. NOTE that
    panel is 35% AUX by construction, so the deck-wide value is smaller.
  - gloss embeddings: +11.1pp on hard words (NOT the ~2pp that wsd_algorithm.md
    implies from its easier 144-item panel).
  - domain ranking in ISOLATION: 92.6% at picking the right domain vs a 43%
    prior, on 500 dictionary examples. But see below -- it buys nothing on top
    of what is already there.
  - MWE as a competing candidate: on the 29 hard-panel items carrying one, the
    multiword sense beat every leaf on 15 -- 9 clearly better by hand-grading.
    NOT a veto; see `mwe_candidates` for why that shape was wrong.

NOT MEASURED, hence defaulted OFF:

  - `commit` thresholds. Defaults emit a leaf always, i.e. v5 behaviour.
  - `aggregate="sum"` in `marginals`. It scored +8 on the hard panel, +1 on the
    unstratified 144, and -8 on the dictionary panel. The hard panel is biased
    toward large tuples (it over-samples haber/ser/tener), and sum-pooling is a
    largest-tuple prior in disguise — a mechanism the repo already identified
    once. Default is "max", which provably reproduces the v5 argmax.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

# --------------------------------------------------------------------------
# keys
# --------------------------------------------------------------------------

def _n(value) -> str:
    return (value or "").strip().lower()


def tuple_of(sense) -> tuple:
    return (sense.get("pos", ""), _n(sense.get("headword")))


def glosskey_of(sense) -> tuple:
    return (sense.get("pos", ""), sense.get("translation") or "<EMPTY>",
            _n(sense.get("headword")))


def leaf_of(sense_id, sense) -> tuple:
    return (sense_id,) + glosskey_of(sense) + (_n(sense.get("context")),)


# --------------------------------------------------------------------------
# 0. CANDIDATES — menu leaves plus any multiword sense the line contains
# --------------------------------------------------------------------------

MWE_POS = "PHRASE"          # already in _ORTHOGONAL_POS, so the filter ignores it
MWE_CONTEXT = "multiword expression"


def index_mwes(payload, min_freq=1):
    """`mwe_merged.json` -> {word: [(expression, row), ...]}.

    `min_freq` keeps tier 1 only. A tier-2 entry (corpus_freq 0) is teachable
    content with no sentence behind it, so it can never be the answer for an
    OCCURRENCE and must not be offered as a candidate here.
    """
    out = defaultdict(list)
    for expression, row in (payload.get("mwes") or {}).items():
        if row.get("corpus_freq", 0) < min_freq:
            continue
        for word in row.get("attach_words", ()):
            out[word].append((expression, row))
    return dict(out)


def mwe_candidates(word, sentence, index):
    """Multiword senses whose expression is literally present in the line.

    Rendered in the SAME shape as a menu leaf so they compete in `rank` on equal
    terms rather than acting as a veto or a back-off trigger. That is the whole
    design: a junk entry like `no tiene` competes and usually loses, which costs
    one mediocre meaning, whereas a veto would delete a correct answer.

    Measured on the 29 hard-panel items carrying an MWE, the multiword candidate
    beat every leaf on 15 -- hand-graded 9 clearly better, 4 false positives, 2
    borderline. The 9 include `a menos que` = unless (previously "minus sign"),
    `por qué` = why (previously "by"), `da igual`, `en todas partes`, and
    `dar cuenta de`, which Flash-Lite also got wrong.

    POS is PHRASE, which `_ORTHOGONAL_POS` already exempts from the POS filter,
    so no special case is needed anywhere downstream. The headword IS the
    expression, so `tuple_of` gives it its own tuple -- correct, because it is a
    different thing to learn than its component word.
    """
    flat = _flat(sentence)
    out = []
    for expression, row in index.get((word or "").lower(), ()):
        if f" {expression} " not in flat:
            continue
        translations = row.get("translations") or []
        if not translations:
            continue
        out.append((row.get("id") or f"mwe:{expression}", {
            "pos": MWE_POS,
            "translation": translations[0],
            "headword": expression,
            "context": MWE_CONTEXT,
            "source": "mwe",
            "mwe_expression": expression,
            "mwe_corpus_freq": row.get("corpus_freq", 0),
        }))
    return out


def render_key(sense, word=None):
    """The text embedded for a candidate. One shape for leaves and MWEs alike.

    A multiword sense passes its own expression as the word, so `de nuevo`
    embeds as `"de nuevo" (PHRASE): again — multiword expression` against a leaf's
    `"nuevo" (ADJ): new — recently made`. Symmetric by construction; if these
    diverged the competition would be measuring the rendering, not the meaning.
    """
    head = word or sense.get("mwe_expression") or sense.get("headword") or ""
    return (f'"{head}" ({sense.get("pos", "")}): '
            f'{sense.get("translation") or ""} — {sense.get("context") or ""}')


# --------------------------------------------------------------------------
# 1. CONSTRAIN
# --------------------------------------------------------------------------

_WORD = re.compile(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ]+")

def _flat(text: str) -> str:
    return " " + _WORD.sub(" ", (text or "").lower()) + " "


def companion_of(sense):
    """The word a leaf says it is 'used with', or None.

    SpanishDict appends these to the context field rather than giving them a
    field of their own: 'to support; used with "por"'. `util_6e_leaf_selection`
    already parses this shape and uses it to repair a rendered leaf; here the
    same note is used to veto a candidate before it is ever chosen.
    """
    m = re.search(r'used with\s+"?([\wáéíóúüñ]+)"?', _n(sense.get("context")))
    return m.group(1) if m else None


def apply_vetoes(word, sentence, candidates, *, example_pos=None,
                 pos_compatible=None, use_companion=True):
    """Drop candidates that cannot be right. Returns (kept, reasons).

    Vetoes are HARD and each records why, because a silent veto is how the AUX
    bug survived: `sense_compatible_bridged` rejected every leaf of an
    auxiliary, the empty-keep-set fallback fired, and the filter became a no-op
    on `haber, ser, estar, deber, saber` with no symptom at all.

    So the empty-keep-set fallback is kept — never return nothing — but the
    caller is told it happened.

    Multiword expressions are deliberately NOT handled here. They were briefly
    a veto and it was the wrong shape: only 9% of MWE hits map cleanly onto an
    existing leaf, and roughly a quarter of hits are compositional strings like
    `no tiene` where a veto would delete the correct answer. They belong in
    `mwe_candidates`, competing.

    `candidates` is [(sense_id, sense_dict), ...].
    """
    reasons = {}
    kept = list(candidates)

    if example_pos and pos_compatible is not None:
        survivors = [(i, s) for i, s in kept
                     if pos_compatible(s.get("pos", ""), example_pos)]
        if survivors:
            for i, s in kept:
                if (i, s) not in survivors:
                    reasons[i] = f"pos:{example_pos}"
            kept = survivors
        else:
            reasons["_pos_filter"] = "vetoed everything; ignored"

    if use_companion:
        flat = _flat(sentence)
        survivors = []
        for i, s in kept:
            comp = companion_of(s)
            if comp and f" {comp} " not in flat:
                reasons[i] = f'companion:"{comp}" absent'
            else:
                survivors.append((i, s))
        if survivors:
            kept = survivors

    return kept, reasons


# --------------------------------------------------------------------------
# 2. RANK
# --------------------------------------------------------------------------

def rank(candidates, *, gloss_score, prior_weight=0.02, prior_decay=0.5,
         domain_score=None, domain_weight=0.0):
    """One score per candidate. Returns {sense_id: score}.

    `gloss_score(sense) -> float` is the embedding cosine against the sentence.
    The menu prior is `prior_weight * prior_decay**rank` over the SURVIVING
    order -- v5 computes rank the same way, and computing it on the original
    menu order instead was measured to change nothing on either panel.

    `domain_score(sense) -> float` applies only where the leaf's context is a
    real domain label (medicine, legal, nautical...). It is off by default and
    should stay off.

    Domain matching in ISOLATION is excellent -- 92.6% at picking the right
    domain from a word's candidates, against a 43% prior, on 500 dictionary
    examples. That looked like a lever, since domains are topical and topical
    similarity is what embeddings are best at.

    It buys nothing. Swept 0.0 -> 1.5 on the hard panel, centred so it re-ranks
    among domain leaves rather than inflating them: flat at 78.4% to weight 0.20,
    then -1 item beyond. On the 22 items where two or more real domains actually
    compete, the baseline is ALREADY 90.9%.

    So the dilution hypothesis is wrong: burying "medicine" as one token in
    eight inside `"gotas" (NOUN): drops — medicine` does not waste it. The
    encoder picks it up. This is also evidence against embedding gloss and
    context separately, which was motivated by the same argument.
    """
    out = {}
    for position, (sense_id, sense) in enumerate(candidates):
        score = gloss_score(sense) + prior_weight * (prior_decay ** position)
        if domain_weight and domain_score is not None:
            extra = domain_score(sense)
            if extra is not None:
                score += domain_weight * extra
        out[sense_id] = score
    return out


# --------------------------------------------------------------------------
# 3. COMMIT
# --------------------------------------------------------------------------

def marginals(scores, candidates, *, temperature=0.02, aggregate="max"):
    """Project the leaf scores onto the tuple / glosskey / leaf axes.

    Returns {"tuple": {...}, "glosskey": {...}, "leaf": {...}} of probabilities.

    aggregate="max" reproduces the v5 argmax exactly (the argmax over per-key
    maxima is the key of the globally best leaf), so it is safe as a default and
    adds confidence without changing any pick.

    aggregate="sum" pools mass across leaves sharing a key. It is NOT validated:
    +8 items on the hard panel, +1 on the unstratified 144, -8 on the dictionary
    panel. The hard panel over-samples large-tuple words, and sum-pooling
    rewards exactly that. Do not switch this on without a frequency-sampled
    panel.
    """
    import math

    if not scores:
        return {"tuple": {}, "glosskey": {}, "leaf": {}}
    top = max(scores.values())
    weight = {k: math.exp((v - top) / temperature) for k, v in scores.items()}
    total = sum(weight.values()) or 1.0
    prob = {k: v / total for k, v in weight.items()}

    axes = {"tuple": defaultdict(float), "glosskey": defaultdict(float),
            "leaf": defaultdict(float)}
    for sense_id, sense in candidates:
        if sense_id not in prob:
            continue
        p = prob[sense_id]
        for name, key in (("tuple", tuple_of(sense)),
                          ("glosskey", glosskey_of(sense)),
                          ("leaf", (sense_id,))):
            if aggregate == "sum":
                axes[name][key] += p
            else:
                axes[name][key] = max(axes[name][key], p)
    return {k: dict(v) for k, v in axes.items()}


def _margin(dist):
    """top1 - top2 on one axis. 1.0 when there is nothing to choose between."""
    if not dist:
        return 0.0
    ordered = sorted(dist.values(), reverse=True)
    return ordered[0] - (ordered[1] if len(ordered) > 1 else 0.0)


def commit(scores, candidates, *, leaf_min=0.0, glosskey_min=0.0,
           tuple_min=0.0, temperature=0.02, aggregate="max"):
    """Emit the most specific claim the scores support.

    Returns a dict:
        level     "leaf" | "glosskey" | "tuple" | "escalate"
        sense_id  the winning leaf (always present; level says how much of it
                  the caller should render)
        margins   the three confidences, for provenance

    The default thresholds are 0.0, which means "always emit a leaf" -- i.e.
    exactly v5. The thresholds are UNMEASURED; calibrating them is the whole
    evidence base for role 3 and wants a frequency-sampled panel.

    Escalation is triggered by the TUPLE margin alone, deliberately. A weak
    gloss margin means the model is torn between synonyms, which the learner
    does not see once the answer is emitted at glosskey level; a weak tuple
    margin means it may have the wrong word entirely, which is never acceptable.
    """
    if not scores:
        return {"level": "escalate", "sense_id": None, "margins": {}}
    best = max(scores, key=scores.get)
    axes = marginals(scores, candidates, temperature=temperature,
                     aggregate=aggregate)
    m = {name: _margin(axes[name]) for name in ("tuple", "glosskey", "leaf")}

    if m["tuple"] < tuple_min:
        level = "escalate"
    elif m["leaf"] >= leaf_min and m["glosskey"] >= glosskey_min:
        level = "leaf"
    elif m["glosskey"] >= glosskey_min:
        level = "glosskey"
    else:
        level = "tuple"
    return {"level": level, "sense_id": best, "margins": m}


def render_at(level, sense):
    """What the card should actually say, given a commit level."""
    if level == "tuple":
        return {"pos": sense.get("pos"), "headword": sense.get("headword")}
    payload = {"pos": sense.get("pos"), "headword": sense.get("headword"),
               "translation": sense.get("translation")}
    if level == "leaf":
        payload["context"] = sense.get("context")
    return payload
