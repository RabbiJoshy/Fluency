#!/usr/bin/env python3
"""
tool_5a_extend_examples.py — Append more example sentences to an existing
examples_raw.json without disturbing any existing entries.

Safe for use AFTER Gemini sense classification. Existing examples are never
moved or replaced — new ones are appended to the END of each word's list —
so downstream sense_assignments that reference example indices by position
remain valid.

Unlike `step_5a_build_examples.py --word`, this tool never re-runs greedy
selection on existing examples. It only finds new candidates for words below
--target and appends them.

Works for normal mode and --artist-dir (per-artist examples). The
OpenSubtitles corpus paths always come from the language-level data dir.

Usage:
    # Normal mode — extend Spanish words up to 40 examples each:
    python3 pipeline/tool_5a_extend_examples.py --target 40

    # Only extend specific words:
    python3 pipeline/tool_5a_extend_examples.py --target 40 --word hacer --word saber

    # Artist mode:
    python3 pipeline/tool_5a_extend_examples.py --artist-dir Artists/es/BadBunny --target 40

    # See what would be backfilled without writing:
    python3 pipeline/tool_5a_extend_examples.py --target 40 --dry-run

Inputs:
    {layers}/examples_raw.json                 (required)
    Data/{Lang}/layers/word_inventory.json      (or artist inventory if available)
    Data/{Lang}/{lang}_ranks.json
    Data/{Lang}/corpora/opensubtitles/OpenSubtitles.en-{xx}.{xx,en}  (raw files)

Output:
    {layers}/examples_raw.json — updated in place (append-only per word)
    {layers}/examples_raw.json.meta.json — sidecar updated
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

# Import pure/parameterised helpers from step_5a — no side-effects on import.
# _backfill_rare_examples takes all paths as explicit arguments; select_examples
# and its dependencies use module-level defaults (MAX_CANDIDATES=50_000,
# MAX_OVERLAP_TIER=10, OVERLAP_WINDOW=50) which are the same good values used
# in normal step_5a runs.
from step_5a_build_examples import (  # noqa: E402
    _backfill_rare_examples,
    _LANGUAGE_CONFIG,
)
from util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

# Default target when --target is not specified. Higher than step_5a's
# MAX_EXAMPLES_PER_WORD=20 so a bare invocation actually adds something.
DEFAULT_TARGET = 40


def main():
    parser = argparse.ArgumentParser(
        description="Append more example sentences to examples_raw.json "
                    "without disturbing existing entries or downstream assignments."
    )
    parser.add_argument(
        "--language", default="spanish", choices=list(_LANGUAGE_CONFIG.keys()),
        help="Language for corpus + rank paths (default: spanish)"
    )
    parser.add_argument(
        "--artist-dir", default=None,
        help="Path to an artist directory (e.g. Artists/es/BadBunny). "
             "When set, examples_raw.json is read from that artist's layers dir. "
             "Corpus files still come from the language-level Data/ dir."
    )
    parser.add_argument(
        "--target", type=int, default=DEFAULT_TARGET,
        help=f"Target number of examples per word (default: {DEFAULT_TARGET}). "
             f"Words already at or above this count are skipped entirely."
    )
    parser.add_argument(
        "--word", action="append", default=[],
        help="Only extend these specific surface words (repeatable). "
             "All other words are left untouched. Useful for surgical top-ups."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count how many words are below --target and exit. Nothing is written."
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Resolve paths
    # ------------------------------------------------------------------
    cfg = _LANGUAGE_CONFIG[args.language]
    lang_dir = args.language.capitalize()
    base = PROJECT_ROOT / "Data" / lang_dir

    ranks_path = base / cfg["ranks_file"]
    opensubs_es = (base / "corpora" / "opensubtitles"
                   / f"OpenSubtitles.en-{cfg['iso2']}.{cfg['iso2']}")
    opensubs_en = (base / "corpora" / "opensubtitles"
                   / f"OpenSubtitles.en-{cfg['iso2']}.en")
    inventory_path = base / "layers" / "word_inventory.json"

    if args.artist_dir:
        artist_base = Path(args.artist_dir).resolve()
        if not artist_base.exists():
            print(f"ERROR: --artist-dir not found: {artist_base}")
            sys.exit(1)
        examples_path = artist_base / "data" / "layers" / "examples_raw.json"
        # Use artist inventory (subset of normal vocab) when available.
        artist_inv = artist_base / "data" / "layers" / "word_inventory.json"
        if artist_inv.exists():
            inventory_path = artist_inv
            print(f"Using artist inventory: {artist_inv}")
        else:
            print(f"No artist inventory found; using language inventory: {inventory_path}")
    else:
        examples_path = base / "layers" / "examples_raw.json"

    # ------------------------------------------------------------------
    # Preflight checks
    # ------------------------------------------------------------------
    missing = []
    if not examples_path.exists():
        missing.append(f"  examples_raw.json: {examples_path}")
    if not inventory_path.exists():
        missing.append(f"  word_inventory.json: {inventory_path}")
    if not ranks_path.exists():
        missing.append(f"  ranks file: {ranks_path}")
    if not opensubs_es.exists():
        missing.append(f"  OpenSubtitles target: {opensubs_es}")
    if not opensubs_en.exists():
        missing.append(f"  OpenSubtitles English: {opensubs_en}")
    if missing:
        print("ERROR: required files not found:")
        for m in missing:
            print(m)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    print(f"Loading {examples_path.name}...")
    with open(examples_path, encoding="utf-8") as f:
        output = json.load(f)
    total_before = sum(len(v) for v in output.values())
    print(f"  {len(output)} words, {total_before:,} total examples")

    print(f"Loading {inventory_path.name}...")
    with open(inventory_path, encoding="utf-8") as f:
        inventory = json.load(f)
    print(f"  {len(inventory)} inventory entries")

    print(f"Loading {ranks_path.name}...")
    with open(ranks_path, encoding="utf-8") as f:
        word_to_rank = json.load(f)
    print(f"  {len(word_to_rank)} rank entries")

    # ------------------------------------------------------------------
    # Build lookups (mirrors step_5a main())
    # ------------------------------------------------------------------
    inv_rank_lookup = {}
    for i, e in enumerate(inventory):
        wl = e["word"].lower()
        if wl not in inv_rank_lookup:
            inv_rank_lookup[wl] = i

    phrase_to_inv_rank = {}
    for i, e in enumerate(inventory):
        w = e["word"].lower()
        if any(c in w for c in " '-") and w not in phrase_to_inv_rank:
            phrase_to_inv_rank[w] = i
    if phrase_to_inv_rank:
        print(f"  {len(phrase_to_inv_rank)} multi-token inventory entries (phrase-indexed)")

    restrict_to = {w.lower() for w in args.word} if args.word else None

    # ------------------------------------------------------------------
    # Report scope
    # ------------------------------------------------------------------
    candidates = [
        e for e in inventory
        if len(output.get(e["word"], [])) < args.target
        and (restrict_to is None or e["word"].lower() in restrict_to)
    ]
    print(f"\n{len(candidates):,} words below --target={args.target} "
          f"(will be streamed for new examples)")

    if restrict_to:
        print(f"  (restricted to {len(restrict_to)} words: "
              f"{', '.join(sorted(restrict_to)[:10])}"
              f"{'...' if len(restrict_to) > 10 else ''})")

    if args.dry_run:
        print("\n--dry-run: no files written.")
        return

    if not candidates:
        print("Nothing to do — all words already at or above --target.")
        return

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------
    print(f"\nStreaming {opensubs_es.name} for new candidates...")
    _backfill_rare_examples(
        output, inventory,
        opensubs_es, opensubs_en,
        word_to_rank, inv_rank_lookup, phrase_to_inv_rank,
        max_per_word=args.target,
        threshold=args.target,
        restrict_to=restrict_to,
    )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    total_after = sum(len(v) for v in output.values())
    added = total_after - total_before
    print(f"\nWriting {examples_path} (+{added:,} examples)...")
    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    write_sidecar(
        examples_path,
        make_meta("extend_examples", 1, extra={
            "target": args.target,
            "language": args.language,
            "artist_dir": str(args.artist_dir) if args.artist_dir else None,
            "added": added,
        }),
    )
    print(f"Done. {total_before:,} → {total_after:,} total examples.")


if __name__ == "__main__":
    main()
