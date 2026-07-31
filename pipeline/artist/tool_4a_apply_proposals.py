#!/usr/bin/env python3
"""Apply accepted proposals from the ledger into the real curation files.

`Artists/curations/proposals.json` is where any source — a detector, Gemini, an
audit flag, an assistant reading the data — records a suggested correction. This
tool is the only thing that turns an accepted suggestion into pipeline input.

    open      nothing happens
    accepted  copied into the curation file for its kind
    rejected  never applied; the entry stays as a permanent veto

Routing by kind:

    lemma               -> lemma_overrides.json      {overrides, keep}
    proper_noun         -> proper_nouns.json         {drop, keep}
    english             -> extra_english.json        {entries, sources}
    cognate             -> cognates.json             {drop, keep}
    noise               -> noise.json                {drop, keep}
    elision             -> elision_mapping.json      elided_only entry
    echo_reduplication  -> noise.json, but ONLY when every occurrence of the
                           string is an echo

That last restriction is the point of the `proposed` field. Echo is a property
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

# kind -> (filename, section holding accepted values, veto section)
KIND_TARGETS = {
    "lemma": ("lemma_overrides.json", "overrides", "keep"),
    "proper_noun": ("proper_nouns.json", "drop", "keep"),
    "english": ("extra_english.json", "entries", None),
    "cognate": ("cognates.json", "drop", "keep"),
    "noise": ("noise.json", "drop", "keep"),
    "echo_reduplication": ("noise.json", "drop", "keep"),
    "elision": ("elision_mapping.json", None, None),
    # A wrong gloss is not a routing decision — no bucket fixes a translation.
    # Glosses live in the shared curated-translation layer, keyed word|lemma,
    # which both builders consult when assembling a card.
    "gloss": (os.path.join(_PROJECT_ROOT, "shared", "curated_translations.json"), "_curated", None),
}


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


def blocked_reason(proposal, doc, veto_section):
    """Why this accepted proposal must not be applied, or None."""
    word = (proposal.get("word") or "").strip().lower()
    if not word:
        return "no word"
    if proposal.get("proposed") == "drop_occurrences":
        return ("only %s of %s occurrences are echoes — needs per-occurrence "
                "handling, not a corpus-wide drop"
                % (proposal.get("echo_occurrences"), proposal.get("total_occurrences")))
    if veto_section and word in {w.lower() for w in doc.get(veto_section, [])}:
        return "in '%s' — human override wins" % veto_section
    return None


def apply_proposal(proposal, doc, section):
    """Write one accepted proposal into the loaded curation doc. True if changed."""
    word = proposal["word"].strip().lower()
    if section == "_curated":
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
    if section is None:  # elision_mapping.json is a list of merge records
        if any(r.get("elided_word") == word for r in doc):
            return False
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
    if isinstance(doc.get(section), dict):  # lemma_overrides
        if doc[section].get(word) == proposal["proposed"]:
            return False
        doc[section][word] = proposal["proposed"]
        return True
    listed = doc.setdefault(section, [])
    if word in {w.lower() for w in listed}:
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
        if kind not in KIND_TARGETS:
            print("   ? unknown kind %r for %s" % (kind, proposal.get("word")))
            continue
        filename, section, veto = KIND_TARGETS[kind]
        if filename not in touched:
            touched[filename] = load_curation(filename)
        path, doc = touched[filename]
        reason = blocked_reason(proposal, doc if isinstance(doc, dict) else {}, veto)
        if reason:
            print("   ! %-12s blocked: %s" % (proposal.get("word"), reason))
            blocked_n += 1
            continue
        if apply_proposal(proposal, doc, section):
            print("   + %-12s -> %s [%s]"
                  % (proposal["word"], os.path.basename(filename), section or "elided_only"))
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
