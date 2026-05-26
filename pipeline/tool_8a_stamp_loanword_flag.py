#!/usr/bin/env python3
"""Stamp `is_english_loanword` flag on vocabulary entries.

End-of-pipeline post-processor: reads `vocabulary.json` and the
`english_loanwords.json` layer (built by tool_4a_build_english_loanwords.py)
and adds an `is_english_loanword: true` field on entries whose surface
appears in the loanword set. Idempotent — re-running with the same inputs
produces the same output.

Does NOT trigger any pipeline reruns. Pure data tagging, safe to undo.

Usage:
    .venv/bin/python3 pipeline/tool_8a_stamp_loanword_flag.py --dry-run
    .venv/bin/python3 pipeline/tool_8a_stamp_loanword_flag.py --language Spanish
    .venv/bin/python3 pipeline/tool_8a_stamp_loanword_flag.py \\
        --vocab-path Artists/spanish/Bad\\ Bunny/BadBunnyvocabulary.json
"""

import argparse
import json
import os
import sys


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)

_LANG_TO_ARTIST_DIR = {
    "Spanish": "spanish",
    "French": "french",
}


def _load_loanwords(language):
    path = os.path.join(_PROJECT_ROOT, "Data", language, "layers",
                        "english_loanwords.json")
    if not os.path.isfile(path):
        print(f"ERROR: loanword layer not found at {path}")
        print("  Run pipeline/tool_4a_build_english_loanwords.py first.")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return set(data.keys()), path


def _stamp_vocab(vocab_path, loanwords, keep_set, dry_run):
    """Stamp/unstamp is_english_loanword on a vocabulary.json list.

    Returns (newly_flagged, already_flagged, unflagged_due_to_keep).
    """
    if not os.path.isfile(vocab_path):
        print(f"  skip: {vocab_path} not found")
        return [], [], []
    with open(vocab_path, "r", encoding="utf-8") as f:
        vocab = json.load(f)
    if not isinstance(vocab, list):
        print(f"  skip: {vocab_path} is not a list ({type(vocab).__name__})")
        return [], [], []

    newly_flagged = []
    already_flagged = []
    kept = []  # in loanword set but allow-listed via keep_set
    for entry in vocab:
        word = (entry.get("word") or "").lower()
        is_loan = word in loanwords and word not in keep_set
        was_flagged = bool(entry.get("is_english_loanword"))
        if is_loan and not was_flagged:
            newly_flagged.append(entry)
            if not dry_run:
                entry["is_english_loanword"] = True
        elif is_loan and was_flagged:
            already_flagged.append(entry)
        elif not is_loan and was_flagged:
            kept.append(entry)
            if not dry_run:
                entry.pop("is_english_loanword", None)

    if not dry_run:
        with open(vocab_path, "w", encoding="utf-8") as f:
            json.dump(vocab, f, ensure_ascii=False)

    return newly_flagged, already_flagged, kept


def _load_keep_set(keep_path):
    if not keep_path or not os.path.isfile(keep_path):
        return set()
    with open(keep_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Sectioned shape {drop, keep} OR flat list. Accept both.
    if isinstance(data, dict):
        words = data.get("keep") or []
    elif isinstance(data, list):
        words = data
    else:
        words = []
    return {w.lower() for w in words if isinstance(w, str)}


def _format_sample(entries, limit=40):
    """Return a sample of entries as (word, lemma, corpus_count) tuples."""
    sample = sorted(entries, key=lambda e: -(e.get("corpus_count") or 0))[:limit]
    return [(e.get("word"), e.get("lemma"),
             e.get("corpus_count"),
             [m.get("translation") for m in (e.get("meanings") or [])][:2])
            for e in sample]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--language", default="Spanish",
                        help="Language whose layer file to load")
    parser.add_argument("--vocab-path", action="append", default=None,
                        help="Specific vocabulary.json to stamp (repeatable). "
                             "If omitted, stamps Data/<lang>/vocabulary.json "
                             "AND every Artists/<lang>/<Name>/*vocabulary.json")
    parser.add_argument("--keep-path",
                        help="Path to a keep-list JSON file (flat list OR "
                             "{keep:[...]}) — words to NOT flag even when "
                             "they're in english_loanwords.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    parser.add_argument("--sample-limit", type=int, default=40,
                        help="How many sample entries to print")
    args = parser.parse_args()

    loanwords, layer_path = _load_loanwords(args.language)
    print(f"Loaded {len(loanwords)} loanwords from {layer_path}")

    keep_set = _load_keep_set(args.keep_path)
    if keep_set:
        print(f"Loaded {len(keep_set)} keep-list entries from {args.keep_path}")

    if args.vocab_path:
        targets = args.vocab_path
    else:
        # Default: normal mode + every artist for this language
        targets = []
        normal = os.path.join(_PROJECT_ROOT, "Data", args.language,
                              "vocabulary.json")
        if os.path.isfile(normal):
            targets.append(normal)
        artist_dir = _LANG_TO_ARTIST_DIR.get(args.language, args.language.lower())
        artists_root = os.path.join(_PROJECT_ROOT, "Artists", artist_dir)
        if os.path.isdir(artists_root):
            for name in sorted(os.listdir(artists_root)):
                sub = os.path.join(artists_root, name)
                if not os.path.isdir(sub):
                    continue
                for fn in os.listdir(sub):
                    if fn.endswith("vocabulary.json") and not fn.endswith(
                            (".examples.json", ".index.json", ".meta.json")):
                        targets.append(os.path.join(sub, fn))

    print(f"\nProcessing {len(targets)} vocabulary file(s)" +
          (" [dry-run]" if args.dry_run else ""))

    grand_new = []
    for vocab_path in targets:
        new, already, kept = _stamp_vocab(vocab_path, loanwords, keep_set,
                                          args.dry_run)
        rel = os.path.relpath(vocab_path, _PROJECT_ROOT)
        print(f"  {rel}: +{len(new)} new, ={len(already)} already, "
              f"-{len(kept)} unflagged (keep-list)")
        grand_new.extend(new)

    if grand_new:
        print(f"\nSample of {min(len(grand_new), args.sample_limit)} entries "
              f"that would be newly flagged (sorted by corpus_count desc):")
        for word, lemma, cc, trs in _format_sample(grand_new, args.sample_limit):
            trs_str = " / ".join(t for t in trs if t) or "(no translation)"
            print(f"  {word!r:20s} → {lemma!r:18s} count={cc!r:6}  {trs_str}")

    if args.dry_run:
        print("\nDRY RUN — no files modified. Re-run without --dry-run to apply.")


if __name__ == "__main__":
    main()
