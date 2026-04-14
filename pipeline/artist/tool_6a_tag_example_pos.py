#!/usr/bin/env python3
"""Step 6a: Tag artist examples with spaCy POS for the target word.

Writes a transparent layer file so POS filtering can be inspected separately
from sense classification.
"""

import argparse
import json
import os
import sys

from util_1a_artist_config import add_artist_arg

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pipeline.pos_menu_filter import load_spacy, tag_examples


def main():
    parser = argparse.ArgumentParser(description="Tag artist examples with POS")
    add_artist_arg(parser)
    parser.add_argument(
        "--model",
        default="es_core_news_md",
        help="Preferred spaCy model (default: es_core_news_md)",
    )
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    layers_dir = os.path.join(artist_dir, "data", "layers")
    examples_path = os.path.join(layers_dir, "examples_raw.json")
    output_path = os.path.join(layers_dir, "example_pos.json")

    print("Loading spaCy...")
    preferred = [args.model]
    if args.model != "es_core_news_lg":
        preferred.append("es_core_news_lg")
    if args.model != "es_core_news_md":
        preferred.append("es_core_news_md")
    if args.model != "es_core_news_sm":
        preferred.append("es_core_news_sm")
    nlp = load_spacy(preferred_models=preferred)
    if nlp is None:
        print("ERROR: No Spanish spaCy model found.")
        print("Install with: .venv/bin/python3 -m spacy download es_core_news_sm")
        raise SystemExit(1)
    print("  Model: %s" % nlp.meta.get("name", "unknown"))

    with open(examples_path, encoding="utf-8") as f:
        examples_data = json.load(f)

    output = {}
    tagged_words = 0
    tagged_examples = 0
    total_words = len(examples_data)
    print("Tagging %d words..." % total_words)
    for idx, (word, examples) in enumerate(examples_data.items(), start=1):
        pos_map = tag_examples(nlp, word, word, examples)
        if pos_map:
            output[word] = {str(idx): pos for idx, pos in sorted(pos_map.items())}
            tagged_words += 1
            tagged_examples += len(pos_map)
        if idx % 500 == 0 or idx == total_words:
            print("  %d/%d words, %d tagged, %d examples" % (
                idx, total_words, tagged_words, tagged_examples))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("Tagged %d words, %d examples" % (tagged_words, tagged_examples))
    print("Wrote %s" % output_path)


if __name__ == "__main__":
    main()
