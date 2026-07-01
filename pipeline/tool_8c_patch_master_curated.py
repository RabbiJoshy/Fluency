#!/usr/bin/env python3
"""No-rerun curated patches to vocabulary_master.json (in place).

Applies a small set of hand-verified corrections directly to the assembled
master, WITHOUT re-running the pipeline. Each edit is in-place (no change to
any card's sense COUNT) so the per-artist index files — which reference senses
positionally — stay in sync. See docs/deck_quality_audit.md.

Two kinds of edit:
  - OVERRIDES      : per-card field corrections (lemma / flag / sense fields).
  - COGNATE_STAMPS : flag single-sense transparent cognates (gloss == the
                     Spanish word, e.g. radio->"radio") with
                     is_transparent_cognate so the front-end hides them by
                     default. Single-sense only — hiding the card loses no
                     other meaning. False friends (cognates.json `keep`) and
                     multi-sense leaks are deliberately excluded.

Idempotent and safe to re-run: it verifies each entry's surface word before
touching it and only reports a change when a value actually differs.

IMPORTANT: `tool_8c_merge_to_master` rebuilds master from layers and drops
these edits. Re-run this script after any master rebuild, until the fixes are
folded into the pipeline proper. Run from project root:

    .venv/bin/python3 pipeline/tool_8c_patch_master_curated.py
"""
import json
import os
import sys

MASTER = "Artists/spanish/vocabulary_master.json"

# key (master hex) -> expected surface word + the in-place mutations.
#   lemma   : new lemma string (or None to leave)
#   flags   : top-level flag overrides
#   senses  : {sense_index: {field: value, ...}}
OVERRIDES = [
    {
        "key": "c7a231", "word": "millo", "lemma": None, "flags": {},
        # "Nací pa' ser millo" — PR slang clip of millón = rich, not "corn".
        "senses": {0: {"translation": "millionaire", "context": "slang"}},
    },
    {
        "key": "7917b4", "word": "niveles", "lemma": "nivel", "flags": {},
        # "es cuestión de niveles" — plural of NOUN nivel, not the verb nivelar.
        "senses": {0: {"pos": "NOUN", "translation": "level", "context": ""}},
    },
    {
        "key": "b7f4e2", "word": "diablo", "lemma": None, "flags": {},
        # Fill the blank interjection sense (the flagged "damn!" usage).
        "senses": {1: {"translation": "damn!; the hell", "context": "exclamation"}},
    },
    {
        "key": "8b83ae", "word": "diablos", "lemma": None, "flags": {},
        # "¿Cómo diablos...?" = how the hell.
        "senses": {0: {"translation": "the hell; devils", "context": "exclamation"}},
    },
    {
        "key": "d15eaf", "word": "bi", "lemma": None, "flags": {},
        # Shorten the verbose gap-fill gloss in place (single real sense).
        "senses": {0: {"translation": "boo; baby (term of endearment)"}},
    },
    {
        "key": "0f1ec2", "word": "shot", "lemma": None,
        # English code-switch — hide via the default-on loanword filter.
        "flags": {"is_english_loanword": True},
        "senses": {},
    },
    {
        "key": "0aa057", "word": "compositor", "lemma": None, "flags": {},
        # Leaked as itself; English "compositor" is an archaic printing term.
        # The music sense (the one in the corpus) is "composer". Fix the gloss
        # rather than hide the card.
        "senses": {0: {"translation": "composer"}},
    },
    {
        "key": "6be7cb", "word": "tití", "lemma": None, "flags": {},
        # PR usage ("Tití me preguntó") = auntie, not the monkey "titi".
        # Fix the gloss rather than hide the card.
        "senses": {0: {"translation": "auntie"}},
    },
    {
        "key": "eeeb94", "word": "eo", "lemma": None,
        # Bad Bunny ad-lib filler ("eo eo eo"), not the rare noun eo=hiatus.
        # Hide as noise (default-on noise filter) rather than teach it.
        "flags": {"is_noise": True},
        "senses": {},
    },
]

# Single-sense transparent cognates: only sense glosses to the Spanish word
# itself, so the card teaches nothing. Stamp is_transparent_cognate -> the
# front-end hides them under the default-on cognate filter. (key, word) pairs;
# word is verified against the master before stamping. Generated from the
# bench cognate-leak scan, hand-reviewed: false friends and multi-sense leaks
# (china, super, union, general, ...) are excluded. See docs/deck_quality_audit.md.
COGNATE_STAMPS = [
    ("19f1f6", "alcohol"),
    ("f4245c", "area"),
    ("a2dcd6", "bachata"),
    ("822807", "bases"),
    ("dc0219", "chicha"),
    ("7cef6e", "control"),
    ("57765a", "crack"),
    ("22f1f4", "dimensión"),
    ("b40305", "formal"),
    ("acd437", "gala"),
    ("78b399", "idea"),
    ("391fac", "iris"),
    ("503471", "legal"),
    ("0e5c84", "local"),
    ("cf0920", "manual"),
    ("9e03b3", "marihuana"),
    ("deeb66", "melón"),
    ("2d00c2", "normal"),
    ("0557d6", "novena"),
    ("835779", "perfume"),
    ("5f478c", "personal"),
    ("71816b", "popular"),
    ("91c4e7", "radio"),
    ("dc47ea", "samurai"),
    ("701880", "sangría"),
    ("6e83d0", "santería"),
    ("353258", "sativa"),
    ("2c66cd", "sensual"),
    ("75b019", "sushi"),
    ("a93b2f", "súper"),
    ("7c2d28", "unión"),
    ("a34e06", "vodka"),
    ("cc4896", "élite"),
    # Short (<4 char) transparent cognates the generator's len>=4 guard skips;
    # hand-verified single-sense gloss==word leaks (see the 6-short-word audit).
    ("0cfe85", "dúo"),
    ("bad194", "era"),    # NOUN era|era only; VERB era|ser ("to be") untouched
    ("b936fa", "ex"),
    ("4c30db", "gas"),
]

# English code-switches the Wiktionary-derived english_loanwords.json layer
# misses (they aren't in es.wiktionary as all-English-borrowing entries, so
# tool_4a/tool_8a never flag them). Same effect as the layer stamp:
# is_english_loanword -> the default-on loanword filter hides them. Surface
# word verified before stamping. The systematic fix is a manual loanword
# supplement folded into tool_8a; until then these live here. (key, word).
LOANWORD_STAMPS = [
    ("8e40c1", "boy"),
    ("6e23bc", "combo"),
    ("1eac4f", "haters"),
    ("f0ae8d", "lean"),
    ("d34a61", "lit"),
    ("9648af", "polaroid"),
    ("ab4169", "sexy"),
    ("39f5f1", "squad"),
]


def main():
    if not os.path.isfile(MASTER):
        sys.exit("master not found: %s (run from project root)" % MASTER)
    with open(MASTER, "r", encoding="utf-8") as f:
        m = json.load(f)

    changes = 0
    for ov in OVERRIDES:
        entry = m.get(ov["key"])
        if entry is None:
            print("SKIP %s (%s): key not in master" % (ov["key"], ov["word"]))
            continue
        if entry.get("word") != ov["word"]:
            print("SKIP %s: expected word %r, found %r — not patching"
                  % (ov["key"], ov["word"], entry.get("word")))
            continue

        if ov.get("lemma") and entry.get("lemma") != ov["lemma"]:
            print("  %-10s lemma %r -> %r" % (ov["word"], entry.get("lemma"), ov["lemma"]))
            entry["lemma"] = ov["lemma"]
            changes += 1

        for flag, val in ov.get("flags", {}).items():
            if entry.get(flag) != val:
                print("  %-10s flag %s -> %r" % (ov["word"], flag, val))
                entry[flag] = val
                changes += 1

        senses = entry.get("senses", [])
        for idx, fields in ov.get("senses", {}).items():
            if idx >= len(senses):
                print("  %-10s SKIP sense[%d]: out of range (have %d)"
                      % (ov["word"], idx, len(senses)))
                continue
            for field, val in fields.items():
                if senses[idx].get(field) != val:
                    print("  %-10s sense[%d].%s %r -> %r"
                          % (ov["word"], idx, field, senses[idx].get(field), val))
                    senses[idx][field] = val
                    changes += 1

    for key, word in COGNATE_STAMPS:
        entry = m.get(key)
        if entry is None:
            print("SKIP %s (%s): key not in master" % (key, word))
            continue
        if entry.get("word") != word:
            print("SKIP %s: expected word %r, found %r — not stamping"
                  % (key, word, entry.get("word")))
            continue
        if entry.get("is_transparent_cognate") is not True:
            print("  %-12s is_transparent_cognate -> True" % word)
            entry["is_transparent_cognate"] = True
            changes += 1

    for key, word in LOANWORD_STAMPS:
        entry = m.get(key)
        if entry is None:
            print("SKIP %s (%s): key not in master" % (key, word))
            continue
        if entry.get("word") != word:
            print("SKIP %s: expected word %r, found %r — not stamping"
                  % (key, word, entry.get("word")))
            continue
        if entry.get("is_english_loanword") is not True:
            print("  %-12s is_english_loanword -> True" % word)
            entry["is_english_loanword"] = True
            changes += 1

    if changes == 0:
        print("No changes (master already patched).")
        return

    # Atomic write, matching the builder's dump format (single line, raw UTF-8).
    tmp = MASTER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False)
    os.replace(tmp, MASTER)
    print("\nApplied %d field change(s) to %s" % (changes, MASTER))


if __name__ == "__main__":
    main()
