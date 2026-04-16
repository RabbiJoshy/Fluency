#!/usr/bin/env python3
"""Step 6a: Tag artist examples with spaCy POS for the target word.

Writes a transparent layer file so POS filtering can be inspected separately
from sense classification.

Incremental by default: skips words whose example IDs haven't changed since
the last run. Use --force to retag everything.
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

from pipeline.util_6a_pos_menu_filter import load_spacy, tag_examples
from pipeline.util_pipeline_meta import make_meta

# Bump when tagging logic or model family changes in a way that invalidates
# previously tagged outputs.
STEP_VERSION = 2
STEP_VERSION_NOTES = {
    1: "legacy es_core_news_* models",
    2: "es_dep_news_trf transformer default",
}


def _example_ids(examples):
    """Return a frozenset of example IDs for change detection."""
    return frozenset(ex.get("id", "") for ex in examples)


def main():
    parser = argparse.ArgumentParser(description="Tag artist examples with POS")
    add_artist_arg(parser)
    parser.add_argument(
        "--model",
        default="es_dep_news_trf",
        help="Preferred spaCy model (default: es_dep_news_trf)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Retag all words (ignore previous results)",
    )
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    layers_dir = os.path.join(artist_dir, "data", "layers")
    examples_path = os.path.join(layers_dir, "examples_raw.json")
    output_path = os.path.join(layers_dir, "example_pos.json")

    with open(examples_path, encoding="utf-8") as f:
        examples_data = json.load(f)

    # Load previous results for incremental mode
    prev_output = {}
    prev_ids = {}  # word -> frozenset of example IDs at last tagging
    if not args.force and os.path.isfile(output_path):
        with open(output_path, encoding="utf-8") as f:
            prev_output = json.load(f)
        # Reconstruct which example IDs each word had by checking the index keys
        # We can't recover exact IDs, so we store a signature in metadata
        prev_ids = prev_output.pop("_example_ids", {})
        prev_output.pop("_meta", None)

    # Determine which words need tagging
    words_to_tag = {}
    skipped = 0
    for word, examples in examples_data.items():
        current_ids = sorted(ex.get("id", "") for ex in examples)
        prev_id_list = prev_ids.get(word)
        if not args.force and prev_id_list == current_ids and word in prev_output:
            skipped += 1
            continue
        words_to_tag[word] = examples

    if not words_to_tag:
        print("All %d words up to date, nothing to tag." % len(examples_data))
        return

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

    if skipped:
        print("  Skipped %d unchanged words, tagging %d" % (skipped, len(words_to_tag)))
    else:
        print("  Tagging %d words..." % len(words_to_tag))

    # Start from previous results (minus metadata)
    output = {k: v for k, v in prev_output.items() if k not in ("_example_ids", "_meta")}
    new_tagged = 0
    new_examples = 0
    total_to_tag = len(words_to_tag)
    for idx, (word, examples) in enumerate(words_to_tag.items(), start=1):
        pos_map = tag_examples(nlp, word, word, examples)
        if pos_map:
            output[word] = {str(i): pos for i, pos in sorted(pos_map.items())}
            new_tagged += 1
            new_examples += len(pos_map)
        elif word in output:
            # Word no longer taggable — remove stale entry
            del output[word]
        if idx % 500 == 0 or idx == total_to_tag:
            print("  %d/%d words, %d tagged, %d examples" % (
                idx, total_to_tag, new_tagged, new_examples))

    # Store example ID signatures for next incremental run
    id_index = {}
    for word, examples in examples_data.items():
        id_index[word] = sorted(ex.get("id", "") for ex in examples)
    output["_example_ids"] = id_index
    output["_meta"] = make_meta(
        "tag_example_pos",
        STEP_VERSION,
        tool_versions={"spacy_model": nlp.meta.get("name", "unknown")},
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    reserved_keys = {"_example_ids", "_meta"}
    total_words = sum(1 for k in output if k not in reserved_keys)
    print("Tagged %d new words (%d examples), %d total words in output" % (
        new_tagged, new_examples, total_words))
    print("Wrote %s" % output_path)


if __name__ == "__main__":
    main()
