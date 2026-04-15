#!/usr/bin/env python3
"""
step_5a_build_examples.py — Match example sentences to vocabulary.

Reads the word inventory and corpora (Tatoeba + OpenSubtitles), finds example
sentences for each word, scores them by easiness, and writes a keyed examples layer.
Tatoeba examples are preferred; OpenSubtitles fills remaining slots up to 50.

Usage:
    python3 pipeline/step_5a_build_examples.py [--max-lines N]

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/corpora/tatoeba/spa.txt
    Data/Spanish/corpora/opensubtitles/OpenSubtitles.en-es.{es,en}
    Data/Spanish/spanish_ranks.json

Output:
    Data/Spanish/layers/examples_raw.json  — {word: [{target, english, source, easiness}]}
"""

import argparse
import json
import random
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from statistics import median

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "word_inventory.json"
TATOEBA_FILE = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "tatoeba" / "spa.txt"
OPENSUBS_ES = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "opensubtitles" / "OpenSubtitles.en-es.es"
OPENSUBS_EN = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "opensubtitles" / "OpenSubtitles.en-es.en"
RANKS_FILE = PROJECT_ROOT / "Data" / "Spanish" / "spanish_ranks.json"
OUTPUT_FILE = PROJECT_ROOT / "Data" / "Spanish" / "layers" / "examples_raw.json"

SENTINEL_RANK = 999_999
DEFAULT_MAX_LINES = 5_000_000
MAX_EXAMPLES_PER_WORD = 20
MAX_CANDIDATES = 500          # random-sample cap before scoring
MIN_SENTENCE_WORDS = 3
MAX_SENTENCE_WORDS = 25
TOP_N_TRIVIAL = 100           # sentences using only top-N words are trivial

_TOKEN_RE = re.compile(r"[a-záéíóúüñ]+")

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


def compute_easiness(spanish_text, word_to_rank):
    tokens = tokenize(spanish_text)
    if not tokens:
        return SENTINEL_RANK
    ranks = []
    for t in tokens:
        rank = word_to_rank.get(t)
        if rank is None:
            rank = word_to_rank.get(strip_accents(t))
        if rank is None:
            rank = SENTINEL_RANK
        ranks.append(rank)
    return int(median(ranks))


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


OPENSUBS_CACHE = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "opensubtitles" / "cached_pairs.json.gz"


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


def build_sentence_index(sentences):
    index = defaultdict(list)
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
                f"\r    {pct:5.1f}%  ~{remaining:.0f}s remaining   "
            )
            sys.stdout.flush()
        tokens = tokenize(spa)
        if len(tokens) < MIN_SENTENCE_WORDS or len(tokens) > MAX_SENTENCE_WORDS:
            continue
        seen = set()
        for t in tokens:
            norm = strip_accents(t)
            if norm not in seen:
                seen.add(norm)
                index[norm].append(i)
    elapsed = time.time() - t0
    print(f"\r    Done in {elapsed:.1f}s" + " " * 30)
    return index


def is_trivial(spanish_text, word_to_rank):
    """True if every token is in the top-N most common words."""
    tokens = tokenize(spanish_text)
    if not tokens:
        return True
    return all(
        (word_to_rank.get(t) or word_to_rank.get(strip_accents(t)) or SENTINEL_RANK)
        <= TOP_N_TRIVIAL
        for t in tokens
    )


OVERLAP_WINDOW = 10      # ±rank window for co-study words
MAX_OVERLAP_TIER = 2     # cap benefit at 2 nearby words
PREFERRED_MAX_WORDS = 12 # sentences under this length pay no penalty
LENGTH_PENALTY_WEIGHT = 5  # per extra word above PREFERRED_MAX_WORDS
MAX_SENTENCE_LEN = 18    # hard reject above this


def overlap_tier(spanish_text, target_rank, inv_rank_lookup):
    """Count inventory words within ±OVERLAP_WINDOW of target rank.

    Capped at MAX_OVERLAP_TIER — having 2 co-study words is enough,
    more doesn't help and would bias toward long sentences.
    """
    if not inv_rank_lookup:
        return 0
    count = 0
    for t in tokenize(spanish_text):
        norm = strip_accents(t)
        rank = inv_rank_lookup.get(norm)
        if rank is not None and rank != target_rank:
            if abs(target_rank - rank) <= OVERLAP_WINDOW:
                count += 1
                if count >= MAX_OVERLAP_TIER:
                    return MAX_OVERLAP_TIER
    return count


def select_examples(candidate_indices, sentences, word_to_rank,
                    source="tatoeba", max_examples=MAX_EXAMPLES_PER_WORD,
                    exclude_targets=None, target_rank=0, inv_rank_lookup=None):
    # Cap candidates to avoid scoring huge lists for common words
    if len(candidate_indices) > MAX_CANDIDATES:
        candidate_indices = random.sample(candidate_indices, MAX_CANDIDATES)

    scored = []
    seen_targets = set(exclude_targets) if exclude_targets else set()
    for idx in candidate_indices:
        eng, spa = sentences[idx]
        key = spa.lower().strip()
        if key in seen_targets:
            continue
        seen_targets.add(key)
        # Skip trivial dialogue (all top-100 words)
        if is_trivial(spa, word_to_rank):
            continue
        # Hard reject sentences that are too long
        word_count = len(tokenize(spa))
        if word_count > MAX_SENTENCE_LEN:
            continue
        easiness = compute_easiness(spa, word_to_rank)
        tier = overlap_tier(spa, target_rank, inv_rank_lookup)
        length_pen = max(0, word_count - PREFERRED_MAX_WORDS) * LENGTH_PENALTY_WEIGHT
        scored.append({
            "target": spa, "english": eng, "source": source,
            "easiness": easiness,
            "_tier": tier, "_length_pen": length_pen,
        })

    # Sort: higher overlap tier first, then lower (easiness + length penalty)
    scored.sort(key=lambda x: (-x["_tier"], x["easiness"] + x["_length_pen"]))

    # Diversity: pick from thirds within the top candidates
    pool = scored[:max_examples * 3]  # generous pool
    if len(pool) <= max_examples:
        selected = pool
    else:
        third = len(pool) // 3
        buckets = [pool[:third], pool[third:2*third], pool[2*third:]]
        per_bucket = max_examples // 3
        selected = buckets[0][:per_bucket] + buckets[1][:per_bucket] + buckets[2][:per_bucket]
        # Fill remainder from whatever's left
        used = set(id(x) for x in selected)
        for ex in pool:
            if len(selected) >= max_examples:
                break
            if id(ex) not in used:
                selected.append(ex)

    # Remove internal scoring fields
    for ex in selected:
        del ex["_tier"]
        del ex["_length_pen"]
    return selected


def parse_args():
    parser = argparse.ArgumentParser(
        description="Match example sentences from corpora to vocabulary words."
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
    return parser.parse_args()


def main():
    args = parse_args()

    print("Loading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        inventory = json.load(f)
    print(f"  {len(inventory)} entries")

    print("Loading spanish_ranks.json...")
    with open(RANKS_FILE, encoding="utf-8") as f:
        word_to_rank = json.load(f)
    print(f"  {len(word_to_rank)} rank entries")

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
    tat_index = build_sentence_index(tat_sentences)
    print(f"  {len(tat_index)} unique normalized tokens indexed")

    # --- OpenSubtitles ---
    print(f"Loading OpenSubtitles (first {max_lines:,} lines)...")
    sub_sentences = load_opensubtitles(OPENSUBS_ES, OPENSUBS_EN, max_lines)
    print(f"  {len(sub_sentences)} sentence pairs after cleaning")

    print("Building OpenSubtitles sentence index...")
    sub_index = build_sentence_index(sub_sentences)
    print(f"  {len(sub_index)} unique normalized tokens indexed")

    # --- Match and merge ---
    print("Matching examples to vocabulary...")
    # Build rank lookup: normalised word -> position in inventory (by frequency order)
    inv_rank_lookup = {}
    for i, e in enumerate(inventory):
        norm = strip_accents(e["word"].lower())
        if norm not in inv_rank_lookup:
            inv_rank_lookup[norm] = i

    output = {}
    coverage = {"0": 0, "1-2": 0, "3-5": 0, "5+": 0}
    total_examples = 0

    for i, entry in enumerate(inventory):
        word_lower = entry["word"].lower()
        word_norm = strip_accents(word_lower)
        # If accent-stripping changes the word (sé→se, más→mas, él→el),
        # filter candidates to those containing the original accented form.
        # This prevents reflexive "se" sentences matching "sé" (I know), etc.
        accent_sensitive = (word_lower != word_norm)

        def _filter_accent(candidate_ids, sentences):
            if not accent_sensitive:
                return candidate_ids
            filtered = []
            for idx in candidate_ids:
                spa = sentences[idx][1].lower()
                # Check the accented form appears as a whole token
                if re.search(r'(?<![a-záéíóúüñ])' + re.escape(word_lower) + r'(?![a-záéíóúüñ])', spa):
                    filtered.append(idx)
            return filtered

        # Tatoeba first (preferred)
        tat_candidates = _filter_accent(tat_index.get(word_norm, []), tat_sentences)
        examples = select_examples(tat_candidates, tat_sentences, word_to_rank,
                                   source="tatoeba",
                                   target_rank=i, inv_rank_lookup=inv_rank_lookup)

        # Fill remaining slots with OpenSubtitles
        remaining = MAX_EXAMPLES_PER_WORD - len(examples)
        if remaining > 0:
            sub_candidates = _filter_accent(sub_index.get(word_norm, []), sub_sentences)
            if sub_candidates:
                # Pass Tatoeba targets to avoid cross-corpus duplicates
                existing_targets = {ex["target"].lower().strip() for ex in examples}
                sub_examples = select_examples(
                    sub_candidates, sub_sentences, word_to_rank,
                    source="opensubtitles", max_examples=remaining,
                    exclude_targets=existing_targets,
                    target_rank=i, inv_rank_lookup=inv_rank_lookup,
                )
                examples.extend(sub_examples)

        if examples:
            output[entry["word"]] = examples

        n = len(examples)
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

    # --- Results ---
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
