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
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SURFACE_CACHE = PROJECT_ROOT / "Data" / "Spanish" / "Senses" / "spanishdict" / "surface_cache.json"

# Single source of truth for fuzzy detection: the same plausibility guard
# step_5c runs at menu-build time. This tool strips fuzzy matches from an
# ALREADY-built menu (no full rebuild); the guard prevents them at build time.
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
from util_5c_spanishdict import is_plausible_headword, _surface_conjugation_lemmas  # noqa: E402


def is_justified(surface, headword, possible_results, _unused=None):
    """Keep vs fuzzy, delegating to step_5c's plausibility guard so the tool and
    the menu builder can never disagree."""
    conj_lemmas = _surface_conjugation_lemmas(possible_results)
    return is_plausible_headword(surface, headword, conj_lemmas=conj_lemmas)


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
    print("Loaded %d menu surfaces (guard-backed fuzzy detection)" % len(menu))

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
            if is_justified(word, hw, pr):
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
