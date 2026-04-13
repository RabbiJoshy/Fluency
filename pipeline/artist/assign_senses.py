#!/usr/bin/env python3
"""
Step 6: Assign artist lyric examples to word senses.

Single entry point that dispatches to the appropriate classifier
based on word_routing.json:

  - biencoder-routed words  → local bi-encoder (match_artist_senses.py)
  - gemini-routed words     → Gemini Flash Lite (build_wiktionary_senses.py)
  - gap-fill words          → reuses existing inline senses, or Gemini if new

Without GEMINI_API_KEY, only the bi-encoder stage runs.
All output merges into a single sense_assignments.json.

Usage (from project root):
    .venv/bin/python3 pipeline/artist/assign_senses.py --artist-dir "Artists/Bad Bunny"
    .venv/bin/python3 pipeline/artist/assign_senses.py --artist-dir "Artists/Bad Bunny" --no-gemini
    .venv/bin/python3 pipeline/artist/assign_senses.py --artist-dir "Artists/Bad Bunny" --keyword-only
"""

import argparse
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(os.path.dirname(os.path.dirname(SCRIPTS_DIR)), ".venv", "bin", "python3")
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


def main():
    parser = argparse.ArgumentParser(
        description="Step 6: Assign senses (bi-encoder + Gemini)")

    sys.path.insert(0, SCRIPTS_DIR)
    from _artist_config import add_artist_arg, load_dotenv_from_project_root
    load_dotenv_from_project_root()
    add_artist_arg(parser)

    parser.add_argument("--no-gemini", action="store_true",
                        help="Skip Gemini stage (bi-encoder only, free)")
    parser.add_argument("--keyword-only", action="store_true",
                        help="Use keyword overlap instead of bi-encoder (instant)")
    parser.add_argument("--force", action="store_true",
                        help="Re-classify all words (ignore existing assignments)")
    parser.add_argument("--all-gemini", action="store_true",
                        help="Skip bi-encoder and promote biencoder-routed words into the Gemini stage for this run")
    parser.add_argument("--gemini-model", default="gemini-2.5-flash-lite",
                        help="Gemini model for the Gemini stage (default: gemini-2.5-flash-lite)")
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    has_api_key = bool(os.environ.get("GEMINI_API_KEY"))

    # Stage 1: bi-encoder for biencoder-routed words
    if args.all_gemini:
        print("\n  Skipping bi-encoder stage (--all-gemini)")
    else:
        bienc_args = ["--artist-dir", artist_dir]
        if args.keyword_only:
            bienc_args.append("--keyword-only")
        if args.force:
            bienc_args.append("--force")
        run_step("STAGE 1: Bi-encoder (biencoder-routed words)",
                 "match_artist_senses.py", bienc_args)

    # Stage 2: Gemini for gemini-routed words
    if args.no_gemini:
        print("\n  Skipping Gemini stage (--no-gemini)")
    elif not has_api_key:
        print("\n  Skipping Gemini stage (no GEMINI_API_KEY set)")
    else:
        gemini_args = ["--artist-dir", artist_dir, "--new-only"]
        if args.all_gemini:
            gemini_args.append("--all-gemini")
        if args.force:
            gemini_args.append("--force")
        if args.gemini_model:
            gemini_args.extend(["--gemini-model", args.gemini_model])
        run_step("STAGE 2: Gemini Flash Lite (gemini-routed words)",
                 "build_wiktionary_senses.py", gemini_args)

    print("\n  Done. All assignments in: %s" %
          os.path.join(artist_dir, "data", "layers", "sense_assignments.json"))


if __name__ == "__main__":
    main()
