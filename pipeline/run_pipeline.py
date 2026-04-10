#!/usr/bin/env python3
"""
Pipeline orchestrator for normal-mode Spanish vocabulary.

Usage (from project root):
    python3 pipeline/run_pipeline.py
    python3 pipeline/run_pipeline.py --from-step 3
    python3 pipeline/run_pipeline.py --dry-run

Steps:
    1.  build_inventory.py     — Word inventory from CSV (IDs, ranks, flags)
    2.  build_examples.py      — Match Tatoeba examples to vocabulary
    2b. build_conjugations.py  — Conjugation tables + reverse lookup (verbecc)
    3.  build_senses.py        — Build sense inventory from Wiktionary
    3b. build_mwes.py          — Extract MWE phrases from Wiktionary derived terms
    4.  match_senses.py        — Assign examples to senses via keyword overlap
    5.  flag_cognates.py       — Flag transparent cognates (suffix rules)
    6.  build_vocabulary.py    — Assemble final vocabulary from all layers
"""

import argparse
import os
import subprocess
import sys
import time

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)
PYTHON = sys.executable

STEPS = [
    {"num": 1, "label": "Word inventory from CSV",
     "script": "build_inventory.py",
     "output": "Data/Spanish/layers/word_inventory.json"},
    {"num": 2, "label": "Match Tatoeba examples to vocabulary",
     "script": "build_examples.py",
     "output": "Data/Spanish/layers/examples_raw.json"},
    {"num": 3, "label": "Build conjugation tables (verbecc)",
     "script": "build_conjugations.py",
     "output": "Data/Spanish/layers/conjugations.json"},
    {"num": 4, "label": "Build sense inventory from Wiktionary",
     "script": "build_senses.py",
     "output": "Data/Spanish/layers/senses_wiktionary.json"},
    {"num": 5, "label": "Extract MWE phrases from Wiktionary",
     "script": "build_mwes.py",
     "output": "Data/Spanish/layers/mwe_phrases.json"},
    {"num": 6, "label": "Assign examples to senses",
     "script": "match_senses.py",
     "output": "Data/Spanish/layers/sense_assignments.json"},
    {"num": 7, "label": "Flag transparent cognates",
     "script": "flag_cognates.py",
     "output": "Data/Spanish/layers/cognates.json"},
    {"num": 8, "label": "Assemble final vocabulary from layers",
     "script": "build_vocabulary.py",
     "output": "Data/Spanish/vocabulary.index.json"},
]

VALID_STEPS = [s["num"] for s in STEPS]


def run_step(step, dry_run=False):
    script_path = os.path.join(SCRIPTS_DIR, step["script"])
    cmd = [PYTHON, script_path]

    print("\n" + "=" * 60)
    print("Step %d: %s" % (step["num"], step["label"]))
    print("  Script: %s" % step["script"])

    if dry_run:
        print("  [DRY RUN] Would run: %s" % " ".join(cmd))
        return True

    print("  Running...")
    start = time.time()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)
    elapsed = time.time() - start

    if result.returncode == 0:
        print("  Done (%.1f seconds)" % elapsed)
        return True
    print("  FAILED with exit code %d (%.1f seconds)" % (result.returncode, elapsed))
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Normal-mode Spanish vocabulary pipeline orchestrator")
    parser.add_argument("--from-step", type=int, default=1, choices=VALID_STEPS,
                        help="Start from this step (default: 1)")
    parser.add_argument("--to-step", type=int, default=8, choices=VALID_STEPS,
                        help="Stop after this step (default: 8)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print commands without running them")
    args = parser.parse_args()

    steps_to_run = [s for s in STEPS if args.from_step <= s["num"] <= args.to_step]

    print("Spanish Normal-Mode Pipeline")
    print("=" * 60)
    print("Steps: %s" % " -> ".join(str(s["num"]) for s in steps_to_run))
    if args.dry_run:
        print("Mode: DRY RUN")

    # File freshness
    print("\n--- File freshness ---")
    for step in STEPS:
        marker = ">>>" if step in steps_to_run else "   "
        out_path = os.path.join(PROJECT_ROOT, step["output"])
        if os.path.exists(out_path):
            age_h = (time.time() - os.path.getmtime(out_path)) / 3600
            if age_h < 1:
                age_str = "%.0f min ago" % (age_h * 60)
            elif age_h < 24:
                age_str = "%.1fh ago" % age_h
            else:
                age_str = "%.0fd ago" % (age_h / 24)
            print("%s Step %d: %-45s  %s" % (marker, step["num"], step["output"], age_str))
        else:
            print("%s Step %d: %-45s  (missing)" % (marker, step["num"], step["output"]))

    total_start = time.time()
    for step in steps_to_run:
        if not run_step(step, dry_run=args.dry_run):
            print("\nAborting — step %d failed." % step["num"])
            sys.exit(1)

    print("\n" + "=" * 60)
    if args.dry_run:
        print("Dry run complete.")
    else:
        print("Pipeline complete! (%.1f seconds)" % (time.time() - total_start))


if __name__ == "__main__":
    main()
