#!/usr/bin/env python3
"""Turn bench_deck_quality.py's detector sweep into a reusable candidates file.

bench_deck_quality.py prints a defect-class report meant to be read and
triaged by hand. This tool runs the same detectors (imported, not
reimplemented — see bench_deck_quality.py's module-level `detect_*`
functions) and writes one row per flagged card to a JSON file, so the manual
"sweep the bench output, look words up, decide" step becomes a reusable
command for every future artist/deck.

The output is a review sheet: each row carries a `verdict` field (starts
null) for a human/reviewer to fill in later with "stamp" (patch the master,
see tool_8c_patch_master_curated.py), "keep" (false positive, leave as-is),
or "fix" (needs a manual gloss/flag correction).

Read-only against the vocabulary data. Run from the project root:

    .venv/bin/python3 pipeline/tool_8d_flag_deck_quality_candidates.py \\
        --master Artists/spanish/vocabulary_master_wikt.json --suffix _wikt \\
        --output Artists/spanish/Bad\\ Bunny/data/reports/deck_quality_candidates_wikt.json
"""
import argparse
import collections
import json
import os
import time

from bench_deck_quality import (
    ARTISTS, DETECTOR_KNOWN_OK, MASTER, keynorm, norm, real_senses, visible,
    detect_blank_rows, detect_verbose_def, detect_cognate_leak, detect_menu_bloat,
    detect_code_switch_verbatim, detect_propernoun_caps,
)

MASTER_SIDE_DETECTORS = ("blank_rows", "verbose_def", "cognate_leak", "menu_bloat")
EXAMPLE_SIDE_DETECTORS = ("code_switch_verbatim", "propernoun_caps")
ALL_DETECTORS = MASTER_SIDE_DETECTORS + EXAMPLE_SIDE_DETECTORS
DEFAULT_DETECTORS = ["cognate_leak", "code_switch_verbatim", "propernoun_caps"]


def _row(artist, word, lemma, pos, gloss, detector, evidence):
    return {
        "artist": artist,
        "word": word,
        "lemma": lemma,
        "pos": pos,
        "gloss": gloss,
        "detector": detector,
        "evidence": evidence,
        "verdict": None,
    }


def resolve_artists(suffix):
    """Same artist/file resolution as bench_deck_quality.main(): apply the
    suffix to each registered artist's index/examples paths and skip artists
    whose suffixed files don't exist."""
    artists = {}
    for name, (ip, ep) in ARTISTS.items():
        if suffix:
            ip = ip.replace("vocabulary.", "vocabulary%s." % suffix)
            ep = ep.replace("vocabulary.", "vocabulary%s." % suffix)
            if not os.path.isfile(ip):
                print("(skipping %s — no %s)" % (name, ip))
                continue
        artists[name] = (ip, ep)
    return artists


def build_candidates(master_path, suffix, detector_names):
    """Mirrors bench_deck_quality.main()'s two scan passes (master-side then
    example-side), calling the same detector functions, but collects rows
    instead of printing a report. Dedup semantics match the bench exactly:
    master-side detectors dedupe a card across artists (first occurrence
    wins); example-side detectors do not (each artist's deck is scanned
    independently, same as the bench)."""
    m = json.load(open(master_path))
    artists = resolve_artists(suffix)
    known_ok = {keynorm(w) for w in DETECTOR_KNOWN_OK}
    want = set(detector_names)

    candidates = []
    counts = collections.Counter()
    visible_ids = set()

    # --- master-side detectors (blank_rows, verbose_def, cognate_leak, menu_bloat) ---
    if want & set(MASTER_SIDE_DETECTORS):
        for artist, (ipath, _epath) in artists.items():
            idx_list = json.load(open(ipath))
            for idx in idx_list:
                mid = idx.get("id")
                mst = m.get(mid)
                if not visible(mst, idx):
                    continue
                if mid in visible_ids:
                    continue
                visible_ids.add(mid)

                word = mst.get("word", "")
                lemma = mst.get("lemma", "")
                all_senses = mst.get("senses", [])
                senses = real_senses(mst)

                if "blank_rows" in want:
                    blanks = detect_blank_rows(all_senses)
                    if blanks:
                        for s in blanks:
                            candidates.append(_row(
                                artist, word, lemma, s.get("pos"), "", "blank_rows",
                                norm(s.get("context")) or "(no context)"))
                            counts["blank_rows"] += 1

                if "verbose_def" in want:
                    vd = detect_verbose_def(senses)
                    if vd:
                        pos, text = vd
                        candidates.append(_row(artist, word, lemma, pos, text,
                                                "verbose_def", text))
                        counts["verbose_def"] += 1

                if "cognate_leak" in want:
                    cl = detect_cognate_leak(word, senses)
                    if cl:
                        pos = senses[0].get("pos") if senses else ""
                        candidates.append(_row(artist, word, lemma, pos, cl,
                                                "cognate_leak", cl))
                        counts["cognate_leak"] += 1

                if "menu_bloat" in want:
                    mb = detect_menu_bloat(senses)
                    if mb:
                        gloss, count = mb
                        candidates.append(_row(
                            artist, word, lemma, "", gloss, "menu_bloat",
                            "%r repeated %dx" % (gloss, count)))
                        counts["menu_bloat"] += 1

    # --- example-side detectors (code_switch_verbatim, propernoun_caps) ---
    if want & set(EXAMPLE_SIDE_DETECTORS):
        for artist, (ipath, epath) in artists.items():
            idx_list = json.load(open(ipath))
            ex = json.load(open(epath))
            vis = {idx["id"]: idx for idx in idx_list if visible(m.get(idx.get("id")), idx)}
            for mid in vis:
                node = ex.get(mid)
                if not node:
                    continue
                flat = [e for grp in node.get("m", []) for e in grp]
                if not flat:
                    continue
                word = m[mid].get("word", "")
                lemma = m[mid].get("lemma", "")
                if keynorm(word) in known_ok:
                    continue
                senses = real_senses(m[mid])
                gloss = norm(senses[0].get("translation"))[:40] if senses else ""
                pos = senses[0].get("pos") if senses else ""

                if "code_switch_verbatim" in want:
                    cs = detect_code_switch_verbatim(word, flat)
                    if cs is not None:
                        first = cs[0]
                        evidence = '"%s" -> "%s"' % (
                            norm(first.get("spanish")), norm(first.get("english")))
                        candidates.append(_row(artist, word, lemma, pos, gloss,
                                                "code_switch_verbatim", evidence))
                        counts["code_switch_verbatim"] += 1

                if "propernoun_caps" in want:
                    pc = detect_propernoun_caps(word, flat)
                    if pc is not None:
                        _mid_line, evidence_examples = pc
                        if evidence_examples:
                            tok = evidence_examples[0]["token"]
                            line = norm(evidence_examples[0]["example"].get("spanish"))
                            evidence = '"%s" in "%s"' % (tok, line)
                        else:
                            evidence = ""
                        candidates.append(_row(artist, word, lemma, pos, gloss,
                                                "propernoun_caps", evidence))
                        counts["propernoun_caps"] += 1

    return candidates, counts


def main():
    ap = argparse.ArgumentParser(
        description="Flag deck-quality candidates (bench_deck_quality.py detectors) "
                     "to a reviewable JSON file")
    ap.add_argument("--master", default=MASTER,
                    help="Master file (default: live). Use vocabulary_master_wikt.json "
                         "with --suffix _wikt to scan the parallel Wiktionary deck.")
    ap.add_argument("--suffix", default="",
                    help="Same semantics as bench_deck_quality.py --suffix "
                         "(e.g. _wikt -> BadBunnyvocabulary_wikt.index.json).")
    ap.add_argument("--detectors", default=",".join(DEFAULT_DETECTORS),
                    help="Comma-separated detector names to run. Default: %(default)s. "
                         "Available: " + ", ".join(ALL_DETECTORS) + ". "
                         "verbose_def is NOT in the default set — mostly bench false "
                         "positives now.")
    ap.add_argument("--output", required=True, help="Path to write the candidates JSON")
    args = ap.parse_args()

    detector_names = [d.strip() for d in args.detectors.split(",") if d.strip()]
    unknown = sorted(set(detector_names) - set(ALL_DETECTORS))
    if unknown:
        raise SystemExit("Unknown detector(s): %s (available: %s)"
                          % (", ".join(unknown), ", ".join(ALL_DETECTORS)))

    candidates, counts = build_candidates(args.master, args.suffix, detector_names)

    out = {
        "_meta": {
            "generated_at": int(time.time()),
            "master": args.master,
            "suffix": args.suffix,
            "detectors": detector_names,
            "counts": {name: counts.get(name, 0) for name in detector_names},
            "total": len(candidates),
        },
        "candidates": candidates,
    }

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("Wrote %d candidate(s) -> %s" % (len(candidates), args.output))
    for name in detector_names:
        print("  %-22s %d" % (name, counts.get(name, 0)))


if __name__ == "__main__":
    main()
