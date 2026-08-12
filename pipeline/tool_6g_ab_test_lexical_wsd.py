#!/usr/bin/env python3
"""Run the lexical-WSD gold benchmark in a randomized, review-blinded order.

The three candidates use the same v2 prompt contract; only the Flash-Lite model
changes. Candidate reports contain A/B/C labels rather than model or prompt ids.
The separate answer key should stay closed until the reports have been reviewed.

This tool never writes assignment layers or builds a deck. Without ``--dry-run``
it does make paid Gemini API calls through ``bench_sense_prompt.py``.
"""

import argparse
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCH = PROJECT_ROOT / "pipeline" / "bench_sense_prompt.py"
DEFAULT_OUTPUT = PROJECT_ROOT / "pipeline" / "reports" / "lexical_wsd_ab"
DEFAULT_CANDIDATES = (
    ("gemini-2.5-flash-lite", "sd-lexical-v2-g25"),
    ("gemini-3.1-flash-lite", "sd-lexical-v2-g31"),
    ("gemini-3.5-flash-lite", "sd-lexical-v2-g35"),
)


def _redact(text, label, model, prompt_id):
    return (text.replace(model, "candidate-%s" % label)
            .replace(prompt_id, "candidate-%s-prompt" % label))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artist-dir", default=None)
    ap.add_argument("--words", default=None,
                    help="Optional comma-separated subset of benchmark words.")
    ap.add_argument("--seed", type=int, default=20260811,
                    help="Stable randomization seed (default: %(default)s).")
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print each exact prompt without calling Gemini.")
    args = ap.parse_args()

    candidates = list(DEFAULT_CANDIDATES)
    random.Random(args.seed).shuffle(candidates)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    key = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "dry_run": args.dry_run,
        "warning": "Keep this file closed until candidate reports are reviewed.",
        "candidates": {},
    }
    failures = 0
    for label, (model, prompt_id) in zip("ABC", candidates):
        cmd = [sys.executable, str(BENCH),
               "--gemini-model", model, "--prompt-id", prompt_id]
        if args.artist_dir:
            cmd.extend(["--artist-dir", args.artist_dir])
        if args.words:
            cmd.extend(["--words", args.words])
        if args.dry_run:
            cmd.append("--dry-run")

        completed = subprocess.run(
            cmd, cwd=str(PROJECT_ROOT), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        report = _redact(completed.stdout, label, model, prompt_id)
        report_path = args.output_dir / ("candidate_%s.txt" % label)
        report_path.write_text(report, encoding="utf-8")
        key["candidates"][label] = {
            "model": model,
            "prompt_id": prompt_id,
            "exit_code": completed.returncode,
            "report": report_path.name,
        }
        if completed.returncode not in (0, 2):
            failures += 1
        print("candidate %s: report=%s exit=%d"
              % (label, report_path, completed.returncode))

    key_path = args.output_dir / "answer_key.json"
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print("answer key (open last): %s" % key_path)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
