#!/usr/bin/env python3
"""Turn audit flags from the FlaggedWords sheet into step_4a routing curations.

Closes the loop that was previously open: the app's flag menu can request a
classification ("this is English", "this is a proper noun", "this is a
cognate"), that request lands in the sheet as a `routing` target with a
`requestedTag` — and nothing consumed it. Words stayed misrouted until someone
re-read the audit by hand.

Reads the pulled sheet (`backend/sync_sheets.py` writes it) and proposes
additions to the sectioned curation files step_4a already honours:

    requestedTag=english     -> Artists/curations/extra_english.json  (entries)
    requestedTag=proper_noun -> Artists/curations/proper_nouns.json   (drop)
    requestedTag=cognate     -> Artists/curations/cognates.json       (drop)

Dry-run by default; `--apply` writes. A word already listed in the target
section is skipped, and a word sitting in that file's `keep` section is
reported as a conflict and never auto-dropped — `keep` is the human's explicit
override and this tool must not silently reverse it.

Usage:
  python3 backend/sync_sheets.py --sheet FlaggedWords     # refresh local flags
  python3 pipeline/artist/tool_4a_apply_flag_routing.py
  python3 pipeline/artist/tool_4a_apply_flag_routing.py --apply
"""

import argparse
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))

FLAGS_PATH = os.path.join(_PROJECT_ROOT, "backend", "local", "FlaggedWords.json")
CURATIONS_DIR = os.path.join(_PROJECT_ROOT, "Artists", "curations")

# requestedTag -> (curation file, section holding the words, section that vetoes)
TAG_TARGETS = {
    "english": ("extra_english.json", "entries", None),
    "proper_noun": ("proper_nouns.json", "drop", "keep"),
    "cognate": ("cognates.json", "drop", "keep"),
}


def load_flags(path):
    if not os.path.isfile(path):
        sys.exit(
            "No local flags at %s\n"
            "Pull them first:  python3 backend/sync_sheets.py --sheet FlaggedWords" % path
        )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("rows", [])


def routing_requests(rows):
    """Collect {tag: {word: flag_row}} for rows asking for a classification."""
    out = {}
    for row in rows:
        tag = (row.get("requestedTag") or "").strip()
        word = (row.get("word") or "").strip().lower()
        if not tag or not word or tag not in TAG_TARGETS:
            continue
        # A later flag for the same word supersedes an earlier one.
        out.setdefault(tag, {})[word] = row
    return out


def load_curation(filename):
    path = os.path.join(CURATIONS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return path, json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Apply audit-flag classification requests to step_4a curations")
    parser.add_argument("--apply", action="store_true",
                        help="Write the curation files (default: dry run)")
    parser.add_argument("--flags", default=FLAGS_PATH,
                        help="Path to the pulled FlaggedWords.json")
    parser.add_argument("--source", default="audit-flag",
                        help="Provenance label recorded for extra_english entries")
    args = parser.parse_args()

    rows = load_flags(args.flags)
    requests = routing_requests(rows)
    if not requests:
        print("No routing-tag flags found in %s" % args.flags)
        print("(flags carry requestedTag only when raised via the Classification tag action)")
        return

    total_new = 0
    total_conflict = 0
    for tag, words in sorted(requests.items()):
        filename, section, veto_section = TAG_TARGETS[tag]
        path, doc = load_curation(filename)
        listed = {w.lower() for w in doc.get(section, [])}
        vetoed = {w.lower() for w in doc.get(veto_section, [])} if veto_section else set()

        new, already, conflicts = [], [], []
        for word in sorted(words):
            if word in vetoed:
                conflicts.append(word)
            elif word in listed:
                already.append(word)
            else:
                new.append(word)

        print("\n%s -> %s [%s]" % (tag, filename, section))
        print("  %d flagged, %d new, %d already listed, %d conflict"
              % (len(words), len(new), len(already), len(conflicts)))
        for word in new:
            print("    + %s" % word)
        for word in conflicts:
            print("    ! %s is in '%s' — human override, not touching it"
                  % (word, veto_section))
        total_new += len(new)
        total_conflict += len(conflicts)

        if new and args.apply:
            doc.setdefault(section, []).extend(new)
            doc[section] = sorted(set(doc[section]))
            # extra_english records provenance per word alongside the list.
            if "sources" in doc:
                for word in new:
                    doc["sources"][word] = args.source
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print("  written")

    print("\n%d new curation entr%s%s%s"
          % (total_new, "y" if total_new == 1 else "ies",
             ", %d conflict(s) skipped" % total_conflict if total_conflict else "",
             "" if args.apply else " — dry run, re-run with --apply to write"))
    if total_new and args.apply:
        print("Re-run step_4a_filter_known_vocab (word routing) for the change to take effect.")


if __name__ == "__main__":
    main()
