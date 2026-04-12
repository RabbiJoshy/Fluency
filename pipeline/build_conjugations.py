#!/usr/bin/env python3
"""
build_conjugations.py — Generate conjugation tables and reverse lookup.

Uses verbecc to conjugate all verb lemmas found in word_inventory.json.
Supplements with Jehle's English translations where available.

Usage:
    python3 pipeline/build_conjugations.py

Run from the project root (Fluency/).

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/layers/senses_wiktionary.json        (to identify verb entries)
    Data/Spanish/corpora/jehle/jehle_verb_database.csv (optional, for translations)

Outputs:
    Data/Spanish/layers/conjugations.json          — full tables for front-end
    Data/Spanish/layers/conjugation_reverse.json   — form→lemma lookup for pipeline
"""

import csv
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"
INVENTORY_FILE = LAYERS / "word_inventory.json"
SENSES_FILE = LAYERS / "senses_wiktionary.json"
JEHLE_FILE = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "jehle" / "jehle_verb_database.csv"
CONJUGATIONS_FILE = LAYERS / "conjugations.json"
REVERSE_FILE = LAYERS / "conjugation_reverse.json"

# The 6 standard pronouns we show in the table (order = yo/tú/él/nosotros/vosotros/ellos)
STANDARD_PRONOUNS = ["yo", "tú", "él", "nosotros", "vosotros", "ellos"]

# Core tenses for the front-end conjugation table
CORE_TENSES = {
    "indicativo": [
        ("presente", "Presente"),
        ("pretérito-perfecto-simple", "Pretérito"),
        ("pretérito-imperfecto", "Imperfecto"),
        ("futuro", "Futuro"),
    ],
    "condicional": [
        ("presente", "Condicional"),
    ],
    "subjuntivo": [
        ("presente", "Subj. Presente"),
    ],
}


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def load_jehle_translations(path: Path) -> dict:
    """Load Jehle CSV and extract infinitive → English translation."""
    if not path.exists():
        print(f"  Jehle file not found at {path}, skipping translations")
        return {}

    translations = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            inf = row["infinitive"].strip().lower()
            eng = row["infinitive_english"].strip()
            if inf and eng and inf not in translations:
                translations[inf] = eng
    print(f"  Loaded {len(translations)} Jehle translations")
    return translations


def extract_forms(persons: list, pronouns: list) -> list:
    """Extract conjugated forms for the standard pronouns from verbecc output."""
    # Build pronoun → form mapping (pick first match per pronoun)
    pronoun_map = {}
    for p in persons:
        pr = p.get("pr", "")
        if pr in pronouns and pr not in pronoun_map:
            conjugation = p["c"][0] if p.get("c") else ""
            # Strip pronoun prefix to get bare form
            if conjugation.startswith(pr + " "):
                conjugation = conjugation[len(pr) + 1:]
            pronoun_map[pr] = conjugation

    return [pronoun_map.get(pr, "—") for pr in pronouns]


def build_conjugation_entry(verb, cg, jehle_trans):
    """Build a conjugation table entry for one verb."""
    try:
        result = cg.conjugate(verb)
    except Exception:
        return None

    j = json.loads(result.to_json())
    moods = j.get("moods", {})

    entry = {}

    # Jehle translation if available
    if verb in jehle_trans:
        entry["translation"] = jehle_trans[verb]

    # Gerund
    gerundio = moods.get("gerundio", {}).get("gerundio", [])
    if gerundio and gerundio[0].get("c"):
        entry["gerund"] = gerundio[0]["c"][0]

    # Past participle
    participo = moods.get("participo", {}).get("participo", [])
    if isinstance(participo, list) and participo:
        pp = participo[0] if isinstance(participo[0], str) else participo[0].get("c", [""])[0]
        entry["past_participle"] = pp
    elif isinstance(participo, str):
        entry["past_participle"] = participo

    # Core tenses
    tenses = {}
    for mood_key, tense_list in CORE_TENSES.items():
        mood_data = moods.get(mood_key, {})
        for tense_key, display_name in tense_list:
            persons = mood_data.get(tense_key, [])
            if persons:
                forms = extract_forms(persons, STANDARD_PRONOUNS)
                tenses[display_name] = forms

    entry["tenses"] = tenses

    return entry


def build_reverse_lookup(verb: str, cg) -> list:
    """Build reverse lookup entries: [(form, {lemma, mood, tense, person}), ...]"""
    try:
        result = cg.conjugate(verb)
    except Exception:
        return []

    j = json.loads(result.to_json())
    moods = j.get("moods", {})
    entries = []

    person_labels = {
        ("s", "1"): "1s",
        ("s", "2"): "2s",
        ("s", "3"): "3s",
        ("p", "1"): "1p",
        ("p", "2"): "2p",
        ("p", "3"): "3p",
    }

    for mood_name, tenses in moods.items():
        if mood_name in ("gerundio", "participo", "participio-pasado"):
            # Handle non-person forms
            for tense_name, persons in tenses.items():
                for p in persons:
                    c_list = p.get("c", []) if isinstance(p, dict) else []
                    for c in c_list:
                        form = c.strip().lower()
                        # Strip "no " prefix from negative imperative
                        if form.startswith("no "):
                            form = form[3:]
                        entries.append((form, {
                            "lemma": verb,
                            "mood": mood_name,
                            "tense": tense_name,
                            "person": "",
                        }))
            continue

        for tense_name, persons in tenses.items():
            for p in persons:
                pr = p.get("pr", "")
                n = p.get("n", "")
                person_num = p.get("p", "")
                person_label = person_labels.get((n, person_num), "")

                c_list = p.get("c", [])
                for c in c_list:
                    # Strip pronoun to get bare form
                    form = c.strip()
                    if form.startswith(pr + " "):
                        form = form[len(pr) + 1:]
                    # Strip "no " for negative imperative
                    if form.startswith("no "):
                        form = form[3:]
                    form = form.lower()

                    entries.append((form, {
                        "lemma": verb,
                        "mood": mood_name,
                        "tense": tense_name,
                        "person": person_label,
                    }))

    return entries


def main():
    # Load inventory to find verb lemmas
    print("Loading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        inventory = json.load(f)

    # Load senses to identify verbs
    print("Loading senses...")
    with open(SENSES_FILE, encoding="utf-8") as f:
        senses_data = json.load(f)

    # Collect unique verb infinitives
    verb_lemmas = set()
    for entry in inventory:
        key = f"{entry['word']}|{entry['lemma']}"
        senses = senses_data.get(key, [])
        has_verb = any(s["pos"] == "VERB" for s in senses)
        if has_verb:
            lemma = entry["lemma"].lower()
            if lemma.endswith(("ar", "er", "ir", "ír")):
                verb_lemmas.add(lemma)

    print(f"  Found {len(verb_lemmas)} unique verb infinitives")

    # Load Jehle translations
    print("Loading Jehle translations...")
    jehle_trans = load_jehle_translations(JEHLE_FILE)

    # Initialize verbecc (suppress logging)
    import logging
    logging.getLogger("verbecc").setLevel(logging.ERROR)
    from verbecc import CompleteConjugator
    cg = CompleteConjugator(lang="es")

    # Generate conjugation tables + reverse lookup
    print(f"\nConjugating {len(verb_lemmas)} verbs...")
    conjugations = {}
    reverse = defaultdict(list)
    success = 0
    failed = []

    for i, verb in enumerate(sorted(verb_lemmas)):
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(verb_lemmas)}...")

        # Conjugation table
        entry = build_conjugation_entry(verb, cg, jehle_trans)
        if entry:
            conjugations[verb] = entry
            success += 1
        else:
            failed.append(verb)
            continue

        # Reverse lookup
        for form, info in build_reverse_lookup(verb, cg):
            # Only add if not already present with same lemma+mood+tense+person
            existing = reverse.get(form, [])
            if not any(e["lemma"] == info["lemma"] and e["mood"] == info["mood"]
                       and e["tense"] == info["tense"] and e["person"] == info["person"]
                       for e in existing):
                reverse[form].append(info)

    # Write outputs
    print(f"\nWriting {CONJUGATIONS_FILE}...")
    with open(CONJUGATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(conjugations, f, ensure_ascii=False, indent=2)

    print(f"Writing {REVERSE_FILE}...")
    with open(REVERSE_FILE, "w", encoding="utf-8") as f:
        json.dump(dict(reverse), f, ensure_ascii=False, indent=2)

    # Report
    print(f"\n{'='*55}")
    print("CONJUGATION BUILD RESULTS")
    print(f"{'='*55}")
    print(f"Verb infinitives:     {len(verb_lemmas):>6}")
    print(f"Successfully conjugated: {success:>6}")
    print(f"Failed:                  {len(failed):>6}")
    if failed:
        print(f"  Failed verbs: {failed[:20]}")
    print(f"Conjugation tables:   {len(conjugations):>6}")
    print(f"Reverse lookup forms: {len(reverse):>6}")
    jehle_count = sum(1 for v in conjugations.values() if "translation" in v)
    print(f"With Jehle translation: {jehle_count:>6}")


if __name__ == "__main__":
    main()
