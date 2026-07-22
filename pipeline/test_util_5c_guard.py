#!/usr/bin/env python3
"""Regression test for the SpanishDict headword plausibility guard.

Exercises ``build_menu_analyses`` / ``is_plausible_headword`` on synthetic
surface-cache entries that mirror the real cache structures for the failing
(perse→purse, cel→cal, totito→torito, revol→revolt) and legit (canción,
gato, vuelvo→volver/volverse, luces→luz) surfaces.

Self-contained: uses synthetic caches for build_menu_analyses; the direct
is_plausible_headword checks read the committed spanish_forms.json /
conjugation_reverse.json layer files. Run:

    .venv/bin/python3 pipeline/test_util_5c_guard.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import util_5c_spanishdict as u  # noqa: E402


def _sense(pos, tr):
    return {"pos": pos, "translation": tr, "source": "spanishdict"}


def _da(headword, *senses):
    return {"headword": headword, "senses": list(senses) or [_sense("NOUN", "x")]}


def _pr(headword, heuristic, result):
    return {"headword": headword, "heuristic": heuristic, "result": result}


# (surface, dictionary_analyses, possible_results, expected_kept_headwords)
CASES = [
    # REJECT — fuzzy English intrusions -> empty menu -> sense_discovery
    ("perse",       [_da("purse")],       [], set()),
    ("revol",       [_da("revolt")],      [], set()),
    ("lary",        [_da("lazy")],        [], set()),
    ("tranquilita", [_da("tranquility")], [], set()),
    # REJECT — wrong-Spanish fuzz
    ("cel",         [_da("cal")],         [], set()),
    ("totito",      [_da("torito")],      [], set()),
    # KEEP — legit
    ("canción",     [_da("canción")],     [], {"canción"}),
    ("gato",        [_da("gato")],        [], {"gato"}),
    ("luces",       [_da("luz")],         [], {"luz"}),  # z→ces plural, no SD pointer
    ("vuelvo",      [_da("volver"), _da("volverse")],
                    [_pr("volver", "conjugation", "vuelvo")], {"volver", "volverse"}),
    ("hablo",       [_da("hablar"), _da("hablarse")],
                    [_pr("hablar", "conjugation", "hablo")], {"hablar", "hablarse"}),
]

# Direct is_plausible_headword() checks: (surface, headword, relation, conj_lemmas, expected)
DIRECT = [
    ("perse", "purse", "", None, False),
    ("cel", "cal", "", None, False),
    ("totito", "torito", "", None, False),
    ("canción", "canción", "", None, True),
    ("luces", "luz", "", None, True),
    ("vuelvo", "volver", "", {"volver"}, True),
    ("vuelvo", "volverse", "", {"volver"}, True),
    ("vuelvo", "volver", "conjugation", None, True),
]


def main():
    failures = 0
    for surface, das, prs, expected in CASES:
        sc = {surface: {"dictionary_analyses": das, "possible_results": prs}}
        got = {
            (a.get("headword") or "").strip()
            for a in u.build_menu_analyses(surface, sc, {})
            if a.get("headword")
        }
        ok = got == expected
        failures += not ok
        print("[%s] %-13s expected=%-22s got=%s"
              % ("OK" if ok else "FAIL", surface,
                 ",".join(sorted(expected)) or "(none)",
                 ",".join(sorted(got)) or "(none)"))

    for surf, hw, rel, cl, exp in DIRECT:
        got = u.is_plausible_headword(surf, hw, surface_relation=rel, conj_lemmas=cl)
        ok = got == exp
        failures += not ok
        print("[%s] is_plausible(%s -> %s, rel=%s) = %s"
              % ("OK" if ok else "FAIL", surf, hw, rel or "-", got))

    print("\n%d case(s), %d failure(s)" % (len(CASES) + len(DIRECT), failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
