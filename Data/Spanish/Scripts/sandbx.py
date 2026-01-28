# add_stub_meanings_for_blank_entries.py
#
# Creates a NEW JSON where entries that have BOTH:
#   - blank lemma ("" or missing)
#   - blank meanings ([] or missing)
# are given a stub lemma + stub meaning with frequency "1.00".
#
# Default paths assume your project structure:
#   Input : Data/Spanish/vocabulary.json
#   Output: Data/Spanish/vocabulary_stubbed.json
#
# Usage:
#   python add_stub_meanings_for_blank_entries.py
# or:
#   python add_stub_meanings_for_blank_entries.py input.json output.json

import json
import os
import sys
from typing import Any, Dict, List


DEFAULT_INPUT = "Data/Spanish/vocabulary.json"
DEFAULT_OUTPUT = "Data/Spanish/vocabulary_stubbed.json"


def norm_str(x: Any) -> str:
    return ("" if x is None else str(x)).strip()


def is_blank_lemma(entry: Dict[str, Any]) -> bool:
    return norm_str(entry.get("lemma")) == ""


def is_blank_meanings(entry: Dict[str, Any]) -> bool:
    meanings = entry.get("meanings", None)
    if meanings is None:
        return True
    if not isinstance(meanings, list):
        # If it's malformed, treat as blank so we can repair it safely.
        return True
    return len(meanings) == 0


def make_stub_meaning() -> Dict[str, str]:
    # Minimal meaning object your downstream app can accept.
    # POS is unknown, so "X" (UD unknown/other) is a safe placeholder.
    return {
        "pos": "X",
        "translation": "",
        "frequency": "1.00",
        "example_spanish": "",
        "example_english": "",
    }


def main():
    input_path = sys.argv[1] if len(sys.argv) >= 2 else DEFAULT_INPUT
    output_path = sys.argv[2] if len(sys.argv) >= 3 else DEFAULT_OUTPUT

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Expected the JSON to be a list of entries (top-level array).")

    stubbed_count = 0

    for entry in data:
        if not isinstance(entry, dict):
            continue

        if is_blank_lemma(entry) and is_blank_meanings(entry):
            word = norm_str(entry.get("word"))
            # If lemma is blank, fall back to the word form.
            entry["lemma"] = word

            # Add the minimal stub meaning.
            entry["meanings"] = [make_stub_meaning()]

            stubbed_count += 1

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("✅ Done")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print(f"Stubbed entries (blank lemma + blank meanings): {stubbed_count}")
    print(f"Total entries written: {len(data)}")


if __name__ == "__main__":
    main()
