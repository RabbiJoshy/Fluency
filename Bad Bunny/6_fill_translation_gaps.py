#!/usr/bin/env python3
"""
Gap-filler: translates any missing word/example translations
in BadBunnyvocabulary.json (in-place update).

Run after 5_add_translations.py (CACHE_ONLY mode) to fill the remaining gaps
with live Google Translate API calls.

Progress is saved every SAVE_EVERY_N translations so the script can be
interrupted and restarted safely.
"""

import json
import time
from pathlib import Path

VOCAB_PATH = Path("Bad Bunny/BadBunnyvocabulary.json")
TRANSLATE_SLEEP = 0.002        # seconds between API calls
SAVE_EVERY_N = 100             # save progress every N translations
PRINT_EVERY_N = 10           # log progress every N translations

# ── translator setup ─────────────────────────────────────────────
from deep_translator import GoogleTranslator  # noqa: E402

translator = GoogleTranslator(source="es", target="en")

_cache: dict[str, str] = {}


def translate(text: str) -> str:
    """Translate text via Google, with in-memory cache and rate limiting."""
    if not text:
        return ""
    if text in _cache:
        return _cache[text]
    try:
        out = translator.translate(text)
        out = (out or "").strip()
    except Exception as exc:
        print(f"  ⚠ translate error: {exc}")
        out = ""
    _cache[text] = out
    time.sleep(TRANSLATE_SLEEP)
    return out


def main():
    if not VOCAB_PATH.exists():
        raise FileNotFoundError(f"Input not found: {VOCAB_PATH}")

    data = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))

    # ── count gaps before starting ──
    word_gaps = 0
    example_gaps = 0
    for entry in data:
        if entry.get("is_english") or entry.get("is_interjection") or entry.get("is_propernoun"):
            continue
        for m in entry.get("meanings", []):
            if not m.get("translation"):
                word_gaps += 1
            for ex in m.get("examples", []):
                if not ex.get("english"):
                    example_gaps += 1

    total_gaps = word_gaps + example_gaps
    print(f"📊 Gaps to fill: {word_gaps} word translations + {example_gaps} example translations = {total_gaps} total")
    if total_gaps == 0:
        print("✅ Nothing to do — all translations are filled!")
        return

    # ── fill gaps ──
    filled = 0
    errors = 0
    start = time.perf_counter()

    for entry in data:
        # Skip entries that don't need translation
        if entry.get("is_english") or entry.get("is_interjection") or entry.get("is_propernoun"):
            continue

        word = entry.get("word", "")

        for m in entry.get("meanings", []):
            # Fill missing word translation
            if not m.get("translation"):
                result = translate(word)
                if result:
                    m["translation"] = result
                    filled += 1
                else:
                    errors += 1

                if (filled + errors) % PRINT_EVERY_N == 0:
                    elapsed = time.perf_counter() - start
                    print(f"⏱ {filled} filled | {errors} errors | {elapsed:.1f}s")

                if filled % SAVE_EVERY_N == 0 and filled > 0:
                    VOCAB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"💾 Saved progress ({filled} filled so far)")

            # Fill missing example translations
            for ex in m.get("examples", []):
                if not ex.get("english"):
                    spanish = ex.get("spanish", "")
                    result = translate(spanish)
                    if result:
                        ex["english"] = result
                        filled += 1
                    else:
                        errors += 1

                    if (filled + errors) % PRINT_EVERY_N == 0:
                        elapsed = time.perf_counter() - start
                        print(f"⏱ {filled} filled | {errors} errors | {elapsed:.1f}s")

                    if filled % SAVE_EVERY_N == 0 and filled > 0:
                        VOCAB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                        print(f"💾 Saved progress ({filled} filled so far)")

    # ── final save ──
    VOCAB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    elapsed = time.perf_counter() - start

    # ── verify remaining gaps ──
    remaining_word = 0
    remaining_ex = 0
    for entry in data:
        if entry.get("is_english") or entry.get("is_interjection") or entry.get("is_propernoun"):
            continue
        for m in entry.get("meanings", []):
            if not m.get("translation"):
                remaining_word += 1
            for ex in m.get("examples", []):
                if not ex.get("english"):
                    remaining_ex += 1

    print(f"\n✅ Done in {elapsed:.1f}s")
    print(f"   Filled: {filled} translations")
    print(f"   Errors: {errors}")
    print(f"   Remaining gaps: {remaining_word} word + {remaining_ex} example translations")


if __name__ == "__main__":
    main()
