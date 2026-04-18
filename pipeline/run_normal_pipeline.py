#!/usr/bin/env python3
"""
Pipeline orchestrator for normal-mode Spanish vocabulary.

Usage (from project root):
    python3 pipeline/run_normal_pipeline.py
    python3 pipeline/run_normal_pipeline.py --from-step 3
    python3 pipeline/run_normal_pipeline.py --dry-run

Steps:
    2.  step_2a_build_inventory.py   — Word inventory from CSV (IDs, ranks, flags)
    5a. step_5a_build_examples.py    — Match Tatoeba examples to vocabulary
    5b. step_5b_build_conjugations.py — Conjugation tables + reverse lookup (verbecc)
    5c. step_5c_build_senses.py      — Build sense inventory from Wiktionary
    5d. step_5d_build_mwes.py        — Extract MWE phrases from Wiktionary derived terms
    6.  step_6a_assign_senses.py     — Assign examples to senses
    7.  step_7a_map_senses_to_lemmas.py — Normalize assignments onto word|lemma keys
    8.  step_7c_flag_cognates.py     — Flag transparent cognates (suffix rules)
    9.  step_8a_assemble_vocabulary.py — Assemble final vocabulary from all layers
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
     "script": "step_2a_build_inventory.py",
     "output": "Data/Spanish/layers/word_inventory.json"},
    {"num": 2, "label": "Match Tatoeba examples to vocabulary",
     "script": "step_5a_build_examples.py",
     "output": "Data/Spanish/layers/examples_raw.json"},
    {"num": 3, "label": "Build conjugation tables (verbecc)",
     "script": "step_5b_build_conjugations.py",
     "output": "Data/Spanish/layers/conjugations.json"},
    {"num": 4, "label": "Route clitics (three-tier classification)",
     "script": "step_4a_route_clitics.py",
     "output": "Data/Spanish/layers/word_routing.json"},
    {"num": 5, "label": "Build sense inventory",
     "script": "step_5c_build_senses.py",
     "output": "Data/Spanish/layers/sense_menu/wiktionary.json"},
    {"num": 6, "label": "Extract MWE phrases from Wiktionary",
     "script": "step_5d_build_mwes.py",
     "output": "Data/Spanish/layers/mwe_phrases.json"},
    {"num": 7, "label": "Assign examples to senses",
     "script": "step_6a_assign_senses.py",
     "output": "Data/Spanish/layers/sense_assignments/wiktionary.json"},
    {"num": 8, "label": "Normalize assignments onto word|lemma keys",
     "script": "step_7a_map_senses_to_lemmas.py",
     "output": "Data/Spanish/layers/sense_assignments_lemma/wiktionary.json"},
    {"num": 9, "label": "Flag transparent cognates",
     "script": "step_7c_flag_cognates.py",
     "output": "Data/Spanish/layers/cognates.json"},
    {"num": 10, "label": "Assemble final vocabulary from layers",
     "script": "step_8a_assemble_vocabulary.py",
     "output": "Data/Spanish/vocabulary.index.json"},
]

VALID_STEPS = [s["num"] for s in STEPS]


def run_step(step, dry_run=False, extra_args=None):
    script_path = os.path.join(SCRIPTS_DIR, step["script"])
    cmd = [PYTHON, script_path] + (extra_args or [])

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
    parser.add_argument("--to-step", type=int, default=10, choices=VALID_STEPS,
                        help="Stop after this step (default: 9)")
    parser.add_argument("--skip-step", type=int, action="append", default=[],
                        choices=VALID_STEPS,
                        help="Skip this step number (repeatable)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print commands without running them")
    parser.add_argument("--sense-source", choices=("wiktionary", "spanishdict"),
                        default="spanishdict",
                        help="Sense dictionary source (default: spanishdict)")
    parser.add_argument("--classifier", choices=["keyword", "biencoder", "gemini"],
                        default="biencoder",
                        help="Primary classifier for step 6a (default: biencoder).")
    gf = parser.add_mutually_exclusive_group()
    gf.add_argument("--gap-fill", dest="gap_fill", action="store_true", default=None,
                    help="Run Gemini gap-fill on zero-sense words. "
                         "Default: on for gemini, off otherwise.")
    gf.add_argument("--no-gap-fill", dest="gap_fill", action="store_false",
                    help="Skip gap-fill.")
    parser.add_argument("--max-examples", type=int, default=None,
                        help="Max examples per word sent to Gemini.")
    parser.add_argument("--remainders", action="store_true",
                        help="Emit SENSE_CYCLE remainder buckets in the final deck (default: off).")
    args = parser.parse_args()

    skip_set = set(args.skip_step)
    steps_to_run = [s for s in STEPS
                    if args.from_step <= s["num"] <= args.to_step
                    and s["num"] not in skip_set]

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
    # Steps that accept --sense-source
    source_aware_scripts = {
        "step_5b_build_conjugations.py",
        "step_5c_build_senses.py",
        "step_6a_assign_senses.py",
        "step_8a_assemble_vocabulary.py",
    }

    for step in steps_to_run:
        extra = []
        if step["script"] in source_aware_scripts:
            extra = ["--sense-source", args.sense_source]
        if step["script"] == "step_6a_assign_senses.py":
            extra.extend(["--classifier", args.classifier])
            if args.gap_fill is True:
                extra.append("--gap-fill")
            elif args.gap_fill is False:
                extra.append("--no-gap-fill")
            if args.max_examples is not None:
                extra.extend(["--max-examples", str(args.max_examples)])
        if step["script"] == "step_8a_assemble_vocabulary.py" and args.remainders:
            extra.append("--remainders")
        if not run_step(step, dry_run=args.dry_run, extra_args=extra):
            print("\nAborting — step %d failed." % step["num"])
            sys.exit(1)

    print("\n" + "=" * 60)
    if args.dry_run:
        print("Dry run complete.")
    else:
        print("Pipeline complete! (%.1f seconds)" % (time.time() - total_start))


if __name__ == "__main__":
    main()
