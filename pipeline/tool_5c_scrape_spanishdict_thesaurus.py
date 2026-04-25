#!/usr/bin/env python3
"""tool_5c_scrape_spanishdict_thesaurus.py — scrape SpanishDict thesaurus pages.

SpanishDict's thesaurus pages live at ``spanishdict.com/thesaurus/<word>`` and
are independent of the dictionary scraper. The redux blob exposes a
``thesaurusProps`` object with four arrays the layer builder joins:

- ``headword`` (``{id, source}``) — the queried lemma.
- ``linkedWords`` (``[{id, source}]``) — every word referenced anywhere on
  the page (synonyms + antonyms + the headword itself).
- ``senses`` (``[{id, wordId, partOfSpeechId, contextEs, contextEn}]``) —
  one entry per displayed sense, owned by ``wordId``.
- ``senseLinks`` (``[{senseLinkA, senseLinkB, relationship}]``) — the
  relationship graph. ``relationship`` is signed: ``+2`` strong synonym,
  ``+1`` weak/related, ``-1`` weak antonym, ``-2`` strong antonym.

The layer builder (``tool_5e_build_synonyms_layer.py``) walks this cache,
joins each link back to the underlying word, and partitions on the sign of
the relationship to produce ``{synonyms: [...], antonyms: [...]}`` per
lemma.

Idempotent: already-cached lemmas are skipped. Use ``--force`` to refetch.
``--word X`` scrapes a single lemma (debug). The default input set is the
distinct lemmas from ``Artists/spanish/vocabulary_master.json``.

Cost: SpanishDict is free, rate-limited by ``REQUEST_DELAY_SECONDS`` (0.35s
global). ~10k lemmas → ~1 hour one-off. Cached payload is ~1 KB per lemma.

Usage (from repo root):
    .venv/bin/python3 pipeline/tool_5c_scrape_spanishdict_thesaurus.py
    .venv/bin/python3 pipeline/tool_5c_scrape_spanishdict_thesaurus.py --word bonito
    .venv/bin/python3 pipeline/tool_5c_scrape_spanishdict_thesaurus.py --force
    .venv/bin/python3 pipeline/tool_5c_scrape_spanishdict_thesaurus.py --limit 50
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

import util_5c_spanishdict as sd_util
from util_5c_spanishdict import (
    SPANISHDICT_THESAURUS_CACHE,
    build_session,
    extract_thesaurus_payload,
    fetch_spanishdict_thesaurus,
    load_json,
    save_json,
)

VOCABULARY_MASTER = PROJECT_ROOT / "Artists" / "spanish" / "vocabulary_master.json"


def lemmas_from_master():
    """Distinct, lowercased, non-empty lemmas from the master vocabulary."""
    master = load_json(VOCABULARY_MASTER, {})
    if not isinstance(master, dict):
        return []
    seen = set()
    out = []
    for entry in master.values():
        if not isinstance(entry, dict):
            continue
        lemma = (entry.get("lemma") or entry.get("word") or "").strip().lower()
        if not lemma or lemma in seen:
            continue
        # Skip multi-word lemmas (the thesaurus page is single-word only).
        if " " in lemma:
            continue
        seen.add(lemma)
        out.append(lemma)
    return out


def _scrape_one(session, word):
    """Worker: fetch + extract for a single lemma. Returns (word, status, payload).

    ``status`` is one of ``"hit"``, ``"empty"``, ``"error"``. ``payload`` is the
    object to store in the cache (or the error dict for ``"error"``).
    """
    try:
        component = fetch_spanishdict_thesaurus(session, word)
    except Exception as exc:
        return word, "error", {"error": str(exc)[:200]}
    payload = extract_thesaurus_payload(component) if component else None
    if payload is None:
        return word, "empty", None
    return word, "hit", payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--word", help="Scrape a single lemma (debug)")
    parser.add_argument("--force", action="store_true", help="Refetch already-cached lemmas")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of lemmas to scrape")
    parser.add_argument(
        "--cache",
        default=str(SPANISHDICT_THESAURUS_CACHE),
        help="Output cache path (default: %(default)s)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Concurrent fetcher threads (default: 8). Use 1 for sequential.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Override per-request throttle in seconds (default: util's "
             "REQUEST_DELAY_SECONDS = 0.35). Lower → faster, higher 429 risk.",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Retry only the cache entries that previously failed with an "
             "error (e.g. 429 rate limits). Implies --force on those keys.",
    )
    args = parser.parse_args()

    if args.delay is not None:
        # The throttle lock is module-global, so all workers share one cadence.
        sd_util.REQUEST_DELAY_SECONDS = args.delay

    cache_path = Path(args.cache)
    cache = load_json(cache_path, {}) if cache_path.exists() else {}

    if args.retry_errors:
        # Pull just the entries previously stored as ``{"error": "..."}`` (no
        # ``headword`` key, so they're not real payloads). These are usually
        # 429s that exhausted the inner retry budget — re-running with a
        # gentler --delay typically clears them.
        targets = [
            w for w, payload in cache.items()
            if isinstance(payload, dict) and "error" in payload and "headword" not in payload
        ]
        if args.limit is not None:
            targets = targets[:args.limit]
        skipped = 0
    else:
        if args.word:
            targets = [args.word.strip().lower()]
        else:
            targets = lemmas_from_master()
        if args.limit is not None:
            targets = targets[:args.limit]
        pre_filter_count = len(targets)
        if not args.force:
            targets = [w for w in targets if w not in cache]
        skipped = pre_filter_count - len(targets)

    if not targets:
        print(f"Nothing to scrape (cache has {len(cache)} entries).")
        return

    workers = max(1, args.workers)
    delay = sd_util.REQUEST_DELAY_SECONDS
    if skipped:
        print(f"Skipping {skipped} already-cached lemma(s) "
              f"(use --force to refetch).")
    print(f"Scraping {len(targets)} lemma(s) with {workers} worker(s), "
          f"throttle {delay:.2f}s → {cache_path}")
    session = build_session()  # requests.Session is thread-safe for GETs
    fetched = 0
    empty = 0
    errors = 0
    started = time.time()
    total = len(targets)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_scrape_one, session, word): word for word in targets}
        for i, future in enumerate(as_completed(futures), 1):
            word, status, payload = future.result()
            if status == "error":
                errors += 1
                print(f"  [{i}/{total}] {word!r}: error {payload.get('error')}")
                cache[word] = payload
            elif status == "empty":
                empty += 1
                cache[word] = None  # mark as "no data" so we don't retry
            else:
                fetched += 1
                cache[word] = payload

            # Save every 50 completions so a crash doesn't lose hours of work.
            if i % 50 == 0:
                save_json(cache_path, cache)
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                remaining = (total - i) / rate if rate else 0
                print(f"  [{i}/{total}] {fetched} hits, {empty} empty, {errors} errs "
                      f"({rate:.1f} req/s, ~{remaining/60:.1f} min remaining)")

    save_json(cache_path, cache)
    print(f"\nDone. {fetched} hits, {empty} empty, {errors} errors.")
    print(f"Cache now has {len(cache)} entries → {cache_path}")


if __name__ == "__main__":
    main()
