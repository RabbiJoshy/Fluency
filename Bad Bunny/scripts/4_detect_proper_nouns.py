#!/usr/bin/env python3
"""
Step 4: Bulk proper noun detection using Gemini.

Sends lyric lines in batches and asks the LLM to identify all proper nouns
(people, brands, places) in context. Uses content-based progress tracking
so only new/unseen lines are processed on re-runs.

Reads:  data/step_3/vocab_evidence.json (for unique lines)
Writes: data/step_4/detected_proper_nouns.json

The output is consumed by step 6, which adds detected names to PROPER_NOUNS.

Usage (from project root):
    .venv/bin/python3 "Bad Bunny/scripts/4_detect_proper_nouns.py"
    .venv/bin/python3 "Bad Bunny/scripts/4_detect_proper_nouns.py" --batch-size 30
    .venv/bin/python3 "Bad Bunny/scripts/4_detect_proper_nouns.py" --refilter

API key is read from .env (GEMINI_API_KEY=...) or --api-key flag.
"""

import json
import os
import sys
import time
import argparse
import re
import hashlib
from typing import Optional, Dict, List, Set


def _load_dotenv():
    """Load .env file from project root if it exists."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_DIR = os.path.dirname(SCRIPT_DIR)  # scripts/ -> Bad Bunny/
INPUT_PATH = os.path.join(PIPELINE_DIR, "data", "step_3", "vocab_evidence.json")
OUTPUT_PATH = os.path.join(PIPELINE_DIR, "data", "step_4", "detected_proper_nouns.json")
PROGRESS_PATH = os.path.join(PIPELINE_DIR, "data", "step_4", "propn_progress.json")

# ---------------------------------------------------------------------------
# Known proper nouns / not-proper-nouns (loaded from JSON config)
# ---------------------------------------------------------------------------
def _load_json(filename):
    path = os.path.join(PIPELINE_DIR, "data", "step_4", filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

KNOWN_PROPER_NOUNS = frozenset(_load_json("known_proper_nouns.json"))
NOT_PROPER_NOUNS = frozenset(_load_json("not_proper_nouns.json"))

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
PROPN_PROMPT = (
    "From these numbered Caribbean Spanish/English lyric lines, extract every "
    "proper noun (person names, artist names, brand names, place names, "
    "song titles, album names, platform names).\n"
    "Return a JSON array of unique lowercase strings: [\"jennifer\",\"lopez\",\"miami\"]\n"
    "Include first names AND last names as separate entries.\n"
    "Do NOT include: common Spanish words, generic nouns, slang terms, "
    "or words like dios/amor/mami/baby even when capitalized.\n"
    "Only include actual named entities.\n\n"
)


# ---------------------------------------------------------------------------
# Gemini API
# ---------------------------------------------------------------------------

def call_gemini(prompt, api_key, model="gemini-2.5-flash-lite"):
    # type: (str, str, str) -> Optional[str]
    from google import genai

    client = genai.Client(api_key=api_key)
    config = {
        "temperature": 0.1,
        "max_output_tokens": 4096,
        "response_mime_type": "application/json",
    }

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        return response.text
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            print("  [RATE LIMITED] Waiting 15s...", file=sys.stderr)
            time.sleep(15)
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )
                return response.text
            except Exception as e2:
                print("  [ERROR] Retry failed: %s" % e2, file=sys.stderr)
                return None
        print("  [ERROR] Gemini call failed: %s" % e, file=sys.stderr)
        return None


def parse_propn_response(text):
    # type: (Optional[str]) -> List[str]
    if not text:
        return []

    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl >= 0:
            text = text[first_nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()

    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0:
        return []

    json_str = text[start:end + 1]
    json_str = re.sub(r',\s*]', ']', json_str)

    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError as e:
        print("  [WARN] JSON parse failed: %s" % e, file=sys.stderr)
        return []

    results = []
    for item in raw:
        if isinstance(item, str):
            w = item.strip().lower()
            if w and w not in NOT_PROPER_NOUNS:
                results.append(w)
    return results


# ---------------------------------------------------------------------------
# Line hashing for content-based progress
# ---------------------------------------------------------------------------

def hash_line(line):
    # type: (str) -> str
    """Short hash of a line for progress tracking."""
    return hashlib.md5(line.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Progress (content-based)
# ---------------------------------------------------------------------------

def load_progress():
    # type: () -> Dict
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Migrate from old batch-index format to content-based format
        if "seen_hashes" not in data:
            print("  Migrating progress to content-based tracking...")
            data["seen_hashes"] = []
            # Old format had batches_done — we can't recover which lines were seen,
            # but we keep the detected proper nouns. Mark as needing full rescan.
            data.pop("batches_done", None)
        return data

    return {"seen_hashes": [], "detected": []}


def save_progress(progress):
    # type: (Dict) -> None
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Step 4: Bulk proper noun detection")
    parser.add_argument("--api-key", type=str, default=os.environ.get("GEMINI_API_KEY", ""),
                        help="Gemini API key (or set GEMINI_API_KEY env var)")
    parser.add_argument("--batch-size", type=int, default=50,
                        help="Lines per API request (default: 50)")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash-lite",
                        help="Gemini model (default: gemini-2.5-flash-lite)")
    parser.add_argument("--reset", action="store_true",
                        help="Ignore saved progress and start fresh")
    parser.add_argument("--rpm", type=int, default=200,
                        help="Max requests per minute (default: 200)")
    parser.add_argument("--refilter", action="store_true",
                        help="Re-apply NOT_PROPER_NOUNS filter to cached progress (no API calls)")
    args = parser.parse_args()

    if not args.refilter and not args.api_key:
        print("ERROR: Provide --api-key or set GEMINI_API_KEY environment variable")
        sys.exit(1)

    # Load input — collect unique lines
    print("Loading %s..." % INPUT_PATH)
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        vocab_data = json.load(f)

    seen_lines = set()  # type: Set[str]
    all_lines = []
    for entry in vocab_data:
        for ex in entry.get("examples", []):
            line = ex.get("line", "")
            if line and line not in seen_lines:
                seen_lines.add(line)
                all_lines.append(line)
    print("  %d unique lines from %d words" % (len(all_lines), len(vocab_data)))

    # Load progress
    if args.reset:
        progress = {"seen_hashes": [], "detected": []}
        print("  Starting fresh (--reset)")
    else:
        progress = load_progress()
        print("  Progress: %d lines already processed, %d proper nouns detected so far" %
              (len(progress.get("seen_hashes", [])), len(progress["detected"])))

    all_detected = set(progress["detected"])  # type: Set[str]
    seen_hashes = set(progress.get("seen_hashes", []))  # type: Set[str]

    if args.refilter:
        # Re-apply updated NOT_PROPER_NOUNS / KNOWN_PROPER_NOUNS to cached results
        before = len(all_detected)
        all_detected = all_detected - NOT_PROPER_NOUNS - KNOWN_PROPER_NOUNS
        removed = before - len(all_detected)
        print("  Refilter: removed %d false positives, %d remain" % (removed, len(all_detected)))
    else:
        # Find lines that haven't been processed yet
        new_lines = []
        for line in all_lines:
            h = hash_line(line)
            if h not in seen_hashes:
                new_lines.append(line)

        if not new_lines:
            print("  All %d lines already processed — nothing new to do." % len(all_lines))
        else:
            print("  %d new lines to process (out of %d total)" % (len(new_lines), len(all_lines)))

            # Process in batches
            batch_size = args.batch_size
            total_batches = (len(new_lines) + batch_size - 1) // batch_size

            min_interval = 60.0 / args.rpm
            last_request_time = 0.0

            print("  %d batches of %d lines, ~%.0f minutes at %d RPM" %
                  (total_batches, batch_size, total_batches / args.rpm, args.rpm))

            for batch_idx in range(total_batches):
                batch_start = batch_idx * batch_size
                batch = new_lines[batch_start:batch_start + batch_size]
                batch_num = batch_idx + 1

                preview = batch[0][:50]
                print("[%d/%d] %d lines (%s...)" % (batch_num, total_batches, len(batch), preview))

                # Rate limiting
                now = time.time()
                wait = min_interval - (now - last_request_time)
                if wait > 0:
                    time.sleep(wait)

                # Build prompt
                parts = [PROPN_PROMPT]
                for i, line in enumerate(batch, 1):
                    parts.append("%d.%s" % (i, line))
                prompt = "\n".join(parts)

                last_request_time = time.time()
                response_text = call_gemini(prompt, args.api_key, model=args.model)
                detected = parse_propn_response(response_text)

                # Filter out known and protected words
                new_names = [w for w in detected if w not in KNOWN_PROPER_NOUNS and w not in NOT_PROPER_NOUNS]
                all_detected.update(new_names)

                # Mark these lines as processed
                for line in batch:
                    seen_hashes.add(hash_line(line))

                if new_names:
                    print("  Found %d: %s" % (len(new_names), ", ".join(sorted(new_names)[:10])))
                    if len(new_names) > 10:
                        print("    ... +%d more" % (len(new_names) - 10))

                progress["seen_hashes"] = sorted(seen_hashes)
                progress["detected"] = sorted(all_detected)
                save_progress(progress)

    # Write final output
    # Cross-reference with actual vocabulary words
    vocab_words = set()  # type: Set[str]
    for entry in vocab_data:
        vocab_words.add(entry["word"].lower())

    # Only keep detected proper nouns that actually appear as vocabulary entries
    in_vocab = sorted(all_detected & vocab_words)
    not_in_vocab = sorted(all_detected - vocab_words)

    output = {
        "proper_nouns": in_vocab,
        "proper_nouns_not_in_vocab": not_in_vocab,
        "total_detected": len(all_detected),
        "in_vocab_count": len(in_vocab),
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\nDone! Detected %d proper nouns (%d in vocabulary)" %
          (len(all_detected), len(in_vocab)))
    print("  Wrote %s" % OUTPUT_PATH)
    if in_vocab:
        print("  Sample: %s" % ", ".join(in_vocab[:20]))


if __name__ == "__main__":
    main()
