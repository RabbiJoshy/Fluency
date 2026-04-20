#!/usr/bin/env python3
"""tool_5c_scrape_spanishdict_phrases.py — scrape per-phrase SpanishDict pages.

SpanishDict's ``phrases`` component (returned alongside a single-word lookup)
only exposes two fields per phrase: ``expression`` and ``quickdef``. That's
what sits in ``phrases_cache.json`` today. Each phrase, however, has its
*own* page at ``spanishdict.com/translate/<expression>`` — and that page
returns the same rich ``neodict`` sense tree as a regular word lookup:

- ``context`` (structured — the real field sense rows already use)
- ``regions`` (per translation)
- ``examples`` (per translation)
- alternate translations with their own context

This tool hits each phrase page and writes the full structured response to
``Data/Spanish/senses/spanishdict/phrases_detail_cache.json``. The MWE
builder (``tool_5d_build_spanishdict_mwes.py``) then reads this cache and
promotes the top sense's structured context into the authoritative
``context`` field on each MWE membership, while keeping the regex-split
``context_heuristic`` as a fallback for phrases not yet scraped.

Idempotent: already-fetched phrases are skipped. Add ``--force`` to refetch.

Cost: SpanishDict is free, rate-limited by ``REQUEST_DELAY_SECONDS`` (0.35s
global). The ``mwe-layer`` source (default) is ~2k phrases → ~12 minutes.
``phrases-cache`` is ~30k phrases → ~3 hours.

Usage (from repo root):
    .venv/bin/python3 pipeline/tool_5c_scrape_spanishdict_phrases.py
    .venv/bin/python3 pipeline/tool_5c_scrape_spanishdict_phrases.py --phrase "para que"
    .venv/bin/python3 pipeline/tool_5c_scrape_spanishdict_phrases.py --source phrases-cache
    .venv/bin/python3 pipeline/tool_5c_scrape_spanishdict_phrases.py --force

After scraping, rebuild the MWE layer + final vocab:
    .venv/bin/python3 pipeline/tool_5d_build_spanishdict_mwes.py
    .venv/bin/python3 pipeline/step_8a_assemble_vocabulary.py
    # per artist:
    .venv/bin/python3 pipeline/artist/run_artist_pipeline.py --artist bad-bunny --from-step 8b
"""

import argparse
import concurrent.futures
import time
from pathlib import Path

from util_5c_spanishdict import (
    SPANISHDICT_DIR,
    SPANISHDICT_PHRASES_CACHE,
    build_session,
    build_surface_entry,
    fetch_spanishdict_component,
    load_json,
    save_json,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MWE_LAYER_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "mwe_phrases.json"
PHRASES_DETAIL_CACHE = SPANISHDICT_DIR / "phrases_detail_cache.json"


def _fetch_phrase_detail(expression):
    """Hit the per-phrase SpanishDict page, return the ``build_surface_entry`` result."""
    session = build_session()
    component = fetch_spanishdict_component(session, expression)
    return expression, build_surface_entry(expression, component)


def _expressions_from_mwe_layer():
    """Distinct MWE expressions that made it into the shared MWE layer.

    These are the phrases currently visible on cards — scraping just this
    subset produces the user-visible win fastest.
    """
    layer = load_json(MWE_LAYER_FILE, {})
    seen = set()
    if isinstance(layer, dict):
        for entries in layer.values():
            if not isinstance(entries, list):
                continue
            for e in entries:
                expr = (e.get("expression") or "").strip() if isinstance(e, dict) else ""
                if expr:
                    seen.add(expr)
    return sorted(seen)


def _expressions_from_phrases_cache():
    """Every distinct expression SpanishDict has ever returned across all word lookups."""
    cache = load_json(SPANISHDICT_PHRASES_CACHE, {})
    seen = set()
    if isinstance(cache, dict):
        for entries in cache.values():
            if not isinstance(entries, list):
                continue
            for e in entries:
                expr = (e.get("expression") or "").strip() if isinstance(e, dict) else ""
                if expr:
                    seen.add(expr)
    return sorted(seen)


def _entry_is_successful(entry):
    """Treat ``{"error": ...}`` sentinels and empty analyses as 'still needs work'."""
    if not isinstance(entry, dict):
        return False
    if entry.get("error"):
        return False
    analyses = entry.get("dictionary_analyses") or []
    return bool(analyses)


def main():
    parser = argparse.ArgumentParser(description="Scrape SpanishDict phrase-detail pages")
    parser.add_argument(
        "--source",
        choices=["mwe-layer", "phrases-cache"],
        default="mwe-layer",
        help=(
            "Which phrase set to scrape. 'mwe-layer' (default): expressions "
            "that actually appear on cards (~2k, ~12 min). 'phrases-cache': "
            "every phrase SpanishDict has ever returned (~30k, ~3 h)."
        ),
    )
    parser.add_argument("--force", action="store_true",
                        help="Refetch phrases already present in the detail cache")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Refetch phrases whose last fetch errored or returned nothing")
    parser.add_argument("--workers", type=int, default=4,
                        help="Concurrent fetch workers (default: 4). Throttle is global "
                             "(0.35s between requests) so workers mainly overlap I/O.")
    parser.add_argument("--save-every", type=int, default=50,
                        help="Write partial progress every N completed fetches (default: 50)")
    parser.add_argument("--max-phrases", type=int, default=None,
                        help="Only process the first N expressions (for testing)")
    parser.add_argument("--phrase", action="append", default=[],
                        help="Scrape only these phrases (repeatable; overrides --source)")
    args = parser.parse_args()

    explicit_phrases = sorted({p.strip() for p in (args.phrase or []) if p and p.strip()})
    if explicit_phrases:
        expressions = explicit_phrases
        source_label = "--phrase (explicit)"
    elif args.source == "mwe-layer":
        expressions = _expressions_from_mwe_layer()
        source_label = "mwe-layer (%s)" % MWE_LAYER_FILE
    else:
        expressions = _expressions_from_phrases_cache()
        source_label = "phrases-cache (%s)" % SPANISHDICT_PHRASES_CACHE

    if args.max_phrases is not None:
        expressions = expressions[:args.max_phrases]

    detail_cache = load_json(PHRASES_DETAIL_CACHE, {})

    queries = []
    for expr in expressions:
        if args.force:
            queries.append(expr)
            continue
        cached = detail_cache.get(expr)
        if cached is None:
            queries.append(expr)
            continue
        if args.retry_failed and not _entry_is_successful(cached):
            queries.append(expr)

    print("SpanishDict phrase-detail scraper")
    print("Source: %s" % source_label)
    print("Candidate expressions: %d" % len(expressions))
    print("Cache already covers:  %d" % len(detail_cache))
    print("Phrases to fetch:      %d" % len(queries))
    print("Workers: %d  (throttle: 0.35s global)" % max(1, args.workers))

    if not queries:
        print("Nothing to do.")
        return

    processed = 0
    successful = 0
    failed = 0
    save_every = max(1, args.save_every)
    start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_to_expr = {executor.submit(_fetch_phrase_detail, expr): expr for expr in queries}
        for future in concurrent.futures.as_completed(future_to_expr):
            expr = future_to_expr[future]
            try:
                _, entry = future.result()
                detail_cache[expr] = entry
                if _entry_is_successful(entry):
                    successful += 1
            except Exception as exc:
                failed += 1
                # Sentinel so we don't spin on the same expression next run.
                detail_cache[expr] = {"query": expr, "error": str(exc)[:200]}
            processed += 1
            if processed % save_every == 0:
                save_json(PHRASES_DETAIL_CACHE, detail_cache)
                elapsed = time.time() - start
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = (len(queries) - processed) / rate if rate > 0 else 0
                print("  %d/%d processed  (ok=%d failed=%d)  ~%.0fs remaining"
                      % (processed, len(queries), successful, failed, remaining))

    save_json(PHRASES_DETAIL_CACHE, detail_cache)
    elapsed = time.time() - start
    print("")
    print("Done. %d processed in %.0fs  (ok=%d failed=%d)"
          % (processed, elapsed, successful, failed))
    print("Wrote: %s" % PHRASES_DETAIL_CACHE)
    print("")
    print("Next: rebuild the MWE layer and final vocab")
    print("  .venv/bin/python3 pipeline/tool_5d_build_spanishdict_mwes.py")
    print("  .venv/bin/python3 pipeline/step_8a_assemble_vocabulary.py")


if __name__ == "__main__":
    main()
