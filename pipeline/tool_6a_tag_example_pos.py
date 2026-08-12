#!/usr/bin/env python3
"""Tag examples with spaCy POS for the target word.

Writes a transparent layer file so POS filtering can be inspected separately
from sense classification. Runs in both normal and artist modes:

    # Normal mode (default)
    .venv/bin/python3 pipeline/tool_6a_tag_example_pos.py

    # Artist mode
    .venv/bin/python3 pipeline/tool_6a_tag_example_pos.py --artist-dir "Artists/spanish/Bad Bunny"

Incremental by default: skips words whose example IDs haven't changed since
the last run. Use --force to retag everything.
"""

import argparse
from collections import Counter, defaultdict
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pipeline.util_6a_pos_menu_filter import load_spacy, tag_examples
from pipeline.util_pipeline_meta import dependency_metadata, make_meta
from pipeline.util_evidence_store import archive_json_artifact

# Bump when tagging logic or model family changes in a way that invalidates
# previously tagged outputs.
STEP_VERSION = 6
STEP_VERSION_NOTES = {
    1: "legacy es_core_news_* models",
    2: "es_dep_news_trf transformer default",
    3: "order-sensitive stable example identity signatures",
    4: "archive every content-distinct POS output as an immutable evidence run",
    5: "upgrade legacy example signatures and remap pure reorders by stable lyric ID",
    6: "+ record the exact examples/ledger dependency used by the POS layer",
}

NORMAL_LAYERS = Path(PROJECT_ROOT) / "Data" / "Spanish" / "layers"


def example_id_signature(examples):
    """Return the ordered example identity sequence used for freshness.

    POS output is indexed by legacy list position. Sorting this signature made
    a pure reorder look unchanged even though every numeric POS key could now
    name a different lyric line.
    """
    return [example.get("segment_id") or example.get("id", "") for example in examples]


def legacy_example_id_signature(examples):
    """Return the persisted pre-ledger lyric IDs for compatibility upgrades."""
    return [example.get("id", "") for example in examples]


def remap_pos_for_reordered_ids(pos_map, previous_ids, current_ids):
    """Move numeric POS keys with their lyric identity after a pure reorder.

    Repeated legacy IDs are matched by occurrence order, so duplicate retained
    examples remain deterministic. ``None`` means the identity sets changed
    and the word should be retagged instead of guessed.
    """
    if len(previous_ids) != len(current_ids) or Counter(previous_ids) != Counter(current_ids):
        return None
    current_slots = defaultdict(list)
    for index, example_id in enumerate(current_ids):
        current_slots[example_id].append(index)
    seen = Counter()
    old_to_new = {}
    for old_index, example_id in enumerate(previous_ids):
        ordinal = seen[example_id]
        seen[example_id] += 1
        old_to_new[old_index] = current_slots[example_id][ordinal]
    remapped = {}
    for old_key, value in (pos_map or {}).items():
        try:
            old_index = int(old_key)
        except (TypeError, ValueError):
            continue
        if old_index in old_to_new:
            remapped[str(old_to_new[old_index])] = value
    return {key: remapped[key] for key in sorted(remapped, key=int)}


def resolve_paths(artist_dir):
    """Return (examples_path, output_path) for either mode."""
    if artist_dir:
        layers = Path(os.path.abspath(artist_dir)) / "data" / "layers"
    else:
        layers = NORMAL_LAYERS
    return layers / "examples_raw.json", layers / "example_pos.json"


def main():
    parser = argparse.ArgumentParser(description="Tag examples with POS (normal or artist mode)")
    parser.add_argument(
        "--artist-dir",
        default=None,
        help="Path to Artists/{lang}/{Name} directory. Omit for normal-mode Data/Spanish/layers.",
    )
    parser.add_argument(
        "--model",
        default="es_dep_news_trf",
        help="Preferred spaCy model (default: es_dep_news_trf)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Retag all words (ignore previous results)",
    )
    parser.add_argument(
        "--identity-baseline-examples",
        default=None,
        help=("Frozen pre-migration examples_raw.json. Use with "
              "--identity-baseline-pos to carry numeric POS tags by their "
              "actual legacy lyric identity."),
    )
    parser.add_argument(
        "--identity-baseline-pos",
        default=None,
        help="Frozen pre-migration example_pos.json paired with the baseline examples.",
    )
    args = parser.parse_args()

    if bool(args.identity_baseline_examples) != bool(args.identity_baseline_pos):
        parser.error(
            "--identity-baseline-examples and --identity-baseline-pos must be used together")

    examples_path, output_path = resolve_paths(args.artist_dir)

    with open(examples_path, encoding="utf-8") as f:
        examples_data = json.load(f)

    # Load previous results for incremental mode
    prev_output = {}
    prev_ids = {}
    prev_meta = {}
    if not args.force and args.identity_baseline_examples:
        with open(args.identity_baseline_examples, encoding="utf-8") as f:
            baseline_examples = json.load(f)
        with open(args.identity_baseline_pos, encoding="utf-8") as f:
            prev_output = json.load(f)
        # STEP_VERSION 2 and earlier sorted _example_ids even though the POS
        # keys themselves followed examples_raw list order. Reconstruct the
        # signature from the frozen examples instead of trusting that index.
        prev_ids = {
            word: legacy_example_id_signature(examples)
            for word, examples in baseline_examples.items()
        }
        prev_output.pop("_example_ids", None)
        prev_meta = prev_output.pop("_meta", {})
    elif not args.force and output_path.is_file():
        with open(output_path, encoding="utf-8") as f:
            prev_output = json.load(f)
        prev_ids = prev_output.pop("_example_ids", {})
        prev_meta = prev_output.pop("_meta", {})

    # Determine which words need tagging
    words_to_tag = {}
    skipped = 0
    upgraded = 0
    reordered = 0
    for word, examples in examples_data.items():
        current_ids = example_id_signature(examples)
        current_legacy_ids = legacy_example_id_signature(examples)
        prev_id_list = prev_ids.get(word)
        if not args.force and prev_id_list == current_ids:
            skipped += 1
            continue
        if not args.force and prev_id_list == current_legacy_ids:
            # Same examples and order; only the identity namespace changed
            # from song:line to persisted segment IDs.
            upgraded += 1
            continue
        if not args.force and prev_id_list:
            remapped = remap_pos_for_reordered_ids(
                prev_output.get(word, {}), prev_id_list, current_legacy_ids)
            if remapped is not None:
                if word in prev_output:
                    prev_output[word] = remapped
                reordered += 1
                continue
        words_to_tag[word] = examples

    if not words_to_tag and not upgraded and not reordered:
        print("All %d words up to date, nothing to tag." % len(examples_data))
        return

    nlp = None
    if words_to_tag:
        print("Loading spaCy...")
        preferred = [args.model]
        # Language-appropriate fallback chain: infer from the model prefix.
        # es_* -> Spanish fallbacks; fr_* -> French fallbacks; anything else -> no fallbacks.
        lang_prefix = args.model.split("_", 1)[0] if "_" in args.model else ""
        _FALLBACK_CHAINS = {
            "es": ("es_core_news_lg", "es_core_news_md", "es_core_news_sm"),
            "fr": ("fr_core_news_lg", "fr_core_news_md", "fr_core_news_sm"),
        }
        for fallback in _FALLBACK_CHAINS.get(lang_prefix, ()):
            if fallback != args.model:
                preferred.append(fallback)
        nlp = load_spacy(preferred_models=preferred)
        if nlp is None:
            print("ERROR: No spaCy model found for chain: %s" % ", ".join(preferred))
            print("Install with: .venv/bin/python3 -m spacy download %s" % args.model)
            raise SystemExit(1)
        print("  Model: %s" % nlp.meta.get("name", "unknown"))

    if skipped:
        print("  Skipped %d unchanged words, tagging %d" % (skipped, len(words_to_tag)))
    else:
        print("  Tagging %d words..." % len(words_to_tag))
    if upgraded or reordered:
        print("  Reused %d legacy-ID words; remapped %d reordered words" % (
            upgraded, reordered))

    # Start from previous results (minus metadata)
    output = {
        k: v for k, v in prev_output.items()
        if k not in ("_example_ids", "_meta") and k in examples_data
    }
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
        id_index[word] = example_id_signature(examples)
    output["_example_ids"] = id_index
    model_name = (
        nlp.meta.get("name", "unknown")
        if nlp is not None
        else (prev_meta.get("tool_versions") or {}).get("spacy_model", "reused")
    )
    upstream = dependency_metadata(examples_path)
    output["_meta"] = make_meta(
        "tag_example_pos",
        STEP_VERSION,
        tool_versions={"spacy_model": model_name},
        extra=upstream,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    archive_json_artifact(
        output_path.parent.parent / "evidence",
        "example_pos",
        output,
        language=(Path(args.artist_dir).resolve().parent.name
                  if args.artist_dir else "spanish"),
        adapter={"name": "tag-example-pos", "version": STEP_VERSION},
        inputs=upstream,
        config={"spacy_model": model_name},
    )

    reserved_keys = {"_example_ids", "_meta"}
    total_words = sum(1 for k in output if k not in reserved_keys)
    print("Tagged %d new words (%d examples), %d total words in output" % (
        new_tagged, new_examples, total_words))
    print("Wrote %s" % output_path)


if __name__ == "__main__":
    main()
