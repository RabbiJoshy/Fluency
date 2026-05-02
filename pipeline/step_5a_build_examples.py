#!/usr/bin/env python3
"""
step_5a_build_examples.py — Match example sentences to vocabulary.

Reads the word inventory and corpora (Tatoeba + optional OpenSubtitles), finds
example sentences for each word, scores them by easiness, and writes a keyed
examples layer. Tatoeba examples are preferred; OpenSubtitles fills remaining
slots up to MAX_EXAMPLES_PER_WORD when enabled.

Usage:
    python3 pipeline/step_5a_build_examples.py [--language {spanish,french}]
                                               [--no-opensubtitles] [--max-lines N]

Inputs (paths derived from --language):
    Data/{Lang}/layers/word_inventory.json
    Data/{Lang}/corpora/tatoeba/{iso639-3}.txt
    Data/{Lang}/corpora/opensubtitles/OpenSubtitles.en-{xx}.{xx,en}   (optional)
    Data/{Lang}/{language}_ranks.json

Output:
    Data/{Lang}/layers/examples_raw.json  — {word: [{target, english, source, easiness}]}
"""

import argparse
import json
import random
import re
import sys
import time
import unicodedata
import zlib
from collections import defaultdict
from pathlib import Path
from statistics import median

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
from util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

# Bump when example-selection logic, scoring, or corpus sources change.
STEP_VERSION = 1
STEP_VERSION_NOTES = {
    1: "tatoeba preferred + opensubs fill, easiness scoring, diversity sampling",
}

# Per-language path config. Tatoeba file is named with ISO 639-3 (spa/fra);
# OpenSubtitles uses ISO 639-1 in the filename pair (es/fr).
_LANGUAGE_CONFIG = {
    "spanish": {
        "iso3": "spa",
        "iso2": "es",
        "ranks_file": "spanish_ranks.json",
    },
    "french": {
        "iso3": "fra",
        "iso2": "fr",
        "ranks_file": "french_ranks.json",
    },
    "dutch": {
        "iso3": "nld",
        "iso2": "nl",
        "ranks_file": "dutch_ranks.json",
    },
}

# Path globals — bound at runtime in main() once --language is known.
INVENTORY_FILE = None
TATOEBA_FILE = None
OPENSUBS_ES = None
OPENSUBS_EN = None
RANKS_FILE = None
OUTPUT_FILE = None
OPENSUBS_CACHE = None

SENTINEL_RANK = 999_999
DEFAULT_MAX_LINES = 5_000_000
MAX_EXAMPLES_PER_WORD = 20
# Pre-scoring sample cap. Was 500 (designed for fast iteration on small
# corpora); raised to 50k so every reasonable candidate gets scored, not
# random-sampled. Set lower to speed up iteration; set higher (or 0 = no
# cap) for maximum-quality runs on big corpora.
MAX_CANDIDATES = 50_000
MIN_SENTENCE_WORDS = 3
TOP_N_TRIVIAL = 100           # sentences using only top-N words are trivial

# Combined Spanish + French + Dutch letter set; harmless to over-match.
# Dutch adds the ĳ ligature (rare, but standard tokenizers preserve it).
_TOKEN_RE = re.compile(r"[a-zàáâäæçèéêëíîïñóôœùúûüÿĳ]+")

# Subtitle junk patterns — reject entire line if matched
_SUBTITLE_JUNK_RE = re.compile(
    r"^\s*$"                    # empty / whitespace-only
    r"|^\.{2,}"                 # leading ellipsis
    r"|[♪♫]"                    # music cues
    r"|^\[.*\]$"               # bracketed stage directions [risas]
    r"|<[^>]+>"                 # HTML tags <i> etc.
    r"|^\d+\s*$"               # bare numbers (leaked timecodes)
    r"|^[A-Z\s]{10,}:$"        # ALL-CAPS headers
)


def strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def tokenize(text):
    return _TOKEN_RE.findall(text.lower())


def clean_subtitle_line(line):
    """Strip subtitle artifacts. Returns cleaned string or None if junk."""
    line = line.strip()
    if not line:
        return None
    if _SUBTITLE_JUNK_RE.search(line):
        return None
    # Strip leading dialogue dash: "- Hola" -> "Hola"
    if line.startswith("- "):
        line = line[2:].strip()
    elif line.startswith("-"):
        line = line[1:].strip()
    if not line:
        return None
    return line


def load_opensubtitles(es_path, en_path, max_lines):
    """Load parallel OpenSubtitles corpus, sampling evenly across the full file.

    Uses stride-based sampling to avoid bias toward whichever movies/shows
    appear first in the file. Reads every Nth line to collect max_lines pairs.

    The full-corpus result is cached to cached_pairs.json.gz (~30MB) so
    subsequent runs skip the 60s stride-sampling step.
    """
    # Try cache first (only for full corpus, not subsampled)
    if OPENSUBS_CACHE.exists():
        import gzip
        print("    Loading cached pairs from {}...".format(OPENSUBS_CACHE.name))
        t0 = time.time()
        with gzip.open(OPENSUBS_CACHE, "rt", encoding="utf-8") as f:
            sentences = json.load(f)
        # Convert lists back to tuples
        sentences = [(eng, spa) for eng, spa in sentences]
        print(f"    {len(sentences):,} cached pairs loaded in {time.time() - t0:.1f}s")
        # Subsample if requesting fewer than cached
        if len(sentences) > max_lines:
            stride = max(1, len(sentences) // max_lines)
            sentences = sentences[::stride][:max_lines]
            print(f"    Subsampled to {len(sentences):,} pairs")
        return sentences

    # No cache — process from raw files
    # First pass: count total lines (fast, just counts newlines)
    print("    Counting total lines...")
    t0 = time.time()
    total = 0
    with open(es_path, "rb") as f:
        for _ in f:
            total += 1
    stride = max(1, total // max_lines)
    print(f"    {total:,} total lines, stride={stride} ({time.time() - t0:.1f}s)")

    sentences = []
    t0 = time.time()
    report_every = total // 20  # report every 5%
    with open(es_path, encoding="utf-8") as f_es, \
         open(en_path, encoding="utf-8") as f_en:
        for i, (line_es, line_en) in enumerate(zip(f_es, f_en)):
            if report_every and i % report_every == 0 and i > 0:
                pct = 100 * i / total
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                remaining = (total - i) / rate if rate > 0 else 0
                sys.stdout.write(
                    f"\r    {pct:5.1f}%  {len(sentences):,} kept  "
                    f"~{remaining:.0f}s remaining   "
                )
                sys.stdout.flush()
            if i % stride != 0:
                continue
            if len(sentences) >= max_lines:
                break
            spa = clean_subtitle_line(line_es)
            eng = clean_subtitle_line(line_en)
            if spa and eng:
                sentences.append((eng, spa))
    elapsed = time.time() - t0
    print(f"\r    Done: {len(sentences):,} pairs in {elapsed:.1f}s" + " " * 30)

    # Save cache for next time
    import gzip
    print(f"    Saving cache to {OPENSUBS_CACHE.name}...")
    t0 = time.time()
    with gzip.open(OPENSUBS_CACHE, "wt", encoding="utf-8") as f:
        json.dump(sentences, f, ensure_ascii=False)
    print(f"    Cached {len(sentences):,} pairs in {time.time() - t0:.1f}s")

    return sentences


def load_tatoeba(path):
    sentences = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                eng, spa = parts[0].strip(), parts[1].strip()
                if eng and spa:
                    sentences.append((eng, spa))
    return sentences


def build_sentence_index(sentences, word_to_rank, inv_rank_lookup,
                         phrase_to_inv_rank=None):
    """One-pass index build. Computes per-sentence scoring metadata once,
    drops trash (too short/long, trivial, no-inventory), and returns:
      - records: list[dict] of surviving sentences with precomputed scores
      - inv_index: dict[token_or_phrase, list[record_idx]] for fast lookup

    Single-token index keys are literal tokens. Wiktionary headwords + the
    inventory both treat accented and unaccented forms as distinct (à vs a,
    où vs ou, sé vs se), so the example index does the same.

    Multi-token inventory entries (l', parce que, grand-père, etc.) can't be
    captured by token-level lookup because the tokenizer regex splits on
    apostrophes, hyphens, and spaces. Pass them via phrase_to_inv_rank — they
    get scanned with a precompiled multi-pattern regex per kept sentence,
    then folded into both inv_ranks (drives tier scoring) and inv_index
    (drives candidate lookup at scoring time).
    """
    phrase_re = None
    if phrase_to_inv_rank:
        # Longest-first ordering so "parce que" wins over "que" at overlaps.
        phrases_sorted = sorted(phrase_to_inv_rank, key=len, reverse=True)
        phrase_re = re.compile("|".join(re.escape(p) for p in phrases_sorted))

    records = []
    inv_index = defaultdict(list)
    drop_short = drop_long = drop_trivial = drop_no_inv = 0
    total = len(sentences)
    report_every = max(1, total // 20)
    t0 = time.time()

    for i, (eng, spa) in enumerate(sentences):
        if i % report_every == 0 and i > 0:
            pct = 100 * i / total
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate if rate > 0 else 0
            sys.stdout.write(
                f"\r    {pct:5.1f}%  {len(records):,} kept  "
                f"~{remaining:.0f}s remaining   "
            )
            sys.stdout.flush()

        tokens = tokenize(spa)
        length = len(tokens)
        if length < MIN_SENTENCE_WORDS:
            drop_short += 1
            continue
        if length > MAX_SENTENCE_LEN:
            drop_long += 1
            continue

        # Single rank pass — reused for trivial check and easiness median.
        ranks = []
        for t in tokens:
            r = word_to_rank.get(t)
            if r is None:
                r = word_to_rank.get(strip_accents(t))
            if r is None:
                r = SENTINEL_RANK
            ranks.append(r)

        if all(r <= TOP_N_TRIVIAL for r in ranks):
            drop_trivial += 1
            continue

        # Inventory ranks present in this sentence (deduped, sorted for
        # stable downstream consumption + future bisect-based queries).
        inv_ranks_set = set()
        for t in tokens:
            ir = inv_rank_lookup.get(t)
            if ir is not None:
                inv_ranks_set.add(ir)

        # Phrase pass: catch multi-token inventory entries the tokenizer
        # splits (l', parce que, grand-père, etc.).
        matched_phrases = ()
        if phrase_re is not None:
            matched_phrases = set(phrase_re.findall(spa.lower()))
            for p in matched_phrases:
                inv_ranks_set.add(phrase_to_inv_rank[p])

        if not inv_ranks_set:
            drop_no_inv += 1
            continue

        easiness = int(median(ranks))
        rec_idx = len(records)
        records.append({
            "eng": eng,
            "spa": spa,
            "length": length,
            "easiness": easiness,
            "inv_ranks": tuple(sorted(inv_ranks_set)),
        })
        seen = set()
        for t in tokens:
            if t not in seen:
                seen.add(t)
                inv_index[t].append(rec_idx)
        for p in matched_phrases:
            inv_index[p].append(rec_idx)

    elapsed = time.time() - t0
    print(f"\r    Done in {elapsed:.1f}s — kept {len(records):,} of {total:,} "
          f"(dropped: {drop_short} short, {drop_long} long, "
          f"{drop_trivial} trivial, {drop_no_inv} no-inv)" + " " * 10)
    return records, inv_index


# Co-study scoring. A candidate sentence's overlap_tier counts how many of
# its tokens have a corpus rank within ±OVERLAP_WINDOW of the target word's
# rank. Higher tier = denser pedagogical pairing (target + nearby-difficulty
# vocab in one sentence).
#
# Was OVERLAP_WINDOW=10 / MAX_OVERLAP_TIER=2 — narrow window + low cap meant
# even a 5-word-rich sentence scored the same as a 2-word-rich one, and
# many medium-frequency words couldn't find tier-2 matches in random 500
# candidates. Raised to 50/10: a wider "nearby" set + uncapped-in-practice
# tiebreak so the best co-study sentences actually float to the top.
OVERLAP_WINDOW = 50
MAX_OVERLAP_TIER = 10
PREFERRED_MAX_WORDS = 12 # sentences under this length pay no penalty
LENGTH_PENALTY_WEIGHT = 5  # per extra word above PREFERRED_MAX_WORDS
MAX_SENTENCE_LEN = 18    # hard reject above this


def select_examples(record_indices, records, source="tatoeba",
                    max_examples=MAX_EXAMPLES_PER_WORD,
                    exclude_targets=None, target_rank=0, word=""):
    # Cap candidates with a per-word deterministic RNG so reruns are stable —
    # same word always samples the same candidates regardless of when step_5a
    # runs. Without this, rerunning step_5a churns example_raw entries for any
    # word with >MAX_CANDIDATES candidates, silently invalidating downstream
    # sense_assignments that reference example indices.
    if len(record_indices) > MAX_CANDIDATES:
        seed = zlib.crc32(word.encode("utf-8")) if word else 0
        rng = random.Random(seed)
        record_indices = rng.sample(record_indices, MAX_CANDIDATES)

    scored = []
    seen_targets = set(exclude_targets) if exclude_targets else set()
    for idx in record_indices:
        rec = records[idx]
        spa = rec["spa"]
        key = spa.lower().strip()
        if key in seen_targets:
            continue
        seen_targets.add(key)

        # Co-study neighbours: inventory ranks within ±OVERLAP_WINDOW of
        # target_rank, excluding target itself. Full set (uncapped) drives
        # greedy set-cover; tier is the capped count used for sort ordering
        # (cap avoids long-sentence bias in tiebreak).
        neighbours = frozenset(
            r for r in rec["inv_ranks"]
            if r != target_rank and abs(r - target_rank) <= OVERLAP_WINDOW
        )
        tier = min(MAX_OVERLAP_TIER, len(neighbours))

        length_pen = max(0, rec["length"] - PREFERRED_MAX_WORDS) * LENGTH_PENALTY_WEIGHT

        scored.append({
            "target": spa,
            "english": rec["eng"],
            "source": source,
            "easiness": rec["easiness"],
            "_tier": tier,
            "_length_pen": length_pen,
            "_neighbours": neighbours,
        })

    # Sort: higher overlap tier first, then lower (easiness + length penalty).
    # This drives the greedy tiebreak — within ties on uncovered count, the
    # earlier (better-scored) candidate wins.
    scored.sort(key=lambda x: (-x["_tier"], x["easiness"] + x["_length_pen"]))

    # Greedy set-cover diversity. From the sorted pool, filter to tier > 0
    # (sentences with no nearby co-study vocab don't help) and at each step
    # pick the candidate that introduces the most *uncovered* nearby-rank
    # neighbours. Stops when no candidate adds anything new OR when
    # max_examples reached. Pool capped so the inner loop stays cheap on
    # high-frequency words; widening it past 200 produces diminishing returns
    # because rare neighbours are usually already covered by top-tier sentences.
    GREEDY_POOL_SIZE = max(200, max_examples * 10)
    pool = [c for c in scored if c["_tier"] > 0][:GREEDY_POOL_SIZE]

    selected = []
    covered = set()
    while len(selected) < max_examples and pool:
        best_idx = None
        best_new = 0
        for i, c in enumerate(pool):
            new_count = len(c["_neighbours"] - covered)
            if new_count > best_new:
                best_new = new_count
                best_idx = i
        if best_idx is None:
            break  # no remaining candidate adds uncovered neighbours
        c = pool.pop(best_idx)
        selected.append(c)
        covered |= c["_neighbours"]

    # Tier-0 fallback: if greedy found nothing (the word's candidates all
    # have tier=0 — no nearby co-study vocab in any sentence), fall back to
    # easiness-sorted candidates so every word with at least one indexed
    # candidate gets at least one example. Only triggers on len(selected)==0
    # so the diversity goal is preserved for words with co-study evidence.
    if not selected and scored:
        fallback = sorted(scored, key=lambda x: x["easiness"] + x["_length_pen"])
        selected = fallback[:max_examples]

    # Remove internal scoring fields
    for ex in selected:
        del ex["_tier"]
        del ex["_length_pen"]
        del ex["_neighbours"]
    return selected


def _backfill_rare_examples(output, inventory, raw_es_path, raw_en_path,
                            word_to_rank, inv_rank_lookup, phrase_to_inv_rank,
                            max_per_word, threshold, restrict_to=None):
    """Streaming pass over the raw OpenSubs files to backfill examples for
    inventory words that finished the main pass with < threshold examples.

    Why streaming: the raw corpus is ~3 GB / ~30M parallel pairs. The main
    pass works from a 5M-pair stride-sampled cache (~30 MB), so rare words
    with corpus_count ≤ 10 typically end up with 1-2 examples. Streaming the
    raw file once, retaining only matches for the ~few-thousand undersupplied
    target words, costs ~5 min wall + ~250 MB peak — far cheaper than
    rebuilding the cache from the full corpus.

    Existing examples are preserved verbatim (so example indices stay stable
    for downstream sense_assignments). New examples are appended.
    """
    # 1. Identify targets
    targets = {}  # word_lower -> (target_rank, original_word, slots)
    target_words_set = set()       # single-token target lookups
    target_phrase_words = set()    # phrase target lookups
    for i, e in enumerate(inventory):
        wl = e["word"].lower()
        if restrict_to is not None and wl not in restrict_to:
            continue
        n = len(output.get(e["word"], []))
        if n >= threshold:
            continue
        slots = max_per_word - n
        if slots <= 0:
            continue
        targets[wl] = (i, e["word"], slots)
        if any(c in wl for c in " '-"):
            target_phrase_words.add(wl)
        else:
            target_words_set.add(wl)

    if not targets:
        print("Backfill: no undersupplied words.")
        return
    print(f"Backfill: {len(targets):,} undersupplied words "
          f"(<{threshold} examples). Streaming raw OpenSubs...")

    # Reuse the full-inventory phrase regex so inv_ranks gets the same scoring
    # signal it would in the main indexer (preserves tier accuracy).
    full_phrase_re = None
    if phrase_to_inv_rank:
        phrases_sorted = sorted(phrase_to_inv_rank, key=len, reverse=True)
        full_phrase_re = re.compile("|".join(re.escape(p) for p in phrases_sorted))

    # 2. Stream the raw files. Cap candidates per target to avoid runaway
    # memory on marginally-undersupplied common-ish words.
    candidates_by_target = defaultdict(list)
    cap_per_target = max_per_word * 5
    line_count = 0
    matched_count = 0
    drop_short = drop_long = drop_trivial = drop_no_inv = 0
    t0 = time.time()

    with open(raw_es_path, encoding="utf-8") as f_es, \
         open(raw_en_path, encoding="utf-8") as f_en:
        for line_es, line_en in zip(f_es, f_en):
            line_count += 1
            if line_count % 1_000_000 == 0:
                elapsed = time.time() - t0
                rate = line_count / elapsed if elapsed > 0 else 0
                sys.stdout.write(
                    f"\r    {line_count:,} lines  "
                    f"{matched_count:,} matches  "
                    f"{rate/1000:.0f}k lines/s   "
                )
                sys.stdout.flush()

            spa = clean_subtitle_line(line_es)
            eng = clean_subtitle_line(line_en)
            if not spa or not eng:
                continue

            tokens = tokenize(spa)
            length = len(tokens)
            if length < MIN_SENTENCE_WORDS:
                drop_short += 1
                continue
            if length > MAX_SENTENCE_LEN:
                drop_long += 1
                continue

            ranks = []
            for t in tokens:
                r = word_to_rank.get(t)
                if r is None:
                    r = word_to_rank.get(strip_accents(t))
                if r is None:
                    r = SENTINEL_RANK
                ranks.append(r)
            if all(r <= TOP_N_TRIVIAL for r in ranks):
                drop_trivial += 1
                continue

            inv_ranks_set = set()
            for t in tokens:
                ir = inv_rank_lookup.get(t)
                if ir is not None:
                    inv_ranks_set.add(ir)
            spa_lower = spa.lower()
            matched_phrases = ()
            if full_phrase_re is not None:
                matched_phrases = set(full_phrase_re.findall(spa_lower))
                for p in matched_phrases:
                    inv_ranks_set.add(phrase_to_inv_rank[p])
            if not inv_ranks_set:
                drop_no_inv += 1
                continue

            # Target match: tokens ∩ target_words_set, plus matched_phrases ∩
            # target_phrase_words (the latter requires the phrase to be both a
            # target AND have shown up in the regex scan above).
            matched_targets = set()
            for t in tokens:
                if t in target_words_set:
                    matched_targets.add(t)
            if matched_phrases and target_phrase_words:
                matched_targets |= matched_phrases & target_phrase_words
            if not matched_targets:
                continue

            matched_count += 1
            easiness = int(median(ranks))
            record = {
                "eng": eng,
                "spa": spa,
                "length": length,
                "easiness": easiness,
                "inv_ranks": tuple(sorted(inv_ranks_set)),
            }
            for t in matched_targets:
                bucket = candidates_by_target[t]
                if len(bucket) < cap_per_target:
                    bucket.append(record)

    elapsed = time.time() - t0
    print(f"\r    Done in {elapsed:.1f}s — scanned {line_count:,} lines, "
          f"{matched_count:,} target-matching records collected "
          f"(dropped: {drop_short} short, {drop_long} long, "
          f"{drop_trivial} trivial, {drop_no_inv} no-inv)" + " " * 5)

    # 3. Score and select per target. Re-uses select_examples, which pulls
    # in greedy + tier-0 fallback for free.
    appended_total = 0
    words_topped_up = 0
    for wl, records in candidates_by_target.items():
        target_rank, original_word, slots = targets[wl]
        existing_for_word = output.get(original_word, [])
        existing_keys = {ex["target"].lower().strip() for ex in existing_for_word}
        new_examples = select_examples(
            list(range(len(records))), records,
            source="opensubtitles",
            max_examples=slots,
            exclude_targets=existing_keys,
            target_rank=target_rank,
            word=wl,
        )
        if new_examples:
            output[original_word] = existing_for_word + new_examples
            appended_total += len(new_examples)
            words_topped_up += 1

    print(f"  added {appended_total:,} examples to {words_topped_up:,} "
          f"of {len(targets):,} target words")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Match example sentences from corpora to vocabulary words."
    )
    parser.add_argument(
        "--language", default="spanish", choices=list(_LANGUAGE_CONFIG.keys()),
        help="Target language (default: spanish)"
    )
    parser.add_argument(
        "--no-opensubtitles", action="store_true",
        help="Skip OpenSubtitles entirely (Tatoeba-only mode)"
    )
    parser.add_argument(
        "--max-lines", type=int, default=DEFAULT_MAX_LINES,
        help="Max OpenSubtitles lines to read (default: %(default)s)"
    )
    parser.add_argument(
        "--half", action="store_true",
        help="Use half the corpus (faster iterative runs)"
    )
    parser.add_argument(
        "--tenth", action="store_true",
        help="Use a tenth of the corpus (fastest iteration)"
    )
    parser.add_argument(
        "--word", action="append", default=[],
        help="Only regenerate examples for these surface words (repeatable). "
             "Loads existing examples_raw.json and replaces only the targeted "
             "entries; all other entries are preserved verbatim. Use this for "
             "surgical fixes when a full rebuild would invalidate downstream "
             "sense_assignments via example index drift."
    )
    parser.add_argument(
        "--max-candidates", type=int, default=MAX_CANDIDATES,
        help="Pre-scoring sample cap (default %(default)s). 0 = no cap (score "
             "every indexed candidate; slow on huge corpora but maximally "
             "thorough). Lower for faster iteration."
    )
    parser.add_argument(
        "--max-overlap-tier", type=int, default=MAX_OVERLAP_TIER,
        help="Cap on the co-study count contribution to a sentence's score "
             "(default %(default)s). With many candidates, raise this so "
             "sentences with 5-10+ nearby words actually outrank sentences "
             "with just 2."
    )
    parser.add_argument(
        "--overlap-window", type=int, default=OVERLAP_WINDOW,
        help="±rank window defining 'nearby' words for the co-study tier "
             "(default %(default)s). Narrower keeps difficulty tightly "
             "matched; wider gives more candidate sentences a tier > 0."
    )
    parser.add_argument(
        "--no-backfill-rare", action="store_true",
        help="Disable the post-pass streaming scan of the raw OpenSubs file "
             "for inventory words that finished with < MAX_EXAMPLES_PER_WORD "
             "examples. Default: backfill is on. The cache is stride-sampled, "
             "so rare words underflow without it; off only for diagnostics."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Allow a full rebuild even when examples_raw.json already exists. "
             "WARNING: re-runs greedy selection for every word, which changes "
             "example indices and invalidates all downstream sense_assignments. "
             "Only use this when you intend to re-classify from scratch. "
             "For safe alternatives see --word and tool_5a_extend_examples.py."
    )
    return parser.parse_args()


def _bind_paths(language):
    """Bind module-level path globals from --language."""
    global INVENTORY_FILE, TATOEBA_FILE, OPENSUBS_ES, OPENSUBS_EN
    global RANKS_FILE, OUTPUT_FILE, OPENSUBS_CACHE
    cfg = _LANGUAGE_CONFIG[language]
    lang_dir = language.capitalize()
    base = PROJECT_ROOT / "Data" / lang_dir
    INVENTORY_FILE = base / "layers" / "word_inventory.json"
    TATOEBA_FILE = base / "corpora" / "tatoeba" / f"{cfg['iso3']}.txt"
    OPENSUBS_ES = base / "corpora" / "opensubtitles" / f"OpenSubtitles.en-{cfg['iso2']}.{cfg['iso2']}"
    OPENSUBS_EN = base / "corpora" / "opensubtitles" / f"OpenSubtitles.en-{cfg['iso2']}.en"
    OPENSUBS_CACHE = base / "corpora" / "opensubtitles" / "cached_pairs.json.gz"
    RANKS_FILE = base / cfg["ranks_file"]
    OUTPUT_FILE = base / "layers" / "examples_raw.json"


def main():
    args = parse_args()
    _bind_paths(args.language)

    # Safety guard: refuse to overwrite an existing examples_raw.json unless
    # --force is given explicitly OR --word limits scope to specific entries.
    #
    # A full rebuild re-runs greedy selection for every word. Even a tiny
    # change in corpus content or candidate ordering can shift which examples
    # get picked, which changes their positions in the output list. Downstream
    # sense_assignments store example indices like [0, 1, 5] — if position 5
    # is now a different sentence, every Gemini classification that touched
    # that word is silently wrong.
    #
    # Safe alternatives:
    #   --word WORD                  Regenerate specific words (all others preserved)
    #   tool_5a_extend_examples.py   Append more examples without touching existing ones
    #   --force                      Full rebuild (only when you intend to re-classify)
    target_words = {w.lower() for w in args.word} if args.word else None
    if OUTPUT_FILE.exists() and target_words is None and not args.force:
        print(
            f"\nERROR: {OUTPUT_FILE} already exists.\n"
            "\nA full rebuild re-runs greedy for every word and changes example\n"
            "indices, silently invalidating all downstream sense_assignments.\n"
            "\nSafe alternatives:\n"
            "  --word WORD          Regenerate only that word (all others preserved)\n"
            "  tool_5a_extend_examples.py --target N\n"
            "                       Append more examples without disturbing anything\n"
            "  --force              Full rebuild (WARNING: invalidates sense_assignments)"
        )
        sys.exit(1)

    # Apply runtime tunables (mutate module globals so build_sentence_index
    # and select_examples see the new values).
    global MAX_CANDIDATES, MAX_OVERLAP_TIER, OVERLAP_WINDOW
    MAX_CANDIDATES = args.max_candidates if args.max_candidates > 0 else 10**12
    MAX_OVERLAP_TIER = args.max_overlap_tier
    OVERLAP_WINDOW = args.overlap_window
    print(f"Scoring config: max_candidates={args.max_candidates or 'unlimited'}, "
          f"max_overlap_tier={MAX_OVERLAP_TIER}, overlap_window=±{OVERLAP_WINDOW}")

    print("Loading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        inventory = json.load(f)
    print(f"  {len(inventory)} entries")

    print(f"Loading {RANKS_FILE.name}...")
    with open(RANKS_FILE, encoding="utf-8") as f:
        word_to_rank = json.load(f)
    print(f"  {len(word_to_rank)} rank entries")

    # Inventory rank lookup: literal surface word -> position in inventory.
    # Built before indexing so the indexer can drop no-inventory sentences in
    # one pass. Keyed by literal token (matches the sentence index keys).
    inv_rank_lookup = {}
    for i, e in enumerate(inventory):
        wl = e["word"].lower()
        if wl not in inv_rank_lookup:
            inv_rank_lookup[wl] = i

    # Multi-token inventory entries (hyphen/apostrophe/space). The tokenizer
    # regex splits on these chars, so per-token lookup never finds them —
    # build_sentence_index does a phrase scan to fill the gap.
    phrase_to_inv_rank = {}
    for i, e in enumerate(inventory):
        w = e["word"].lower()
        if any(c in w for c in " '-") and w not in phrase_to_inv_rank:
            phrase_to_inv_rank[w] = i
    print(f"  {len(phrase_to_inv_rank)} multi-token entries (phrase-indexed)")

    # --- Corpora ---
    if args.tenth:
        max_lines = args.max_lines // 10
        stride = 10
        print("*** --tenth mode: using 1/10 corpus for fastest iteration ***\n")
    elif args.half:
        max_lines = args.max_lines // 2
        stride = 2
        print("*** --half mode: using half corpus for faster iteration ***\n")
    else:
        max_lines = args.max_lines
        stride = 1

    print("Loading Tatoeba corpus...")
    tat_sentences = load_tatoeba(TATOEBA_FILE)
    if stride > 1:
        tat_sentences = tat_sentences[::stride]
    print(f"  {len(tat_sentences)} sentence pairs")

    print("Building Tatoeba sentence index...")
    tat_records, tat_index = build_sentence_index(tat_sentences, word_to_rank, inv_rank_lookup, phrase_to_inv_rank)
    print(f"  {len(tat_index)} unique tokens indexed across {len(tat_records):,} kept sentences")
    del tat_sentences  # records carry eng/spa from here on

    # --- OpenSubtitles (optional) ---
    if args.no_opensubtitles:
        print("Skipping OpenSubtitles (--no-opensubtitles).")
        sub_records = []
        sub_index = {}
    else:
        print(f"Loading OpenSubtitles (first {max_lines:,} lines)...")
        sub_sentences = load_opensubtitles(OPENSUBS_ES, OPENSUBS_EN, max_lines)
        print(f"  {len(sub_sentences)} sentence pairs after cleaning")

        print("Building OpenSubtitles sentence index...")
        sub_records, sub_index = build_sentence_index(sub_sentences, word_to_rank, inv_rank_lookup, phrase_to_inv_rank)
        print(f"  {len(sub_index)} unique tokens indexed across {len(sub_records):,} kept sentences")
        del sub_sentences

    # --- Match and merge ---
    print("Matching examples to vocabulary...")

    # --word mode: load existing examples_raw and regenerate only targeted
    # entries. All other entries stay byte-identical, so downstream sense
    # assignments remain valid for the words we don't touch.
    target_words = {w.lower() for w in args.word} if args.word else None
    output = {}
    if target_words is not None:
        if OUTPUT_FILE.exists():
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                output = json.load(f)
            print(f"\n--word mode: loaded existing {OUTPUT_FILE.name} "
                  f"({len(output)} entries); regenerating only: "
                  f"{sorted(target_words)}")
        else:
            print(f"\n--word mode: {OUTPUT_FILE} not found; will create with "
                  f"only the {len(target_words)} targeted entries")

    for i, entry in enumerate(inventory):
        word_lower = entry["word"].lower()

        if target_words is not None and word_lower not in target_words:
            continue  # preserve existing entry verbatim

        # Tatoeba first (preferred). Index lookups are now strict — sentences
        # for "ou" don't include "où"-content and vice versa, so no post-filter.
        tat_candidates = tat_index.get(word_lower, [])
        examples = select_examples(tat_candidates, tat_records,
                                   source="tatoeba",
                                   target_rank=i, word=word_lower)

        # Fill remaining slots with OpenSubtitles
        remaining = MAX_EXAMPLES_PER_WORD - len(examples)
        if remaining > 0:
            sub_candidates = sub_index.get(word_lower, [])
            if sub_candidates:
                # Pass Tatoeba targets to avoid cross-corpus duplicates
                existing_targets = {ex["target"].lower().strip() for ex in examples}
                sub_examples = select_examples(
                    sub_candidates, sub_records,
                    source="opensubtitles", max_examples=remaining,
                    exclude_targets=existing_targets,
                    target_rank=i, word=word_lower,
                )
                examples.extend(sub_examples)

        if examples:
            output[entry["word"]] = examples
        elif target_words is not None and entry["word"] in output:
            # Targeted regeneration produced zero examples — drop stale entry.
            del output[entry["word"]]

    # Backfill rare words from the raw OpenSubs file. Default on; opt-out
    # for diagnostics. Skipped when --no-opensubtitles (nothing to backfill
    # from). In --word mode, restricted to the targeted words so non-targeted
    # entries stay byte-identical.
    if not args.no_backfill_rare and not args.no_opensubtitles:
        _backfill_rare_examples(
            output, inventory,
            OPENSUBS_ES, OPENSUBS_EN,
            word_to_rank, inv_rank_lookup, phrase_to_inv_rank,
            max_per_word=MAX_EXAMPLES_PER_WORD,
            threshold=MAX_EXAMPLES_PER_WORD,
            restrict_to=target_words,
        )

    # Recompute coverage from the final output dict so backfill counts land
    # in the printed breakdown.
    coverage = {"0": 0, "1-2": 0, "3-5": 0, "5+": 0}
    total_examples = 0
    for entry in inventory:
        n = len(output.get(entry["word"], []))
        total_examples += n
        if n == 0:
            coverage["0"] += 1
        elif n <= 2:
            coverage["1-2"] += 1
        elif n <= 5:
            coverage["3-5"] += 1
        else:
            coverage["5+"] += 1

    print(f"\nWriting {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    write_sidecar(OUTPUT_FILE, make_meta("build_examples", STEP_VERSION))

    # --- Results ---
    if target_words is not None:
        # Targeted summary — only the words we regenerated. Full-coverage
        # stats are meaningless because we skipped most of the inventory.
        print(f"\n{'='*50}")
        print(f"TARGETED REBUILD ({len(target_words)} words)")
        print(f"{'='*50}")
        for entry in inventory:
            if entry["word"].lower() in target_words:
                n = len(output.get(entry["word"], []))
                print(f"  {entry['word']}: {n} examples")
        print(f"\nTotal entries in {OUTPUT_FILE.name}: {len(output)}")
    else:
        tat_count = sum(1 for exs in output.values() for ex in exs if ex["source"] == "tatoeba")
        sub_count = sum(1 for exs in output.values() for ex in exs if ex["source"] == "opensubtitles")

        print(f"\n{'='*50}")
        print("RESULTS")
        print(f"{'='*50}")
        print(f"Total vocabulary entries: {len(inventory)}")
        print(f"Total examples attached:  {total_examples}")
        print(f"  From Tatoeba:       {tat_count:,}")
        print(f"  From OpenSubtitles: {sub_count:,}")
        print(f"")
        print(f"Coverage breakdown:")
        print(f"  0 examples:   {coverage['0']:5d} words")
        print(f"  1-2 examples: {coverage['1-2']:5d} words")
        print(f"  3-5 examples: {coverage['3-5']:5d} words")
        print(f"  5+ examples:  {coverage['5+']:5d} words")
        print(f"")
        pct = 100 * (len(inventory) - coverage["0"]) / len(inventory)
        print(f"Words with at least 1 example: {pct:.1f}%")


if __name__ == "__main__":
    main()
