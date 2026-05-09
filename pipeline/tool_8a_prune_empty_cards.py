#!/usr/bin/env python3
"""Drop vocabulary entries whose every sense has zero examples.

Such entries are typically phantom cards produced when a sense menu lists an
analysis (e.g. SpanishDict's `beber` headword for surface `bebé`) that the
classifier never actually picked. They show up as blank cards on the
front-end. Run after step_8a (normal mode) and/or tool_8c_merge_to_master
(artist mode) to clean up.

Usage:
    .venv/bin/python3 pipeline/tool_8a_prune_empty_cards.py --language Spanish
    .venv/bin/python3 pipeline/tool_8a_prune_empty_cards.py --vocab-path PATH
                                                            [--master-path PATH]
                                                            [--dry-run]

By default, prunes:
    Data/<Language>/vocabulary.json   (and its sibling .index.json + .examples.json)
    Artists/<language>/vocabulary_master.json
"""

import argparse
import json
import os
import sys


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)


def _meanings_all_empty(entry):
    meanings = entry.get("meanings") or []
    if not meanings:
        return True
    return all(not (m.get("examples") or []) for m in meanings)


def _prune_vocab_list(vocab):
    """Filter a list-shaped vocabulary.json. Returns (kept, dropped).

    Rule (conservative): drop an entry if all its meanings have zero examples
    AND there is at least one *other* entry for the same surface word that
    does have examples. This targets phantom-duplicate cards (e.g. a
    `bebé|beber` card sitting next to a real `bebé|bebé`) without removing
    legitimate cards that simply weren't classified yet (e.g. low-frequency
    nouns where Gemini was skipped).
    """
    by_word = {}
    for e in vocab:
        by_word.setdefault(e.get("word"), []).append(e)

    has_examples = {
        word: any(not _meanings_all_empty(e) for e in entries)
        for word, entries in by_word.items()
    }

    kept, dropped = [], []
    for e in vocab:
        if _meanings_all_empty(e) and has_examples.get(e.get("word"), False):
            dropped.append(e)
        else:
            kept.append(e)
    return kept, dropped


def _rewrite_index_examples(vocab_path, kept_ids):
    """If sibling .index.json / .examples.json exist, drop entries whose IDs
    aren't in `kept_ids`. Keeps the front-end split files in sync."""
    base = vocab_path.rsplit(".", 1)[0]
    index_path = base + ".index.json"
    examples_path = base + ".examples.json"
    touched = []

    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
        new_index = [e for e in index if e.get("id") in kept_ids]
        if len(new_index) != len(index):
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(new_index, f, ensure_ascii=False)
            touched.append((index_path, len(index) - len(new_index)))

    if os.path.isfile(examples_path):
        with open(examples_path, "r", encoding="utf-8") as f:
            examples = json.load(f)
        before = len(examples)
        examples = {k: v for k, v in examples.items() if k in kept_ids}
        if len(examples) != before:
            with open(examples_path, "w", encoding="utf-8") as f:
                json.dump(examples, f, ensure_ascii=False)
            touched.append((examples_path, before - len(examples)))

    return touched


def prune_vocab_file(vocab_path, dry_run=False):
    if not os.path.isfile(vocab_path):
        print(f"  skip: {vocab_path} not found")
        return
    with open(vocab_path, "r", encoding="utf-8") as f:
        vocab = json.load(f)
    if not isinstance(vocab, list):
        print(f"  skip: {vocab_path} is not a list (shape: {type(vocab).__name__})")
        return

    kept, dropped = _prune_vocab_list(vocab)
    print(f"  {vocab_path}: {len(vocab)} → {len(kept)} entries (dropped {len(dropped)})")
    if dropped:
        print(f"    sample dropped: " + ", ".join(
            f"{d['word']}|{d['lemma']}" for d in dropped[:8]
        ))

    if dry_run or not dropped:
        return

    with open(vocab_path, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False)
    kept_ids = {e["id"] for e in kept if "id" in e}
    touched = _rewrite_index_examples(vocab_path, kept_ids)
    for path, delta in touched:
        print(f"    sync: {path} (-{delta})")


def prune_master_file(master_path, dry_run=False):
    """Master pruning is a no-op: tool_8c_merge_to_master rebuilds the master
    from scratch each run, so stale (word, lemma) pairs disappear automatically
    once the per-artist monoliths are regenerated. Kept as a hook in case we
    ever need to add narrower master-only cleanup."""
    if not os.path.isfile(master_path):
        print(f"  skip: {master_path} not found")
        return
    print(f"  {master_path}: skipped — master is rebuilt fresh by tool_8c_merge_to_master")


_LANG_TO_ARTIST_DIR = {
    "Spanish": "spanish",
    "French": "french",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--language", default="Spanish",
                        help="Front-end language directory (Data/<Language>/...)")
    parser.add_argument("--vocab-path",
                        help="Override vocabulary.json path (default: Data/<Language>/vocabulary.json)")
    parser.add_argument("--master-path",
                        help="Override master path (default: Artists/<lang>/vocabulary_master.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be dropped without writing")
    args = parser.parse_args()

    vocab_path = args.vocab_path or os.path.join(
        _PROJECT_ROOT, "Data", args.language, "vocabulary.json")
    artist_subdir = _LANG_TO_ARTIST_DIR.get(args.language, args.language.lower())
    master_path = args.master_path or os.path.join(
        _PROJECT_ROOT, "Artists", artist_subdir, "vocabulary_master.json")

    print("Pruning empty-meaning vocabulary entries..." + (" [dry-run]" if args.dry_run else ""))
    prune_vocab_file(vocab_path, dry_run=args.dry_run)
    prune_master_file(master_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
