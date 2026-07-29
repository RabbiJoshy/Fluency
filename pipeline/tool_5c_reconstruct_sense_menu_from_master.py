#!/usr/bin/env python3
"""tool_5c_reconstruct_sense_menu_from_master.py — Rebuild a missing sense_menu
from the tracked master vocabulary.

WHY THIS EXISTS
---------------
`data/layers/sense_menu/spanishdict.json` — the analysis layer that maps each
surface form to its lemma/headword (``estaban`` -> ``estar``) and lists that
lemma's candidate senses — is **gitignored** (it's large and normally
regenerable from the SpanishDict cache). A fresh clone therefore doesn't have it,
and the SpanishDict cache is gitignored too. Without this file,
``step_8b_assemble_artist_vocabulary.py`` can't look up lemmas (it reads
``senses.get(word)`` at the grouping step) and falls back to self-keying every
word — so ``estaban`` becomes its own card instead of joining ``estar``. That
regresses verb lemmatization across the whole deck and shifts card IDs, which
breaks saved progress on rebuild.

The tracked ``vocabulary_master.json`` still contains every ``word -> lemma ->
senses`` mapping, so the analysis layer is fully reconstructable **without any
re-scrape or network access**. Verified: a rebuild off the reconstructed menu
restores correct lemmatization and reproduces ~99.6% of the live deck's card IDs.

USAGE
-----
    .venv/bin/python3 pipeline/tool_5c_reconstruct_sense_menu_from_master.py \\
        --artist-dir "Artists/spanish/Bad Bunny"

By default reconstructs the ``spanishdict`` menu, scoped to the artist's
``word_inventory.json`` words, writing
``<artist>/data/layers/sense_menu/spanishdict.json``. Pass ``--dry-run`` to
report without writing.
"""

import argparse
import json
import os
from collections import defaultdict


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def inventory_words(artist_dir):
    """Return the lowercased set of surface words in the artist's inventory.

    Returns None if the inventory is absent (caller then reconstructs for every
    master word rather than scoping — extra words are harmless to step_8b).
    """
    path = os.path.join(artist_dir, "data", "layers", "word_inventory.json")
    if not os.path.isfile(path):
        return None
    data = load_json(path)
    words = set()
    if isinstance(data, list):
        for item in data:
            w = item.get("word") if isinstance(item, dict) else item
            if w:
                words.add(str(w).lower())
    elif isinstance(data, dict):
        words = {str(w).lower() for w in data.keys()}
    return words or None


def reconstruct(master, source, scope_words):
    """Build a {word: [{headword, senses:{sid:{...}}}]} menu from the master.

    Groups master entries by surface word; each entry becomes one analysis with
    ``headword`` = its lemma and the entry's ``source``-matching senses keyed by
    sense_id. Words outside ``scope_words`` (when provided) are skipped.
    """
    menu = defaultdict(list)
    kept_senses = 0
    for _mid, entry in master.items():
        if not isinstance(entry, dict):
            continue
        word = entry.get("word")
        if not word:
            continue
        if scope_words is not None and str(word).lower() not in scope_words:
            continue
        lemma = entry.get("lemma") or word
        senses = {}
        for s in (entry.get("senses") or []):
            if not isinstance(s, dict) or s.get("source") != source:
                continue
            sid = s.get("sense_id")
            if not sid:
                continue
            senses[sid] = {k: s[k] for k in ("pos", "translation", "source", "context")
                           if s.get(k) is not None}
        if senses:
            menu[word].append({"headword": lemma, "senses": senses})
            kept_senses += len(senses)
    return dict(menu), kept_senses


def default_master_path(artist_dir):
    # Shared per-language master lives one directory above the artist dir.
    return os.path.join(os.path.dirname(os.path.normpath(artist_dir)),
                        "vocabulary_master.json")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artist-dir", required=True,
                        help="Artist directory, e.g. 'Artists/spanish/Bad Bunny'.")
    parser.add_argument("--master", default=None,
                        help="Master vocabulary path (default: sibling vocabulary_master.json).")
    parser.add_argument("--source", default="spanishdict",
                        help="Sense source to reconstruct (default: spanishdict).")
    parser.add_argument("--output", default=None,
                        help="Output path (default: <artist>/data/layers/sense_menu/<source>.json).")
    parser.add_argument("--all-master-words", action="store_true",
                        help="Reconstruct for every master word, not just the artist's inventory.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report without writing.")
    args = parser.parse_args()

    master_path = args.master or default_master_path(args.artist_dir)
    if not os.path.isfile(master_path):
        raise SystemExit("Master not found: %s" % master_path)
    master = load_json(master_path)

    scope = None if args.all_master_words else inventory_words(args.artist_dir)
    menu, kept_senses = reconstruct(master, args.source, scope)

    out = args.output or os.path.join(
        args.artist_dir, "data", "layers", "sense_menu", "%s.json" % args.source)

    scope_note = ("all %d master words" % len(master) if scope is None
                  else "%d inventory words" % len(scope))
    print("Reconstructed %s menu: %d words, %d senses (scope: %s)"
          % (args.source, len(menu), kept_senses, scope_note))
    if args.dry_run:
        print("Dry run — would write %s" % out)
        return
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(menu, f, ensure_ascii=False, indent=2)
    print("Wrote %s" % out)


if __name__ == "__main__":
    main()
