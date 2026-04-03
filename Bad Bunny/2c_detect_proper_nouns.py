#!/usr/bin/env python3
"""
Step 2c: Bulk proper noun detection using Gemini.

Sends lyric lines in large batches and asks the LLM to identify all proper nouns
(people, brands, places) in context. Much more accurate than per-word analysis
since the LLM sees names in their natural sentence context.

Reads:  intermediates/2_vocab_evidence.json (for unique lines)
Writes: intermediates/2c_detected_proper_nouns.json

The output is consumed by step 4, which adds detected names to PROPER_NOUNS.

Usage (from project root):
    .venv/bin/python3 "Bad Bunny/2c_detect_proper_nouns.py" --api-key YOUR_KEY
"""

import json
import os
import sys
import time
import argparse
import re
import hashlib
from typing import Optional, Dict, List, Set

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_PATH = os.path.join(SCRIPT_DIR, "intermediates", "2_vocab_evidence.json")
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "intermediates", "2c_detected_proper_nouns.json")
PROGRESS_PATH = os.path.join(SCRIPT_DIR, "intermediates", "2c_propn_progress.json")

# ---------------------------------------------------------------------------
# Known proper nouns (seed set — these skip detection)
# ---------------------------------------------------------------------------
KNOWN_PROPER_NOUNS = frozenset({
    # Already in step 4's PROPER_NOUNS — no need to re-detect
    "luian", "balvin", "tainy", "anuel", "romeo", "becky", "nicky", "tego",
    "shakira", "yandel", "ozuna", "farru", "farruko", "drake", "diddy",
    "maluma", "rauw", "cardi", "karol", "myke", "rihanna", "natti", "noriel",
    "rvssian", "lavoe", "eladio", "ricky", "miko", "miky", "benny",
    "brytiago", "yovngchimi", "amenazzy", "pusho", "jeday", "juhn",
    "tokischa", "diplo", "alofoke",
    "benito", "bryant", "myers", "rocky", "kobe", "messi", "verstappen",
    "miami", "york", "santurce", "colombia", "bronx",
    "instagram", "netflix", "soundcloud", "snapchat", "tiktok", "twitter",
    "spotify", "youtube", "billboard",
    "gucci", "louis", "vuitton", "jordan", "bugatti", "lamborghini", "ferrari",
    "chanel", "nike", "versace", "prada", "iphone", "rolex", "balenciaga",
})

# Words that look like proper nouns but aren't — protect from false positives
NOT_PROPER_NOUNS = frozenset({
    # Religious / mythological
    "dios", "diablo", "santa", "cristo", "jesucristo", "jesus", "cupido",
    # Common Spanish nouns / adjectives wrongly flagged
    "amor", "muerte", "vida", "sol", "luna", "rey", "reina",
    "alto", "real", "don", "gran", "nueva", "nuevo", "buenos",
    "jefe", "querida", "sagrado", "puerto", "rico", "torre", "perla",
    "paleta", "mambo", "esclava", "perico", "marte", "papa", "inter",
    "capitolio", "bandera", "coronas", "combo", "condado", "frontón",
    "maduro", "menudo", "retro", "turbo", "visa", "mercedes",
    "más", "está", "sin", "el", "la", "da",
    # Common Spanish person references (not specific people)
    "mami", "papi", "mamita", "papito", "nena", "nene", "bebe",
    "negro", "negra", "morena", "moreno", "gringo", "gringa",
    "loco", "loca", "baby", "daddy", "mommy", "titi", "chavo",
    # English common words
    "all", "and", "the", "bad", "big", "boy", "boys", "boss",
    "code", "cold", "dam", "dumb", "dumber", "flow", "glue", "gone",
    "life", "magic", "new", "ring", "star", "sugar", "trap", "wild",
    "will", "spirit", "lady", "father", "cherry", "heat", "pin",
    "carbon", "met", "mill", "stone", "van", "pep", "bon",
    # Too short / junk
    "g", "l", "dm", "kr", "pr", "rd", "sb",
})

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
# Progress
# ---------------------------------------------------------------------------

def load_progress():
    # type: () -> Dict
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"batches_done": 0, "detected": []}


def save_progress(progress):
    # type: (Dict) -> None
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Step 2c: Bulk proper noun detection")
    parser.add_argument("--api-key", type=str, default=os.environ.get("GEMINI_API_KEY", ""),
                        help="Gemini API key (or set GEMINI_API_KEY env var)")
    parser.add_argument("--batch-size", type=int, default=250,
                        help="Lines per API request (default: 250)")
    parser.add_argument("--model", type=str, default="gemini-2.5-pro",
                        help="Gemini model (default: gemini-2.5-pro)")
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

    seen = set()  # type: Set[str]
    all_lines = []
    for entry in vocab_data:
        for ex in entry.get("examples", []):
            line = ex.get("line", "")
            if line and line not in seen:
                seen.add(line)
                all_lines.append(line)
    print("  %d unique lines from %d words" % (len(all_lines), len(vocab_data)))

    # Load progress
    if args.reset:
        progress = {"batches_done": 0, "detected": []}
        print("  Starting fresh (--reset)")
    else:
        progress = load_progress()
        print("  Progress: %d batches done, %d proper nouns detected so far" %
              (progress["batches_done"], len(progress["detected"])))

    all_detected = set(progress["detected"])  # type: Set[str]

    if args.refilter:
        # Re-apply updated NOT_PROPER_NOUNS / KNOWN_PROPER_NOUNS to cached results
        before = len(all_detected)
        all_detected = all_detected - NOT_PROPER_NOUNS - KNOWN_PROPER_NOUNS
        removed = before - len(all_detected)
        print("  Refilter: removed %d false positives, %d remain" % (removed, len(all_detected)))
    else:
        # Process in batches
        batch_size = args.batch_size
        total_batches = (len(all_lines) + batch_size - 1) // batch_size
        start_batch = progress["batches_done"]

        min_interval = 60.0 / args.rpm
        last_request_time = 0.0

        if start_batch >= total_batches:
            print("  All batches already processed!")
        else:
            remaining = total_batches - start_batch
            print("  %d batches remaining, ~%.0f minutes at %d RPM" %
                  (remaining, remaining / args.rpm, args.rpm))

            for batch_idx in range(start_batch, total_batches):
                batch_start = batch_idx * batch_size
                batch = all_lines[batch_start:batch_start + batch_size]
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

                if new_names:
                    print("  Found %d: %s" % (len(new_names), ", ".join(sorted(new_names)[:10])))
                    if len(new_names) > 10:
                        print("    ... +%d more" % (len(new_names) - 10))

                progress["batches_done"] = batch_idx + 1
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
