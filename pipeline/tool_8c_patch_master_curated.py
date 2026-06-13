#!/usr/bin/env python3
"""No-rerun curated patches to vocabulary_master.json (in place).

Applies a small set of hand-verified corrections directly to the assembled
master, WITHOUT re-running the pipeline. Each edit is in-place (no change to
any card's sense COUNT) so the per-artist index files — which reference senses
positionally — stay in sync. See docs/deck_quality_audit.md.

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
