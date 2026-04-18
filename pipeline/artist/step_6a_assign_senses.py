#!/usr/bin/env python3
"""
Step 6: Assign artist lyric examples to word senses.

Single entry point. One classifier runs per invocation across every
learnable word (non-excluded, non-clitic-merge). Optionally a Gemini
gap-fill pass runs on zero-sense words.

Flags:
    --classifier {keyword, biencoder, gemini}  (required)
    --gap-fill / --no-gap-fill                 (default: on for gemini, off otherwise)
    --sense-source {wiktionary, spanishdict}   (default: spanishdict)
    --max-examples N                           (Gemini per-word cap, default 10)
    --force                                    (re-classify everything)
    --gemini-model MODEL                       (default: gemini-2.5-flash-lite)

Usage:
    .venv/bin/python3 pipeline/artist/step_6a_assign_senses.py \
        --artist-dir "Artists/spanish/Bad Bunny" --classifier gemini
"""

import argparse
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.dirname(SCRIPTS_DIR)
PYTHON = os.path.join(os.path.dirname(PIPELINE_DIR), ".venv", "bin", "python3")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable


def run_step(label, script, args):
    cmd = [PYTHON, os.path.join(PIPELINE_DIR, script)] + args
    print("\n" + "=" * 60)
    print(label)
    print("=" * 60)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("ERROR: %s failed (exit code %d)" % (script, result.returncode))
        sys.exit(result.returncode)


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
    parser = argparse.ArgumentParser(description="Step 6: Assign senses (artist mode)")

    sys.path.insert(0, SCRIPTS_DIR)
    from util_1a_artist_config import add_artist_arg, load_dotenv_from_project_root
    load_dotenv_from_project_root()
    add_artist_arg(parser)

    parser.add_argument("--classifier", choices=["keyword", "biencoder", "gemini"],
                        required=True,
                        help="Primary classifier (one only).")
    gf = parser.add_mutually_exclusive_group()
    gf.add_argument("--gap-fill", dest="gap_fill", action="store_true", default=None,
                    help="Run Gemini gap-fill (default: on for gemini, off otherwise).")
    gf.add_argument("--no-gap-fill", dest="gap_fill", action="store_false",
                    help="Skip gap-fill.")
    parser.add_argument("--sense-source", choices=["wiktionary", "spanishdict"],
                        default="spanishdict")
    parser.add_argument("--max-examples", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--gemini-model", default="gemini-2.5-flash-lite")
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    has_api_key = bool(os.environ.get("GEMINI_API_KEY"))

    gap_fill = args.gap_fill
    if gap_fill is None:
        gap_fill = (args.classifier == "gemini")

    if (args.classifier == "gemini" or gap_fill) and not has_api_key:
        if args.classifier == "gemini":
            print("ERROR: --classifier gemini requires GEMINI_API_KEY")
            sys.exit(1)
        print("WARNING: gap-fill requires GEMINI_API_KEY; skipping gap-fill.")
        gap_fill = False

    # -----------------------------------------------------------------
    # Primary classifier
    # -----------------------------------------------------------------
    if args.classifier in ("keyword", "biencoder"):
        bienc_args = ["--artist-dir", artist_dir]
        if args.sense_source == "spanishdict":
            bienc_args.extend(_spanishdict_args_local())
        elif args.sense_source == "wiktionary":
            # If the artist has a per-language Wiktionary menu on disk
            # (e.g. French from kaikki-french via step_5c), point step_6b
            # at it so it skips loading raw kaikki-spanish + the normal-mode
            # Spanish shared menu. If the artist menu is absent, we fall
            # through to step_6b's Spanish-default behaviour (unchanged).
            _artist_wikt_menu = os.path.join(
                artist_dir, "data", "layers", "sense_menu", "wiktionary.json"
            )
            if os.path.exists(_artist_wikt_menu):
                bienc_args.extend([
                    "--sense-menu-file", "sense_menu/wiktionary.json",
                ])
        if args.classifier == "keyword":
            bienc_args.append("--keyword-only")
        if args.force:
            bienc_args.append("--force")
        run_step("Classifier: %s" % args.classifier,
                 "step_6b_assign_senses_local.py", bienc_args)
    else:
        gemini_args = ["--artist-dir", artist_dir]
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
        run_step("Classifier: gemini" + (" + gap-fill" if gap_fill else ""),
                 "step_6c_assign_senses_gemini.py", gemini_args)

    # -----------------------------------------------------------------
    # Gap-fill pass (only when classifier != gemini)
    # -----------------------------------------------------------------
    if gap_fill and args.classifier != "gemini":
        gemini_args = ["--artist-dir", artist_dir, "--skip-classification"]
        if args.sense_source == "spanishdict":
            gemini_args.extend(_spanishdict_args_gemini(args.gemini_model))
        if args.force:
            gemini_args.append("--force")
        if args.gemini_model:
            gemini_args.extend(["--gemini-model", args.gemini_model])
        if args.max_examples is not None:
            gemini_args.extend(["--max-examples", str(args.max_examples)])
        run_step("Gap-fill (zero-sense words only)",
                 "step_6c_assign_senses_gemini.py", gemini_args)

    print("\nDone. All assignments in: %s" %
          os.path.join(artist_dir, "data", "layers",
                       "sense_assignments",
                       "spanishdict.json" if args.sense_source == "spanishdict" else "wiktionary.json"))


if __name__ == "__main__":
    main()
