#!/usr/bin/env python3
"""tool_8d_patch_artist_morphology.py — stamp `morphology` onto artist index
entries in place (no rerun).

Artist decks had 0% morphology coverage: `step_8b_assemble_artist_vocabulary`
never writes the field, so verb cards show no tense/person tag on the front
(the #frontMorph element renders `card.morphology` — normal mode has 42%
coverage from step_8a). This mirrors step_8a's stamping logic exactly
(Wiktionary morphology layer first, verbecc conjugation_reverse fallback,
lemma-filtered; single match -> object, multiple -> array, word == lemma with
a VERB sense -> {mood: infinitivo}).

Safe: adds/updates a per-entry FIELD in the index files — sense positions are
untouched. Idempotent. Re-run after `step_5b_build_conjugations.py` rebuilds
conjugation_reverse.json (more lemmas covered = more cards stamped), and
after any artist index rebuild. Run from project root:

    .venv/bin/python3 pipeline/tool_8d_patch_artist_morphology.py
"""
import json
import os

MASTER = "Artists/spanish/vocabulary_master.json"
WIKT_MORPH = "Data/Spanish/layers/morphology.json"
CONJ_REVERSE = "Data/Spanish/layers/conjugation_reverse.json"
INDEXES = [
    "Artists/spanish/Bad Bunny/BadBunnyvocabulary.index.json",
    "Artists/spanish/Young Miko/YoungMikovocabulary.index.json",
    "Artists/spanish/Rosalía/Rosaliavocabulary.index.json",
]


def load(path, default):
    if not os.path.isfile(path):
        print("  (missing: %s)" % path)
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def lemma_matches(candidate_lemma, lemma_l):
    """Reverse-lookup lemmas are base infinitives; master lemmas may be
    reflexive (quejarse) — accept the base form too."""
    if candidate_lemma == lemma_l:
        return True
    return lemma_l.endswith("se") and candidate_lemma == lemma_l[:-2]


def compute(word_l, lemma_l, senses, wikt_morph, conj_reverse):
    has_verb = any(s.get("pos") == "VERB" and (s.get("translation") or "").strip()
                   for s in senses)
    if word_l == lemma_l:
        return {"mood": "infinitivo"} if has_verb else None
    matches = [
        {"mood": c["mood"], "tense": c["tense"], "person": c["person"]}
        for c in wikt_morph.get(word_l, [])
        if lemma_matches(c.get("lemma", ""), lemma_l)
    ]
    if not matches:
        matches = [
            {"mood": c["mood"], "tense": c["tense"], "person": c["person"]}
            for c in conj_reverse.get(word_l, [])
            if lemma_matches(c.get("lemma", ""), lemma_l)
        ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return matches
    return None


def main():
    master = load(MASTER, None)
    if master is None:
        raise SystemExit("master not found (run from project root)")
    wikt_morph = load(WIKT_MORPH, {})
    conj_reverse = load(CONJ_REVERSE, {})

    for path in INDEXES:
        idx = load(path, None)
        if idx is None:
            continue
        stamped = changed = 0
        for entry in idx:
            m = master.get(entry.get("id"))
            if not m:
                continue
            morph = compute((m.get("word") or "").lower(),
                            (m.get("lemma") or "").lower(),
                            m.get("senses", []), wikt_morph, conj_reverse)
            if morph is not None:
                stamped += 1
                if entry.get("morphology") != morph:
                    entry["morphology"] = morph
                    changed += 1
            elif "morphology" in entry:
                del entry["morphology"]
                changed += 1
        name = os.path.basename(path)
        print("%-40s stamped %5d / %5d entries (%d changed)"
              % (name, stamped, len(idx), changed))
        if changed:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(idx, f, ensure_ascii=False)
            os.replace(tmp, path)


if __name__ == "__main__":
    main()
