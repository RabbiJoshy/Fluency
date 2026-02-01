#!/usr/bin/env python3
"""
Input : Bad Bunny/vocab_word_lemma_preview.json
Output: Bad Bunny/vocabulary_app_preview.json

Rules:
- POS = meaning (sense) for now.
- meanings[].frequency is derived from pos_summary.pos_counts (NOT example counts).
- meanings[].examples contains at most MAX_EXAMPLES_PER_POS and all of them are translated
  (no untranslated empty placeholders).

Assumes input examples may include 'example_song_name' (optional).
"""

import json
import os
import time
from collections import defaultdict
from pathlib import Path

IN_PATH = Path("Bad Bunny/vocab_word_lemma_preview.json")
OUT_PATH = Path("Bad Bunny/vocabulary_app_preview.json")

MAX_ENTRIES = 1000
MAX_EXAMPLES_PER_POS = 3

# Translation settings
DO_TRANSLATE_WORDS = True
DO_TRANSLATE_EXAMPLES = True
TRANSLATE_SLEEP_SECONDS = 0.04
PRINT_EVERY_N_TRANSLATIONS = 5

translator = None
if DO_TRANSLATE_WORDS or DO_TRANSLATE_EXAMPLES:
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="es", target="en")
    except Exception:
        translator = None
        DO_TRANSLATE_WORDS = False
        DO_TRANSLATE_EXAMPLES = False


def parse_example_id(example_id: str) -> tuple[str, str]:
    if not example_id or ":" not in example_id:
        return "", ""
    song_id, line_no = example_id.split(":", 1)
    return song_id.strip(), line_no.strip()


_word_cache: dict[str, str] = {}
_line_cache: dict[str, str] = {}


def safe_translate(text: str, is_word: bool) -> str:
    if translator is None or not text:
        return ""
    cache = _word_cache if is_word else _line_cache
    if text in cache:
        return cache[text]
    try:
        out = translator.translate(text)
        out = (out or "").strip()
    except Exception:
        out = ""
    cache[text] = out
    return out


def build_evidence_maps(entry: dict):
    """
    Build:
    - id2line: example_id -> spanish line (from evidence)
    - id2songname: example_id -> song name (from matches)
    """
    # Get lines from evidence
    evidence = (entry.get("evidence") or {}).get("examples") or []
    id2line = {}
    for ex in evidence:
        ex_id = ex.get("id")
        line = ex.get("line")
        if ex_id and line:
            id2line[ex_id] = line

    # Get song names from matches (where example_song_name is stored)
    matches = entry.get("matches") or []
    id2songname = {}
    for m in matches:
        ex_id = m.get("example_id")
        song_name = m.get("example_song_name", "")
        if ex_id and song_name:
            id2songname[ex_id] = song_name

    return id2line, id2songname


def pos_to_example_ids(entry: dict) -> dict[str, list[str]]:
    """
    Route example_ids to POS buckets using matches[] (example_id -> pos).
    Dedup while preserving first-seen order.
    """
    matches = entry.get("matches") or []
    buckets: dict[str, list[str]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)

    for m in matches:
        ex_id = m.get("example_id")
        pos = m.get("pos") or "X"
        if not ex_id:
            continue
        if ex_id in seen[pos]:
            continue
        seen[pos].add(ex_id)
        buckets[pos].append(ex_id)

    # Fallback if no matches
    if not buckets:
        evidence = (entry.get("evidence") or {}).get("examples") or []
        ids = []
        s = set()
        for ex in evidence:
            ex_id = ex.get("id")
            if ex_id and ex_id not in s:
                s.add(ex_id)
                ids.append(ex_id)
        buckets["X"] = ids

    return dict(buckets)


def format_freq(x: float) -> str:
    # Keep app-friendly string formatting like "0.37"
    return f"{x:.2f}"


def compute_pos_frequencies(entry: dict) -> dict[str, float]:
    """
    frequency per POS = pos_counts[pos] / sum(pos_counts)
    If pos_counts missing, return {} and caller uses 1.00.
    """
    pos_counts = (entry.get("pos_summary") or {}).get("pos_counts") or {}
    if not pos_counts:
        return {}
    total = sum(pos_counts.values())
    if total <= 0:
        return {}
    return {pos: (count / total) for pos, count in pos_counts.items()}


def compute_most_frequent_flags(app_entries: list[dict]) -> None:
    grouped = defaultdict(list)
    for i, e in enumerate(app_entries):
        grouped[e["word"]].append((i, e))

    for _, items in grouped.items():
        best_j = max(
            range(len(items)),
            key=lambda j: (items[j][1].get("_meta_match_count", 0), -items[j][0])
        )
        for j, (_, e) in enumerate(items):
            e["most_frequent_lemma_instance"] = (j == best_j)

    for e in app_entries:
        e.pop("_meta_match_count", None)


def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Input not found: {IN_PATH}")

    raw = json.loads(IN_PATH.read_text(encoding="utf-8"))
    subset = raw[:MAX_ENTRIES]

    out = []
    translated = 0
    start = time.perf_counter()

    for rank, entry in enumerate(subset, start=1):
        word = str(entry.get("word", "")).strip()
        lemma = str(entry.get("lemma", "")).strip()

        lang_flags = entry.get("language_flags") or {}
        is_english = bool(lang_flags.get("is_english", False))

        id2line, id2songname = build_evidence_maps(entry)
        pos_buckets = pos_to_example_ids(entry)
        pos_freqs = compute_pos_frequencies(entry)

        # Translate the word once (skip if English-flagged)
        word_translation = ""
        if DO_TRANSLATE_WORDS and not is_english:
            word_translation = safe_translate(word, is_word=True)
            translated += 1
            if translated % PRINT_EVERY_N_TRANSLATIONS == 0:
                elapsed = time.perf_counter() - start
                print(f"⏱ {translated} translations | {elapsed:.1f}s")
            time.sleep(TRANSLATE_SLEEP_SECONDS)

        meanings = []
        # Order meanings by descending pos_counts if available; else by bucket size
        pos_counts = (entry.get("pos_summary") or {}).get("pos_counts") or {}
        if pos_counts:
            pos_order = [p for p, _ in sorted(pos_counts.items(), key=lambda kv: kv[1], reverse=True)]
        else:
            pos_order = [p for p, _ in sorted(pos_buckets.items(), key=lambda kv: len(kv[1]), reverse=True)]

        for pos in pos_order:
            ex_ids = pos_buckets.get(pos, [])
            examples = []
            seen_lines = set()

            for ex_id in ex_ids:
                line = (id2line.get(ex_id) or "").strip()
                if not line or line in seen_lines:
                    continue
                seen_lines.add(line)

                song_id, _ = parse_example_id(ex_id)

                ex_obj = {
                    "song": song_id,
                    "song_name": id2songname.get(ex_id, "") or "",
                    "spanish": line,
                    "english": ""
                }

                # Translate this example (unless english-flagged)
                if DO_TRANSLATE_EXAMPLES and not is_english:
                    ex_obj["english"] = safe_translate(line, is_word=False)
                    translated += 1
                    if translated % PRINT_EVERY_N_TRANSLATIONS == 0:
                        elapsed = time.perf_counter() - start
                        print(f"⏱ {translated} translations | {elapsed:.1f}s")
                    time.sleep(TRANSLATE_SLEEP_SECONDS)

                examples.append(ex_obj)
                if len(examples) >= MAX_EXAMPLES_PER_POS:
                    break

            # If we have no examples for this POS (rare), skip it
            if not examples:
                continue

            freq = pos_freqs.get(pos, 1.0 if len(pos_order) == 1 else 0.0)

            meanings.append({
                "pos": pos,
                "translation": word_translation,
                "frequency": format_freq(freq),
                "examples": examples
            })

        match_count = (entry.get("pos_summary") or {}).get("match_count", 0)

        out.append({
            "rank": rank,
            "word": word,
            "lemma": lemma,
            "meanings": meanings,
            "most_frequent_lemma_instance": False,  # post-pass
            "is_english": is_english,
            "_meta_match_count": match_count
        })

    compute_most_frequent_flags(out)

    os.makedirs(OUT_PATH.parent, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Wrote {len(out)} entries → {OUT_PATH}")


if __name__ == "__main__":
    main()
