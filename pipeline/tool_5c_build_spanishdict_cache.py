#!/usr/bin/env python3
"""Build shared SpanishDict cache files from artist or normal-mode inventory words."""

import argparse
import concurrent.futures
from pathlib import Path
import time

from util_5c_spanishdict import (
    SPANISHDICT_HEADWORD_CACHE,
    SPANISHDICT_PHRASES_CACHE,
    SPANISHDICT_REDIRECTS,
    SPANISHDICT_SURFACE_CACHE,
    SPANISHDICT_STATUS,
    build_session,
    build_surface_entry,
    extract_phrases,
    fetch_spanishdict_component,
    load_json,
    save_json,
    should_keep_possible_result,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Bump when the scraper's extraction logic changes in a way that invalidates
# previously cached entries. Entries tagged with an older step_version are
# re-fetched on the next run (no --force needed).
STEP_VERSION = 2
STEP_VERSION_NOTES = {
    1: "initial — surface + headword caches",
    2: "adds phrases_cache extraction alongside surface fetch",
}


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


def load_artist_words(artist_dir, include_excluded=False, include_clitics=False):
    inventory = load_json(artist_dir / "data" / "layers" / "word_inventory.json", [])
    excluded = set() if include_excluded else load_excluded_words(artist_dir, include_clitics=include_clitics)
    out = []
    for entry in inventory:
        word = (entry.get("word") or "").strip()
        if word and word not in excluded:
            out.append(word)
    return out, excluded


def load_inventory_words(inventory_path):
    inventory = load_json(inventory_path, [])
    out = []
    for entry in inventory:
        word = (entry.get("word") or "").strip()
        if word:
            out.append(word)
    return out


def fetch_surface(query):
    session = build_session()
    component = fetch_spanishdict_component(session, query)
    return query, build_surface_entry(query, component), extract_phrases(component)


def fetch_headword(headword):
    session = build_session()
    component = fetch_spanishdict_component(session, headword)
    entry = build_surface_entry(headword, component)
    return headword, {
        "headword": headword,
        "dictionary_analyses": entry.get("dictionary_analyses", []),
    }


def _artist_key(artist_dir):
    return str(Path(artist_dir).resolve())


def _now():
    return int(time.time())


def _status_for_error(exc):
    message = str(exc)
    if "429" in message or "Too Many Requests" in message or "503" in message:
        return "retryable"
    return "failed"


def main():
    parser = argparse.ArgumentParser(description="Build shared SpanishDict cache files")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--artist-dir",
                        help="Path to artist dir used to source candidate words")
    source.add_argument("--inventory-file",
                        help="Path to a word_inventory.json file to source candidate words")
    parser.add_argument("--force", action="store_true",
                        help="Refetch words already present in shared cache")
    parser.add_argument("--include-excluded", action="store_true",
                        help="Include step-4 excluded words from the artist inventory")
    parser.add_argument("--include-clitics", action="store_true",
                        help="Include clitic-merge words (skipped by default)")
    parser.add_argument("--workers", type=int, default=8,
                        help="Concurrent fetch workers (default: 8)")
    parser.add_argument("--save-every", type=int, default=100,
                        help="Write partial progress every N completed fetches (default: 100)")
    parser.add_argument("--max-words", type=int, default=None,
                        help="Only process the first N artist words")
    parser.add_argument("--word", action="append", default=[],
                        help="Only process a specific surface word (repeatable)")
    args = parser.parse_args()

    artist_dir = Path(args.artist_dir).resolve() if args.artist_dir else None
    inventory_path = Path(args.inventory_file).resolve() if args.inventory_file else None
    if artist_dir is not None:
        words, excluded = load_artist_words(artist_dir, include_excluded=args.include_excluded,
                                              include_clitics=args.include_clitics)
    else:
        words = load_inventory_words(inventory_path)
        excluded = set()
    requested_words = set(w.strip() for w in (args.word or []) if w and w.strip())
    if requested_words:
        words = [w for w in words if w in requested_words]
    if args.max_words is not None:
        words = words[:args.max_words]

    surface_cache = load_json(SPANISHDICT_SURFACE_CACHE, {})
    headword_cache = load_json(SPANISHDICT_HEADWORD_CACHE, {})
    phrases_cache = load_json(SPANISHDICT_PHRASES_CACHE, {})
    redirects = load_json(SPANISHDICT_REDIRECTS, {})
    status = load_json(SPANISHDICT_STATUS, {"surface": {}, "headwords": {}, "artists": {}})
    surface_status = status.setdefault("surface", {})
    headword_status = status.setdefault("headwords", {})
    artist_status = status.setdefault("artists", {})

    requested_words = set(w.strip() for w in (args.word or []) if w and w.strip())
    full_artist_run = artist_dir is not None and not requested_words and args.max_words is None

    queries = []
    stale_version_count = 0
    for w in words:
        if args.force:
            queries.append(w)
            continue
        entry_status = surface_status.get(w) or {}
        entry_version = int(entry_status.get("step_version", 0) or 0)
        if entry_version < STEP_VERSION:
            # Cached under an older scraper version — re-fetch to pick up the
            # fields that version didn't know about (e.g. phrases in v2).
            queries.append(w)
            if w in surface_cache:
                stale_version_count += 1
            continue
        if entry_status.get("status") == "failed":
            continue
        if w in surface_cache:
            continue
        queries.append(w)

    print("SpanishDict shared cache builder")
    if artist_dir is not None:
        print("Artist dir: %s" % artist_dir)
        print("Artist words: %d" % len(words))
    else:
        print("Inventory file: %s" % inventory_path)
        print("Inventory words: %d" % len(words))
    if artist_dir is not None and excluded and not args.include_excluded:
        print("Skipped excluded words: %d" % len(excluded))
    print("Surface queries to fetch: %d (of which %d are stale-version re-fetches)"
          % (len(queries), stale_version_count))
    print("Scraper step_version: %d" % STEP_VERSION)
    print("Workers: %d" % max(1, args.workers))

    processed = 0
    built = 0
    failed = 0
    save_every = max(1, args.save_every)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_to_query = {executor.submit(fetch_surface, query): query for query in queries}
        for future in concurrent.futures.as_completed(future_to_query):
            query = future_to_query[future]
            try:
                resolved_query, entry, phrases = future.result()
                entry["possible_results"] = [
                    r for r in entry.get("possible_results", [])
                    if should_keep_possible_result(resolved_query, r)
                ]
                surface_cache[resolved_query] = entry
                if phrases:
                    phrases_cache[resolved_query] = phrases
                redirects[resolved_query] = entry.get("possible_results", [])
                surface_status[resolved_query] = {
                    "status": "ok",
                    "updated_at": _now(),
                    "step_version": STEP_VERSION,
                }
                built += 1
            except Exception as exc:
                failed += 1
                surface_status[query] = {
                    "status": _status_for_error(exc),
                    "updated_at": _now(),
                    "step_version": STEP_VERSION,
                    "error": str(exc)[:300],
                }
                print("  surface %s failed: %s" % (query, exc))
            processed += 1
            if processed % save_every == 0:
                save_json(SPANISHDICT_SURFACE_CACHE, surface_cache)
                save_json(SPANISHDICT_PHRASES_CACHE, phrases_cache)
                save_json(SPANISHDICT_REDIRECTS, redirects)
                save_json(SPANISHDICT_STATUS, status)
                print("  Saved surface progress at %d/%d" % (processed, len(queries)))

    save_json(SPANISHDICT_SURFACE_CACHE, surface_cache)
    save_json(SPANISHDICT_PHRASES_CACHE, phrases_cache)
    save_json(SPANISHDICT_REDIRECTS, redirects)
    save_json(SPANISHDICT_STATUS, status)

    needed_headwords = set()
    for query in words:
        entry = surface_cache.get(query) or {}
        for result in entry.get("possible_results", []):
            headword = (result.get("headword") or "").strip()
            if headword:
                needed_headwords.add(headword)

    headwords = []
    for h in sorted(needed_headwords):
        if args.force:
            headwords.append(h)
            continue
        entry_status = headword_status.get(h) or {}
        entry_version = int(entry_status.get("step_version", 0) or 0)
        if entry_version < STEP_VERSION:
            headwords.append(h)
            continue
        if entry_status.get("status") == "failed":
            continue
        if h in headword_cache:
            continue
        headwords.append(h)
    print("Headwords to fetch: %d" % len(headwords))

    processed = 0
    built_headwords = 0
    failed_headwords = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_to_headword = {executor.submit(fetch_headword, headword): headword for headword in headwords}
        for future in concurrent.futures.as_completed(future_to_headword):
            headword = future_to_headword[future]
            try:
                resolved_headword, entry = future.result()
                headword_cache[resolved_headword] = entry
                headword_status[resolved_headword] = {
                    "status": "ok",
                    "updated_at": _now(),
                    "step_version": STEP_VERSION,
                }
                built_headwords += 1
            except Exception as exc:
                failed_headwords += 1
                headword_status[headword] = {
                    "status": _status_for_error(exc),
                    "updated_at": _now(),
                    "step_version": STEP_VERSION,
                    "error": str(exc)[:300],
                }
                print("  headword %s failed: %s" % (headword, exc))
            processed += 1
            if processed % save_every == 0:
                save_json(SPANISHDICT_HEADWORD_CACHE, headword_cache)
                save_json(SPANISHDICT_STATUS, status)
                print("  Saved headword progress at %d/%d" % (processed, len(headwords)))

    save_json(SPANISHDICT_HEADWORD_CACHE, headword_cache)
    if full_artist_run:
        artist_status[_artist_key(artist_dir)] = {
            "status": "complete",
            "updated_at": _now(),
            "step_version": STEP_VERSION,
            "include_excluded": bool(args.include_excluded),
            "word_count": len(words),
        }
    elif artist_dir is not None:
        artist_status[_artist_key(artist_dir)] = {
            "status": "partial",
            "updated_at": _now(),
            "step_version": STEP_VERSION,
            "include_excluded": bool(args.include_excluded),
            "word_count": len(words),
        }
    save_json(SPANISHDICT_STATUS, status)

    print("\nDone.")
    print("Surface fetched: %d" % built)
    print("Surface failed: %d" % failed)
    print("Headwords fetched: %d" % built_headwords)
    print("Headwords failed: %d" % failed_headwords)
    print("Surface cache: %s" % SPANISHDICT_SURFACE_CACHE)
    print("Headword cache: %s" % SPANISHDICT_HEADWORD_CACHE)
    print("Redirects: %s" % SPANISHDICT_REDIRECTS)
    print("Status: %s" % SPANISHDICT_STATUS)


if __name__ == "__main__":
    main()
