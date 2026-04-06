#!/usr/bin/env python3
"""
Pipeline orchestrator for artist vocabulary pipelines.

Usage (from project root):
    .venv/bin/python3 Artists/run_pipeline.py --artist "Bad Bunny"
    .venv/bin/python3 Artists/run_pipeline.py --artist "Bad Bunny" --from-step 6
    .venv/bin/python3 Artists/run_pipeline.py --artist "Rosalía" --dry-run

API key is read from .env (GEMINI_API_KEY=...) or --api-key flag.
"""

import argparse
import json
import os
import subprocess
import sys
import time


def _load_dotenv():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


ARTISTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ARTISTS_DIR)
PYTHON = os.path.join(PROJECT_ROOT, ".venv", "bin", "python3")
SCRIPTS_DIR = os.path.join(ARTISTS_DIR, "scripts")

_load_dotenv()


def _base_args(artist_dir):
    return ["--artist-dir", artist_dir]

def _step_3_args(args, artist_dir):
    return _base_args(artist_dir) + [
        "--batch_glob", os.path.join(artist_dir, "data", "input", "batches", "batch_*.json"),
        "--out", os.path.join(artist_dir, "data", "word_counts", "vocab_evidence.json"),
        "--mwe-out", os.path.join(artist_dir, "data", "word_counts", "mwe_detected.json"),
    ]

def _step_3b_args(args, artist_dir):
    return _base_args(artist_dir) + ["--align"]

def _step_4_args(args, artist_dir):
    return _base_args(artist_dir)

def _step_5_args(args, artist_dir):
    return _base_args(artist_dir)

def _step_6_args(args, artist_dir):
    a = _base_args(artist_dir)
    if args.no_gemini:
        a.append("--no-gemini")
    else:
        a.extend(["--api-key", args.api_key])
    if args.words_only:
        a.append("--words-only")
    if args.reset:
        a.extend(["--reset-sentences", "--reset-words"])
    return a

def _step_7_args(args, artist_dir):
    return _base_args(artist_dir)

def _step_8_args(args, artist_dir):
    return _base_args(artist_dir)


FINALIZE_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "finalize_vocabulary.py")


def finalize_vocabulary(vocab_path):
    """Run the shared finalize script to split monolith into index + examples."""
    cmd = [PYTHON, FINALIZE_SCRIPT, "--input", vocab_path]
    print("\n  Finalizing: %s" % " ".join(cmd))
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode == 0


def build_steps(vocab_file):
    return [
        {"num": 3, "label": "Tokenise, count words, detect MWEs",
         "script": "3_count_words.py", "args_fn": _step_3_args,
         "input": None, "output": "data/word_counts/vocab_evidence.json", "needs_api_key": False},
        {"num": "3b", "label": "Scrape Genius translations",
         "script": "3b_scrape_translations.py", "args_fn": _step_3b_args,
         "input": None, "output": "data/input/translations/aligned_translations.json", "needs_api_key": False},
        {"num": 4, "label": "Detect proper nouns, interjections, English (local)",
         "script": "4_detect_proper_nouns.py", "args_fn": _step_4_args,
         "input": "data/word_counts/vocab_evidence.json",
         "output": "data/proper_nouns/detected_proper_nouns.json", "needs_api_key": False},
        {"num": 5, "label": "Merge elisions",
         "script": "5_merge_elisions.py", "args_fn": _step_5_args,
         "input": "data/word_counts/vocab_evidence.json",
         "output": "data/elision_merge/vocab_evidence_merged.json", "needs_api_key": False},
        {"num": 6, "label": "LLM word analysis (Gemini)",
         "script": "6_llm_analyze.py", "args_fn": _step_6_args,
         "input": "data/elision_merge/vocab_evidence_merged.json",
         "output": vocab_file, "needs_api_key": True},
        {"num": 7, "label": "Flag cognates",
         "script": "7_flag_cognates.py", "args_fn": _step_7_args,
         "input": vocab_file, "output": vocab_file, "needs_api_key": False},
        {"num": 8, "label": "Rerank",
         "script": "8_rerank.py", "args_fn": _step_8_args,
         "input": vocab_file, "output": vocab_file, "needs_api_key": False},
    ]


def parse_step(value, steps):
    for i, s in enumerate(steps):
        if str(s["num"]) == value:
            return i
    valid = ", ".join(str(s["num"]) for s in steps)
    print("ERROR: Unknown step '%s'. Valid steps: %s" % (value, valid))
    sys.exit(1)


def file_mtime(artist_dir, path):
    full = os.path.join(artist_dir, path) if not os.path.isabs(path) else path
    return os.path.getmtime(full) if os.path.exists(full) else 0


def run_step(step, args, artist_dir, dry_run=False):
    script_path = os.path.join(SCRIPTS_DIR, step["script"])
    extra_args = step["args_fn"](args, artist_dir)
    cmd = [PYTHON, script_path] + extra_args

    print("\n" + "=" * 60)
    print("Step %s: %s" % (step["num"], step["label"]))
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
    available = [name for name in sorted(os.listdir(ARTISTS_DIR))
                 if os.path.isfile(os.path.join(ARTISTS_DIR, name, "artist.json"))]

    parser = argparse.ArgumentParser(
        description="Artist vocabulary pipeline orchestrator",
        epilog="Available artists: %s" % ", ".join(available) if available else "")
    parser.add_argument("--artist", type=str, required=True)
    parser.add_argument("--api-key", type=str, default=os.environ.get("GEMINI_API_KEY", ""))
    parser.add_argument("--from-step", type=str, default=None)
    parser.add_argument("--to-step", type=str, default=None)
    parser.add_argument("--skip", type=str, nargs="*", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--no-gemini", action="store_true",
                        help="Skip Gemini API calls in step 6. Uses only Genius translations + overrides.")
    parser.add_argument("--words-only", action="store_true",
                        help="Step 6: run word analysis but skip sentence translation.")
    args = parser.parse_args()

    artist_dir = os.path.join(ARTISTS_DIR, args.artist)
    if not os.path.isdir(artist_dir):
        print("ERROR: Artist directory not found: %s" % artist_dir)
        sys.exit(1)

    with open(os.path.join(artist_dir, "artist.json")) as f:
        config = json.load(f)

    STEPS = build_steps(config["vocabulary_file"])

    start_idx = parse_step(args.from_step, STEPS) if args.from_step else 0
    end_idx = parse_step(args.to_step, STEPS) if args.to_step else len(STEPS) - 1
    skip_set = set(args.skip)
    steps_to_run = [s for s in STEPS[start_idx:end_idx + 1] if str(s["num"]) not in skip_set]

    needs_key = any(s["needs_api_key"] for s in steps_to_run) and not args.no_gemini
    if needs_key and not args.api_key and not args.dry_run:
        print("ERROR: Steps %s require --api-key (or use --no-gemini)" %
              ", ".join(str(s["num"]) for s in steps_to_run if s["needs_api_key"]))
        sys.exit(1)

    print("%s Pipeline" % config["name"])
    print("=" * 60)
    print("Artist dir: %s" % artist_dir)
    print("Steps: %s" % " -> ".join(str(s["num"]) for s in steps_to_run))
    if args.dry_run:
        print("Mode: DRY RUN")

    # Freshness check
    print("\n--- File freshness ---")
    for step in STEPS:
        marker = ">>>" if step in steps_to_run else "   "
        out_path = os.path.join(artist_dir, step["output"]) if step["output"] else None
        if out_path and os.path.exists(out_path):
            age_h = (time.time() - os.path.getmtime(out_path)) / 3600
            age_str = "%.0f min ago" % (age_h * 60) if age_h < 1 else "%.1fh ago" % age_h if age_h < 24 else "%.0fd ago" % (age_h / 24)
            print("%s Step %s: %-35s  %s" % (marker, step["num"], step["output"], age_str))
        else:
            print("%s Step %s: %-35s  (missing)" % (marker, step["num"], step["output"] or "(none)"))

    total_start = time.time()
    for step in steps_to_run:
        if not run_step(step, args, artist_dir, dry_run=args.dry_run):
            print("\nAborting — step %s failed." % step["num"])
            sys.exit(1)

    # Auto-finalize: clean translations + split into index + examples
    if not args.dry_run:
        vocab_path = os.path.join(artist_dir, config["vocabulary_file"])
        if os.path.exists(vocab_path):
            if not finalize_vocabulary(vocab_path):
                print("\nWarning: finalize step failed, split files may be stale.")

    print("\n" + "=" * 60)
    if args.dry_run:
        print("Dry run complete.")
    else:
        print("Pipeline complete! (%.1f minutes)" % ((time.time() - total_start) / 60))


if __name__ == "__main__":
    main()
