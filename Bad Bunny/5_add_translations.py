#!/usr/bin/env python3
"""
Input : Bad Bunny/intermediates/4_spacy_output.json
Output: Bad Bunny/BadBunnyvocabulary.json

Rules:
- POS = meaning (sense) for now.
- meanings[].frequency is derived from pos_summary.pos_counts (NOT example counts).
- meanings[].examples contains at most MAX_EXAMPLES_PER_POS.
  In CACHE_ONLY mode, examples may have empty english fields (filled by 4b).

Assumes input examples may include 'example_song_name' (optional).
"""

import json
import os
import time
from collections import defaultdict
from pathlib import Path

IN_PATH = Path("Bad Bunny/intermediates/4_spacy_output.json")
OUT_PATH = Path("Bad Bunny/BadBunnyvocabulary.json")
OLD_VOCAB_PATH = Path("Bad Bunny/intermediates/old_vocabulary_cache.json")

MAX_ENTRIES = None  # process all entries
MAX_EXAMPLES_PER_POS = 1

# Translation settings
# Cache-only mode: use pre-loaded translations, no API calls.
# Run 6_fill_translation_gaps.py afterward to fill gaps.
DO_TRANSLATE_WORDS = True
DO_TRANSLATE_EXAMPLES = True
CACHE_ONLY = True           # <-- set False to allow live API calls
TRANSLATE_SLEEP_SECONDS = 0.002
PRINT_EVERY_N_WORDS = 50

translator = None
if not CACHE_ONLY and (DO_TRANSLATE_WORDS or DO_TRANSLATE_EXAMPLES):
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="es", target="en")
    except Exception:
        translator = None
        DO_TRANSLATE_WORDS = False
        DO_TRANSLATE_EXAMPLES = False


_word_cache: dict[str, str] = {}
_line_cache: dict[str, str] = {}

# ── Pre-load translation caches and curated flags from old vocabulary ──
_old_flags: dict[str, dict] = {}
if OLD_VOCAB_PATH.exists():
    _old_data = json.loads(OLD_VOCAB_PATH.read_text(encoding="utf-8"))
    for _e in _old_data:
        _w = _e["word"]
        # Cache word translations
        for _m in _e.get("meanings", []):
            _t = _m.get("translation", "")
            if _t and _w not in _word_cache:
                _word_cache[_w] = _t
            # Cache line translations
            for _ex in _m.get("examples", []):
                _sp = _ex.get("spanish", "")
                _en = _ex.get("english", "")
                if _sp and _en and _sp not in _line_cache:
                    _line_cache[_sp] = _en
        # Store curated flags (keep first seen per word)
        if _w not in _old_flags:
            _old_flags[_w] = {
                "is_english": _e.get("is_english", False),
                "is_interjection": _e.get("is_interjection", False),
                "is_propernoun": _e.get("is_propernoun", False),
                "is_transparent_cognate": _e.get("is_transparent_cognate", False),
            }
    print(f"📦 Pre-loaded {len(_word_cache)} word + {len(_line_cache)} line translations from old vocab")
    print(f"📦 Pre-loaded {len(_old_flags)} curated flag entries")
    del _old_data


def parse_example_id(example_id: str) -> tuple[str, str]:
    if not example_id or ":" not in example_id:
        return "", ""
    song_id, line_no = example_id.split(":", 1)
    return song_id.strip(), line_no.strip()


def safe_translate(text: str, is_word: bool) -> str:
    if not text:
        return ""
    cache = _word_cache if is_word else _line_cache
    if text in cache:
        return cache[text]
    if CACHE_ONLY or translator is None:
        return ""
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
    words_processed = 0
    api_calls = 0
    cache_hits = 0
    skipped_no_translate = 0
    start = time.perf_counter()

    for rank, entry in enumerate(subset, start=1):
        word = str(entry.get("word", "")).strip()
        lemma = str(entry.get("lemma", "")).strip()
        display_form = entry.get("display_form")

        lang_flags = entry.get("language_flags") or {}
        is_english_spacy = bool(lang_flags.get("is_english", False))

        # Merge curated flags from old vocab
        old_flags = _old_flags.get(word, {})
        is_english = is_english_spacy or old_flags.get("is_english", False)
        is_interjection = old_flags.get("is_interjection", False)
        is_propernoun = old_flags.get("is_propernoun", False)
        is_transparent_cognate = old_flags.get("is_transparent_cognate", False)

        # Skip translation for English words, interjections, and proper nouns
        skip_translation = is_english or is_interjection or is_propernoun

        id2line, id2songname = build_evidence_maps(entry)
        pos_buckets = pos_to_example_ids(entry)
        pos_freqs = compute_pos_frequencies(entry)

        # Translate the word once (skip if flagged)
        word_translation = ""
        if DO_TRANSLATE_WORDS and not skip_translation:
            was_cached = word in _word_cache
            word_translation = safe_translate(word, is_word=True)
            if was_cached:
                cache_hits += 1
            else:
                api_calls += 1
                time.sleep(TRANSLATE_SLEEP_SECONDS)
        elif skip_translation:
            skipped_no_translate += 1
            # For English words, use the word itself as translation
            if is_english:
                word_translation = word

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

                # Translate this example (unless flagged to skip)
                if DO_TRANSLATE_EXAMPLES and not skip_translation:
                    was_cached = line in _line_cache
                    ex_obj["english"] = safe_translate(line, is_word=False)
                    if was_cached:
                        cache_hits += 1
                    else:
                        api_calls += 1
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
        occ_ppm = entry.get("occurrences_ppm", 0)

        out_entry = {
            "rank": rank,
            "word": word,
            "lemma": lemma,
            "meanings": meanings,
            "most_frequent_lemma_instance": False,  # post-pass
            "is_english": is_english,
            "is_interjection": is_interjection,
            "is_propernoun": is_propernoun,
            "is_transparent_cognate": is_transparent_cognate,
            "occurrences_ppm": occ_ppm,
            "_meta_match_count": match_count,
        }
        if display_form:
            out_entry["display_form"] = display_form

        out.append(out_entry)

        words_processed += 1
        if words_processed % PRINT_EVERY_N_WORDS == 0:
            elapsed = time.perf_counter() - start
            print(f"⏱ {words_processed} words | {api_calls} API calls | {cache_hits} cache hits | {skipped_no_translate} skipped | {elapsed:.1f}s")

    compute_most_frequent_flags(out)

    # Count gaps
    words_missing = 0
    examples_missing = 0
    for e in out:
        for m in e.get("meanings", []):
            if not m.get("translation"):
                words_missing += 1
            for ex in m.get("examples", []):
                if not ex.get("english"):
                    examples_missing += 1

    os.makedirs(OUT_PATH.parent, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = time.perf_counter() - start
    print(f"✅ Wrote {len(out)} entries → {OUT_PATH}")
    print(f"   {api_calls} API calls | {cache_hits} cache hits | {skipped_no_translate} skipped | {elapsed:.1f}s")
    if CACHE_ONLY:
        print(f"   Gaps: {words_missing} word translations + {examples_missing} example translations missing")
        print(f"   Run 6_fill_translation_gaps.py to fill gaps.")


if __name__ == "__main__":
    main()
