#!/usr/bin/env python3
"""
tool_5a_build_backup_examples.py — Sense-free "in the wild" example sentences.

A parallel journey from corpus to app that deliberately does NOT depend on
sense assignment. Every sentence here is attached to a WORD, never to a sense,
so this layer stays valid while sense assignment is still being reworked.

Why it is not step_5a
---------------------
`step_5a_build_examples` optimises for CO-STUDY: it scores a candidate by how
many of its other words sit within +/-OVERLAP_WINDOW (50) ranks of the target,
so a set of cards reinforces itself. That is the right goal for the sentence
shown ON the card.

These backup sentences want the opposite property — comprehensible input. The
only word that should be new is the target; everything else should already be
known. Because frequency rank is stable, "already known" is approximated
without any progress data, recency, or set membership: a word more frequent
than the target has been met earlier in the deck by construction. That makes
this layer computable once, offline, and identical for every learner.

Selection
---------
Scored, not gated. Every non-target token carries a difficulty relative to the
target's rank R:

    d(r) = 0                     when r <= R   (met earlier in the deck)
    d(r) = log10(r / R)          when r  > R   (how many multiples beyond)

This is deliberately continuous. A fixed "known floor" said every word under
rank 1000 was free, which is a cliff: a learner at 600 was told a rank-950 word
cost nothing while a rank-1050 word was expensive. Under the ratio, a rank-1050
word costs a learner at 600 about 0.24, and one at 100 about 1.02 — pressure
that eases smoothly as the learner descends the list, so more of the corpus
becomes admissible the further in they get, with no constant to tune.

It also removes the need for the old hard `harder <= N` gate. Since candidates
are ranked rather than rejected, the most frequent words cannot be starved: they
simply take the cheapest sentences available to them.

One new word is the goal, not zero. Nine known words plus a single rank-40,000
word is a normal sentence and good input; three unknowns is not. Summed log
difficulty encodes that directly — one nearby unknown is a rounding error, a
pile of distant ones is not — so nothing has to target a count explicitly.

Proper nouns cost nothing. They are detected from the corpus itself (unranked
tokens that appear capitalised mid-sentence) rather than a stoplist, so this
carries to other languages. Tatoeba is 15% Tom/Mary sentences, and charging
those names as unknown vocabulary was spending the whole difficulty budget on
material a learner reads straight through.

Length is a band, not a ceiling. Very short sentences are as unhelpful as very
long ones — "Es así." teaches nothing about usage — so anything outside
PREFERRED_MIN_WORDS..PREFERRED_MAX_WORDS pays a penalty in the same units as
difficulty, and the band sits where ordinary sentences live.

Output
------
`Data/{Lang}/vocabulary.backup_examples.index.json`   — manifest
`Data/{Lang}/backup_examples/backup_examples.NNN.json` — {word_id: [sentences]}

Sharded by deck position, not by id hash: a study set is ~20 consecutive
positions, so one shard covers a whole level, where hashing would scatter the
same 20 cards across every shard. The app derives the shard arithmetically —
`floor((rank - 1) / shardSize)` — so no per-word lookup table has to ship.

Deliberately separate from `vocabulary.examples.json`: the shard is fetched
only when the learner opens the sentence list, so the deck payload every
session pays for does not grow.

Usage:
    python3 pipeline/tool_5a_build_backup_examples.py --language spanish
    python3 pipeline/tool_5a_build_backup_examples.py --language spanish \
        --opensubtitles --max-lines 2000000       # slow; Tatoeba-only default
"""

import argparse
import json
import math
import random
import sys
import zlib
from collections import defaultdict
from pathlib import Path
from statistics import median

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

from step_5a_build_examples import (  # noqa: E402
    SENTINEL_RANK,
    clean_subtitle_line,
    load_opensubtitles,
    load_tatoeba,
    strip_accents,
    tokenize,
)
from util_5a_example_id import example_id  # noqa: E402
from util_pipeline_meta import make_meta, write_sidecar  # noqa: E402

STEP_VERSION = 1
STEP_VERSION_NOTES = {
    1: "rank-monotone comprehensible-input selection, sense-free, word-keyed",
}

_LANGUAGE_CONFIG = {
    "spanish": {"iso3": "spa", "iso2": "es", "ranks_file": "spanish_ranks.json"},
    "french": {"iso3": "fra", "iso2": "fr", "ranks_file": "french_ranks.json"},
    "dutch": {"iso3": "nld", "iso2": "nl", "ranks_file": "dutch_ranks.json"},
}

DEFAULT_PER_WORD = 10
DEFAULT_SHARD_SIZE = 2000
# Hard bounds; the band inside them is what scoring actually aims for.
MIN_WORDS = 5
MAX_WORDS = 16
PREFERRED_MIN_WORDS = 6
PREFERRED_MAX_WORDS = 12
# Charged per word outside the band, in the same log10 units as difficulty.
# Asymmetric on purpose: a four-word fragment shows nothing about how a word
# behaves, while a thirteen-word sentence is merely more work than it needs to
# be, so undershooting the band costs about twice as much as overshooting.
SHORT_PENALTY_WEIGHT = 0.60
LONG_PENALTY_WEIGHT = 0.30
# One new word is the goal, not zero: a sentence made only of words already met
# is not the kind of sentence a learner needs to read. The single hardest
# unknown is therefore charged at a fraction of its cost — enough that a
# sentence teaching one word competes with an entirely known one — while every
# further unknown pays in full.
FIRST_NEW_WORD_DISCOUNT = 0.35
# Rank assumed for a token absent from the frequency list and not a name. The
# sentinel (999,999) would dominate the log, so cap the damage somewhere
# defensible — unranked here means "outside the measured list", not "hapax".
UNRANKED_ASSUMED_RANK = 60_000
# A token is treated as a name when it never appears lowercase and is unranked.
PROPER_NOUN_MIN_OCCURRENCES = 3
# Two sentences sharing this many word bigrams are near-restatements; the
# second is skipped while alternatives remain.
DIVERSITY_BIGRAM_OVERLAP = 2
# Beyond this many candidate sentences for one word, score a deterministic
# slice instead. Keeps the high-frequency words (which match hundreds of
# thousands of sentences) from dominating runtime; the slice is taken in
# corpus order so reruns are stable without needing an RNG seed.
MAX_CANDIDATES_PER_WORD = 4000


def load_ranks(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def detect_proper_nouns(pairs, ranks):
    """Names, learned from the corpus instead of a stoplist.

    A token qualifies when it is absent from the frequency list and never
    appears lowercased anywhere in the corpus. Tatoeba's Tom/Mary/Boston are
    the obvious cases; charging them as unknown vocabulary spent the entire
    difficulty budget on words a learner reads straight through.
    """
    capitalised = defaultdict(int)
    lowercased = set()
    for _eng, target in pairs:
        seen_word = False
        for raw in target.split():
            token = "".join(ch for ch in raw if ch.isalpha() or ch in "'-")
            if len(token) < 2:
                continue
            # Skip the sentence-initial word: its capital says nothing about
            # whether it is a name. Counting it made every verb that happens to
            # open a sentence and is missing from the frequency list — abramos,
            # admití, aférrate — look like a proper noun.
            first, seen_word = not seen_word, True
            if first:
                continue
            if token[0].isupper():
                capitalised[token.lower()] += 1
            else:
                lowercased.add(token.lower())
    return {
        token for token, count in capitalised.items()
        if count >= PROPER_NOUN_MIN_OCCURRENCES
        and token not in lowercased
        and rank_of(token, ranks) >= SENTINEL_RANK
    }


def rank_of(token, ranks):
    value = ranks.get(token)
    if value is None:
        value = ranks.get(strip_accents(token))
    return value if value is not None else SENTINEL_RANK


def build_index(pairs, ranks, wanted_tokens, source, proper_nouns):
    """One pass over the corpus: keep usable sentences, index by token.

    `wanted_tokens` restricts indexing to tokens we will actually query, which
    keeps the index proportional to the deck rather than to the corpus.
    """
    records = []
    index = defaultdict(list)
    dropped = defaultdict(int)

    for eng, target in pairs:
        if source == "opensubtitles":
            cleaned_target = clean_subtitle_line(target)
            cleaned_eng = clean_subtitle_line(eng)
            if not cleaned_target or not cleaned_eng:
                dropped["junk"] += 1
                continue
            target, eng = cleaned_target, cleaned_eng

        tokens = tokenize(target)
        if len(tokens) < MIN_WORDS:
            dropped["short"] += 1
            continue
        if len(tokens) > MAX_WORDS:
            dropped["long"] += 1
            continue

        # Names are free, and an unranked ordinary word is treated as merely
        # rare rather than as the sentinel, which would swamp the log.
        token_ranks = {}
        for token in set(tokens):
            if token in proper_nouns:
                continue
            rank = rank_of(token, ranks)
            token_ranks[token] = (UNRANKED_ASSUMED_RANK
                                  if rank >= SENTINEL_RANK else rank)
        record_index = len(records)
        records.append({
            "eng": eng,
            "target": target,
            "length": len(tokens),
            "ranks": token_ranks,
            "easiness": int(median(token_ranks.values())) if token_ranks else 0,
            "bigrams": frozenset(zip(tokens, tokens[1:])),
            "source": source,
        })
        for token in token_ranks:
            if token in wanted_tokens:
                index[token].append(record_index)

    return records, index, dropped


def dedupe_key(sentence):
    """Collapse punctuation-only differences.

    Tatoeba carries statement/question twins of the same sentence ("Es hora de
    comer." / "¿Es hora de comer?"). Matching on raw text keeps both and spends
    two of a word's slots on what a learner reads as one sentence.
    """
    return " ".join(tokenize(sentence))


def select_for_word(word, target_rank, candidate_indices, records,
                    per_word, usage, reuse_cap):
    """Cheapest-first pick under a continuous difficulty model."""
    if len(candidate_indices) > MAX_CANDIDATES_PER_WORD:
        # Seeded sample, not the first N. Corpus order is not neutral —
        # Tatoeba runs roughly by contribution era — so slicing gave the most
        # common words their oldest sentences. The per-word seed keeps reruns
        # stable, matching step_5a's reasoning for the same cap.
        rng = random.Random(zlib.crc32(word.encode("utf-8")))
        candidate_indices = rng.sample(candidate_indices, MAX_CANDIDATES_PER_WORD)

    log_target = math.log10(max(target_rank, 1))
    scored = []
    for record_index in candidate_indices:
        record = records[record_index]
        costs = sorted(
            (math.log10(rank) - log_target
             for token, rank in record["ranks"].items()
             if token != word and rank > target_rank),
            reverse=True,
        )
        beyond = len(costs)
        # Discount the hardest single unknown — that is the word the sentence
        # is teaching — and charge the remainder at full rate.
        burden = (FIRST_NEW_WORD_DISCOUNT * costs[0] + sum(costs[1:])) if costs else 0.0
        length = record["length"]
        penalty = (SHORT_PENALTY_WEIGHT * max(0, PREFERRED_MIN_WORDS - length)
                   + LONG_PENALTY_WEIGHT * max(0, length - PREFERRED_MAX_WORDS))
        scored.append((burden + penalty, burden, beyond, record_index))

    scored.sort()

    selected = []
    seen_here = set()
    chosen_bigrams = []
    # Two passes: fill on the diversity rule, then relax it rather than return
    # fewer sentences than the corpus can actually support.
    for allow_similar in (False, True):
        for total, burden, beyond, record_index in scored:
            if len(selected) >= per_word:
                break
            record = records[record_index]
            key = dedupe_key(record["target"])
            if key in seen_here:
                continue
            # A soft global cap rather than once-only. Words are processed in
            # frequency order, so a strict rule let common words claim every
            # good sentence and left rare words with nothing.
            if usage[key] >= reuse_cap:
                continue
            if not allow_similar and any(
                len(record["bigrams"] & prior) >= DIVERSITY_BIGRAM_OVERLAP
                for prior in chosen_bigrams
            ):
                continue
            seen_here.add(key)
            chosen_bigrams.append(record["bigrams"])
            usage[key] += 1
            selected.append({
                "id": example_id(record["target"], record["eng"]),
                "target": record["target"],
                "english": record["eng"],
                "source": record["source"],
                # Rounded so the shards stay compact; the app sorts on it to
                # show fully-known sentences first where they exist.
                "burden": round(burden, 2),
                "harder": beyond,
            })
        if len(selected) >= per_word:
            break
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--language", default="spanish", choices=sorted(_LANGUAGE_CONFIG))
    parser.add_argument("--per-word", type=int, default=DEFAULT_PER_WORD,
                        help=f"sentences kept per word (default {DEFAULT_PER_WORD})")
    parser.add_argument("--opensubtitles", action="store_true",
                        help="also mine OpenSubtitles (slow; Tatoeba only by default)")
    parser.add_argument("--max-lines", type=int, default=2_000_000,
                        help="OpenSubtitles pairs to sample when enabled")
    parser.add_argument("--shard-size", type=int, default=DEFAULT_SHARD_SIZE,
                        help=f"deck positions per shard (default {DEFAULT_SHARD_SIZE})")
    parser.add_argument("--reuse-cap", type=int, default=3,
                        help="how many words may share one sentence (default 2)")
    parser.add_argument("--limit-words", type=int, default=0,
                        help="only process the N most frequent words (smoke tests)")
    args = parser.parse_args()

    conf = _LANGUAGE_CONFIG[args.language]
    lang_dir = PROJECT_ROOT / "Data" / args.language.capitalize()
    index_path = lang_dir / "vocabulary.index.json"
    ranks_path = lang_dir / conf["ranks_file"]
    output_path = lang_dir / "vocabulary.backup_examples.json"   # legacy single file
    manifest_path = lang_dir / "vocabulary.backup_examples.index.json"

    for required in (index_path, ranks_path):
        if not required.exists():
            print(f"Missing required input: {required}")
            return 1

    print(f"Loading {index_path.name} + {ranks_path.name}...")
    with open(index_path, encoding="utf-8") as handle:
        inventory = json.load(handle)
    ranks = load_ranks(ranks_path)
    if args.limit_words:
        inventory = inventory[:args.limit_words]

    wanted = {entry["word"].lower() for entry in inventory if entry.get("word")}
    print(f"  {len(inventory):,} deck entries, {len(wanted):,} distinct surface forms")

    pairs = []
    tatoeba_path = lang_dir / "corpora" / "tatoeba" / f"{conf['iso3']}.txt"
    if tatoeba_path.exists():
        print(f"Loading Tatoeba from {tatoeba_path.name}...")
        tatoeba_pairs = load_tatoeba(tatoeba_path)
        print(f"  {len(tatoeba_pairs):,} pairs")
        pairs.append(("tatoeba", tatoeba_pairs))
    else:
        print(f"  (no Tatoeba corpus at {tatoeba_path})")

    if args.opensubtitles:
        es_path = lang_dir / "corpora" / "opensubtitles" / f"OpenSubtitles.en-{conf['iso2']}.{conf['iso2']}"
        en_path = lang_dir / "corpora" / "opensubtitles" / f"OpenSubtitles.en-{conf['iso2']}.en"
        if es_path.exists() and en_path.exists():
            print("Loading OpenSubtitles (this takes a while)...")
            subs_pairs = load_opensubtitles(es_path, en_path, args.max_lines)
            print(f"  {len(subs_pairs):,} pairs")
            pairs.append(("opensubtitles", subs_pairs))
        else:
            print("  (OpenSubtitles requested but corpus files are missing)")

    if not pairs:
        print("No corpora available — nothing to build.")
        return 1

    print("Detecting proper nouns...")
    proper_nouns = set()
    for _source, source_pairs in pairs:
        proper_nouns |= detect_proper_nouns(source_pairs, ranks)
    print(f"  {len(proper_nouns):,} names treated as free "
          f"(e.g. {', '.join(sorted(proper_nouns)[:5])})")

    all_records = []
    merged_index = defaultdict(list)
    for source, source_pairs in pairs:
        print(f"Indexing {source}...")
        records, index, dropped = build_index(source_pairs, ranks, wanted, source,
                                              proper_nouns)
        offset = len(all_records)
        all_records.extend(records)
        for token, indices in index.items():
            merged_index[token].extend(i + offset for i in indices)
        print(f"  kept {len(records):,} sentences "
              f"(dropped {dict(dropped) or 'none'})")

    print(f"Selecting up to {args.per_word} per word "
          f"(graded difficulty, {PREFERRED_MIN_WORDS}-{PREFERRED_MAX_WORDS} word band)...")
    shards = defaultdict(dict)
    usage = defaultdict(int)
    histogram = defaultdict(int)
    covered_words = 0
    for position, entry in enumerate(inventory):
        word = (entry.get("word") or "").lower()
        if not word:
            continue
        target_rank = rank_of(word, ranks)
        candidates = merged_index.get(word)
        chosen = select_for_word(
            word, target_rank, candidates, all_records,
            args.per_word, usage, args.reuse_cap
        ) if candidates else []
        histogram[min(len(chosen), args.per_word)] += 1
        if chosen:
            covered_words += 1
            # Shard by deck position, not by id hash. A study set is ~20
            # consecutive positions, so position-banding means opening the
            # sentence list pulls one shard for the whole level; hashing would
            # scatter those 20 cards across every shard.
            shards[position // args.shard_size][entry["id"]] = chosen
        if position % 2000 == 0 and position:
            print(f"\r  {position:,}/{len(inventory):,}", end="", flush=True)

    shard_dir = lang_dir / "backup_examples"
    shard_dir.mkdir(exist_ok=True)
    print(f"\rWriting {len(shards)} shards to {shard_dir}/..." + " " * 20)
    manifest_shards = []
    total = 0
    total_bytes = 0
    for shard_index in sorted(shards):
        payload = shards[shard_index]
        name = f"backup_examples.{shard_index:03d}.json"
        path = shard_dir / name
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        sentences = sum(len(v) for v in payload.values())
        total += sentences
        total_bytes += path.stat().st_size
        manifest_shards.append({
            "file": f"backup_examples/{name}",
            "shard": shard_index,
            "rankStart": shard_index * args.shard_size + 1,
            "rankEnd": (shard_index + 1) * args.shard_size,
            "words": len(payload),
            "sentences": sentences,
            "bytes": path.stat().st_size,
        })

    # Ship an explicit word-id -> shard map rather than making the app derive
    # the shard from a card's deck position. Position arithmetic only works for
    # the deck this file was built from: artist decks share the same word-id
    # space but order their entries differently, so the same id sits at a
    # different position and the derived shard was simply wrong. The map is a
    # few tens of KB and makes lookup deck-agnostic.
    shard_by_id = {}
    for shard_index, payload in shards.items():
        for word_id in payload:
            shard_by_id[word_id] = shard_index
    index_path = shard_dir / "shard_index.json"
    with open(index_path, "w", encoding="utf-8") as handle:
        json.dump(shard_by_id, handle, ensure_ascii=False, separators=(",", ":"))
    manifest = {
        "schemaVersion": 1,
        "shardSize": args.shard_size,
        "perWord": args.per_word,
        "properNouns": len(proper_nouns),
        "words": covered_words,
        "sentences": total,
        "shardIndexFile": "backup_examples/shard_index.json",
        "shards": manifest_shards,
    }
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    write_sidecar(manifest_path, make_meta("build_backup_examples", STEP_VERSION))

    # The single-file build is superseded by the shards; leaving it behind
    # would ship both copies to anyone syncing the data directory.
    if output_path.exists():
        output_path.unlink()
        sidecar = output_path.with_suffix(output_path.suffix + ".meta.json")
        if sidecar.exists():
            sidecar.unlink()

    largest = max(manifest_shards, key=lambda s: s["bytes"]) if manifest_shards else None
    print(f"\nDone. {total:,} sentences across {covered_words:,} words")
    print(f"  {len(manifest_shards)} shards, {total_bytes / (1024 * 1024):.1f} MB total, "
          f"largest {largest['bytes'] / 1024:.0f} KB" if largest else "  no shards")
    print("Sentences per word:")
    for count in sorted(histogram):
        share = 100 * histogram[count] / len(inventory)
        print(f"  {count}: {histogram[count]:6,} words ({share:.1f}%)")
    print(f"Words with at least one backup sentence: {100 * covered_words / len(inventory):.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
