#!/usr/bin/env python3
"""
step_5e_build_conjugated_english.py — Person-matched English for verb senses.

Pure English-to-English step: for every verb sense in the sense menu, generate
the 3 tenses x 6 persons grid of English forms via LemmInflect (e.g.
"to eat" -> {presente: ["I eat", "you eat", "he eats", ...], ...}). The
front-end picks a cell at render time using the morphology field already
stamped on the vocabulary entry.

This step is language-agnostic — it never touches the source-language verb
or its conjugation table. The only Spanish-specific bits are the carve-out
constants (GUSTAR_BLACKLIST, BE_FORMS lemma allow-list) and the input path.
The morphology stamping (Wiktionary primary, verbecc fallback) is the
language-specific dependency, and lives in step_8a / tool_4a.

Output keys (`presente`, `pretérito-perfecto-simple`, `futuro`) match the
verbecc tense convention used by `vocabulary.index.json`'s `morphology.tense`,
so the front-end looks up without remapping. If a lookup misses (blacklisted
lemma, non-conjugatable sense shape, missing morphology) the front-end falls
back to the infinitive display.

Usage:
    python3 pipeline/step_5e_build_conjugated_english.py [--verify] [--limit N]

Run from the project root.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
from util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

STEP_VERSION = 2
STEP_VERSION_NOTES = {
    1: "lemminflect-driven person/tense English conjugation for verb senses "
       "(presente, pretérito-perfecto-simple, futuro)",
    2: "drop conjugations.json dependency — walk sense_menu directly. Step "
       "is now language-agnostic; coverage extends to verbs Wiktionary "
       "tagged but verbecc didn't handle (voseo, regional, tail verbs).",
}

LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"
SENSE_MENU_FILE = LAYERS / "sense_menu" / "spanishdict.json"
OUTPUT_FILE = LAYERS / "senses_conjugated_english.json"

# Reverse-subject verbs: Spanish 1sg subject corresponds to the English object
# (me gusta = "I like it"). Mechanical conjugation produces semantically wrong
# English here, so we drop the lemma entirely and let the front-end show the
# infinitive instead.
GUSTAR_BLACKLIST = {
    "gustar", "encantar", "faltar", "doler", "importar", "quedar",
    "sobrar", "parecer", "apetecer", "molestar", "interesar",
    "fascinar", "preocupar", "convenir", "tocar",
}

# Bare-modal senses: kept as-is in present, remapped in past, dropped in future
# (English modals don't take "will").
MODALS_PAST = {"can": "could", "may": "might"}
MODALS_KEEP = {"must", "should"}

PRONOUNS = ["I", "you", "he", "we", "you (pl)", "they"]

# Tense keys exactly match vocabulary.index.json's morphology.tense values
# (verbecc convention), so the front-end can look up without remapping.
TENSES = ["presente", "pretérito-perfecto-simple", "futuro"]

# "to be" head — fully irregular, override LemmInflect.
BE_FORMS = {
    "presente":                   ["am", "are", "is", "are", "are", "are"],
    "pretérito-perfecto-simple":  ["was", "were", "was", "were", "were", "were"],
    "futuro":                     ["will be"] * 6,
}


def _vbz(head, _cache={}):
    """3sg present form, cached. Falls back to head+s if LemmInflect doesn't know."""
    if head in _cache:
        return _cache[head]
    from lemminflect import getInflection
    forms = getInflection(head, tag="VBZ")
    out = forms[0] if forms else (head + "s")
    _cache[head] = out
    return out


def _vbd(head, _cache={}):
    """Simple past form, cached."""
    if head in _cache:
        return _cache[head]
    from lemminflect import getInflection
    forms = getInflection(head, tag="VBD")
    out = forms[0] if forms else (head + "ed")
    _cache[head] = out
    return out


def conjugate_translation(translation, tense, person_idx):
    """Render a single (translation, tense, person) cell.

    Returns the English string, or None if the shape isn't conjugatable
    (front-end falls back to infinitive in that case).
    """
    s = translation.strip()
    if not s:
        return None
    pron = PRONOUNS[person_idx]

    # Bare modal sense
    if s in MODALS_PAST or s in MODALS_KEEP:
        if tense == "presente":
            return f"{pron} {s}"
        if tense == "pretérito-perfecto-simple":
            return f"{pron} {MODALS_PAST.get(s, s)}"
        return None  # futuro: drop, no clean English

    if not s.startswith("to "):
        return None
    body = s[3:].strip()
    if not body:
        return None

    parts = body.split(" ", 1)
    head = parts[0]
    rest = (" " + parts[1]) if len(parts) > 1 else ""

    # "to be ..." — person- and tense-aware "be" form, then concat rest.
    if head == "be":
        return f"{pron} {BE_FORMS[tense][person_idx]}{rest}"

    if tense == "futuro":
        return f"{pron} will {head}{rest}"
    if tense == "presente":
        if person_idx == 2:  # 3sg
            return f"{pron} {_vbz(head)}{rest}"
        return f"{pron} {head}{rest}"
    if tense == "pretérito-perfecto-simple":
        return f"{pron} {_vbd(head)}{rest}"
    return None


def collect_lemma_translations(sense_menu):
    """Walk sense_menu, collect ordered unique translations per verb lemma.

    Returns (lemma_translations, skipped_blacklist, skipped_to_be).
    """
    lemma_translations = {}
    skipped_blacklist = set()
    skipped_to_be = 0

    for groups in sense_menu.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            headword = (group.get("headword") or "").lower()
            if not headword:
                continue
            if headword in GUSTAR_BLACKLIST:
                skipped_blacklist.add(headword)
                continue

            for sense in group.get("senses", {}).values():
                if sense.get("pos") not in ("VERB", "AUX"):
                    continue
                trans = (sense.get("translation") or "").strip()
                if not trans:
                    continue
                if trans == "to be" and headword not in ("ser", "estar"):
                    skipped_to_be += 1
                    continue
                bucket = lemma_translations.setdefault(headword, [])
                if trans not in bucket:
                    bucket.append(trans)

    # Dedupe "to have got" against "to have" (British variant of same sense)
    for trans_list in lemma_translations.values():
        if "to have" in trans_list and "to have got" in trans_list:
            trans_list.remove("to have got")

    return lemma_translations, skipped_blacklist, skipped_to_be


def main():
    parser = argparse.ArgumentParser(
        description="Generate person-matched English for Spanish verb senses.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N lemmas (debug)")
    parser.add_argument("--verify", action="store_true",
                        help="Print spot-check output for 10 reference verbs")
    args = parser.parse_args()

    print(f"Loading {SENSE_MENU_FILE.relative_to(PROJECT_ROOT)}...")
    with open(SENSE_MENU_FILE, encoding="utf-8") as f:
        sense_menu = json.load(f)

    print("Walking sense_menu for verb senses...")
    lemma_translations, skipped_bl, skipped_tobe = collect_lemma_translations(
        sense_menu)

    if args.limit is not None:
        keep = list(lemma_translations.keys())[:args.limit]
        lemma_translations = {k: lemma_translations[k] for k in keep}

    print(f"  {len(lemma_translations)} verb lemmas with eligible senses")

    print("Generating conjugated English...")
    out = {}
    senses_total = 0
    senses_with_output = 0
    senses_skipped = 0
    for lemma, trans_list in lemma_translations.items():
        per_sense = {}
        for trans in trans_list:
            senses_total += 1
            tense_dict = {}
            for tense in TENSES:
                row = [conjugate_translation(trans, tense, p) for p in range(6)]
                if any(x is not None for x in row):
                    tense_dict[tense] = row
            if tense_dict:
                per_sense[trans] = tense_dict
                senses_with_output += 1
            else:
                senses_skipped += 1
        if per_sense:
            out[lemma] = per_sense

    print(f"Writing {OUTPUT_FILE.relative_to(PROJECT_ROOT)}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
    write_sidecar(OUTPUT_FILE, make_meta("build_conjugated_english", STEP_VERSION))

    coverage_pct = (100.0 * senses_with_output / senses_total) if senses_total else 0.0
    print()
    print("=" * 55)
    print("CONJUGATED ENGLISH BUILD RESULTS")
    print("=" * 55)
    print(f"Verb lemmas in output:           {len(out):>6}")
    print(f"Senses considered:               {senses_total:>6}")
    print(f"Senses with conjugated output:   {senses_with_output:>6}  ({coverage_pct:.1f}%)")
    print(f"Senses skipped (non-conjugatable): {senses_skipped:>4}")
    print(f"'to be' contamination filtered:    {skipped_tobe:>4}")
    print(f"gustar-class lemmas blacklisted:   {len(skipped_bl):>4}")
    if skipped_bl:
        print(f"  Blacklisted: {sorted(skipped_bl)}")

    if args.verify:
        print()
        print("=" * 55)
        print("SPOT CHECK (10 reference verbs)")
        print("=" * 55)
        for v in ["hablar", "comer", "vivir", "trabajar", "tener",
                  "ir", "hacer", "decir", "gustar", "poder"]:
            print(f"\n{v}:")
            entry = out.get(v)
            if not entry:
                reason = "blacklisted" if v in GUSTAR_BLACKLIST else "no eligible senses"
                print(f"  (not in output — {reason})")
                continue
            for trans, tenses in list(entry.items())[:3]:
                print(f"  [{trans}]")
                for tense in TENSES:
                    row = tenses.get(tense)
                    if row:
                        print(f"    {tense:32}: {row}")


if __name__ == "__main__":
    main()
