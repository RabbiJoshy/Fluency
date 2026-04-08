#!/usr/bin/env python3
"""
Step 7: Flag transparent cognates → cognates.json layer.

Thin wrapper around shared/flag_cognates.py.
Uses intersection mode: both LLM flag (from master) and suffix rules must agree.
"""

import os
import sys

# Allow importing from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.flag_cognates import detect_cognates_from_layers


def main():
    import argparse
    from _artist_config import add_artist_arg, load_artist_config

    parser = argparse.ArgumentParser(description="Step 7: Flag transparent cognates")
    add_artist_arg(parser)
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    layers_dir = os.path.join(artist_dir, "data", "layers")

    print("=== Layer-based cognate detection (artist mode) ===")
    detect_cognates_from_layers(layers_dir)


if __name__ == "__main__":
    main()
