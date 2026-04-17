#!/usr/bin/env python3
"""
step_6a_assign_senses.py — Assign Spanish examples to word senses (normal mode).

Single entry point that dispatches to the same shared classifiers used by
artist mode:

  - biencoder-routed words  → local bi-encoder (step_6b_assign_senses_local.py)
  - gemini-routed words     → Gemini Flash Lite (step_6c_assign_senses_gemini.py)

Without GEMINI_API_KEY, only the bi-encoder stage runs.
All output merges into Data/Spanish/layers/sense_assignments/{source}.json.

Usage:
    .venv/bin/python3 pipeline/step_6a_assign_senses.py
    .venv/bin/python3 pipeline/step_6a_assign_senses.py --no-gemini
    .venv/bin/python3 pipeline/step_6a_assign_senses.py --keyword-only
    .venv/bin/python3 pipeline/step_6a_assign_senses.py --sense-source spanishdict

The legacy monolithic implementation is preserved at legacy_6a_assign_senses.py
for reference.
"""

import argparse
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)
PYTHON = os.path.join(PROJECT_ROOT, ".venv", "bin", "python3")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable


def run_step(label, script, args):
    """Run a pipeline step, streaming output."""
    cmd = [PYTHON, os.path.join(SCRIPTS_DIR, script)] + args
    print("\n" + "=" * 60)
    print(label)
    print("=" * 60)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("ERROR: %s failed (exit code %d)" % (script, result.returncode))
        sys.exit(result.returncode)


def _load_dotenv():
    """Load .env from project root so GEMINI_API_KEY propagates to children."""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


def main():
    parser = argparse.ArgumentParser(
        description="Step 6: Assign senses (bi-encoder + Gemini)")

    parser.add_argument("--no-gemini", action="store_true",
                        help="Skip Gemini stage (bi-encoder only, free)")
    parser.add_argument("--keyword-only", action="store_true",
                        help="Use keyword overlap instead of bi-encoder (instant)")
    parser.add_argument("--force", action="store_true",
                        help="Re-classify all words (ignore existing assignments)")
    parser.add_argument("--all-gemini", action="store_true",
                        help="Skip bi-encoder and promote biencoder-routed words "
                             "into the Gemini stage for this run")
    parser.add_argument("--gemini-model", default="gemini-2.5-flash-lite",
                        help="Gemini model for the Gemini stage (default: gemini-2.5-flash-lite)")
    parser.add_argument("--sense-source", choices=["wiktionary", "spanishdict"],
                        default="wiktionary",
                        help="Sense menu source to use for assignment (default: wiktionary)")
    parser.add_argument("--max-examples", type=int, default=None,
                        help="Max examples per word sent to Gemini (step 6c default is 10). "
                             "Re-running with a larger value picks up new examples only.")
    args = parser.parse_args()

    _load_dotenv()
    has_api_key = bool(os.environ.get("GEMINI_API_KEY"))

    # Stage 1: bi-encoder for biencoder-routed words
    if args.all_gemini:
        print("\n  Skipping bi-encoder stage (--all-gemini)")
    else:
        bienc_args = []
        if args.sense_source == "spanishdict":
            bienc_args.extend([
                "--sense-menu-file", "sense_menu/spanishdict.json",
                "--assignments-file", "sense_assignments/spanishdict.json",
                "--biencoder-method-name", "spanishdict-biencoder",
                "--keyword-method-name", "spanishdict-keyword",
                "--auto-method-name", "spanishdict-auto",
                "--menu-source-label", "spanishdict",
            ])
        if args.keyword_only:
            bienc_args.append("--keyword-only")
        if args.force:
            bienc_args.append("--force")
        run_step("STAGE 1: Bi-encoder (biencoder-routed words)",
                 "step_6b_assign_senses_local.py", bienc_args)

    # Stage 2: Gemini for gemini-routed words
    if args.no_gemini:
        print("\n  Skipping Gemini stage (--no-gemini)")
    elif not has_api_key:
        print("\n  Skipping Gemini stage (no GEMINI_API_KEY set)")
    else:
        gemini_args = ["--new-only"]
        if args.sense_source == "spanishdict":
            gemini_args = [
                "--sense-menu-file", "sense_menu/spanishdict.json",
                "--assignments-file", "sense_assignments/spanishdict.json",
                "--method-name", "spanishdict-flash-lite" if "flash-lite" in args.gemini_model else "spanishdict-flash",
                "--keyword-method-name", "spanishdict-keyword",
                "--auto-method-name", "spanishdict-auto",
                "--menu-source-label", "spanishdict",
            ]
        if args.all_gemini:
            gemini_args.append("--all-gemini")
        if args.force:
            gemini_args.append("--force")
        if args.gemini_model:
            gemini_args.extend(["--gemini-model", args.gemini_model])
        if args.max_examples is not None:
            gemini_args.extend(["--max-examples", str(args.max_examples)])
        run_step("STAGE 2: Gemini Flash Lite (gemini-routed words)",
                 "step_6c_assign_senses_gemini.py", gemini_args)

    out_rel = os.path.join("sense_assignments",
                           "spanishdict.json" if args.sense_source == "spanishdict" else "wiktionary.json")
    print("\n  Done. All assignments in: %s" %
          os.path.join("Data", "Spanish", "layers", out_rel))


if __name__ == "__main__":
    main()
