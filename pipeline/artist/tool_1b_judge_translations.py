#!/usr/bin/env python3
"""Judge Google Translate sentence translations using Gemini, re-translate bad ones.

Reads example_translations.json, batches Spanish+English pairs to Gemini for
quality scoring, then re-translates lines that score below a threshold.

Usage (from project root):
    .venv/bin/python3 pipeline/artist/tool_1b_judge_translations.py --artist-dir "Artists/Young Miko"
    .venv/bin/python3 pipeline/artist/tool_1b_judge_translations.py --artist-dir "Artists/Young Miko" --judge-only
    .venv/bin/python3 pipeline/artist/tool_1b_judge_translations.py --artist-dir "Artists/Young Miko" --threshold 3
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(__file__))
from util_1a_artist_config import add_artist_arg, load_artist_config, load_dotenv_from_project_root

load_dotenv_from_project_root()

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

JUDGE_PROMPT = (
    "You are a Spanish-English translation quality judge.\n"
    "Below are numbered Spanish lyric lines with their English translations.\n"
    "Rate each translation 1-5:\n"
    "  5 = perfect natural translation\n"
    "  4 = good, minor style issues\n"
    "  3 = acceptable, meaning preserved but awkward\n"
    "  2 = poor, meaning partially lost or wrong\n"
    "  1 = bad, mistranslation or nonsensical\n"
    "Pay special attention to:\n"
    "  - Slang and idioms that were translated too literally\n"
    "  - Caribbean/reggaeton dialect (pa'=para, to'=todo, ere'=eres, -a'o/-í'o=-ado/-ido)\n"
    "  - Tone preservation (street, romantic, boastful, etc.)\n"
    "  - Meaning accuracy\n"
    "Return JSON: {\"1\":{\"score\":N},\"2\":{\"score\":N},...}\n"
    "Only include the score. Be strict — literal Google Translate output that misses "
    "slang or idiom should score 2 or below.\n\n"
)

TRANSLATE_PROMPT = (
    "Translate each numbered Spanish lyric line to natural English.\n"
    "Caribbean/reggaeton dialect: ere'=eres, to'=todo, pa'=para, na'=nada, -a'o/-í'o = -ado/-ido.\n"
    "Return a JSON object mapping line numbers to translations: {\"1\":\"...\",\"2\":\"...\"}\n"
    "Keep translations natural and colloquial. Preserve the tone (street, romantic, etc.).\n\n"
)

# ---------------------------------------------------------------------------
# Gemini API (duplicated from 6_llm_analyze.py for independence)
# ---------------------------------------------------------------------------


def call_gemini(prompt, api_key, model="gemini-2.5-flash-lite", json_mode=True):
    # type: (str, str, str, bool) -> Optional[str]
    from google import genai

    client = genai.Client(api_key=api_key)
    config = {
        "temperature": 0.1,
        "max_output_tokens": 8192,
    }
    if json_mode:
        config["response_mime_type"] = "application/json"

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
                print("  [ERROR] Gemini retry failed: %s" % e2, file=sys.stderr)
                return None
        print("  [ERROR] Gemini call failed: %s" % e, file=sys.stderr)
        return None


def strip_markdown_fences(text):
    # type: (str) -> str
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        text = text[first_nl + 1:] if first_nl >= 0 else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


# ---------------------------------------------------------------------------
# Judge logic
# ---------------------------------------------------------------------------


def build_judge_prompt(batch):
    # type: (List[Tuple[str, str]]) -> str
    """Build a judge prompt from (spanish, english) pairs."""
    parts = [JUDGE_PROMPT]
    for i, (spanish, english) in enumerate(batch, 1):
        parts.append("%d. %s | %s" % (i, spanish, english))
    return "\n".join(parts)


def parse_judge_response(text, batch):
    # type: (Optional[str], List[Tuple[str, str]]) -> Dict[str, int]
    """Parse judge response, return {spanish_line: score}."""
    if not text:
        return {}

    text = strip_markdown_fences(text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return {}

    json_str = text[start:end + 1]
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError as e:
        print("  [WARN] Judge JSON parse failed: %s" % e, file=sys.stderr)
        return {}

    result = {}  # type: Dict[str, int]
    for k, v in raw.items():
        try:
            idx = int(k) - 1
            if 0 <= idx < len(batch):
                spanish = batch[idx][0]
                score = v if isinstance(v, int) else v.get("score", 3)
                result[spanish] = int(score)
        except (ValueError, TypeError, AttributeError):
            pass
    return result


# ---------------------------------------------------------------------------
# Re-translation logic
# ---------------------------------------------------------------------------


def build_translate_prompt(lines):
    # type: (List[str]) -> str
    parts = [TRANSLATE_PROMPT]
    for i, line in enumerate(lines, 1):
        parts.append("%d.%s" % (i, line))
    return "\n".join(parts)


def parse_translate_response(text, lines):
    # type: (Optional[str], List[str]) -> Dict[str, str]
    if not text:
        return {}

    text = strip_markdown_fences(text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return {}

    json_str = text[start:end + 1]
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)

    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError as e:
        print("  [WARN] Translate JSON parse failed: %s" % e, file=sys.stderr)
        return {}

    result = {}  # type: Dict[str, str]
    for k, v in raw.items():
        try:
            idx = int(k) - 1
            if 0 <= idx < len(lines):
                result[lines[idx]] = str(v)
        except (ValueError, TypeError):
            pass
    return result


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def compute_prompt_hash(prompt_text):
    # type: (str) -> str
    return hashlib.sha256(prompt_text.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Judge Google Translate translations, re-translate bad ones via Gemini")
    add_artist_arg(parser)
    parser.add_argument("--api-key", type=str,
                        default=os.environ.get("GEMINI_API_KEY", ""),
                        help="Gemini API key (or set GEMINI_API_KEY env var)")
    parser.add_argument("--model", type=str, default="gemini-2.5-flash-lite",
                        help="Gemini model (default: gemini-2.5-flash-lite)")
    parser.add_argument("--threshold", type=int, default=2,
                        help="Re-translate lines scoring <= this (default: 2)")
    parser.add_argument("--judge-batch-size", type=int, default=80,
                        help="Lines per judge API call (default: 80)")
    parser.add_argument("--translate-batch-size", type=int, default=40,
                        help="Lines per re-translation API call (default: 40)")
    parser.add_argument("--rpm", type=int, default=200,
                        help="Max requests per minute (default: 200)")
    parser.add_argument("--judge-only", action="store_true",
                        help="Score translations but don't re-translate flagged ones")
    parser.add_argument("--source-filter", type=str, default=None,
                        help="Only judge lines from this source (e.g. 'google')")
    parser.add_argument("--reset", action="store_true",
                        help="Ignore cached judge scores and re-judge everything")
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: No Gemini API key. Set GEMINI_API_KEY or use --api-key.", file=sys.stderr)
        sys.exit(1)

    artist_dir = args.artist_dir
    config = load_artist_config(artist_dir)
    artist_name = config["name"]

    # Paths
    translations_path = os.path.join(artist_dir, "data", "layers", "example_translations.json")
    scores_path = os.path.join(artist_dir, "data", "layers", "translation_scores.json")
    judge_cache_path = os.path.join(artist_dir, "data", "llm_analysis", "translation_judge.json")

    # Load translations
    translations = load_json(translations_path)
    if not translations:
        print("ERROR: No example_translations.json at %s" % translations_path)
        sys.exit(1)

    # Filter to judgeable lines
    to_judge = []  # type: List[Tuple[str, str]]
    for spanish, entry in translations.items():
        if not isinstance(entry, dict):
            continue
        english = entry.get("english", "")
        source = entry.get("source", "")
        if not english:
            continue
        if args.source_filter and source != args.source_filter:
            continue
        to_judge.append((spanish, english))

    print("[%s] %d lines to judge (from %d total translations)" % (
        artist_name, len(to_judge), len(translations)))

    # Load judge cache
    judge_cache = load_json(judge_cache_path) if not args.reset else {}
    prompt_hash = compute_prompt_hash(JUDGE_PROMPT)
    if judge_cache.get("_prompt_hash") != prompt_hash:
        print("  Judge prompt changed — resetting cache")
        judge_cache = {"_prompt_hash": prompt_hash}

    # Filter out already-judged lines
    unjudged = [(s, e) for s, e in to_judge if s not in judge_cache]
    print("  %d already judged, %d remaining" % (len(to_judge) - len(unjudged), len(unjudged)))

    # ---- Phase 1: Judge ----
    min_interval = 60.0 / args.rpm
    last_request_time = 0.0

    if unjudged:
        print("\n--- Phase 1: Judging translations ---")
        batches = [unjudged[i:i + args.judge_batch_size]
                   for i in range(0, len(unjudged), args.judge_batch_size)]
        print("  %d batches of ~%d lines" % (len(batches), args.judge_batch_size))

        for batch_idx, batch in enumerate(batches):
            now = time.time()
            wait = min_interval - (now - last_request_time)
            if wait > 0:
                time.sleep(wait)

            prompt = build_judge_prompt(batch)
            last_request_time = time.time()
            response = call_gemini(prompt, args.api_key, model=args.model)
            scores = parse_judge_response(response, batch)

            for spanish, score in scores.items():
                judge_cache[spanish] = score

            parsed = len(scores)
            expected = len(batch)
            if parsed < expected:
                print("  Batch %d/%d: %d/%d parsed (retrying missing with half-batch)" % (
                    batch_idx + 1, len(batches), parsed, expected))
                # Retry unparsed lines
                missing = [(s, e) for s, e in batch if s not in scores]
                if missing:
                    half = len(missing) // 2 or 1
                    for sub_batch in [missing[:half], missing[half:]]:
                        if not sub_batch:
                            continue
                        now = time.time()
                        wait = min_interval - (now - last_request_time)
                        if wait > 0:
                            time.sleep(wait)
                        prompt = build_judge_prompt(sub_batch)
                        last_request_time = time.time()
                        response = call_gemini(prompt, args.api_key, model=args.model)
                        retry_scores = parse_judge_response(response, sub_batch)
                        for spanish, score in retry_scores.items():
                            judge_cache[spanish] = score
            else:
                print("  Batch %d/%d: %d lines scored" % (
                    batch_idx + 1, len(batches), parsed))

            # Save progress periodically
            if (batch_idx + 1) % 5 == 0 or batch_idx == len(batches) - 1:
                save_json(judge_cache_path, judge_cache)

        save_json(judge_cache_path, judge_cache)

    # ---- Write scores layer ----
    scores_layer = {}  # type: Dict[str, Dict]
    for spanish, score in judge_cache.items():
        if spanish.startswith("_"):
            continue
        if isinstance(score, int):
            scores_layer[spanish] = {"score": score}

    save_json(scores_path, scores_layer)

    # ---- Stats ----
    score_counts = {}  # type: Dict[int, int]
    for entry in scores_layer.values():
        s = entry["score"]
        score_counts[s] = score_counts.get(s, 0) + 1

    print("\nScore distribution:")
    for s in sorted(score_counts):
        print("  %d: %d lines (%.1f%%)" % (
            s, score_counts[s], 100.0 * score_counts[s] / len(scores_layer) if scores_layer else 0))

    flagged = [spanish for spanish, entry in scores_layer.items()
               if entry["score"] <= args.threshold]
    print("\n%d lines flagged (score <= %d)" % (len(flagged), args.threshold))

    if args.judge_only or not flagged:
        if args.judge_only:
            print("(--judge-only: skipping re-translation)")
        print("Done.")
        return

    # ---- Phase 2: Re-translate flagged lines ----
    print("\n--- Phase 2: Re-translating %d flagged lines ---" % len(flagged))
    batches = [flagged[i:i + args.translate_batch_size]
               for i in range(0, len(flagged), args.translate_batch_size)]
    print("  %d batches of ~%d lines" % (len(batches), args.translate_batch_size))

    retranslated = 0
    for batch_idx, batch in enumerate(batches):
        now = time.time()
        wait = min_interval - (now - last_request_time)
        if wait > 0:
            time.sleep(wait)

        prompt = build_translate_prompt(batch)
        last_request_time = time.time()
        response = call_gemini(prompt, args.api_key, model=args.model)
        new_translations = parse_translate_response(response, batch)

        for spanish, english in new_translations.items():
            if english and spanish in translations:
                old = translations[spanish].get("english", "")
                translations[spanish]["english"] = english
                translations[spanish]["source"] = "gemini"
                retranslated += 1

        parsed = len(new_translations)
        if parsed < len(batch):
            print("  Batch %d/%d: %d/%d re-translated" % (
                batch_idx + 1, len(batches), parsed, len(batch)))
        else:
            print("  Batch %d/%d: %d lines re-translated" % (
                batch_idx + 1, len(batches), parsed))

    # Write updated translations
    save_json(translations_path, translations)
    print("\n%d lines re-translated and saved to example_translations.json" % retranslated)
    print("Done.")


if __name__ == "__main__":
    main()
