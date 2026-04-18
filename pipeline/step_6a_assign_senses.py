#!/usr/bin/env python3
"""
step_6a_assign_senses.py — Assign Spanish examples to word senses.

Single entry point. One classifier runs per invocation. Every learnable word
(not excluded, not folded into a clitic base) gets exactly one assignment
from the chosen classifier. Optionally, zero-sense words get a Gemini
gap-fill pass too.

Flags:
    --classifier {keyword, biencoder, gemini}   (required)
        Picks the single classifier that runs over every learnable word.
    --gap-fill / --no-gap-fill
        Whether to also run Gemini gap-fill on zero-sense words.
        Default: on for `gemini`, off for `keyword` and `biencoder`.
    --sense-source {wiktionary, spanishdict}    (default: spanishdict)
    --max-examples N
        Per-word example cap sent to Gemini (default 10 in step_6c).
    --force
        Re-classify everything, ignoring existing assignments.
    --gemini-model MODEL
        Override the Gemini model (default: gemini-2.5-flash-lite).

Output merges into Data/Spanish/layers/sense_assignments/{source}.json
(or the artist equivalent if step_6c is called with --artist-dir —
artist mode has its own dispatcher).

Usage:
    .venv/bin/python3 pipeline/step_6a_assign_senses.py --classifier keyword
    .venv/bin/python3 pipeline/step_6a_assign_senses.py --classifier biencoder
    .venv/bin/python3 pipeline/step_6a_assign_senses.py --classifier gemini
    .venv/bin/python3 pipeline/step_6a_assign_senses.py --classifier gemini \
        --sense-source spanishdict --max-examples 20
    .venv/bin/python3 pipeline/step_6a_assign_senses.py --classifier biencoder --gap-fill
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
    cmd = [PYTHON, os.path.join(SCRIPTS_DIR, script)] + args
    print("\n" + "=" * 60)
    print(label)
    print("=" * 60)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("ERROR: %s failed (exit code %d)" % (script, result.returncode))
        sys.exit(result.returncode)


def _load_dotenv():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


def _spanishdict_args_local():
    return [
        "--sense-menu-file", "sense_menu/spanishdict.json",
        "--assignments-file", "sense_assignments/spanishdict.json",
        "--biencoder-method-name", "spanishdict-biencoder",
        "--keyword-method-name", "spanishdict-keyword",
        "--auto-method-name", "spanishdict-auto",
        "--menu-source-label", "spanishdict",
    ]


def _spanishdict_args_gemini(gemini_model):
    method = "spanishdict-flash-lite" if "flash-lite" in gemini_model else "spanishdict-flash"
    return [
        "--sense-menu-file", "sense_menu/spanishdict.json",
        "--assignments-file", "sense_assignments/spanishdict.json",
        "--method-name", method,
        "--keyword-method-name", "spanishdict-keyword",
        "--auto-method-name", "spanishdict-auto",
        "--menu-source-label", "spanishdict",
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Step 6: Assign senses (one classifier + optional Gemini gap-fill)")

    parser.add_argument("--classifier", choices=["keyword", "biencoder", "gemini"],
                        required=True,
                        help="Primary classifier that runs on every learnable word.")
    gf = parser.add_mutually_exclusive_group()
    gf.add_argument("--gap-fill", dest="gap_fill", action="store_true", default=None,
                    help="Run Gemini gap-fill on zero-sense words. "
                         "Default: on for gemini, off for keyword/biencoder.")
    gf.add_argument("--no-gap-fill", dest="gap_fill", action="store_false",
                    help="Skip gap-fill (no Gemini gap-fill pass).")
    parser.add_argument("--sense-source", choices=["wiktionary", "spanishdict"],
                        default="spanishdict",
                        help="Sense menu source (default: spanishdict)")
    parser.add_argument("--max-examples", type=int, default=None,
                        help="Max examples per word sent to Gemini (step 6c default 10).")
    parser.add_argument("--force", action="store_true",
                        help="Re-classify everything, ignoring existing assignments.")
    parser.add_argument("--gemini-model", default="gemini-2.5-flash-lite",
                        help="Gemini model (default: gemini-2.5-flash-lite)")
    args = parser.parse_args()

    _load_dotenv()
    has_api_key = bool(os.environ.get("GEMINI_API_KEY"))

    # Default gap-fill: on for gemini, off for keyword/biencoder.
    gap_fill = args.gap_fill
    if gap_fill is None:
        gap_fill = (args.classifier == "gemini")

    # Preflight: Gemini-using paths need an API key.
    gemini_needed = args.classifier == "gemini" or gap_fill
    if gemini_needed and not has_api_key:
        if args.classifier == "gemini":
            print("ERROR: --classifier gemini requires GEMINI_API_KEY in .env")
            sys.exit(1)
        if gap_fill:
            print("WARNING: --gap-fill requires GEMINI_API_KEY; skipping gap-fill.")
            gap_fill = False

    # -----------------------------------------------------------------
    # Primary classifier
    # -----------------------------------------------------------------
    if args.classifier in ("keyword", "biencoder"):
        bienc_args = []
        if args.sense_source == "spanishdict":
            bienc_args.extend(_spanishdict_args_local())
        if args.classifier == "keyword":
            bienc_args.append("--keyword-only")
        if args.force:
            bienc_args.append("--force")
        label = "Classifier: %s" % args.classifier
        run_step(label, "step_6b_assign_senses_local.py", bienc_args)
    else:
        # classifier == "gemini" — run step_6c classification, and optionally gap-fill
        gemini_args = []
        if args.sense_source == "spanishdict":
            gemini_args.extend(_spanishdict_args_gemini(args.gemini_model))
        if args.force:
            gemini_args.append("--force")
        if args.gemini_model:
            gemini_args.extend(["--gemini-model", args.gemini_model])
        if args.max_examples is not None:
            gemini_args.extend(["--max-examples", str(args.max_examples)])
        if not gap_fill:
            gemini_args.append("--skip-gap-fill")
        label = "Classifier: gemini" + (" + gap-fill" if gap_fill else "")
        run_step(label, "step_6c_assign_senses_gemini.py", gemini_args)

    # -----------------------------------------------------------------
    # Gap-fill pass (only needed when classifier != gemini; gemini path
    # handles it inline above).
    # -----------------------------------------------------------------
    if gap_fill and args.classifier != "gemini":
        gemini_args = ["--skip-classification"]
        if args.sense_source == "spanishdict":
            gemini_args.extend(_spanishdict_args_gemini(args.gemini_model))
        if args.force:
            gemini_args.append("--force")
        if args.gemini_model:
            gemini_args.extend(["--gemini-model", args.gemini_model])
        if args.max_examples is not None:
            gemini_args.extend(["--max-examples", str(args.max_examples)])
        run_step("Gap-fill (Gemini, zero-sense words only)",
                 "step_6c_assign_senses_gemini.py", gemini_args)

    out_rel = os.path.join("sense_assignments",
                           "spanishdict.json" if args.sense_source == "spanishdict" else "wiktionary.json")
    print("\nDone. All assignments in: %s" %
          os.path.join("Data", "Spanish", "layers", out_rel))


if __name__ == "__main__":
    main()
