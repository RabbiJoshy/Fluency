#!/usr/bin/env python3
"""Assign artist examples to the parallel SpanishDict sense menu."""

import argparse
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(os.path.dirname(os.path.dirname(SCRIPTS_DIR)), ".venv", "bin", "python3")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable


def main():
    parser = argparse.ArgumentParser(
        description="Assign artist examples to SpanishDict menu senses")
    from util_1a_artist_config import add_artist_arg
    add_artist_arg(parser)
    parser.add_argument("--keyword-only", action="store_true",
                        help="Use keyword overlap instead of the local bi-encoder")
    parser.add_argument("--force", action="store_true",
                        help="Rebuild assignments even if they already exist")
    parser.add_argument("--word", action="append", default=[],
                        help="Only process a specific surface word (repeatable)")
    args = parser.parse_args()

    cmd = [
        PYTHON,
        os.path.join(SCRIPTS_DIR, "step_6b_assign_senses_local.py"),
        "--artist-dir", args.artist_dir,
        "--sense-menu-file", "sense_menu/spanishdict.json",
        "--assignments-file", "sense_assignments/spanishdict.json",
        "--biencoder-method-name", "spanishdict-biencoder",
        "--keyword-method-name", "spanishdict-keyword",
        "--auto-method-name", "spanishdict-auto",
        "--menu-source-label", "spanishdict",
    ]
    if args.keyword_only:
        cmd.append("--keyword-only")
    if args.force:
        cmd.append("--force")
    for word in args.word:
        cmd.extend(["--word", word])

    raise SystemExit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
