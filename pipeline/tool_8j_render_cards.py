#!/usr/bin/env python3
"""tool_8j_render_cards — show what a learner actually sees on a card.

Why this exists
---------------
Every audit of this deck has been run against the deck JSON, and the deck JSON
systematically OVERSTATES defects, because `js/vocab.js` and `js/flashcards.js`
repair a lot at render time. Three separate "findings" in one session were
phantoms:

  claimed from the JSON              what the front end already does      real
  ---------------------------------  -----------------------------------  ----
  93 blank visible cards             vocab.js strips empty-gloss meanings   47
  152 junk POS=X cards               107 hidden by is_english/_noise/_propn  45
  78 duplicated meaning rows         flashcards.js groups them by gloss       0

That is why opening one card has repeatedly beaten benchmarking: the JSON is
not the artifact the learner reads, and until now nothing could show the one
that is. This tool applies the real render chain so a claim about a card can be
checked against the same object the learner sees.

It is deliberately READ-ONLY and rebuilds nothing.

What it mirrors, and where from
-------------------------------
  1. scope split           js/vocab.js  ARTIST_EXTRA_CATEGORIES  (Main vs Extra)
  2. artist flag filters   js/vocab.js  buildFilteredVocab       (english/noise/
                                                                  loanword/propn)
  3. empty-gloss strip     js/vocab.js  meanings.filter(m.translation.trim())
  4. raw-card rule         js/vocab.js  allowsRawArtistCard (corpus_count <= 1)
  5. duplicate grouping    js/flashcards.js GROUP_DUPLICATE_MEANINGS

Drift is the obvious failure mode: this is a second implementation of somebody
else's live code (js/ belongs to Codex), so it can silently fall behind. The
guard is `test_tool_8j_render_parity.py`, which pins the exact predicates above
and FAILS when js/ moves. Treat a failure there as "this tool is now lying",
not as a broken test. Same contract as FEATURE_VERSION refusing a mismatched
calibrator, and check_asset_versions.py failing on disagreement.

Usage:
    tool_8j_render_cards.py --artist-dir "Artists/spanish/SpanishTestPlaylist" --word una
    tool_8j_render_cards.py --artist-dir ... --audit
    tool_8j_render_cards.py --artist-dir ... --scope extra --sample 20
"""
from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# --- mirrored from js/vocab.js -------------------------------------------
# ARTIST_EXTRA_CATEGORIES: a card whose extra_category is in this set is Extra
# and is EXCLUDED from Main; everything else is Main. Absence is not proof of
# core-ness -- the front end says as much -- but it is what the split does.
ARTIST_EXTRA_CATEGORIES = {
    "loanword", "english", "proper_noun", "cognate", "noise", "unresolved"}


def load_deck(artist_dir: Path):
    """Monolith + index, joined on card id.

    The app joins a split index against the master; the monolith carries the
    same meanings, so for auditing what is DISPLAYED the monolith is the
    faithful and much cheaper source. The index supplies scope and counts.
    """
    stem = artist_dir.name.replace(" ", "")
    mono = next(artist_dir.glob("*vocabulary.json"), None)
    idx = next(artist_dir.glob("*vocabulary.index.json"), None)
    if not mono or not idx:
        raise SystemExit(f"no deck found in {artist_dir} (looked for *vocabulary.json)")
    cards = json.loads(mono.read_text(encoding="utf-8"))
    index = {r["id"]: r for r in json.loads(idx.read_text(encoding="utf-8"))}
    return cards, index, stem


def hidden_reason(card, excl):
    """The front end's artist flag filters, in its order.

    is_english is unconditional -- an English borrowing has no Spanish meaning
    to teach. The rest are toggles, defaulted here to how Josh runs the app
    (proper nouns and loanwords excluded, noise excluded, cognates excluded).
    """
    if card.get("duplicate"):
        return "duplicate"
    if card.get("is_english"):
        return "english"
    if "noise" in excl and (card.get("is_noise") or card.get("is_interjection")):
        return "noise"
    if "loanword" in excl and card.get("is_english_loanword"):
        return "loanword"
    if "propn" in excl and (card.get("is_propernoun") or card.get("is_propernoun_corpus")):
        return "proper noun"
    if "cognate" in excl and card.get("is_transparent_cognate"):
        return "cognate"
    return None


def render(card, index_row, excl, scope):
    """Return the rendered card, or (None, why-it-is-not-shown)."""
    cat = str((index_row or {}).get("extra_category") or "").lower()
    is_extra = cat in ARTIST_EXTRA_CATEGORIES
    if (scope == "extra") != is_extra:
        return None, f"not in {scope} scope (extra_category={cat or 'core'})"

    if scope == "main":
        why = hidden_reason(card, excl)
        if why:
            return None, f"filtered: {why}"

    corpus_count = int((index_row or {}).get("corpus_count") or 0)
    # allowsRawArtistCard: Extra keeps everything, and Main keeps a
    # single-occurrence card even with no renderable meaning.
    allows_raw = (scope == "extra") or corpus_count <= 1

    meanings = [m for m in (card.get("meanings") or [])
                if (m.get("translation") or "").strip()]
    if not meanings and not allows_raw:
        return None, "dropped: no meaning survives the empty-gloss strip"

    # GROUP_DUPLICATE_MEANINGS: rows sharing (pos, headword, gloss) collapse to
    # one row. This is why `para` reads as 3 rows and not 5.
    groups, order = {}, []
    for m in meanings:
        key = (m.get("pos"), m.get("headword") or "", (m.get("translation") or "").strip())
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(m)
    return {"word": card.get("word"), "lemma": card.get("lemma"),
            "id": card.get("id"), "extra_category": cat or "core",
            "corpus_count": corpus_count, "raw": not meanings,
            "groups": [(k, groups[k]) for k in order]}, None


def show(r):
    out = [f"### {r['word']}    lemma={r['lemma']}  [{r['extra_category']}]  "
           f"seen {r['corpus_count']}x  id={r['id']}"]
    if r["raw"]:
        out.append("    (no meaning — renders as a bare lyric card)")
    for (pos, hw, gloss), members in r["groups"]:
        extra = f"  <{hw}>" if hw and hw != r["lemma"] else ""
        ctxs = [m.get("context") for m in members if m.get("context")]
        note = f"   ({' / '.join(dict.fromkeys(ctxs))})" if ctxs else ""
        sub = f"   [{len(members)} senses grouped]" if len(members) > 1 else ""
        out.append(f"  - {pos}: {gloss}{extra}{note}{sub}")
        seen = set()
        for m in members:
            for e in (m.get("examples") or [])[:2]:
                s = e.get("spanish")
                if not s or s in seen:
                    continue
                seen.add(s)
                b, c = e.get("band"), e.get("confidence")
                tag = f"[{b} {c}]" if b else "[--]"
                out.append(f"      {tag} {s}")
                if e.get("english"):
                    out.append(f"           {e['english']}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artist-dir", required=True)
    ap.add_argument("--word", nargs="*", help="render these words")
    ap.add_argument("--scope", default="main", choices=["main", "extra"])
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--audit", action="store_true",
                    help="counts of what is actually rendered, not what the JSON holds")
    ap.add_argument("--exclude", default="noise,loanword,propn,cognate",
                    help="toggles the learner has on (default matches Josh's settings)")
    a = ap.parse_args()

    artist_dir = (REPO / a.artist_dir) if not Path(a.artist_dir).is_absolute() else Path(a.artist_dir)
    cards, index, _ = load_deck(artist_dir)
    excl = {t.strip() for t in a.exclude.split(",") if t.strip()}

    if a.word:
        want = {w.lower() for w in a.word}
        for c in cards:
            if str(c.get("word", "")).lower() not in want:
                continue
            reasons = {}
            for scope in ("main", "extra"):
                r, why = render(c, index.get(c["id"]), excl, scope)
                if r:
                    print(show(r) + "\n")
                    break
                reasons[scope] = why
            else:
                # Report why it failed in the scope it BELONGS to. Reporting
                # the last loop iteration blamed "not in extra scope" for a
                # core card whose real problem was an empty gloss -- the one
                # thing this tool exists not to do.
                cat = str((index.get(c["id"]) or {}).get("extra_category") or "").lower()
                home = "extra" if cat in ARTIST_EXTRA_CATEGORIES else "main"
                other = "main" if home == "extra" else "extra"
                print(f"### {c.get('word')} — NOT SHOWN in {home}: {reasons[home]}"
                      f"\n      (and in {other}: {reasons[other]})\n")
        return

    rendered, dropped = [], collections.Counter()
    for c in cards:
        r, why = render(c, index.get(c["id"]), excl, a.scope)
        if r:
            rendered.append(r)
        else:
            dropped[why.split(":")[0].split("(")[0].strip()] += 1

    if a.audit:
        rows = sum(len(r["groups"]) for r in rendered)
        raw = sum(1 for r in rendered if r["raw"])
        noex = sum(1 for r in rendered
                   if not any(m.get("examples") for _k, ms in r["groups"] for m in ms))
        print(f"RENDERED {a.scope.upper()} CARDS: {len(rendered):,}")
        print(f"  meaning rows shown            {rows:,}")
        print(f"  cards with NO meaning at all  {raw:,}   <- these teach nothing")
        print(f"  cards with no example shown   {noex:,}")
        print(f"  cards grouped >1 sense/row    "
              f"{sum(1 for r in rendered if any(len(ms) > 1 for _k, ms in r['groups'])):,}")
        print("\nnot rendered in this scope:")
        for k, v in dropped.most_common():
            print(f"  {v:>5}  {k}")
        if raw:
            print("\ncards that teach nothing:")
            print("  " + ", ".join(r["word"] for r in rendered if r["raw"]))
        return

    pool = rendered
    if a.sample:
        random.seed(a.seed)
        pool = random.sample(rendered, min(a.sample, len(rendered)))
    for r in pool:
        print(show(r) + "\n")


if __name__ == "__main__":
    main()
