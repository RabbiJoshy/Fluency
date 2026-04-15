#!/usr/bin/env python3
"""Build an artist SpanishDict menu from the shared SpanishDict cache."""

import argparse
from copy import deepcopy
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from util_1a_artist_config import add_artist_arg, load_artist_config, artist_sense_menu_path
from util_5c_sense_menu_format import flatten_analyses_with_ids, normalize_artist_sense_menu
from pipeline.util_5c_spanishdict import (
    SPANISHDICT_HEADWORD_CACHE,
    SPANISHDICT_REDIRECTS,
    SPANISHDICT_SURFACE_CACHE,
    SPANISHDICT_STATUS,
    load_json,
)


def load_excluded_words(artist_dir, include_clitics=False):
    routing_path = artist_dir / "data" / "known_vocab" / "word_routing.json"
    routing = load_json(routing_path, {})
    exclude = routing.get("exclude", {}) if isinstance(routing, dict) else {}
    skipped = set()
    for category in ("english", "proper_nouns", "interjections", "low_frequency"):
        values = exclude.get(category, [])
        if isinstance(values, list):
            skipped.update(v for v in values if isinstance(v, str))
    if not include_clitics:
        clitic_merge = routing.get("clitic_merge", {})
        if isinstance(clitic_merge, dict):
            skipped.update(clitic_merge.keys())
    return skipped


def normalize_cached_analyses(analyses):
    out = []
    for analysis in analyses or []:
        senses = analysis.get("senses") or []
        if isinstance(senses, dict):
            senses = list(senses.values())
        out.append({
            "headword": analysis.get("headword"),
            "senses": [deepcopy(s) for s in senses if isinstance(s, dict)],
        })
    return out


def analysis_signature(analysis):
    senses = analysis.get("senses") or []
    if isinstance(senses, dict):
        senses = senses.values()
    normalized = []
    for sense in senses:
        normalized.append((
            sense.get("pos", ""),
            sense.get("translation", ""),
            sense.get("context", ""),
        ))
    normalized.sort()
    return (
        analysis.get("headword"),
        tuple(normalized),
    )


def build_menu_analyses(surface, surface_cache, headword_cache, include_redirects=True):
    surface_entry = surface_cache.get(surface) or {}
    analyses = normalize_cached_analyses(surface_entry.get("dictionary_analyses") or [])
    seen_headwords = {a.get("headword") for a in analyses if a.get("headword")}
    seen_signatures = {analysis_signature(a) for a in analyses}

    if include_redirects:
        for result in surface_entry.get("possible_results") or []:
            headword = (result.get("headword") or "").strip()
            if not headword or headword in seen_headwords:
                continue
            headword_entry = headword_cache.get(headword) or {}
            headword_analyses = normalize_cached_analyses(headword_entry.get("dictionary_analyses") or [])
            for analysis in headword_analyses:
                if not analysis.get("headword"):
                    analysis["headword"] = headword
                analysis["surface_relation"] = result.get("heuristic", "")
                analysis["surface_from"] = surface
                sig = analysis_signature(analysis)
                if sig in seen_signatures:
                    continue
                analyses.append(analysis)
                seen_headwords.add(analysis.get("headword"))
                seen_signatures.add(sig)
    return analyses


def artist_cache_state(artist_dir):
    status = load_json(SPANISHDICT_STATUS, {"artists": {}})
    artist_key = str(Path(artist_dir).resolve())
    return (status.get("artists") or {}).get(artist_key) or {}


def main():
    parser = argparse.ArgumentParser(description="Build artist SpanishDict menu from shared cache")
    add_artist_arg(parser)
    parser.add_argument("--force", action="store_true",
                        help="Rebuild words even if already present in the artist menu")
    parser.add_argument("--word", action="append", default=[],
                        help="Only process a specific surface word (repeatable)")
    parser.add_argument("--max-words", type=int, default=None,
                        help="Only process the first N eligible words")
    parser.add_argument("--include-excluded", action="store_true",
                        help="Include step-4 excluded words instead of skipping them")
    parser.add_argument("--include-clitics", action="store_true",
                        help="Include clitic-merge words (skipped by default)")
    parser.add_argument("--no-redirects", action="store_true",
                        help="Only use the direct surface-page dictionary analyses")
    parser.add_argument("--allow-incomplete-cache", action="store_true",
                        help="Allow building from a partial shared SpanishDict cache instead of requiring a completed artist scrape")
    args = parser.parse_args()

    artist_dir = Path(args.artist_dir).resolve()
    config = load_artist_config(str(artist_dir))
    layers_dir = artist_dir / "data" / "layers"
    menu_path = Path(artist_sense_menu_path(str(layers_dir), "spanishdict"))

    inventory = load_json(layers_dir / "word_inventory.json", [])
    existing_menu = normalize_artist_sense_menu(load_json(menu_path, {}))
    surface_cache = load_json(SPANISHDICT_SURFACE_CACHE, {})
    headword_cache = load_json(SPANISHDICT_HEADWORD_CACHE, {})
    redirects = load_json(SPANISHDICT_REDIRECTS, {})
    excluded_words = set() if args.include_excluded else load_excluded_words(artist_dir, include_clitics=args.include_clitics)

    requested_words = set(args.word or [])
    words = []
    skipped_excluded = 0
    skipped_uncached = 0
    for entry in inventory:
        word = (entry.get("word") or "").strip()
        if not word:
            continue
        if requested_words and word not in requested_words:
            continue
        if word in excluded_words:
            skipped_excluded += 1
            continue
        if not args.force and word in existing_menu:
            continue
        words.append(word)

    if args.max_words is not None:
        words = words[:args.max_words]

    is_full_build = not requested_words and args.max_words is None
    cache_state = artist_cache_state(artist_dir)
    if is_full_build and not args.allow_incomplete_cache:
        if cache_state.get("status") != "complete":
            print("ERROR: SpanishDict cache is not complete for this artist.")
            print("Run the shared cache phase first:")
            print("  .venv/bin/python3 %s --artist-dir \"%s\"" % (
                PROJECT_ROOT / "pipeline" / "tool_5c_build_spanishdict_cache.py",
                artist_dir,
            ))
            raise SystemExit(1)

    words_with_cache = []
    for word in words:
        if word not in surface_cache:
            skipped_uncached += 1
            continue
        words_with_cache.append(word)
    words = words_with_cache

    print("SpanishDict artist menu builder")
    print("Artist: %s" % config.get("name", artist_dir.name))
    print("Eligible words: %d" % len(words))
    if skipped_excluded:
        print("Skipped excluded words: %d" % skipped_excluded)
    if skipped_uncached:
        print("Skipped uncached words: %d" % skipped_uncached)
    print("Surface cache: %d words" % len(surface_cache))
    print("Headword cache: %d words" % len(headword_cache))
    print("Redirect entries: %d" % len(redirects))
    if cache_state:
        print("Cache state: %s" % cache_state.get("status", "unknown"))
    print("Output: %s" % menu_path)

    built = 0
    empty = 0
    for word in words:
        analyses = build_menu_analyses(
            word,
            surface_cache,
            headword_cache,
            include_redirects=not args.no_redirects,
        )
        if not analyses:
            empty += 1
            continue
        _, _, normalized_analyses = flatten_analyses_with_ids(analyses)
        existing_menu[word] = normalized_analyses
        built += 1

    with open(menu_path, "w", encoding="utf-8") as f:
        import json
        json.dump(existing_menu, f, ensure_ascii=False, indent=2)

    print("\nDone.")
    print("Built/updated words: %d" % built)
    print("Empty words: %d" % empty)
    print("Total menu words: %d" % len(existing_menu))


if __name__ == "__main__":
    main()
