#!/usr/bin/env python3
"""Deck-quality diagnostics for the assembled Spanish artist decks.

Replicates the front-end default filters (see js/vocab.js buildFilteredVocab)
to count VISIBLE cards, then scans those cards for defect classes that hurt
deck quality:

  - blank_rows          : a sense whose translation is empty (SpanishDict
                          captured the usage label but not the gloss). The
                          front-end empty-meaning guard drops these.
  - verbose_def         : Gemini gap-fill wrote a sentence-style definition
                          instead of a short gloss (NOUN/ADJ especially).
  - cognate_leak        : single sense whose gloss == the Spanish word and
                          cognate_score < threshold (cognate slipped the net).
  - menu_bloat          : the same gloss repeated >= 4x across senses.
  - example_empty_en    : example rows with no English translation.
  - example_untranslated: example rows where english == spanish verbatim.

Read-only. Run from the project root:

    .venv/bin/python3 pipeline/bench_deck_quality.py
"""
import json
import re
import collections
import unicodedata

MASTER = "Artists/spanish/vocabulary_master.json"
ARTISTS = {
    "BadBunny": (
        "Artists/spanish/Bad Bunny/BadBunnyvocabulary.index.json",
        "Artists/spanish/Bad Bunny/BadBunnyvocabulary.examples.json",
    ),
    "YoungMiko": (
        "Artists/spanish/Young Miko/YoungMikovocabulary.index.json",
        "Artists/spanish/Young Miko/YoungMikovocabulary.examples.json",
    ),
    "Rosalia": (
        "Artists/spanish/Rosalía/Rosaliavocabulary.index.json",
        "Artists/spanish/Rosalía/Rosaliavocabulary.examples.json",
    ),
}

COGNATE_THRESHOLD = 0.85

# Phrases that signal a definitional sentence rather than a gloss.
CONNECT = re.compile(
    r"\b(used to|used for|refers? to|similar to|term (of|for)|expression|"
    r"slang for|a way of|the act of|denoting|describ\w+|informal|colloquial|"
    r"referring to|nickname|brand name|a type of|a person who|a group of|"
    r"characteriz)\b",
    re.I,
)


def norm(t):
    return (t or "").strip()


def keynorm(t):
    """Case- and accent-insensitive, trimmed (área == area, melón == melon)."""
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").strip().lower())
                   if unicodedata.category(c) != "Mn")


def cognate_score(mst, idx):
    """Mirror the front-end (js/vocab.js ~line 166):
    idx.cognate_score ?? master.cognate_score ?? (is_transparent_cognate ? 1 : 0).
    Without the is_transparent_cognate fallback the bench would count stamped
    cognates as visible even though the deck hides them.
    """
    for v in (idx.get("cognate_score"), mst.get("cognate_score")):
        if v is not None:
            return v
    return 1 if mst.get("is_transparent_cognate") else 0


def real_senses(mst):
    """Senses the front-end would render: drop empty-translation senses.

    Mirrors the post-fix empty-meaning guard in js/vocab.js (drop ANY meaning
    with no translation, not just POS=X). A card with no real sense is hidden.
    """
    return [s for s in mst.get("senses", []) if norm(s.get("translation"))]


def visible(mst, idx):
    """True if this card survives the front-end default filters."""
    if not mst:
        return False
    if mst.get("is_english") or mst.get("is_noise") or mst.get("is_interjection"):
        return False
    if mst.get("is_english_loanword"):
        return False
    if mst.get("is_propernoun") or mst.get("is_propernoun_corpus"):
        return False
    senses = real_senses(mst)
    if not senses:
        return False
    if all(s.get("pos") == "PROPN" for s in senses):
        return False
    if cognate_score(mst, idx) >= COGNATE_THRESHOLD:
        return False
    if (idx.get("corpus_count", 0) or 0) <= 1:
        return False
    return True


def main():
    m = json.load(open(MASTER))

    visible_ids = set()
    per_artist = collections.Counter()
    defect = collections.defaultdict(list)

    # Per-card structural defects (master-side).
    for artist, (ipath, _epath) in ARTISTS.items():
        idx_list = json.load(open(ipath))
        for idx in idx_list:
            mid = idx.get("id")
            mst = m.get(mid)
            if not visible(mst, idx):
                continue
            per_artist[artist] += 1
            if mid in visible_ids:
                continue
            visible_ids.add(mid)
            word = mst.get("word", "")
            all_senses = mst.get("senses", [])
            senses = real_senses(mst)

            # blank_rows: empty-translation sense on an otherwise-visible card
            blanks = [s for s in all_senses if not norm(s.get("translation"))
                      and not (s.get("pos") == "X")]
            if blanks:
                defect["blank_rows"].append(
                    (artist, word, len(blanks),
                     [norm(s.get("context")) for s in blanks][:3]))

            # verbose_def: definitional gloss
            for s in senses:
                t = norm(s.get("translation"))
                if not t:
                    continue
                if len(t.split()) > 5 or CONNECT.search(t) or ";" in t or t.endswith("."):
                    defect["verbose_def"].append((artist, word, s.get("pos"), t[:80]))
                    break

            # cognate_leak: single sense, gloss == word (accent-insensitive)
            if len(senses) == 1:
                t = norm(senses[0].get("translation"))
                if t and keynorm(t) == keynorm(word):
                    defect["cognate_leak"].append((artist, word, t))

            # menu_bloat: one gloss repeated >= 4x
            gl = collections.Counter(norm(s.get("translation")).lower()
                                     for s in senses if norm(s.get("translation")))
            for g, c in gl.items():
                if c >= 4:
                    defect["menu_bloat"].append((artist, word, g, c))
                    break

    # Example-level defects (examples-side).
    ex_total = ex_empty = ex_untrans = 0
    cards_all_empty = []
    for artist, (ipath, epath) in ARTISTS.items():
        idx_list = json.load(open(ipath))
        ex = json.load(open(epath))
        vis = {idx["id"]: idx for idx in idx_list if visible(m.get(idx.get("id")), idx)}
        for mid in vis:
            node = ex.get(mid)
            if not node:
                continue
            flat = [e for grp in node.get("m", []) for e in grp]
            if not flat:
                continue
            word = m[mid].get("word", "")
            n = len(flat)
            e_empty = 0
            for e in flat:
                ex_total += 1
                es = norm(e.get("spanish"))
                en = norm(e.get("english"))
                if not en:
                    ex_empty += 1
                    e_empty += 1
                elif en.lower() == es.lower():
                    ex_untrans += 1
            if n > 0 and e_empty == n:
                cards_all_empty.append((artist, word, n))

    # ---- report ----
    print("=" * 64)
    print("VISIBLE cards (front-end default filters): %d unique" % len(visible_ids))
    print("  per-artist (overlaps counted separately): %s" % dict(per_artist))
    print("=" * 64)
    for cat in ["blank_rows", "verbose_def", "cognate_leak", "menu_bloat"]:
        items = defect[cat]
        print("\n### %s : %d cards" % (cat, len(items)))
        for it in items[:20]:
            print("   ", it)
        if len(items) > 20:
            print("    ... (%d more)" % (len(items) - 20))

    print("\n" + "=" * 64)
    print("EXAMPLES on visible cards: %d total" % ex_total)
    print("  empty english        : %d (%.1f%%)" % (
        ex_empty, 100.0 * ex_empty / ex_total if ex_total else 0))
    print("  english == spanish   : %d (%.1f%%)" % (
        ex_untrans, 100.0 * ex_untrans / ex_total if ex_total else 0))
    print("  cards w/ ALL examples empty-english: %d" % len(cards_all_empty))
    for it in sorted(cards_all_empty, key=lambda x: -x[2])[:15]:
        print("   ", it)


if __name__ == "__main__":
    main()
