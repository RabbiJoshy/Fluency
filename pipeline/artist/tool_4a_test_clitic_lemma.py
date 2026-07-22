#!/usr/bin/env python3
"""Unit-level smoke test for clitic-aware lemma selection in step_4a.

Exercises strip_clitic on the audit's F7 cases against the real
conjugation_reverse.json / spanish_forms.json / es_50k data. Prints
expected vs. actual and exits non-zero on any mismatch.

Run:
    .venv/bin/python3 pipeline/artist/tool_4a_test_clitic_lemma.py
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)

from step_4a_filter_known_vocab import (  # noqa: E402
    strip_clitic, load_spanish_forms, load_es_50k_freq,
    SPANISH_FORMS_PATH, ES_50K_PATH, _PROJECT_ROOT,
)
import json  # noqa: E402


def main():
    conj_path = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "layers",
                             "conjugation_reverse.json")
    with open(conj_path, "r", encoding="utf-8") as f:
        conj_reverse = json.load(f)
    spanish_forms = load_spanish_forms(SPANISH_FORMS_PATH)
    verb_forms = {w for w, pos in spanish_forms.items() if "verb" in pos}
    lemma_freq = load_es_50k_freq(ES_50K_PATH)

    def resolve(word):
        return strip_clitic(word, verb_forms, conj_reverse,
                            spanish_forms=spanish_forms, lemma_freq=lemma_freq)

    # (surface, expected_lemma, note)
    cases = [
        # Multi-lemma collision → frequency tie-break (was entries[0]=sentar)
        ("siénteme", "sentir", "feel-me (object me): sentir beats sentar by freq"),
        ("párame",   "parar",  "stop-me (object me): parar beats parir by freq"),
        # Object enclitics keep the PLAIN lemma
        ("muéveme",  "mover",  "move-me (object): plain lemma"),
        ("pónme",    "poner",  "put-on-me (object): plain lemma"),
        ("salúdenme", "saludar", "greet-me (object): plain lemma, NOT saludarse"),
        ("dedícame", "dedicar", "dedicate-to-me (object): plain lemma"),
        # Reflexive enclitics prefer the -SE lemma
        ("múdate",   "mudarse",   "move-yourself (te + 2s imperative): reflexive"),
        ("escápate", "escaparse", "escape (te reflexive): -se lemma"),
        ("actívate", "activarse", "activate-yourself (te reflexive): -se lemma"),
        ("agarrense", "agarrarse", "hold-on (se + 3p imperative): reflexive"),
        ("suéltate", "soltarse",  "let-yourself-go (te reflexive): -se lemma"),
    ]

    print("=" * 78)
    print("strip_clitic clitic-aware lemma selection")
    print("=" * 78)
    fails = 0
    for surface, expected, note in cases:
        result = resolve(surface)
        got = result[0] if result else None
        ok = got == expected
        fails += not ok
        flag = "OK  " if ok else "FAIL"
        print(f"[{flag}] {surface:12} -> {str(got):12} (expect {expected:12})  {note}")

    print("-" * 78)
    # Show the raw analyses for the two headline collisions (before/after clarity).
    for surface in ("siénteme", "párame"):
        base = surface[:-2]
        import unicodedata
        base_na = "".join(c for c in unicodedata.normalize("NFD", base)
                          if c != "́")
        lemmas = sorted({e["lemma"] for e in conj_reverse.get(base_na, [])})
        freqs = {lm: lemma_freq.get(lm, 0) for lm in lemmas}
        print(f"{surface}: base={base_na!r} lemmas={lemmas} freqs={freqs}")

    print("-" * 78)
    if fails:
        print(f"{fails} case(s) FAILED")
        sys.exit(1)
    print(f"all {len(cases)} cases passed")


if __name__ == "__main__":
    main()
