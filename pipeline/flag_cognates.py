#!/usr/bin/env python3
"""
Step 7: Flag transparent cognates → cognates.json layer.

Shared layer used by both normal and artist pipelines.
All voters written to one file: score (suffix/similarity), CogNet, Gemini.

Usage (from project root):
    python3 pipeline/flag_cognates.py
"""

import json
import os
import sys

# Allow importing from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.flag_cognates import detect_cognates

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYERS_DIR = os.path.join(PROJECT_ROOT, "Data", "Spanish", "layers")


def main():
    senses_path = os.path.join(LAYERS_DIR, "senses_wiktionary.json")
    if not os.path.isfile(senses_path):
        print("ERROR: %s not found. Run build_senses.py first." % senses_path)
        sys.exit(1)

    with open(senses_path, "r", encoding="utf-8") as f:
        senses_data = json.load(f)

    print("=== Flag transparent cognates (all voters) ===")
    print("  Loaded %d sense entries from senses_wiktionary.json" % len(senses_data))

    output_path = os.path.join(LAYERS_DIR, "cognates.json")
    detect_cognates(senses_data, output_path)


if __name__ == "__main__":
    main()
