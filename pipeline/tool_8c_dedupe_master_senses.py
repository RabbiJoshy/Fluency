#!/usr/bin/env python3
"""Collapse exact duplicate senses in the shared master vocabulary.

Master senses accumulate and are never removed, so a card re-analysed across
runs can end up holding the same sense twice — `manín` carried sense id 830
("peanut") as two identical rows.

Scope is deliberately narrow: only rows that are duplicates by `sense_id`, or by
(pos, translation, context) when neither carries an id. Identity is preserved by
merging aliases onto the survivor, so knowledge IDs keyed on a sense id keep
resolving.

What this does NOT do — and must not — is prune "stale" senses. The obvious
heuristic (drop senses no current assignment claims) is actively wrong: on
`manín` the correct gloss "bro, buddy (slang)" is unclaimed because it is a
generated artist-master id, while the wrong "peanut" IS claimed. Pruning on that
signal deletes the right sense and keeps the wrong one. Retiring a semantically
stale sense needs judgment, so it belongs in proposals.json.

    python3 pipeline/tool_8c_dedupe_master_senses.py            # dry run
    python3 pipeline/tool_8c_dedupe_master_senses.py --apply
"""

import argparse
import json
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = os.path.join(_PROJECT_ROOT, "Artists", "spanish", "vocabulary_master.json")


def sense_key(s):
    sid = s.get("sense_id")
    if sid:
        return ("id", str(sid))
    return ("txt", s.get("pos"), (s.get("translation") or "").strip().lower(),
            (s.get("context") or "").strip().lower())


def dedupe(entry):
    """Return (senses, removed). Survivor is the first occurrence; later rows
    donate any aliases and any field the survivor is missing."""
    out, seen = [], {}
    removed = 0
    for s in entry.get("senses") or []:
        k = sense_key(s)
        if k not in seen:
            seen[k] = s
            out.append(s)
            continue
        keeper = seen[k]
        aliases = set(keeper.get("sense_id_aliases") or []) | set(s.get("sense_id_aliases") or [])
        for field, value in s.items():
            if field != "sense_id_aliases" and value and not keeper.get(field):
                keeper[field] = value
        if aliases:
            keeper["sense_id_aliases"] = sorted(aliases)
        removed += 1
    return out, removed


def main():
    parser = argparse.ArgumentParser(description="Collapse duplicate master senses")
    parser.add_argument("--apply", action="store_true", help="Write (default: dry run)")
    parser.add_argument("--master-path", default=MASTER)
    args = parser.parse_args()

    with open(args.master_path, "r", encoding="utf-8") as f:
        master = json.load(f)

    touched = total = 0
    samples = []
    for key, entry in master.items():
        senses, removed = dedupe(entry)
        if not removed:
            continue
        touched += 1
        total += removed
        if len(samples) < 10:
            samples.append((entry.get("word"), removed, len(entry.get("senses") or []), len(senses)))
        entry["senses"] = senses

    print("entries with duplicates: %d | duplicate rows removed: %d" % (touched, total))
    for word, removed, before, after in samples:
        print("   %-16s %d -> %d (-%d)" % (word, before, after, removed))

    if not args.apply:
        print("\ndry run — re-run with --apply to write")
        return
    with open(args.master_path, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False)
    print("\nwritten: %s" % os.path.relpath(args.master_path, _PROJECT_ROOT))


if __name__ == "__main__":
    main()
