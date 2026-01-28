# repair_vocab_fill_lemma_and_one_meaning.py
#
# Policy:
#  - If lemma is blank -> fill using spaCy lemma(word)
#  - If meanings is missing/empty -> add EXACTLY ONE meaning (max one)
#  - If meanings already has >= 1 item -> do nothing to meanings
#
# Output written to a new file by default.

import json
import os
import sys
import time
from time import perf_counter
from typing import Any, Dict, List, Tuple

import spacy

# -------------------------
# Defaults (edit if needed)
# -------------------------
DEFAULT_INPUT = "Data/Spanish/vocabulary.json"
DEFAULT_OUTPUT = "Data/Spanish/vocabulary_repaired.json"

# -------------------------
# Translation options
# -------------------------
DO_TRANSLATE = True
TRANSLATE_SLEEP_SECONDS = 0.05
PRINT_EVERY_N_TRANSLATIONS = 100

# Translate "word" (better for clitics) or "lemma" (more consistent)
TRANSLATE_SOURCE = "word"  # "word" or "lemma"

translator = None
if DO_TRANSLATE:
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="es", target="en")
    except Exception:
        translator = None
        DO_TRANSLATE = False


def norm_str(x: Any) -> str:
    return ("" if x is None else str(x)).strip()


def lemma_blank(entry: Dict[str, Any]) -> bool:
    return norm_str(entry.get("lemma")) == ""


def meanings_count(entry: Dict[str, Any]) -> int:
    m = entry.get("meanings", None)
    if m is None:
        return 0
    if not isinstance(m, list):
        return 0
    return len(m)


def spacy_pos_lemma(nlp, word: str) -> Tuple[str, str]:
    doc = nlp(word)
    if len(doc) == 0:
        return ("X", "")
    tok = doc[0]
    pos = tok.pos_ or "X"
    lemma = (tok.lemma_ or "").strip()
    return (pos, lemma)


def translate(text: str) -> str:
    if not DO_TRANSLATE or translator is None:
        return ""
    if not text:
        return ""
    try:
        out = translator.translate(text)
        return (out or "").strip()
    except Exception:
        return ""


def make_one_meaning(pos: str, translation: str) -> Dict[str, str]:
    return {
        "pos": pos or "X",
        "translation": translation or "",
        "frequency": "1.00",
        "example_spanish": "",
        "example_english": "",
    }


def main():
    # Ignore PyCharm console injected args like --mode=client
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    input_path = args[0] if len(args) >= 1 else DEFAULT_INPUT
    output_path = args[1] if len(args) >= 2 else DEFAULT_OUTPUT

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Expected top-level JSON to be a list of entries.")

    nlp = spacy.load("es_core_news_sm")

    # Caches to speed things up
    pos_lemma_cache: Dict[str, Tuple[str, str]] = {}
    translation_cache: Dict[str, str] = {}

    filled_lemmas = 0
    added_one_meaning = 0
    translated = 0
    start = perf_counter()

    for entry in data:
        if not isinstance(entry, dict):
            continue

        word = norm_str(entry.get("word"))

        # Ensure meanings is a list if present but malformed
        if "meanings" in entry and not isinstance(entry.get("meanings"), list):
            entry["meanings"] = []

        # Get spaCy info once per word form (cached)
        if word not in pos_lemma_cache:
            pos_lemma_cache[word] = spacy_pos_lemma(nlp, word)
        pos, lemma_guess = pos_lemma_cache[word]

        # 1) Fill lemma if blank
        if lemma_blank(entry):
            if lemma_guess:
                entry["lemma"] = lemma_guess
                filled_lemmas += 1

        # 2) If meanings empty -> add EXACTLY ONE meaning
        if meanings_count(entry) == 0:
            lemma_now = norm_str(entry.get("lemma")) or lemma_guess
            translate_input = word if TRANSLATE_SOURCE == "word" else lemma_now

            translation = ""
            if DO_TRANSLATE:
                if translate_input in translation_cache:
                    translation = translation_cache[translate_input]
                else:
                    translation = translate(translate_input)
                    translation_cache[translate_input] = translation

                translated += 1
                if translated % PRINT_EVERY_N_TRANSLATIONS == 0:
                    elapsed = perf_counter() - start
                    print(
                        f"⏱ {translated} translations | {elapsed:.1f}s elapsed | "
                        f"{(elapsed/translated):.3f}s/item"
                    )
                time.sleep(TRANSLATE_SLEEP_SECONDS)

            entry["meanings"] = [make_one_meaning(pos, translation)]
            added_one_meaning += 1

        # If meanings already exists (>=1), do nothing (maximum one added)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("✅ Done")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print(f"Filled lemmas:        {filled_lemmas}")
    print(f"Entries given 1 meaning: {added_one_meaning}")
    print(f"Translations attempted: {translated}")
    print(f"Total entries:        {len(data)}")


if __name__ == "__main__":
    main()
