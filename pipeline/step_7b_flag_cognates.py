#!/usr/bin/env python3
"""
Step 7b: Flag transparent cognates → cognates.json layer.

Shared layer used by both normal and artist pipelines.
All voters written to one file: score (suffix/similarity), CogNet, Gemini.

Auto-discovers sense menus from sense_menu/ subdirectory. Cognates are
source-agnostic — reads from all available menus and merges.

Usage (from project root):
    python3 pipeline/step_7b_flag_cognates.py
"""

import json
import os
import sys
from pathlib import Path

# Allow importing from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.flag_cognates import detect_cognates

from util_5c_sense_paths import discover_sources, sense_menu_path
from util_pipeline_meta import make_meta, write_sidecar

STEP_VERSION = 1
STEP_VERSION_NOTES = {
    1: "suffix score + CogNet voters merged across all sense menus",
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYERS_DIR = os.path.join(PROJECT_ROOT, "Data", "Spanish", "layers")


def flatten_menu(senses_data):
    """Flatten analysis-based menu to word|lemma keys for detect_cognates()."""
    flat = {}
    for word, analyses in senses_data.items():
        if not isinstance(analyses, list):
            flat[word] = analyses
            continue
        for analysis in analyses:
            if not isinstance(analysis, dict) or "senses" not in analysis:
                continue
            lemma = analysis.get("headword", word)
            key = "%s|%s" % (word, lemma)
            senses = analysis["senses"]
            if isinstance(senses, dict):
                flat[key] = list(senses.values())
            else:
                flat[key] = list(senses)
    return flat


def main():
    sources = discover_sources(LAYERS_DIR, "sense_menu")

    if not sources:
        print("ERROR: No sense menus found in %s" % os.path.join(LAYERS_DIR, "sense_menu"))
        sys.exit(1)

    print("=== Flag transparent cognates (all voters) ===")
    flat_menu = {}
    for source in sources:
        menu_path = sense_menu_path(LAYERS_DIR, source)
        with open(menu_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        flattened = flatten_menu(data)
        # Merge — later sources overwrite earlier for the same word|lemma key
        flat_menu.update(flattened)
        print("  Loaded %s: %d entries -> %d word|lemma" % (source, len(data), len(flattened)))

    print("  Combined: %d word|lemma entries" % len(flat_menu))

    output_path = os.path.join(LAYERS_DIR, "cognates.json")
    detect_cognates(flat_menu, output_path)
    write_sidecar(output_path, make_meta("flag_cognates", STEP_VERSION))


if __name__ == "__main__":
    main()
