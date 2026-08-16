#!/usr/bin/env python3
"""
step_5e_build_conjugated_english.py — Morphology-matched English for verb senses.

Pure English-to-English step: for every verb sense in the sense menu, generate
the English forms whose spelling requires inflection knowledge (e.g. ``to
eat`` -> indicative/person grids plus ``eating`` and ``eaten``). The front-end
picks a cell at render time using the morphology field already stamped on the
vocabulary entry, and derives regular ``would eat`` / ``eat!`` frames from the
same infinitive gloss without bloating this shared layer with repeated strings.

This step is language-agnostic — it never touches the source-language verb
or its conjugation table. The only Spanish-specific bits are the carve-out
constants (GUSTAR_BLACKLIST, BE_FORMS lemma allow-list) and the input path.
The morphology stamping (Wiktionary primary, verbecc fallback) is the
language-specific dependency, and lives in step_8a / tool_4a.

Output keys are ``mood/tense`` analysis keys matching the two corresponding
fields in ``vocabulary.index.json``. We intentionally abstain from Spanish
imperfect and subjunctive: neither has one context-free English realization.
If a lookup misses (unsupported analysis, blacklisted lemma, non-conjugatable
sense shape, missing morphology) the front-end keeps the dictionary gloss and
its separate visible grammar cue.

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

STEP_VERSION = 3
STEP_VERSION_NOTES = {
    1: "lemminflect-driven person/tense English conjugation for verb senses "
       "(presente, pretérito-perfecto-simple, futuro)",
    2: "drop conjugations.json dependency — walk sense_menu directly. Step "
       "is now language-agnostic; coverage extends to verbs Wiktionary "
       "tagged but verbecc didn't handle (voseo, regional, tail verbs).",
    3: "key output by full mood/tense analysis, add inflection-dependent "
       "gerund and past-participle forms, and support render-time conditional "
       "and imperative frames; continue to abstain from context-dependent "
       "imperfect and subjunctive forms",
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

# Analysis keys exactly match vocabulary.index.json's morphology mood + tense
# fields. Spanish imperfect and subjunctive are deliberately absent: emitting
# one English paraphrase would falsely make a context-sensitive choice for the
# learner. The UI still shows those grammar labels next to the dictionary gloss.
STORED_FINITE_ANALYSES = [
    ("indicativo", "presente"),
    ("indicativo", "pretérito-perfecto-simple"),
    ("indicativo", "futuro"),
]
NONFINITE_ANALYSES = [
    ("gerundio", "gerundio"),
    ("participo", "participo"),
]
ANALYSES = STORED_FINITE_ANALYSES + NONFINITE_ANALYSES

# "to be" head — fully irregular, override LemmInflect.
BE_FORMS = {
    "presente":                   ["am", "are", "is", "are", "are", "are"],
    "pretérito-perfecto-simple":  ["was", "were", "was", "were", "were", "were"],
    "futuro":                     ["will be"] * 6,
}


def analysis_key(mood, tense):
    return f"{mood}/{tense}"


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


def _inflection(head, tag, fallback_suffix, _cache={}):
    """Return one LemmInflect form for a base verb, cached by POS tag."""
    key = (head, tag)
    if key in _cache:
        return _cache[key]
    from lemminflect import getInflection
    forms = getInflection(head, tag=tag)
    out = forms[0] if forms else (head + fallback_suffix)
    _cache[key] = out
    return out


def _translation_parts(translation):
    """Split ``to VERB ...`` into its inflected head and unchanged tail."""
    s = translation.strip()
    if not s.startswith("to "):
        return None
    body = s[3:].strip()
    if not body:
        return None
    parts = body.split(" ", 1)
    return parts[0], ((" " + parts[1]) if len(parts) > 1 else "")


def conjugate_translation(translation, tense, person_idx, mood="indicativo"):
    """Render one finite (translation, analysis, person) cell.

    Returns the English string, or None if the shape isn't conjugatable
    (front-end falls back to infinitive in that case).
    """
    s = translation.strip()
    if not s:
        return None
    pron = PRONOUNS[person_idx]

    # Bare modal sense. It has no imperative/conditional inflection and adding
    # ``will`` or ``would`` would produce ungrammatical English.
    if s in MODALS_PAST or s in MODALS_KEEP:
        if mood != "indicativo":
            return None
        if tense == "presente":
            return f"{pron} {s}"
        if tense == "pretérito-perfecto-simple":
            return f"{pron} {MODALS_PAST.get(s, s)}"
        return None  # futuro: drop, no clean English

    parts = _translation_parts(s)
    if not parts:
        return None
    head, rest = parts

    if mood == "condicional" and tense == "presente":
        return f"{pron} would {head}{rest}"

    if mood == "imperativo":
        if person_idx == 0:
            return None  # Spanish has no 1st-person singular imperative.
        if tense == "negativo":
            if person_idx == 3:
                return f"let's not {head}{rest}!"
            return f"don't {head}{rest}!"
        if tense != "afirmativo":
            return None
        if person_idx == 3:
            return f"let's {head}{rest}!"
        return f"{head}{rest}!"

    if mood != "indicativo":
        return None

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


def nonfinite_translation(translation, mood, tense):
    """Render a context-free gerund or past participle, without a subject."""
    if translation.strip() in MODALS_PAST or translation.strip() in MODALS_KEEP:
        return None
    parts = _translation_parts(translation)
    if not parts:
        return None
    head, rest = parts
    if mood == "gerundio" and tense == "gerundio":
        form = "being" if head == "be" else _inflection(head, "VBG", "ing")
        return f"{form}{rest}"
    if mood in ("participo", "participio") and tense in ("participo", "participio"):
        form = "been" if head == "be" else _inflection(head, "VBN", "ed")
        return f"{form}{rest}"
    return None


def build_analysis_forms(translation):
    """Build every supported mood/tense row for one English translation."""
    rows = {}
    for mood, tense in STORED_FINITE_ANALYSES:
        row = [conjugate_translation(translation, tense, p, mood=mood)
               for p in range(6)]
        if any(value is not None for value in row):
            rows[analysis_key(mood, tense)] = row
    for mood, tense in NONFINITE_ANALYSES:
        form = nonfinite_translation(translation, mood, tense)
        if form:
            rows[analysis_key(mood, tense)] = [form]
    return rows


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
            analysis_dict = build_analysis_forms(trans)
            if analysis_dict:
                per_sense[trans] = analysis_dict
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
            for trans, analyses in list(entry.items())[:3]:
                print(f"  [{trans}]")
                for mood, tense in ANALYSES:
                    key = analysis_key(mood, tense)
                    row = analyses.get(key)
                    if row:
                        print(f"    {key:32}: {row}")


if __name__ == "__main__":
    main()
