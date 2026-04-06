#!/usr/bin/env python3
"""
Pipeline orchestrator for normal-mode Spanish vocabulary.

Usage (from project root):
    python3 Data/Spanish/Scripts/run_pipeline.py
    python3 Data/Spanish/Scripts/run_pipeline.py --from-step 2
    python3 Data/Spanish/Scripts/run_pipeline.py --dry-run

Steps:
    1. build_examples.py  — Match Tatoeba examples to vocabulary
    2. build_senses.py    — Build sense inventory from Wiktionary
    3. match_senses.py    — Assign examples to senses via keyword overlap
    4. finalize           — Split into index + examples for front end
"""

import argparse
import os
import subprocess
import sys
import time

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS_DIR)))
PYTHON = sys.executable

FINALIZE_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "finalize_vocabulary.py")
VOCAB_PATH = "Data/Spanish/vocabulary.json"

STEPS = [
    {"num": 1, "label": "Match Tatoeba examples to vocabulary",
     "script": "build_examples.py",
     "output": "Data/Spanish/vocabulary.json"},
    {"num": 2, "label": "Build sense inventory from Wiktionary",
     "script": "build_senses.py",
     "output": "Data/Spanish/senses_wiktionary.json"},
    {"num": 3, "label": "Assign examples to senses",
     "script": "match_senses.py",
     "output": "Data/Spanish/vocabulary.json"},
    {"num": 4, "label": "Split into index + examples for front end",
     "script": None,  # handled specially
     "output": "Data/Spanish/vocabulary.index.json"},
]


def run_step(step, dry_run=False):
    if step["num"] == 4:
        # Finalize: shared script with --input arg
        cmd = [PYTHON, FINALIZE_SCRIPT, "--input", VOCAB_PATH]
    else:
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
    parser.add_argument("--from-step", type=int, default=1, choices=[1, 2, 3, 4],
                        help="Start from this step (default: 1)")
    parser.add_argument("--to-step", type=int, default=4, choices=[1, 2, 3, 4],
                        help="Stop after this step (default: 4)")
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
            print("%s Step %d: %-40s  %s" % (marker, step["num"], step["output"], age_str))
        else:
            print("%s Step %d: %-40s  (missing)" % (marker, step["num"], step["output"]))

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
