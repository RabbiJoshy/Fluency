#!/usr/bin/env python3
"""Apply accepted proposals from the ledger into the real curation files.

`Artists/curations/proposals.json` is where any source — a detector, Gemini, an
audit flag, an assistant reading the data — records a suggested correction. This
tool is the only thing that turns an accepted suggestion into pipeline input.

    open      nothing happens
    accepted  copied into the curation file for its kind
    rejected  never applied; the entry stays as a permanent veto

Routing is controlled by the structured ``operation`` field, never by prose in
``proposed``. Supported operations are:

    add_drop / add_keep / remove_drop / remove_keep
    add_occurrence_override
    add_override (lemma), set_gloss, merge_elision, replace_elision

That occurrence restriction is the point of the structured operation. Echo is a property
of an OCCURRENCE, not of a string: `over` is an ad-lib in "mover, -over" and an
ordinary word in "game over" and "Lary Over". Its detector records
echo_occurrences/total_occurrences, and a partial word carries
`proposed: drop_occurrences`, which this tool refuses to apply corpus-wide —
dropping the string would destroy the six real lines.

`keep` always wins. A word a human put in a keep section is never auto-dropped,
because keep is the veto that makes model judgment safe to accept at all.

Usage:
  python3 pipeline/artist/tool_4a_apply_proposals.py                 # what would apply
  python3 pipeline/artist/tool_4a_apply_proposals.py --apply
  python3 pipeline/artist/tool_4a_apply_proposals.py --status open   # review queue
"""

import argparse
import json
import os
import sys
from collections import Counter

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
CURATIONS = os.path.join(_PROJECT_ROOT, "Artists", "curations")
PROPOSALS_PATH = os.path.join(CURATIONS, "proposals.json")

LEMMA_OVERRIDES_SEED = {
    "_format": "Sectioned curation file. overrides = {word: lemma} forced onto the "
               "builder. keep = words whose current lemma is correct and must never "
               "be overridden, including by a model proposal.",
    "_intent": "Lemma is card identity — fullId derives from it and progress rows key "
               "off it — so a lemma that moves between runs detaches the learner's "
               "history. Models therefore never set a lemma directly; they propose "
               "into proposals.json and an accepted proposal is written here, where "
               "it is diffable and revertible. keep wins on conflicts.",
    "overrides": {},
    "keep": [],
}

KIND_FILES = {
    "lemma": "lemma_overrides.json",
    "proper_noun": "proper_nouns.json",
    "english": "extra_english.json",
    "cognate": "cognates.json",
    "noise": "noise.json",
    "echo_reduplication": "noise.json",
    "elision": "elision_mapping.json",
    # A wrong gloss is not a routing decision — no bucket fixes a translation.
    "gloss": os.path.join(_PROJECT_ROOT, "shared", "curated_translations.json"),
}

SECTIONED_KINDS = {"proper_noun", "cognate", "noise", "echo_reduplication"}
VALID_OPERATIONS = {
    "add_drop", "add_keep", "remove_drop", "remove_keep",
    "add_occurrence_override", "add_override", "set_gloss", "merge_elision",
    "replace_elision",
}


def proposal_operation(proposal):
    """Return a machine operation without interpreting human-readable prose.

    The narrow fallbacks keep accepted records written before the operation
    field was introduced reproducible. Routing proposals never infer keep/drop
    from strings such as ``keep (real word ...)``.
    """
    operation = proposal.get("operation")
    if operation:
        return operation if operation in VALID_OPERATIONS else None
    kind = proposal.get("kind")
    proposed = proposal.get("proposed")
    if kind == "lemma":
        return "add_override"
    if kind == "gloss":
        return "set_gloss"
    if kind == "elision":
        return "merge_elision"
    if kind == "echo_reduplication" and proposed == "noise":
        return "add_drop"
    if kind == "echo_reduplication" and proposed == "drop_occurrences":
        return "add_occurrence_override"
    return None


def operation_target(proposal, operation):
    """Return ``(filename, section, remove)`` or None for occurrence overlays."""
    kind = proposal.get("kind")
    filename = KIND_FILES.get(kind)
    if not filename:
        return None
    if operation == "add_occurrence_override":
        return None
    if operation == "add_override" and kind == "lemma":
        return filename, "overrides", False
    if operation == "set_gloss" and kind == "gloss":
        return filename, "_curated", False
    if operation in ("merge_elision", "replace_elision") and kind == "elision":
        return filename, None, False
    if operation.startswith(("add_", "remove_")):
        action, section = operation.split("_", 1)
        if kind in SECTIONED_KINDS and section in ("drop", "keep"):
            return filename, section, action == "remove"
        if kind == "english" and section == "drop":
            return filename, "entries", action == "remove"
    return None


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_curation(filename):
    # Absolute paths address shared layers outside Artists/curations.
    path = filename if os.path.isabs(filename) else os.path.join(CURATIONS, filename)
    if not os.path.isfile(path) and os.path.basename(path) == "lemma_overrides.json":
        return path, json.loads(json.dumps(LEMMA_OVERRIDES_SEED))
    return path, load_json(path)


def blocked_reason(proposal, operation, doc):
    """Why this accepted proposal must not be applied, or None."""
    word = (proposal.get("word") or "").strip().lower()
    if not word:
        return "no word"
    if not operation:
        return "missing or unsupported structured operation"
    if operation == "add_occurrence_override":
        occurrence_action = proposal.get("occurrence_action")
        if occurrence_action is None and proposal.get("proposed") == "drop_occurrences":
            occurrence_action = "drop"
        if occurrence_action not in ("drop", "normalize"):
            return "occurrence override needs occurrence_action=drop|normalize"
        if (occurrence_action == "normalize"
                and not (proposal.get("normalization_target") or "").strip()):
            return "normalization occurrence override has no target"
        ids = proposal.get("occurrence_ids") or proposal.get("echo_example_ids") or []
        if not ids:
            return "occurrence override has no stable occurrence/example IDs"
        if occurrence_action == "normalize":
            return ("normalization occurrence override is recorded but has no "
                    "safe pre-routing materializer yet")
        return None
    if operation == "add_drop" and word in {w.lower() for w in doc.get("keep", [])}:
        return "in 'keep' — human override wins"
    return None


def apply_proposal(proposal, doc, operation, section, remove=False):
    """Write one accepted proposal into the loaded curation doc. True if changed."""
    word = proposal["word"].strip().lower()
    if operation == "set_gloss" and section == "_curated":
        # curated_translations.json is a flat map keyed `word|lemma`. mode=all
        # so the override applies whichever sense source built the deck.
        key = "%s|%s" % (word, (proposal.get("lemma") or word).strip().lower())
        if doc.get(key, {}).get("translation") == proposal["proposed"]:
            return False
        doc[key] = {
            "translation": proposal["proposed"],
            "pos": proposal.get("pos") or "X",
            "mode": "all",
            "source": "proposal (%s)" % proposal.get("source", "unknown"),
        }
        return True
    if operation in ("merge_elision", "replace_elision") and section is None:
        existing = next(
            (row for row in doc if row.get("elided_word") == word), None)
        if existing is not None:
            if operation == "merge_elision":
                return False
            target = str(proposal["proposed"]).strip().lower()
            changed = existing.get("target_word") != target
            existing.update({
                "action": "merge",
                "merge_type": "elided_only",
                "target_word": target,
                "display_form": word,
                "target_lemma": proposal.get("target_lemma") or target,
                "note": "accepted proposal (%s)" % proposal.get("source", "unknown"),
            })
            existing.pop("full_word", None)
            return changed
        doc.append({
            "action": "merge",
            "merge_type": "elided_only",
            "elided_word": word,
            "target_word": proposal["proposed"],
            "display_form": word,
            "target_lemma": proposal.get("current") or proposal["proposed"],
            "note": "accepted proposal (%s)" % proposal.get("source", "unknown"),
        })
        return True
    if operation == "add_override" and isinstance(doc.get(section), dict):
        if doc[section].get(word) == proposal["proposed"]:
            return False
        doc[section][word] = proposal["proposed"]
        return True
    listed = doc.setdefault(section, [])
    matching = [value for value in listed if str(value).lower() == word]
    if remove:
        if not matching:
            return False
        doc[section] = [value for value in listed if str(value).lower() != word]
        if section == "entries" and "sources" in doc:
            doc["sources"].pop(word, None)
        return True
    if matching:
        return False
    listed.append(word)
    doc[section] = sorted(set(listed))
    if "sources" in doc:
        doc["sources"][word] = proposal.get("source", "proposal")
    return True


def main():
    parser = argparse.ArgumentParser(description="Apply accepted proposals to curation files")
    parser.add_argument("--apply", action="store_true", help="Write (default: dry run)")
    parser.add_argument("--status", default="accepted",
                        choices=["accepted", "open", "rejected", "all"],
                        help="Which proposals to report on (only 'accepted' can be applied)")
    args = parser.parse_args()

    ledger = load_json(PROPOSALS_PATH)
    proposals = ledger["proposals"]
    counts = Counter(p.get("status") for p in proposals)
    print("ledger: %d proposals — %s"
          % (len(proposals), ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items()))))

    if args.status != "accepted":
        selected = [p for p in proposals
                    if args.status == "all" or p.get("status") == args.status]
        print("\n%s (%d):" % (args.status, len(selected)))
        for p in selected:
            print("   [%-18s] %-12s %s -> %s"
                  % (p["kind"], p["word"], p.get("current"), p.get("proposed")))
            print("        %s" % p["reason"][:110])
        return

    accepted = [p for p in proposals if p.get("status") == "accepted"]
    if not accepted:
        print("\nNothing accepted yet. Review with --status open, then set "
              "\"status\": \"accepted\" on the entries you want applied.")
        return

    touched, applied_n, blocked_n = {}, 0, 0
    for proposal in accepted:
        kind = proposal.get("kind")
        if kind not in KIND_FILES:
            print("   ? unknown kind %r for %s" % (kind, proposal.get("word")))
            continue
        operation = proposal_operation(proposal)
        if not operation:
            print("   ! %-12s blocked: missing or unsupported structured operation"
                  % proposal.get("word"))
            blocked_n += 1
            continue
        if operation == "add_occurrence_override":
            reason = blocked_reason(proposal, operation, {})
            if reason:
                print("   ! %-12s blocked: %s" % (proposal.get("word"), reason))
                blocked_n += 1
            else:
                print("   = %-12s occurrence override remains in accepted ledger"
                      % proposal.get("word"))
            continue
        target = operation_target(proposal, operation)
        if not target:
            print("   ! %-12s blocked: operation %s is invalid for kind %s"
                  % (proposal.get("word"), operation, kind))
            blocked_n += 1
            continue
        filename, section, remove = target
        if filename not in touched:
            touched[filename] = load_curation(filename)
        path, doc = touched[filename]
        reason = blocked_reason(
            proposal, operation, doc if isinstance(doc, dict) else {})
        if reason:
            print("   ! %-12s blocked: %s" % (proposal.get("word"), reason))
            blocked_n += 1
            continue
        if apply_proposal(proposal, doc, operation, section, remove=remove):
            print("   %s %-12s -> %s [%s]"
                  % ("-" if remove else "+", proposal["word"],
                     os.path.basename(filename), section or "elided_only"))
            applied_n += 1
        else:
            print("   = %-12s already present in %s" % (proposal["word"], filename))

    if args.apply:
        for path, doc in touched.values():
            save_json(path, doc)
        print("\napplied %d, blocked %d — curation files written" % (applied_n, blocked_n))
        print("Re-run step_4a_filter_known_vocab (word routing) to pick the changes up.")
    else:
        print("\nwould apply %d, blocked %d — dry run, re-run with --apply"
              % (applied_n, blocked_n))


if __name__ == "__main__":
    main()
