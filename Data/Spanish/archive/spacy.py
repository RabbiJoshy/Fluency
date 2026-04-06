# build_vocab_from_csv.py
# Input:  Data/Spanish/SpanishRaw600110K.csv
# Output: Data/Spanish/vocab_6001_10000.json

import json
import os
import time
from time import perf_counter

import pandas as pd
import spacy

# Optional translator (cheap/easy). If you don't want translations yet, set DO_TRANSLATE = False.
DO_TRANSLATE = True
TRANSLATE_SLEEP_SECONDS = 0.05  # small delay to reduce rate-limits
PRINT_EVERY_N_TRANSLATIONS = 100

if DO_TRANSLATE:
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="es", target="en")
    except Exception:
        translator = None
        DO_TRANSLATE = False

INPUT_CSV = "Data/Spanish/SpanishRaw600110K.csv"
OUTPUT_JSON = "Data/Spanish/vocab_6001_10000.json"

NBSP = "\u00A0"


def split_lemmas(lemma_forms: str) -> list[str]:
    """
    Split alternate lemmas on NBSP, but keep spaces inside a lemma (e.g. 'por favor').

    Example: 'servido\u00A0servir' -> ['servido', 'servir']
             'kung fu\u00A0fu' -> ['kung fu', 'fu']
    """
    if lemma_forms is None:
        return [""]

    s = str(lemma_forms).strip()
    if not s:
        return [""]

    parts = [p.strip() for p in s.split(NBSP)]
    return [p for p in parts if p] or [""]


def spacy_pos(nlp, word: str) -> str:
    """
    Get spaCy's single best POS for the *word form*.
    Word forms in your CSV should not contain spaces, so doc[0] is safe.
    """
    doc = nlp(word)
    if len(doc) == 0:
        return "X"
    return doc[0].pos_ or "X"


def translate_word(word: str) -> str:
    if not DO_TRANSLATE or translator is None:
        return ""
    try:
        # Translating the *word form* gives better results for clitics like 'permíteme' -> 'allow me'
        out = translator.translate(word)
        return (out or "").strip()
    except Exception:
        return ""


def main():
    # One-time setup:
    #   pip install spacy pandas deep-translator
    #   python -m spacy download es_core_news_sm
    nlp = spacy.load("es_core_news_sm")

    df = pd.read_csv(INPUT_CSV)

    required = {"rank", "word", "occurrences (ppm)", "lemma forms"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {missing}. Found: {list(df.columns)}")

    out = []

    start_time = perf_counter()
    translated = 0

    for _, row in df.iterrows():
        rank = int(row["rank"])
        word = str(row["word"])
        lemma_forms = row["lemma forms"]

        lemmas = split_lemmas(lemma_forms)
        pos = spacy_pos(nlp, word)

        translation = translate_word(word)

        if DO_TRANSLATE:
            translated += 1

            if translated % PRINT_EVERY_N_TRANSLATIONS == 0:
                elapsed = perf_counter() - start_time
                rate = elapsed / translated
                print(
                    f"⏱ {translated} translations | "
                    f"{elapsed:.1f}s elapsed | "
                    f"{rate:.3f}s / item"
                )

            time.sleep(TRANSLATE_SLEEP_SECONDS)

        # One JSON entry per (word, lemma).
        # If the same word appears with multiple lemmas, it becomes multiple entries (same rank, different lemma).
        for i, lemma in enumerate(lemmas):
            entry = {
                "rank": rank,
                "word": word,
                "lemma": lemma,
                "meanings": [
                    {
                        "pos": pos,
                        "translation": translation,
                        "frequency": "1.00",
                        "example_spanish": "",
                        "example_english": ""
                    }
                ],
                # First lemma gets True, alternates get False
                "most_frequent_lemma_instance": (i == 0)
            }
            out.append(entry)

    # Keep sorted by rank, then stable order within rank
    out.sort(key=lambda x: x["rank"])

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"✅ Wrote {len(out)} entries to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
