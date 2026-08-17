#!/usr/bin/env python3
"""util_6e_leaf_selection — choose which gloss a card actually shows.

The tuple (headword, POS) is what every accuracy number in this project
measures, and it is what the calibrator predicts: `tool_6d_train_calibrator`
trains on `ok_tup`. Which LEAF inside the winning tuple gets emitted has never
been managed — it falls out of the same argmax and nothing checks it. Two
defects in the shipped test-playlist deck come from that and from nothing else:

  1. 199 of 3,480 assignments (5.7%) land on a leaf whose `translation` is
     empty, so the card renders a word with no English at all. `bien` shows
     nothing; `caer`, `haber`, `dar`, `vez`, `poco`, `al`, `del` show nothing.
     A non-empty leaf exists in the SAME tuple for 197 of those 199.
  2. 58 assignments land on a leaf whose context note names a companion the
     sentence does not contain -- `eres` -> "to root for" (used with "de") on
     `Es que en mi lista tú eres la favorita`. 54 of the 58 have a clean
     sibling in the same tuple.

Both are repaired by re-picking inside the tuple, which is why they share a
module. Because the tuple never changes, this cannot move lemma+POS accuracy
and cannot invalidate a confidence that was calibrated against `ok_tup`.

On the two rejected findings this deliberately does NOT contradict:

  * "deleting empty-translation leaves makes accuracy worse" -- true, and this
    does not delete them. They stay in the menu and keep scoring, because their
    context notes carry real POS and sense signal. They are only barred from
    being the thing displayed.
  * "`used with` as a ranking feature / soft prior is noise" -- also true, and
    this is neither. It is the leaf-level gate, the one form of the signal that
    measured positive (111 wrong glosses removed against 12 right, ~9:1) and
    was left unbuilt for want of a leaf-selection stage. This is that stage.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from util_6d_wsd_features import companion_of  # noqa: E402  (re-exported)

_TOKEN = re.compile(r"[a-záéíóúüñ0-9']+")

# Spanish fuses the exact prepositions SpanishDict names as companions, so a
# literal token test scores `Yo me caso contigo` as violating "used with con"
# and `al carajo` as violating "used with a". Both are satisfied. Without this
# the gate fires on correct picks; the previously measured 91% constraint hold
# rate was quoted WITH contraction handling, so it is part of the finding, not
# a refinement of it.
_FUSED = {
    "al": ("a", "el"),
    "del": ("de", "el"),
    "conmigo": ("con",),
    "contigo": ("con",),
    "consigo": ("con",),
    # Reggaeton elides `de` to `'e` and `para` to `pa'` constantly. Treating the
    # elided form as absent would make the gate fire hardest on exactly the
    # register this deck is built from.
    "'e": ("de",),
    "e'": ("de",),
    "pa": ("para",),
    "pa'": ("para",),
    "p'": ("para",),
    "po'": ("por",),
}


def _expand(sentence: str) -> set[str]:
    """Tokens of `sentence`, plus whatever its fused/elided forms stand for."""
    toks = _TOKEN.findall((sentence or "").lower())
    out = set(toks)
    for t in toks:
        out.update(_FUSED.get(t, ()))
    return out


# SpanishDict marks soft collocations too: `often used with "a"` on llegar, and
# `often used with "para"` on aprovechar. Those are tendencies, not
# requirements, and gating on them demotes correct picks -- replay turned a
# right `llegan` -> "to arrive" into a wrong "to be enough". Only the
# unqualified form is treated as a constraint.
_SOFT = re.compile(r"\b(?:often|sometimes|usually|frequently|typically|"
                   r"generally|normally|commonly|may be|can be)\s+used with", re.I)


def hard_companion_of(sense: dict) -> str | None:
    """The companion a sense REQUIRES, ignoring ones it merely tends to take.

    Separate from `companion_of` in util_6d on purpose: that one feeds the
    calibrator's frozen feature contract and must keep behaving exactly as the
    trained model saw it.
    """
    ctx = (sense.get("context") or "")
    if _SOFT.search(ctx):
        return None
    return companion_of(sense)


def companion_satisfied(companion: str | None, sentence: str) -> bool:
    """Does `sentence` contain the companion this sense's note requires?

    No companion means nothing to satisfy, so an unconstrained leaf is never
    penalised against a constrained one -- the gate only ever removes.
    """
    if not companion:
        return True
    toks = _expand(sentence)
    return all(p in toks for p in companion.split())


def renderable(sense: dict) -> bool:
    """Would this leaf put an English gloss on the card?"""
    return bool((sense.get("translation") or "").strip())


def defective(sense: dict, sentence: str) -> bool:
    """Would emitting this leaf put something broken on the card?"""
    return (not renderable(sense)
            or not companion_satisfied(hard_companion_of(sense), sentence))


def select_display_leaf(sentence, menu, sids, scores, k, tuple_ids):
    """Repair the emitted leaf, inside the tuple the pick already won.

    `k` is the chosen index; `scores` are the ungated gloss similarities for
    this sentence against every leaf, in `sids` order. Returns an index into
    `sids` -- `k` itself unless `k` is defective and the tuple holds something
    better.

    Strictly a repair, never a re-rank. A pick that renders and satisfies its
    note is returned untouched even when a sibling scores higher, because by
    this point the leaf may have come from Gemini escalation rather than the
    argmax, and escalation is the better picker on disagreement (right 80.3% vs
    18.0%). Quietly replacing its choice with the embedding runner-up would
    throw away the more accurate signal to fix a card that was not broken.
    """
    if not defective(menu[sids[k]], sentence):
        return k
    same = [i for i in range(len(sids)) if tuple_ids[i] == tuple_ids[k]]
    ok = [i for i in same if not defective(menu[sids[i]], sentence)]
    if not ok:
        # Every leaf in the tuple is unrenderable or construction-blocked. The
        # tuple is still the best evidence available, so keep the original pick
        # rather than inventing a worse one or dropping a real occurrence.
        return k
    return max(ok, key=lambda i: scores[i])
