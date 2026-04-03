#!/usr/bin/env python3
"""
Pipeline orchestrator for the Bad Bunny vocabulary pipeline.

Runs steps in order, checks intermediate file freshness, and supports
partial re-runs with --from-step and --to-step.

Usage (from project root):
    .venv/bin/python3 "Bad Bunny/run_pipeline.py"
    .venv/bin/python3 "Bad Bunny/run_pipeline.py" --from-step 6
    .venv/bin/python3 "Bad Bunny/run_pipeline.py" --dry-run
    .venv/bin/python3 "Bad Bunny/run_pipeline.py" --from-step 3 --to-step 5

API key is read from .env (GEMINI_API_KEY=...) or --api-key flag.
"""

import argparse
import os
import subprocess
import sys
import time


def _load_dotenv():
    """Load .env file from project root if it exists."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PYTHON = os.path.join(PROJECT_ROOT, ".venv", "bin", "python3")

# ---------------------------------------------------------------------------
# Step definitions
# ---------------------------------------------------------------------------
# Each step: (number, label, script, args_fn, input_file, output_file)
# args_fn receives the parsed args and returns a list of extra arguments.
# input_file/output_file are relative to SCRIPT_DIR for freshness checks.

def _step_3_args(args):
    return [
        "--batch_glob", os.path.join(SCRIPT_DIR, "data", "input", "batches", "batch_*.json"),
        "--out", os.path.join(SCRIPT_DIR, "data", "word_counts", "vocab_evidence.json"),
        "--mwe-out", os.path.join(SCRIPT_DIR, "data", "word_counts", "mwe_detected.json"),
    ]

def _step_4_args(args):
    a = ["--api-key", args.api_key]
    if args.reset:
        a.append("--reset")
    return a

def _step_6_args(args):
    a = ["--api-key", args.api_key]
    if args.reset:
        a.extend(["--reset-sentences", "--reset-words"])
    return a

def _no_args(args):
    return []


STEPS = [
    {
        "num": 3,
        "label": "Tokenise, count words, detect MWEs",
        "script": "scripts/3_count_words.py",
        "args_fn": _step_3_args,
        "input": None,
        "output": "data/word_counts/vocab_evidence.json",
        "needs_api_key": False,
    },
    {
        "num": 4,
        "label": "Detect proper nouns (Gemini)",
        "script": "scripts/4_detect_proper_nouns.py",
        "args_fn": _step_4_args,
        "input": "data/word_counts/vocab_evidence.json",
        "output": "data/proper_nouns/detected_proper_nouns.json",
        "needs_api_key": True,
    },
    {
        "num": 5,
        "label": "Merge elisions",
        "script": "scripts/5_merge_elisions.py",
        "args_fn": _no_args,
        "input": "data/word_counts/vocab_evidence.json",
        "output": "data/elision_merge/vocab_evidence_merged.json",
        "needs_api_key": False,
    },
    {
        "num": 6,
        "label": "LLM word analysis (Gemini)",
        "script": "scripts/6_llm_analyze.py",
        "args_fn": _step_6_args,
        "input": "data/elision_merge/vocab_evidence_merged.json",
        "output": "BadBunnyvocabulary.json",
        "needs_api_key": True,
    },
    {
        "num": 7,
        "label": "Flag cognates",
        "script": "scripts/7_flag_cognates.py",
        "args_fn": _no_args,
        "input": "BadBunnyvocabulary.json",
        "output": "BadBunnyvocabulary.json",
        "needs_api_key": False,
    },
    {
        "num": 8,
        "label": "Rerank",
        "script": "scripts/8_rerank.py",
        "args_fn": _no_args,
        "input": "BadBunnyvocabulary.json",
        "output": "BadBunnyvocabulary.json",
        "needs_api_key": False,
    },
]

# Map step numbers to index for --from-step / --to-step
STEP_NUMS = [str(s["num"]) for s in STEPS]


def parse_step(value):
    """Parse a step number string (e.g. '2', '2c', '4') and return the index in STEPS."""
    for i, s in enumerate(STEPS):
        if str(s["num"]) == value:
            return i
    valid = ", ".join(STEP_NUMS)
    print("ERROR: Unknown step '%s'. Valid steps: %s" % (value, valid))
    sys.exit(1)


def file_mtime(path):
    """Return mtime or 0 if file doesn't exist."""
    full = os.path.join(SCRIPT_DIR, path) if not os.path.isabs(path) else path
    if os.path.exists(full):
        return os.path.getmtime(full)
    return 0


def check_freshness(step):
    """Warn if output is older than input."""
    if not step["input"] or not step["output"]:
        return
    in_mtime = file_mtime(step["input"])
    out_mtime = file_mtime(step["output"])
    if in_mtime > 0 and out_mtime > 0 and out_mtime < in_mtime:
        print("  WARNING: output is older than input — this step should be re-run")
    elif out_mtime == 0:
        print("  (output does not exist yet)")


def run_step(step, args, dry_run=False):
    """Run a single pipeline step."""
    script_path = os.path.join(SCRIPT_DIR, step["script"])
    extra_args = step["args_fn"](args)
    cmd = [PYTHON, script_path] + extra_args

    print("\n" + "=" * 60)
    print("Step %s: %s" % (step["num"], step["label"]))
    print("  Script: %s" % step["script"])
    check_freshness(step)

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
    else:
        print("  FAILED with exit code %d (%.1f seconds)" % (result.returncode, elapsed))
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Bad Bunny vocabulary pipeline orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Steps: %s" % " -> ".join("%s (%s)" % (s["num"], s["label"]) for s in STEPS),
    )
    parser.add_argument("--api-key", type=str, default=os.environ.get("GEMINI_API_KEY", ""),
                        help="Gemini API key (or set GEMINI_API_KEY env var)")
    parser.add_argument("--from-step", type=str, default=None,
                        help="Start from this step (e.g. 4, 2c)")
    parser.add_argument("--to-step", type=str, default=None,
                        help="Stop after this step (e.g. 3, 8)")
    parser.add_argument("--skip", type=str, nargs="*", default=[],
                        help="Skip these steps (e.g. --skip 2c 2d)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would run without executing")
    parser.add_argument("--reset", action="store_true",
                        help="Pass --reset to steps that support it (4, 6)")
    args = parser.parse_args()

    # Determine step range
    start_idx = parse_step(args.from_step) if args.from_step else 0
    end_idx = parse_step(args.to_step) if args.to_step else len(STEPS) - 1
    skip_set = set(args.skip)

    steps_to_run = STEPS[start_idx:end_idx + 1]
    steps_to_run = [s for s in steps_to_run if str(s["num"]) not in skip_set]

    # Check API key requirement
    needs_key = any(s["needs_api_key"] for s in steps_to_run)
    if needs_key and not args.api_key and not args.dry_run:
        print("ERROR: Steps %s require --api-key (or set GEMINI_API_KEY env var)" %
              ", ".join(str(s["num"]) for s in steps_to_run if s["needs_api_key"]))
        sys.exit(1)

    # Show plan
    print("Bad Bunny Pipeline")
    print("=" * 60)
    print("Steps to run: %s" % " -> ".join(str(s["num"]) for s in steps_to_run))
    if skip_set:
        print("Skipping: %s" % ", ".join(sorted(skip_set)))
    if args.dry_run:
        print("Mode: DRY RUN")
    print()

    # Freshness check for all steps
    print("--- File freshness check ---")
    for step in STEPS:
        marker = ">>>" if step in steps_to_run else "   "
        out_path = os.path.join(SCRIPT_DIR, step["output"]) if step["output"] else None
        if out_path and os.path.exists(out_path):
            age_hours = (time.time() - os.path.getmtime(out_path)) / 3600
            if age_hours < 1:
                age_str = "%.0f min ago" % (age_hours * 60)
            elif age_hours < 24:
                age_str = "%.1f hours ago" % age_hours
            else:
                age_str = "%.0f days ago" % (age_hours / 24)
            print("%s Step %3s: %-35s  %s" % (marker, step["num"], step["output"], age_str))
        else:
            print("%s Step %3s: %-35s  (missing)" % (marker, step["num"], step["output"] or "(no output)"))

    # Run steps
    total_start = time.time()
    failed = []

    for step in steps_to_run:
        ok = run_step(step, args, dry_run=args.dry_run)
        if not ok:
            failed.append(step)
            print("\nAborting pipeline — step %s failed." % step["num"])
            break

    total_elapsed = time.time() - total_start
    print("\n" + "=" * 60)
    if failed:
        print("Pipeline FAILED at step %s (%.1f minutes total)" %
              (failed[0]["num"], total_elapsed / 60))
        sys.exit(1)
    elif args.dry_run:
        print("Dry run complete — no steps were executed.")
    else:
        print("Pipeline complete! (%.1f minutes total)" % (total_elapsed / 60))


if __name__ == "__main__":
    main()
