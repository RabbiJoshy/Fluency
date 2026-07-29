#!/usr/bin/env python3
"""tool_8b_patch_provenance_into_index.py — Add sense provenance to a LIVE index
in place, without a full deck rebuild.

WHY
---
A full `step_8b` rebuild would carry provenance, but it also regenerates the
whole deck and shifts ~0.4% of card IDs — a small but real progress hit. This
tool instead splices the per-sense provenance arrays (`sense_prompt_ids`,
`sense_run_ts`) onto the EXISTING committed `*.index.json`, keyed by master
sense_id, changing nothing else. Card IDs, examples, frequencies, and every
other field are untouched, so saved progress is fully preserved.

Provenance per sense = the most trustworthy claim on it (highest registry
capability_tier, then latest run_ts), read from the backfilled
`sense_assignments_lemma/*.json` (run tool_6a_backfill_provenance.py first).

USAGE
-----
    .venv/bin/python3 pipeline/tool_8b_patch_provenance_into_index.py \\
        --artist-dir "Artists/spanish/Bad Bunny" [--dry-run]

Patches every ``*vocabulary.index.json`` under the artist dir (skipping
``_``-suffixed sandbox variants). Idempotent — re-running recomputes cleanly.
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from util_6a_prompt_registry import load_registry, capability_tier  # noqa: E402
from util_6a_assignment_format import load_assignments  # noqa: E402


def resolve_sense_provenance(raw_assignments, registry):
    """{sense_id: {prompt_id, run_ts}} — highest-tier claim per sense, tie by run_ts."""
    best = {}
    if not isinstance(raw_assignments, dict):
        return {}
    for _method, items in raw_assignments.items():
        for item in items or []:
            if not isinstance(item, dict):
                continue
            sid = item.get("sense")
            prompt_id = item.get("prompt_id")
            if not sid or not prompt_id:
                continue
            rank = (capability_tier(prompt_id, registry), item.get("run_ts") or "")
            cur = best.get(sid)
            if cur is None or rank > cur[0]:
                best[sid] = (rank, prompt_id, item.get("run_ts"))
    return {sid: {"prompt_id": pid, "run_ts": rts} for sid, (_r, pid, rts) in best.items()}


def default_master_path(artist_dir):
    return os.path.join(os.path.dirname(os.path.normpath(artist_dir)), "vocabulary_master.json")


def lemma_assignments_path(artist_dir, source):
    return os.path.join(artist_dir, "data", "layers",
                        "sense_assignments_lemma", "%s.json" % source)


def build_word_provenance(lemma_assignments, registry):
    """Group lemma-keyed provenance by surface word (union across word|lemma keys)."""
    by_word = {}
    for wl, methods in lemma_assignments.items():
        word = wl.split("|", 1)[0]
        prov = resolve_sense_provenance(methods, registry)
        if prov:
            by_word.setdefault(word, {}).update(prov)
    return by_word


def patch_index(index_path, master, by_word, dry_run=False):
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)
    stamped_senses = touched_cards = 0
    for entry in index:
        m = master.get(entry.get("id"))
        if not m:
            continue
        word = (m.get("word") or "").strip()
        prov_map = by_word.get(word, {})
        if not prov_map:
            continue
        senses = m.get("senses", [])
        freqs = entry.get("sense_frequencies") or []
        prompt_ids = []
        run_ts = []
        any_here = False
        for i, sense in enumerate(senses):
            fr = freqs[i] if i < len(freqs) else 0
            prov = prov_map.get(sense.get("sense_id")) if fr and fr > 0 else None
            if prov:
                prompt_ids.append(prov.get("prompt_id"))
                run_ts.append(prov.get("run_ts"))
                any_here = True
                stamped_senses += 1
            else:
                prompt_ids.append(None)
                run_ts.append(None)
        if any_here:
            entry["sense_prompt_ids"] = prompt_ids
            entry["sense_run_ts"] = run_ts
            touched_cards += 1
        else:
            entry.pop("sense_prompt_ids", None)
            entry.pop("sense_run_ts", None)
    if not dry_run:
        with open(index_path, "w", encoding="utf-8") as f:
            # Match write_split_files' serialization exactly (default separators,
            # no indent) so the diff is purely the two added arrays per card.
            json.dump(index, f, ensure_ascii=False)
    return stamped_senses, touched_cards, len(index)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artist-dir", required=True)
    parser.add_argument("--master", default=None)
    parser.add_argument("--sources", default="spanishdict,wiktionary",
                        help="Comma-separated sense sources to read (default: both).")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    master_path = args.master or default_master_path(args.artist_dir)
    master = json.load(open(master_path, encoding="utf-8"))
    registry = load_registry()

    by_word = {}
    for source in [s.strip() for s in args.sources.split(",") if s.strip()]:
        p = lemma_assignments_path(args.artist_dir, source)
        if os.path.isfile(p):
            for word, prov in build_word_provenance(load_assignments(p), registry).items():
                by_word.setdefault(word, {}).update(prov)

    indexes = [p for p in glob.glob(os.path.join(args.artist_dir, "*vocabulary.index.json"))
               if "_" not in os.path.basename(p).replace("vocabulary.index.json", "")]
    if not indexes:
        raise SystemExit("No live *vocabulary.index.json under %s" % args.artist_dir)

    for index_path in indexes:
        senses, cards, total = patch_index(index_path, master, by_word, dry_run=args.dry_run)
        verb = "Would stamp" if args.dry_run else "Stamped"
        print("%s %d senses on %d/%d cards -> %s"
              % (verb, senses, cards, total, os.path.relpath(index_path)))


if __name__ == "__main__":
    main()
