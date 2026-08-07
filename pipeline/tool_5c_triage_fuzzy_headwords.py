#!/usr/bin/env python3
"""
tool_5c_triage_fuzzy_headwords.py — find the SpanishDict cache entries whose
headwords are fuzzy-match damage, and split them into the two things you can
actually do about it.

Why this exists
---------------
SpanishDict's surface->headword resolver answers a query for a word it does not
know with its nearest dictionary neighbour, crossing into its English dictionary
freely (`kil` -> "kill", `sein` -> "sin", `todito` -> "torito"). Those bogus
headwords become a card's lemma AND a meaningless sense menu, so the word then
burns a Gemini classification against senses that have nothing to do with it.

`is_plausible_headword` (util_5c_spanishdict) already rejects these at SCRAPE
time, but it cannot retroactively clean entries cached before it existed. This
tool applies the live guard to the committed cache and reports what is damaged,
so a targeted fix replaces a full re-scrape (~5% of the cache, not 100%).

Two outcomes, because they have different fixes:

  * **requery** — the surface is an elision/orthography variant SpanishDict
    would answer correctly if asked properly (`curarno'`, `hidratá'`,
    `inmortale'`). Reggaeton spelling drops a final consonant and marks it with
    an apostrophe. We propose restorations and keep only those that are real
    Spanish forms, so this class is fixable with no scrape at all.
  * **quarantine** — SpanishDict genuinely has no entry and invented one. The
    menu should be dropped so the word routes to sense_discovery instead of
    being classified against nonsense.

Over-rejection is acceptable and useful: a plausible-looking entry in the report
tells you where to add a manual override, which is strictly better than silently
shipping a wrong lemma.

Usage:
    python3 pipeline/tool_5c_triage_fuzzy_headwords.py [--language spanish]
        [--artist-dir "Artists/spanish/Bad Bunny"]   # scope to one deck
        [--out PATH] [--limit N]

Output:
    Data/{Lang}/layers/spanishdict_fuzzy_triage.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
import util_5c_spanishdict as sd  # noqa: E402
from util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

STEP_VERSION = 1
STEP_NAME = "triage_fuzzy_headwords"

LANGUAGE_DIRS = {"spanish": "Spanish", "french": "French", "dutch": "Dutch"}

# Reggaeton/Caribbean orthography marks a dropped final segment with an
# apostrophe. These are the segments that actually go missing, longest first so
# `-do` is tried before `-d`.
_ELISION_RESTORATIONS = ("dos", "das", "do", "da", "os", "as", "es", "s", "r", "d", "z", "ve")


def restoration_candidates(surface):
    """Propose full spellings for an apostrophe-elided surface.

    `curarno'` -> curarnos, `hidratá'` -> hidratar, `inmortale'` -> inmortales.
    Returns candidates in priority order; the caller filters to real forms.
    """
    out = []
    if "'" not in surface:
        return out
    # Trailing apostrophe: a final segment was dropped.
    if surface.endswith("'"):
        stem = surface[:-1]
        for suffix in _ELISION_RESTORATIONS:
            out.append(stem + suffix)
        # The accent often only marked the stress the dropped 'r' carried.
        out.append(sd._deaccent(stem) + "r")
    # Internal apostrophe: a medial segment was dropped (na'ita -> nadita).
    else:
        head, _, tail = surface.partition("'")
        for filler in ("d", "da", "de", "r", "ra"):
            out.append(head + filler + tail)
        out.append(head + tail)
    seen, unique = set(), []
    for cand in out:
        if cand and cand not in seen:
            seen.add(cand)
            unique.append(cand)
    return unique


def load_known_forms(lang_dir):
    """spanish_forms.json — every known surface form, used to vet candidates."""
    path = lang_dir / "layers" / "spanish_forms.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_artist_words(artist_dir):
    """The surfaces that actually appear in one artist's corpus."""
    if not artist_dir:
        return None
    path = Path(artist_dir) / "data" / "layers" / "word_inventory.json"
    if not path.exists():
        path = Path(artist_dir) / "data" / "known_vocab" / "word_routing.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if isinstance(data, list):
        return {(e.get("word") or "").lower() for e in data if isinstance(e, dict)}
    if isinstance(data, dict):
        words = set()
        for key in ("classifier", "exclude"):
            section = data.get(key) or {}
            if isinstance(section, dict):
                for bucket in section.values():
                    if isinstance(bucket, list):
                        words.update(str(w).lower() for w in bucket)
        for key in ("sense_discovery",):
            if isinstance(data.get(key), list):
                words.update(str(w).lower() for w in data[key])
        for key in ("clitic_merge", "derivation_map"):
            if isinstance(data.get(key), dict):
                words.update(str(w).lower() for w in data[key])
        return words or None
    return None


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--language", default="spanish", choices=sorted(LANGUAGE_DIRS))
    parser.add_argument("--artist-dir", default=None,
                        help="scope the report to surfaces in this artist's corpus")
    parser.add_argument("--out", default=None)
    parser.add_argument("--limit", type=int, default=25,
                        help="how many samples to print per class")
    args = parser.parse_args()

    lang_dir = PROJECT_ROOT / "Data" / LANGUAGE_DIRS[args.language]
    cache_path = lang_dir / "Senses" / "spanishdict" / "surface_cache.json"
    if not cache_path.exists():
        print(f"ERROR: SpanishDict cache not found: {cache_path}")
        return 1

    with open(cache_path, encoding="utf-8") as f:
        cache = json.load(f)
    known_forms = load_known_forms(lang_dir)
    artist_words = load_artist_words(args.artist_dir)
    if args.artist_dir:
        print(f"  scoped to {args.artist_dir}: "
              f"{len(artist_words) if artist_words else 0} corpus surfaces")

    requery, quarantine, degraded = [], [], []
    scanned = 0
    for surface, entry in cache.items():
        analyses = entry.get("dictionary_analyses") or []
        if not analyses:
            continue
        if artist_words is not None and surface.lower() not in artist_words:
            continue
        scanned += 1
        # Same arguments the real menu build passes — SD's own conjugation
        # pointers vouch for stem-changing paradigms, so without these the
        # guard wrongly flags legitimate forms like `pasó` -> `pasar`.
        conj_lemmas = sd._surface_conjugation_lemmas(entry.get("possible_results"))
        rejected = [
            (a.get("headword") or "").strip()
            for a in analyses
            if not sd.is_plausible_headword(
                surface, a.get("headword"),
                surface_relation=a.get("surface_relation", ""),
                conj_lemmas=conj_lemmas,
            )
        ]
        if not rejected:
            continue
        if len(rejected) < len(analyses):
            degraded.append({"surface": surface, "rejected": rejected})
            continue

        row = {"surface": surface, "bogus_headwords": rejected}
        if "'" in surface:
            candidates = [c for c in restoration_candidates(surface) if c in known_forms]
            row["candidates"] = candidates
            # Only a real restoration is actionable without a scrape; an
            # apostrophe form with no valid candidate is just as unknown to SD.
            (requery if candidates else quarantine).append(row)
        else:
            quarantine.append(row)

    print(f"\n  scanned                 : {scanned:,} surfaces with analyses")
    print(f"  REQUERY (elision fix)   : {len(requery):,}")
    print(f"  QUARANTINE (drop menu)  : {len(quarantine):,}")
    print(f"  degraded (some survive) : {len(degraded):,}")

    if requery:
        print("\n  --- requery: ask SpanishDict the restored spelling ---")
        for row in requery[:args.limit]:
            print(f"    {row['surface']:16} -> {row['bogus_headwords']}"
                  f"   try: {row['candidates'][:3]}")
    if quarantine:
        print("\n  --- quarantine: drop the menu, route to sense_discovery ---")
        for row in quarantine[:args.limit]:
            print(f"    {row['surface']:16} -> {row['bogus_headwords']}")

    out_path = Path(args.out) if args.out else lang_dir / "layers" / "spanishdict_fuzzy_triage.json"
    payload = {
        "_meta": {
            "note": "Entries whose SpanishDict headwords fail the live "
                    "plausibility guard. requery = fixable by asking a restored "
                    "spelling; quarantine = SD has no real entry, drop the menu. "
                    "Over-rejection is expected — review before acting.",
            "artist_scope": args.artist_dir or None,
            "scanned": scanned,
        },
        "requery": requery,
        "quarantine": quarantine,
        "degraded": degraded,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    write_sidecar(out_path, make_meta(STEP_NAME, STEP_VERSION))
    print(f"\n  wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
