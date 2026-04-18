#!/usr/bin/env python3
"""
8_rerank.py — Re-rank BadBunnyvocabulary.json using meaningful tiebreakers.

Primary sort: corpus_count descending (unchanged between groups).
Within each corpus_count tie group, break ties using:
  1. General Spanish vocabulary rank (lower = more common = better)
     - Match on word first, fall back to lemma
     - Unmatched words sort after all matched ones
  2. Distinct song count (higher = more generalizable = better)
  3. Non-cognate before cognate (harder words first, cognates are "free")
  4. Word length ascending (shorter = more fundamental)

Preserves the old rank as 'original_rank' and assigns new sequential 'rank'.

Input:  BadBunnyvocabulary.json  (output of 8_flag_cognates.py)
        data/Spanish/vocabulary.json  (general Spanish frequency list)
Output: BadBunnyvocabulary.json  (updated with new ranks)
"""

import json
import os
import re
import sys
from statistics import median

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pipeline.util_6a_method_priority import METHOD_PRIORITY
from pipeline.util_5c_sense_menu_format import normalize_artist_sense_menu, resolve_analysis_for_assignments
from pipeline.util_pipeline_meta import make_meta, write_sidecar

STEP_VERSION = 1
STEP_VERSION_NOTES = {
    1: "rerank by corpus_count + frequency tiebreakers + cognate penalty",
}

SENTINEL_RANK = 999_999  # For words not found in Spanish vocabulary
_ADLIB_RE = re.compile(r'\[[^\]]*\]|\([^\)]*\)')

BB_VOCAB_PATH = None
SPANISH_VOCAB_PATH = None
MWE_PATH = None


def tokenize_spanish(text):
    """Lowercase, strip punctuation (keep apostrophes for elisions), split on whitespace."""
    cleaned = re.sub(r"[^\w\s']", " ", text.lower())
    return [t for t in cleaned.split() if t]


def build_elision_map(bb_data):
    """Build display_form -> (word, lemma) dict from BB vocab for elision resolution."""
    elision_map = {}
    for entry in bb_data:
        display_form = entry.get("display_form", "")
        if display_form:
            word = entry.get("word", "").lower().strip()
            lemma = entry.get("lemma", "").lower().strip()
            df_lower = display_form.lower().strip()
            if df_lower and df_lower != word:
                elision_map[df_lower] = (word, lemma)
    return elision_map


def get_token_rank(token, word_to_rank, lemma_to_rank, elision_map):
    """Look up Spanish frequency rank for a raw token string."""
    # Direct match
    if token in word_to_rank:
        return word_to_rank[token]
    if token in lemma_to_rank:
        return lemma_to_rank[token]

    # Resolve elision and retry
    if token in elision_map:
        canonical_word, canonical_lemma = elision_map[token]
        if canonical_word in word_to_rank:
            return word_to_rank[canonical_word]
        if canonical_lemma and canonical_lemma in word_to_rank:
            return word_to_rank[canonical_lemma]
        if canonical_lemma and canonical_lemma in lemma_to_rank:
            return lemma_to_rank[canonical_lemma]

    return SENTINEL_RANK


def compute_easiness(spanish_text, word_to_rank, lemma_to_rank, elision_map,
                     ignore_words=None):
    """Compute sentence easiness as median Spanish frequency rank of tokens.

    Strips bracketed/parenthetical ad-libs before tokenizing.
    Tokens in ignore_words (interjections, English, proper nouns) are excluded
    from the median so they don't inflate the score with sentinel ranks.
    """
    if not spanish_text:
        return SENTINEL_RANK
    # Strip ad-libs/brackets before tokenizing
    cleaned = _ADLIB_RE.sub('', spanish_text).strip()
    if not cleaned:
        return SENTINEL_RANK
    tokens = tokenize_spanish(cleaned)
    if not tokens:
        return SENTINEL_RANK
    if ignore_words:
        tokens = [t for t in tokens if t not in ignore_words]
    if not tokens:
        return SENTINEL_RANK
    ranks = [get_token_rank(t, word_to_rank, lemma_to_rank, elision_map) for t in tokens]
    return int(median(ranks))


def build_spanish_lookup(spanish_path):
    """Build word -> rank and lemma -> rank lookups from the general Spanish vocabulary."""
    with open(spanish_path, "r", encoding="utf-8") as f:
        spanish_data = json.load(f)

    word_to_rank = {}
    lemma_to_rank = {}

    for i, entry in enumerate(spanish_data):
        rank = i + 1  # Array position is the rank (sorted by corpus_count desc)
        word = entry.get("word", "").lower().strip()
        lemma = entry.get("lemma", "").lower().strip()

        if word and word not in word_to_rank:
            word_to_rank[word] = rank
        if lemma and lemma not in lemma_to_rank:
            lemma_to_rank[lemma] = rank

    return word_to_rank, lemma_to_rank


def count_distinct_songs(entry):
    """Count distinct song_name values across all meanings' examples."""
    songs = set()
    for meaning in entry.get("meanings", []):
        for example in meaning.get("examples", []):
            song_name = example.get("song_name")
            if song_name:
                songs.add(song_name)
    return len(songs)


def get_spanish_rank(entry, word_to_rank, lemma_to_rank):
    """Get the Spanish vocabulary rank for a word, trying word then lemma."""
    word = entry.get("word", "").lower().strip()
    lemma = entry.get("lemma", "").lower().strip()

    # Try exact word match first
    if word in word_to_rank:
        return word_to_rank[word]

    # Fall back to lemma match
    if lemma and lemma in word_to_rank:
        return word_to_rank[lemma]

    # Try lemma-to-lemma match
    if lemma and lemma in lemma_to_rank:
        return lemma_to_rank[lemma]

    # Try word in lemma lookup
    if word in lemma_to_rank:
        return lemma_to_rank[word]

    return SENTINEL_RANK


def load_artist_senses(layers_dir, sense_source):
    """Load the artist sense menu, falling back to legacy Gemini senses."""
    from util_1a_artist_config import artist_sense_menu_path
    sense_menu_path = artist_sense_menu_path(layers_dir, sense_source, prefer_new=False)
    if os.path.isfile(sense_menu_path):
        with open(sense_menu_path, "r", encoding="utf-8") as f:
            return normalize_artist_sense_menu(json.load(f)), "sense_menu"

    legacy_path = os.path.join(layers_dir, "senses_gemini.json")
    with open(legacy_path, "r", encoding="utf-8") as f:
        return json.load(f), "senses_gemini"


def flatten_best_assignments(raw_assignments):
    """Normalize assignments to a simple list aligned with the builder."""
    if isinstance(raw_assignments, dict):
        best_method = max(raw_assignments.keys(),
                          key=lambda m: METHOD_PRIORITY.get(m, -1))
        return raw_assignments.get(best_method, [])
    if isinstance(raw_assignments, list):
        return raw_assignments
    return []


def sort_key(entry, word_to_rank, lemma_to_rank):
    """
    Generate sort key for an entry. Python sorts tuples element by element.
    We want:
      1. corpus_count descending (negate)
      2. Spanish rank ascending (lower = more common)
      3. Song count descending (negate)
      4. Cognate status: False (0) before True (1)
      5. Word length ascending
    """
    corpus_count = entry.get("corpus_count") or 0
    spanish_rank = get_spanish_rank(entry, word_to_rank, lemma_to_rank)
    # _song_count is set by layer-based main(); fall back to counting from meanings
    song_count = entry.get("_song_count") or count_distinct_songs(entry)
    is_cognate = 1 if entry.get("is_transparent_cognate", False) else 0
    word_len = len(entry.get("word", ""))

    return (-corpus_count, spanish_rank, -song_count, is_cognate, word_len)


def main():
    import argparse
    from util_1a_artist_config import add_artist_arg, load_artist_config, artist_sense_assignments_path

    parser = argparse.ArgumentParser(description="Step 7: Rerank vocabulary")
    add_artist_arg(parser)
    parser.add_argument("--sense-source", choices=("wiktionary", "spanishdict"),
                        default="wiktionary",
                        help="Which sense source to use for assignments and sense menu")
    parser.add_argument("--skip-split", action="store_true",
                        help="(Deprecated, ignored — builder handles splits)")
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    config = load_artist_config(artist_dir)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    layers_dir = os.path.join(artist_dir, "data", "layers")
    spanish_vocab_path = os.path.join(project_root, "Data", "Spanish", "vocabulary.json")

    # Load layers
    print("Loading layers...")
    with open(os.path.join(layers_dir, "word_inventory.json"), "r", encoding="utf-8") as f:
        inventory = json.load(f)
    print(f"  word_inventory: {len(inventory)} entries")

    senses_data, senses_label = load_artist_senses(layers_dir, args.sense_source)
    print(f"  {senses_label}: {len(senses_data)} entries")

    with open(os.path.join(layers_dir, "examples_raw.json"), "r", encoding="utf-8") as f:
        examples_raw = json.load(f)
    print(f"  examples_raw: {len(examples_raw)} entries")

    with open(artist_sense_assignments_path(layers_dir, args.sense_source, prefer_new=False), "r", encoding="utf-8") as f:
        assignments = json.load(f)
    print(f"  sense_assignments: {len(assignments)} entries")

    cognates = {}
    cognates_path = os.path.join(layers_dir, "cognates.json")
    if os.path.isfile(cognates_path):
        with open(cognates_path, "r", encoding="utf-8") as f:
            cognates = json.load(f)
        print(f"  cognates: {len(cognates)} entries")

    # Load master for flags (ignore words in easiness)
    master_path = os.path.join(project_root, "Artists", "vocabulary_master.json")
    master = {}
    if os.path.isfile(master_path):
        with open(master_path, "r", encoding="utf-8") as f:
            master = json.load(f)
    wl_to_master = {}
    for mid, m in master.items():
        wl_to_master["%s|%s" % (m["word"], m["lemma"])] = m

    # Build lightweight entries for sorting (word, lemma, corpus_count, cognate, song count)
    print("\nBuilding sort entries...")
    entries = []
    for inv in inventory:
        word = inv["word"]
        # Find lemma from sense menu / assignments
        analysis = resolve_analysis_for_assignments(senses_data, word, assignments.get(word, []))
        lemma = analysis.get("headword", analysis.get("lemma", word))

        # Count distinct songs from examples
        songs = set()
        for ex in examples_raw.get(word, []):
            songs.add(ex.get("title", ""))

        cognate_key = "%s|%s" % (word, lemma)
        is_cognate = cognate_key in cognates

        entries.append({
            "word": word,
            "lemma": lemma,
            "corpus_count": inv.get("corpus_count", 0),
            "display_form": inv.get("display_form"),
            "is_transparent_cognate": is_cognate,
            "_song_count": len(songs),
        })

    print("Loading Spanish vocabulary...")
    word_to_rank, lemma_to_rank = build_spanish_lookup(spanish_vocab_path)
    print(f"  {len(word_to_rank)} word entries, {len(lemma_to_rank)} lemma entries")

    # Sort
    print("Sorting with tiebreakers...")
    entries.sort(key=lambda e: sort_key(e, word_to_rank, lemma_to_rank))

    matched = sum(1 for e in entries if get_spanish_rank(e, word_to_rank, lemma_to_rank) < SENTINEL_RANK)
    print(f"  {len(entries)} entries sorted, {matched} matched in Spanish vocab ({matched * 100 / len(entries):.1f}%)")

    # Build elision map for easiness scoring
    elision_map = {}
    for e in entries:
        df = e.get("display_form")
        if df:
            df_lower = df.lower().strip()
            w_lower = e["word"].lower().strip()
            if df_lower and df_lower != w_lower:
                elision_map[df_lower] = (w_lower, e["lemma"].lower().strip())
    print(f"  {len(elision_map)} elision mappings")

    # Build ignore set for easiness (interjections, English, proper nouns from master)
    ignore_words = set()
    for e in entries:
        wl_key = "%s|%s" % (e["word"], e["lemma"])
        m = wl_to_master.get(wl_key, {})
        if m.get("is_interjection") or m.get("is_english") or m.get("is_propernoun"):
            ignore_words.add(e["word"].lower())
            df = (e.get("display_form") or "").lower().strip()
            if df:
                ignore_words.add(df)
    print(f"  {len(ignore_words)} words ignored in easiness")

    # Score easiness per example per meaning
    print("Scoring example easiness...")
    # We need: for each word, for each meaning (via assignments), for each example, compute easiness
    easiness_data = {}
    total_examples = 0
    all_scores = []

    for entry in entries:
        word = entry["word"]
        word_assignments = flatten_best_assignments(assignments.get(word, []))
        raw_exs = examples_raw.get(word, [])

        per_meaning = []
        for assignment in word_assignments:
            scores = []
            for ex_idx in assignment.get("examples", []):
                if ex_idx < len(raw_exs):
                    spanish = raw_exs[ex_idx].get("spanish", "")
                    score = compute_easiness(spanish, word_to_rank, lemma_to_rank,
                                             elision_map, ignore_words=ignore_words)
                    scores.append(score)
                    all_scores.append(score)
                    total_examples += 1
            # Sort scores ascending (easiest first) to match example sort order
            scores.sort()
            per_meaning.append(scores)

        if per_meaning:
            # We need a stable ID for the ranking layer. Use word|lemma for now,
            # the builder will resolve to actual IDs.
            easiness_data[word] = {"m": per_meaning}

    if all_scores:
        all_scores.sort()
        recognized = sum(1 for s in all_scores if s < SENTINEL_RANK)
        print(f"  {total_examples} examples scored")
        print(f"  {recognized} with recognized tokens ({recognized * 100 / total_examples:.1f}%)")

    # Build ranking layer keyed by word (builder resolves to IDs)
    ranking_layer = {
        "order": [e["word"] for e in entries],
        "easiness": easiness_data,
    }

    ranking_path = os.path.join(layers_dir, "ranking.json")
    os.makedirs(layers_dir, exist_ok=True)
    with open(ranking_path, "w", encoding="utf-8") as f:
        json.dump(ranking_layer, f, ensure_ascii=False)
    write_sidecar(ranking_path, make_meta("rerank", STEP_VERSION))
    print(f"\n  Ranking layer: {len(ranking_layer['order'])} entries -> {ranking_path}")
    print("Done!")


if __name__ == "__main__":
    main()
