#!/usr/bin/env python3
"""Word==translation routing tag (runs after the sense menu is built).

A word whose Spanish surface equals its English translation is a transparent
cognate, a loanword, or a proper-noun/acronym — not plain learnable vocab. This
is a LATER-STAGE tag (translations don't exist at step_4a), so it runs after
step_5c and re-tags classifier-bucketed words in word_routing.json, moving them
to the right exclude bucket (→ Extra) before step_6/Gemini.

Split (using the SpanishDict first-sense translation):
  - translation has uppercase (dj→DJ, pr→PR, vip→VIP)  → proper_nouns
  - word is a real Spanish word (in es_50k)            → cognate
  - otherwise                                          → english (loanword)

Guards: skip always_teach (cognates.json keep) and the ~500 most frequent
Spanish function words (so `no`→"no", `a`→"a" are never excluded).

Usage:
  .venv/bin/python3 pipeline/artist/tool_5c_tag_word_eq_translation.py \
      --artist-dir "Artists/spanish/Bad Bunny"
"""
import argparse, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Function/grammar POS never get excluded even if word==translation (protects
# no→"no", a→"a"). Content POS (NOUN/ADJ/VERB) are safe cognates/loanwords.
FUNCTION_POS = {"ADV", "ADP", "PREP", "CONJ", "CCONJ", "SCONJ", "PRON",
                "DET", "INTJ", "PART", "AUX", "X"}


def _load(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return d if d is not None else {}


def _first_sense(menu_entry):
    ana = menu_entry[0] if isinstance(menu_entry, list) else menu_entry
    if not isinstance(ana, dict):
        return None
    senses = ana.get("senses")
    if isinstance(senses, dict):
        senses = list(senses.values())
    if isinstance(senses, list) and senses and isinstance(senses[0], dict):
        return senses[0]
    return ana


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artist-dir", required=True)
    ap.add_argument("--language", default="Spanish")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    adir = os.path.abspath(args.artist_dir)

    menu = _load(os.path.join(ROOT, "Data", args.language, "layers", "sense_menu", "spanishdict.json"))
    # es_50k membership → distinguishes transparent cognate (real Spanish word)
    # from loanword in the split below.
    es_words = set()
    p = os.path.join(ROOT, "Data", args.language, "es_50k_wordlist.txt")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                tok = line.strip().split()
                if tok:
                    es_words.add(tok[0].lower())

    # curated teach-allowlist
    cur = _load(os.path.join(adir, "..", "..", "curations", "cognates.json"), {})
    always_teach = set((cur.get("keep") or []) if isinstance(cur, dict) else [])

    wr_path = os.path.join(adir, "data", "known_vocab", "word_routing.json")
    wr = _load(wr_path)
    excl = wr.setdefault("exclude", {})
    clf = wr.get("classifier", {}) or {}
    for b in ("english", "cognate", "proper_nouns"):
        excl.setdefault(b, [])
    excl_sets = {k: set(v) for k, v in excl.items()}
    clf_sets = {k: set(v) for k, v in clf.items()}

    moves = {"proper_nouns": [], "cognate": [], "english": []}
    for cbucket in ("normal_vocab", "conjugation"):
        for w in list(clf_sets.get(cbucket, set())):
            wl = w.lower()
            if wl in always_teach:
                continue
            sense = _first_sense(menu.get(w) or menu.get(wl))
            if not isinstance(sense, dict):
                continue
            if (sense.get("pos") or "").upper() in FUNCTION_POS:
                continue  # protects no→"no", a→"a", etc.
            t = sense.get("translation")
            if not t or t.strip().lower() != wl:
                continue
            if t != t.lower():                 # DJ, PR, VIP → acronym/proper noun
                dest = "proper_nouns"
            elif wl in es_words:               # real Spanish word → transparent cognate
                dest = "cognate"
            else:                              # not in Spanish freq → loanword
                dest = "english"
            clf_sets[cbucket].discard(w)
            excl_sets[dest].add(w)
            moves[dest].append("%s=%s" % (w, t))

    total = sum(len(v) for v in moves.values())
    print("word==translation re-tags: %d" % total)
    for k, v in moves.items():
        print("  → %-13s %3d  %s" % (k, len(v), ", ".join(v[:12]) + (" …" if len(v) > 12 else "")))

    if args.dry_run:
        print("(dry-run — not written)")
        return
    for k in excl_sets:
        excl[k] = sorted(excl_sets[k])
    for k in clf_sets:
        clf[k] = sorted(clf_sets[k])
    wr["classifier"] = clf
    with open(wr_path, "w", encoding="utf-8") as f:
        json.dump(wr, f, ensure_ascii=False, indent=2)
    print("Wrote %s" % wr_path)


if __name__ == "__main__":
    main()
