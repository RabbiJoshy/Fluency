#!/usr/bin/env python3
"""Build english_loanwords.json from the kaikki-spanish Wiktionary dump.

A word qualifies as an "English loanword" if ALL of its Wiktionary entries
carry a borrowing-template (bor / bor+ / ubor / ubor+ / lbor / lbor+ /
der / der+ / dbor) whose source-language arg is ``en``. The "all entries
must agree" rule prevents words like ``sol`` (whose musical-note sense is
an English loan but whose celestial-body sense is inherited Latin) from
being flagged.

Substring fallbacks like ``'from english' in etymology_text`` are NOT
used — they false-positive on doublet mentions ("maestro … doublet of
máster, borrowed from English").

Output schema: ``{word_lowercase: {"sources": ["en"], "wikt_pos": [...]}}``.
The dict shape leaves room for future per-language voters (cognet, manual
verdict) without breaking consumers.

Usage:
    .venv/bin/python3 pipeline/tool_4a_build_english_loanwords.py
    .venv/bin/python3 pipeline/tool_4a_build_english_loanwords.py --language Spanish
"""

import argparse
import gzip
import json
import os
import sys
from collections import defaultdict


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)

# Wiktionary etymology template names that indicate a borrowing.
# bor   = borrowed
# bor+  = borrowed (with explicit source)
# ubor  = unadapted borrowing
# lbor  = learned borrowing
# der   = derived (sometimes used for loans)
# dbor  = direct borrowing
# Each has a "+" variant that surfaces the source language in display.
_BORROW_TEMPLATES = frozenset({
    "bor", "bor+", "ubor", "ubor+", "lbor", "lbor+",
    "der", "der+", "dbor",
})


def _entry_borrows_from(entry, source_lang):
    """Return True iff `entry`'s etymology says it was borrowed from `source_lang`.

    Template-only check — substring matching on etymology_text causes
    false positives on doublet/cognate mentions.
    """
    for template in entry.get("etymology_templates", []) or []:
        if template.get("name") not in _BORROW_TEMPLATES:
            continue
        args = template.get("args") or {}
        # Wiktionary convention: args['1'] = target language, args['2'] = source.
        if args.get("2") == source_lang:
            return True
    return False


def collect_loanwords(kaikki_path, source_lang="en"):
    """Scan a kaikki JSONL.GZ dump and return {word: {sources, wikt_pos}}.

    A word is a loanword iff every Wiktionary entry for it is a borrowing
    from `source_lang`.
    """
    per_word_loan = defaultdict(list)  # word -> list[bool]
    per_word_pos = defaultdict(set)    # word -> set[pos]

    with gzip.open(kaikki_path, "rt", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            word = (entry.get("word") or "").lower()
            if not word:
                continue
            pos = entry.get("pos")
            if pos:
                per_word_pos[word].add(pos)
            per_word_loan[word].append(_entry_borrows_from(entry, source_lang))

    loanwords = {}
    for word, verdicts in per_word_loan.items():
        if not verdicts:
            continue
        if all(verdicts):
            loanwords[word] = {
                "sources": [source_lang],
                "wikt_pos": sorted(per_word_pos.get(word, set())),
            }
    return loanwords


_LANG_TO_KAIKKI = {
    "Spanish": ("Data", "Spanish", "Senses", "wiktionary", "kaikki-spanish.jsonl.gz"),
    # Future languages: drop their kaikki dumps in matching paths and add
    # entries here.
}

_LANG_TO_OUTPUT = {
    "Spanish": ("Data", "Spanish", "layers", "english_loanwords.json"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--language", default="Spanish",
                        help="Target language whose Wiktionary dump to scan")
    parser.add_argument("--source-lang", default="en",
                        help="Wiktionary code for the loanword source language "
                             "(default 'en' = English)")
    parser.add_argument("--kaikki-path",
                        help="Override path to the kaikki .jsonl.gz dump")
    parser.add_argument("--output-path",
                        help="Override output path")
    args = parser.parse_args()

    if args.kaikki_path:
        kaikki_path = args.kaikki_path
    else:
        rel = _LANG_TO_KAIKKI.get(args.language)
        if not rel:
            print(f"ERROR: no kaikki path configured for language {args.language!r}")
            sys.exit(1)
        kaikki_path = os.path.join(_PROJECT_ROOT, *rel)

    if args.output_path:
        out_path = args.output_path
    else:
        rel = _LANG_TO_OUTPUT.get(args.language)
        if not rel:
            print(f"ERROR: no output path configured for language {args.language!r}")
            sys.exit(1)
        out_path = os.path.join(_PROJECT_ROOT, *rel)

    if not os.path.isfile(kaikki_path):
        print(f"ERROR: kaikki dump not found at {kaikki_path}")
        sys.exit(1)

    print(f"Scanning {kaikki_path}")
    print(f"  source language: {args.source_lang!r}")
    loanwords = collect_loanwords(kaikki_path, source_lang=args.source_lang)
    print(f"  loanwords found: {len(loanwords)}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(loanwords, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"  wrote {out_path}")


if __name__ == "__main__":
    main()
