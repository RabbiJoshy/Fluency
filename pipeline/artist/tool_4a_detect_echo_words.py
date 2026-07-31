#!/usr/bin/env python3
"""Detect echo-reduplication artefacts and propose them as noise.

Rap and reggaeton lyrics repeat the tail of a word as an ad-lib — a partial
(echo) reduplication:

    "Vamo' a guayar la noche entera-tera"        -> tera
    "sale' pa' la disco a perrear, -rrear"       -> rrear
    "Y tú quieres mover, -over"                  -> over
    "Humo y alcohol-cohol"                       -> cohol

The echo is not a word. With no dictionary menu it lands in
``word_routing.sense_discovery``, Gemini is asked to invent a meaning, and the
learner gets a card for a syllable. `tera` was glossed "ter (ADJ, legal)".

Detection is precise because the source word is almost always sitting directly
beside the echo. Requiring adjacency — source, then an optional hyphen/comma,
then the echo — takes the Bad Bunny corpus from 15 matches with 4 false
positives (acho/cacho, all/mall, urba/masturba, all coincidental tail matches
elsewhere in the line) to 10 matches with none.

Both guards matter:
  * the echo must NOT itself be a known Spanish form — `sol` in "sol-sol" is a
    real word and must keep its card;
  * the source MUST be a known Spanish form, so one ad-lib cannot certify
    another.

Writes proposals to Artists/curations/proposals.json with status=open. It never
edits a curation file directly — a human accepts or rejects first, and a
rejected entry is a permanent veto.

Usage:
  python3 pipeline/artist/tool_4a_detect_echo_words.py --artist-dir "Artists/spanish/Bad Bunny"
  python3 pipeline/artist/tool_4a_detect_echo_words.py --artist-dir "Artists/spanish/Bad Bunny" --write
"""

import argparse
import json
import os
import re
import sys
from datetime import date

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))

PROPOSALS_PATH = os.path.join(_PROJECT_ROOT, "Artists", "curations", "proposals.json")
SPANISH_FORMS = os.path.join(_PROJECT_ROOT, "Data", "Spanish", "layers", "spanish_forms.json")

MIN_ECHO_LEN = 3


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def echo_occurrences(word, examples):
    """Split a word's examples into echo and non-echo occurrences.

    Returns (source_word, echo_example_ids, echo_line, total). Echo is a
    property of an OCCURRENCE, not of a string: `over` is an echo in
    "mover, -over" but an ordinary word in "game over" and the artist name
    "Lary Over". Only 1 of its 7 Bad Bunny lines is an echo, so tagging the
    string as noise would destroy six legitimate occurrences.
    """
    pattern = re.compile(
        r"([\wáéíóúüñ]{4,})\s*[-,]\s*-?\s*%s\b" % re.escape(word),
        re.IGNORECASE | re.UNICODE,
    )
    source = None
    echo_ids = []
    echo_line = None
    examples = examples or []
    for example in examples:
        line = example.get("line") or ""
        for match in pattern.finditer(line):
            candidate = match.group(1).lower()
            if len(candidate) > len(word) and candidate.endswith(word.lower()):
                source = source or candidate
                echo_ids.append(example.get("id"))
                echo_line = echo_line or line
                break
    return source, echo_ids, echo_line, len(examples)


def main():
    parser = argparse.ArgumentParser(description="Propose echo-reduplication ad-libs as noise")
    parser.add_argument("--artist-dir", required=True)
    parser.add_argument("--write", action="store_true",
                        help="Append proposals to proposals.json (default: preview)")
    args = parser.parse_args()

    evidence_path = os.path.join(args.artist_dir, "data", "elision_merge",
                                 "vocab_evidence_merged.json")
    if not os.path.isfile(evidence_path):
        sys.exit("No merged evidence at %s — run step_3a_merge_elisions first." % evidence_path)

    evidence = {e["word"]: e for e in load_json(evidence_path)}
    spanish_forms = set(load_json(SPANISH_FORMS))
    artist = os.path.basename(os.path.normpath(args.artist_dir))

    found = []
    for word, entry in evidence.items():
        # A real Spanish word keeps its card even when it is also echoed.
        if word in spanish_forms or len(word) < MIN_ECHO_LEN:
            continue
        source, echo_ids, line, total = echo_occurrences(word, entry.get("examples"))
        # The source must be real Spanish; one ad-lib cannot certify another.
        if not source or source not in spanish_forms:
            continue
        # A word every one of whose lines is an echo can be dropped outright.
        # A word with surviving real lines must only lose those occurrences,
        # or the card loses genuine evidence.
        pure = len(echo_ids) == total
        found.append({
            "id": "echo_reduplication:%s" % word,
            "kind": "echo_reduplication",
            "word": word,
            "current": None,
            "proposed": "noise" if pure else "drop_occurrences",
            "reason": "Echo reduplication of '%s' — the tail of the preceding word "
                      "repeated as an ad-lib, not a word.%s"
                      % (source,
                         "" if pure else
                         " Only %d of %d occurrences are echoes, so the string is "
                         "NOT noise corpus-wide — drop those lines only."
                         % (len(echo_ids), total)),
            "evidence": (line or "").strip(),
            "echo_occurrences": len(echo_ids),
            "total_occurrences": total,
            "echo_example_ids": echo_ids,
            "source": "tool_4a_detect_echo_words",
            "confidence": "high" if pure else "medium",
            "status": "open",
            "created": date.today().isoformat(),
            "artist": artist,
        })

    found.sort(key=lambda p: (p["proposed"], p["word"]))
    pure = [p for p in found if p["proposed"] == "noise"]
    partial = [p for p in found if p["proposed"] != "noise"]
    print("%d echo-reduplication candidate(s) in %s\n" % (len(found), artist))
    print("  pure ad-libs (every occurrence is an echo) — safe to drop as noise:")
    for p in pure:
        print("     %-10s %d/%d  %s" % (p["word"], p["echo_occurrences"],
                                        p["total_occurrences"], p["evidence"][:50]))
    if partial:
        print("\n  partial — the string is also a real word elsewhere, drop occurrences only:")
        for p in partial:
            print("     %-10s %d/%d  %s" % (p["word"], p["echo_occurrences"],
                                            p["total_occurrences"], p["evidence"][:50]))

    if not args.write:
        print("\nPreview only — re-run with --write to append to proposals.json")
        return

    ledger = load_json(PROPOSALS_PATH)
    by_id = {p["id"]: p for p in ledger["proposals"]}
    new, refreshed = [], 0
    for proposal in found:
        existing = by_id.get(proposal["id"])
        if existing is None:
            new.append(proposal)
            continue
        # Never overwrite a human decision; refresh the measured fields only.
        if existing.get("status") != "open":
            continue
        before = dict(existing)
        existing.update({k: v for k, v in proposal.items() if k != "status"})
        if existing != before:
            refreshed += 1
    if not new and not refreshed:
        print("\nNothing new — all candidates are already in the ledger.")
        return
    ledger["proposals"].extend(new)
    with open(PROPOSALS_PATH, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("\n%d new, %d refreshed in %s (status=open; decided entries untouched)"
          % (len(new), refreshed, os.path.relpath(PROPOSALS_PATH, _PROJECT_ROOT)))


if __name__ == "__main__":
    main()
