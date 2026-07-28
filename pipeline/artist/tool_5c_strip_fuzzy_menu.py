#!/usr/bin/env python3
"""tool_5c_strip_fuzzy_menu.py — Remove SpanishDict fuzzy-spelling matches from an
artist sense menu, so a targeted re-classify can propose the real meaning.

When SpanishDict has no entry for a surface word it spell-corrects to a neighbour
(manín→maní "peanut", perse→purse). That wrong headword becomes a menu analysis and
then a wrong deck card. This tool detects those fuzzy analyses and strips them from
the per-artist menu, WITHOUT touching legit non-self headwords — conjugations
(fueron→ir), elisions (cargá'→cargar), clitics (muévete→mover), reflexives
(mamar→mamarse).

An analysis (surface W, headword H) is KEPT when any of:
  - H == W (self / exact dictionary word)
  - possible_results links W→H (SpanishDict's own conjugation/inflection/dictionary tag)
  - W (accent/apostrophe-folded) is a jehle conjugation of H
  - W is a fold-stem / clitic / reflexive relative of H
Otherwise the analysis is FUZZY and stripped.

Dry-run by default; pass --apply to write. Backs up the menu first. Writes the
affected surface words to <layers>/fuzzy_words.txt for the targeted rerun:

    step_6a_assign_senses.py --classifier gemini --artist-dir DIR --force \
        $(awk '{printf "--word %s ", $0}' <layers>/fuzzy_words.txt)
"""

import argparse
import json
import os
import shutil
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SURFACE_CACHE = PROJECT_ROOT / "Data" / "Spanish" / "Senses" / "spanishdict" / "surface_cache.json"
# Complete form→lemma reverse map built by step_5b_build_conjugations (~143k forms).
CONJ_REVERSE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "conjugation_reverse.json"

_CLITICS = ["selos", "selas", "melo", "mela", "telo", "tela", "selo", "sela",
            "noslo", "nosla", "me", "te", "se", "lo", "la", "le", "nos", "os",
            "los", "las", "les"]


def fold(s):
    s = unicodedata.normalize("NFD", (s or "").lower().rstrip("'’"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def load_conjugations():
    """Return {folded_form: set(lemmas)} from the pipeline's complete reverse map."""
    forms = {}
    if not CONJ_REVERSE.exists():
        return forms
    with open(CONJ_REVERSE, encoding="utf-8") as f:
        rev = json.load(f)
    for form, entries in rev.items():
        ff = fold(form)
        for e in entries:
            lem = (e.get("lemma") or "").lower() if isinstance(e, dict) else str(e).lower()
            if lem:
                forms.setdefault(ff, set()).add(lem)
    return forms


def _surface_variants(fW):
    """Folded morphological variants of a surface to look up in the reverse map:
    the form itself, elision (+s), each clitic stripped, and participle
    gender/number normalised to the -o base."""
    variants = {fW, fW + "s"}
    for c in _CLITICS:
        if fW.endswith(c) and len(fW) > len(c) + 1:
            variants.add(fW[:-len(c)])
            variants.add(fW[:-len(c)] + "s")
    for v in list(variants):
        if v.endswith("as") or v.endswith("os"):
            variants.add(v[:-2] + "o")
        elif v.endswith("a"):
            variants.add(v[:-1] + "o")
        if v.endswith("s"):
            variants.add(v[:-1])
    return variants


def is_justified(surface, headword, possible_results, conj_forms):
    """True if the analysis is a legit form of the headword (keep), False if fuzzy.

    Keeps self/exact matches, SpanishDict-tagged conjugations (possible_results),
    any form in the complete reverse conjugation map (incl. clitic/elision/
    participle variants), and regular plural/gender pairs. Everything else — a
    headword the surface is not a real form of — is a fuzzy spelling match.
    """
    W, H = surface.lower(), (headword or "").lower()
    if not H or H == W:
        return True
    for p in possible_results:
        if (str(p.get("result", "")).lower() == W
                and str(p.get("headword", "")).lower() == H):
            return True
    fW, fH = fold(surface), fold(headword)
    if fW == fH:
        return True
    base = fH[:-2] if fH.endswith("se") else fH   # reflexive lemma → base
    for cand in _surface_variants(fW):
        lemmas = conj_forms.get(cand, set())
        if H in lemmas or base in lemmas or cand == fH or cand == base:
            return True
    # regular plural / gender pair
    if fW in {fH + "s", fH + "es", (fH[:-1] + "ces" if fH.endswith("z") else "")}:
        return True
    if fH in {fW + "s", fW + "es"}:
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--artist-dir", required=True,
                    help="e.g. 'Artists/spanish/Bad Bunny'")
    ap.add_argument("--apply", action="store_true",
                    help="Actually strip + write (default: dry-run report only)")
    ap.add_argument("--aggressive", action="store_true",
                    help="Strip individual fuzzy analyses even when the word keeps "
                         "a legit one (default: only strip words that are ALL fuzzy)")
    args = ap.parse_args()

    layers = Path(os.path.abspath(args.artist_dir)) / "data" / "layers"
    menu_path = layers / "sense_menu" / "spanishdict.json"
    if not menu_path.exists():
        raise SystemExit("menu not found: %s" % menu_path)

    with open(menu_path, encoding="utf-8") as f:
        menu = json.load(f)
    with open(SURFACE_CACHE, encoding="utf-8") as f:
        surface_cache = json.load(f)
    conj_forms = load_conjugations()
    print("Loaded %d menu surfaces, %d conjugation-reverse forms" % (len(menu), len(conj_forms)))

    stripped = {}   # word -> [removed headwords]
    new_menu = {}
    for word, analyses in menu.items():
        if not isinstance(analyses, list):
            new_menu[word] = analyses
            continue
        pr = (surface_cache.get(word) or {}).get("possible_results") or []
        kept, removed = [], []
        for a in analyses:
            hw = a.get("headword") if isinstance(a, dict) else None
            if is_justified(word, hw, pr, conj_forms):
                kept.append(a)
            else:
                removed.append(hw)
        # SAFE default: only strip when EVERY analysis is fuzzy — i.e. the word
        # has no legit headword, so its only card is the fuzzy one (the manín=
        # peanut double-card case). If any real analysis survives (e.g. a base
        # verb alongside a mis-stripped reflexive), leave the word untouched —
        # its menu is already anchored on something real. --aggressive strips
        # individual fuzzy analyses too.
        if removed and (args.aggressive or not kept):
            stripped[word] = removed
            new_menu[word] = kept
        else:
            new_menu[word] = analyses

    total_removed = sum(len(v) for v in stripped.values())
    mode = "aggressive (per-analysis)" if args.aggressive else "safe (whole-word fuzzies only)"
    print("\nMode: %s" % mode)
    print("Fuzzy analyses to strip: %d across %d surface words" % (total_removed, len(stripped)))
    for w in sorted(stripped)[:40]:
        print("  %-16s remove headword(s): %s" % (w, ", ".join(map(str, stripped[w]))))
    if len(stripped) > 40:
        print("  ... and %d more" % (len(stripped) - 40))

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply to strip.")
        return

    backup = menu_path.with_suffix(".json.prefuzzy.bak")
    shutil.copy(menu_path, backup)
    with open(menu_path, "w", encoding="utf-8") as f:
        json.dump(new_menu, f, ensure_ascii=False, indent=2)
    words_file = layers / "fuzzy_words.txt"
    with open(words_file, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(stripped)) + "\n")
    print("\n  Backed up menu → %s" % backup)
    print("  Stripped menu written → %s" % menu_path)
    print("  Affected words (%d) → %s" % (len(stripped), words_file))
    print("\nNext: targeted re-classify then rebuild (see tool header).")


if __name__ == "__main__":
    main()
