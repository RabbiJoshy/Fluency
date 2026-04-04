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
from statistics import median

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

    for entry in spanish_data:
        rank = entry["rank"]
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
    song_count = count_distinct_songs(entry)
    is_cognate = 1 if entry.get("is_transparent_cognate", False) else 0
    word_len = len(entry.get("word", ""))

    return (-corpus_count, spanish_rank, -song_count, is_cognate, word_len)


def write_split_files(bb_data, vocab_path):
    """Write index and examples split files alongside the monolith.

    Index file: all entries with meanings[].examples and mwe_memberships[].examples stripped.
    Examples file: { id: { "m": [[examples], ...], "w": [[mwe_examples], ...] } }
    """
    base = vocab_path.rsplit('.', 1)[0]
    index_path = base + '.index.json'
    examples_path = base + '.examples.json'

    index = []
    examples = {}

    for entry in bb_data:
        # Build index entry (strip examples from meanings and mwe_memberships)
        idx_entry = {}
        for k, v in entry.items():
            if k in ('meanings', 'mwe_memberships'):
                continue
            idx_entry[k] = v

        idx_entry['meanings'] = [
            {k: v for k, v in m.items() if k != 'examples'}
            for m in entry.get('meanings', [])
        ]
        if entry.get('mwe_memberships'):
            idx_entry['mwe_memberships'] = [
                {k: v for k, v in mwe.items() if k != 'examples'}
                for mwe in entry['mwe_memberships']
            ]
        index.append(idx_entry)

        # Build examples entry
        m_examples = [m.get('examples', []) for m in entry.get('meanings', [])]
        ex_entry = {'m': m_examples}
        if entry.get('mwe_memberships'):
            w_examples = [mwe.get('examples', []) for mwe in entry['mwe_memberships']]
            if any(w_examples):
                ex_entry['w'] = w_examples
        examples[entry['id']] = ex_entry

    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False)
    with open(examples_path, 'w', encoding='utf-8') as f:
        json.dump(examples, f, ensure_ascii=False)

    idx_size = os.path.getsize(index_path)
    ex_size = os.path.getsize(examples_path)
    print(f"\n  Split files written:")
    print(f"    {index_path}: {idx_size:,} bytes")
    print(f"    {examples_path}: {ex_size:,} bytes")


def main():
    global BB_VOCAB_PATH, SPANISH_VOCAB_PATH, MWE_PATH
    import argparse
    from _artist_config import add_artist_arg, load_artist_config

    parser = argparse.ArgumentParser(description="Step 8: Rerank vocabulary")
    add_artist_arg(parser)
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    config = load_artist_config(artist_dir)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    BB_VOCAB_PATH = os.path.join(artist_dir, config["vocabulary_file"])
    SPANISH_VOCAB_PATH = os.path.join(project_root, "Data", "Spanish", "vocabulary.json")
    MWE_PATH = os.path.join(artist_dir, "data", "word_counts", "mwe_detected.json")

    print("Loading artist vocabulary...")
    with open(BB_VOCAB_PATH, "r", encoding="utf-8") as f:
        bb_data = json.load(f)
    print(f"  {len(bb_data)} entries")

    print("Loading Spanish vocabulary...")
    word_to_rank, lemma_to_rank = build_spanish_lookup(SPANISH_VOCAB_PATH)
    print(f"  {len(word_to_rank)} word entries, {len(lemma_to_rank)} lemma entries")

    # Sort using tiebreakers — array position becomes the effective rank
    print("Sorting with tiebreakers...")
    bb_data.sort(key=lambda e: sort_key(e, word_to_rank, lemma_to_rank))

    # Strip any leftover rank/original_rank fields from previous pipeline runs
    for entry in bb_data:
        entry.pop("rank", None)
        entry.pop("original_rank", None)

    # Report statistics
    matched = sum(
        1
        for e in bb_data
        if get_spanish_rank(e, word_to_rank, lemma_to_rank) < SENTINEL_RANK
    )
    print(f"\nResults:")
    print(f"  {len(bb_data)} entries sorted (rank = array position + 1)")
    print(f"  {matched} entries matched in Spanish vocab ({matched * 100 / len(bb_data):.1f}%)")

    # Show sample of ordering within a tie group
    cc3 = [e for e in bb_data if e["corpus_count"] == 3]
    print(f"\n  Sample: corpus_count=3 ({len(cc3)} words)")
    print(f"  First 10 (highest priority):")
    for i, e in enumerate(cc3[:10]):
        sp_rank = get_spanish_rank(e, word_to_rank, lemma_to_rank)
        songs = count_distinct_songs(e)
        sp_str = str(sp_rank) if sp_rank < SENTINEL_RANK else "—"
        print(
            f"    pos {bb_data.index(e) + 1:>5}: "
            f"{e['word']:<20} sp_rank={sp_str:<6} songs={songs} "
            f"cognate={e.get('is_transparent_cognate', False)}"
        )

    # Score and sort examples by easiness (median Spanish frequency rank)
    print("\nScoring example easiness...")
    elision_map = build_elision_map(bb_data)
    print(f"  {len(elision_map)} elision mappings built")

    # Build set of words to ignore in easiness calculation (interjections,
    # English words, proper nouns) — these would otherwise get sentinel rank
    # and inflate scores for sentences containing them.
    ignore_words = set()
    for entry in bb_data:
        w = entry.get("word", "").lower().strip()
        if entry.get("is_interjection") or entry.get("is_english") or entry.get("is_propernoun"):
            ignore_words.add(w)
            df = (entry.get("display_form") or "").lower().strip()
            if df:
                ignore_words.add(df)
    print(f"  {len(ignore_words)} words ignored in easiness (interjections/English/proper nouns)")

    total_examples = 0
    all_easiness = []
    for entry in bb_data:
        for meaning in entry.get("meanings", []):
            examples = meaning.get("examples", [])
            for ex in examples:
                score = compute_easiness(
                    ex.get("spanish", ""), word_to_rank, lemma_to_rank, elision_map,
                    ignore_words=ignore_words
                )
                ex["easiness"] = score
                all_easiness.append(score)
                total_examples += 1
            examples.sort(key=lambda e: e.get("easiness", SENTINEL_RANK))

    if all_easiness:
        all_easiness.sort()
        recognized = sum(1 for e in all_easiness if e < SENTINEL_RANK)
        print(f"  {total_examples} examples scored")
        print(f"  {recognized} with recognized tokens ({recognized * 100 / total_examples:.1f}%)")
        print(f"  Easiness range: {all_easiness[0]} / {all_easiness[len(all_easiness)//2]} / {all_easiness[-1]} (min/median/max)")

    # Re-annotate MWE memberships from latest 2d output
    # This ensures MWEs are always up-to-date even when step 4 is skipped
    if os.path.exists(MWE_PATH):
        with open(MWE_PATH, "r", encoding="utf-8") as f:
            mwe_data = json.load(f)
        mwe_index = {}  # word -> list of {expression, translation}
        for mwe in mwe_data.get("mwes", []):
            expr = mwe["expression"]
            translation = mwe["translation"] or ""
            for token in expr.split():
                token_lower = token.lower()
                if token_lower not in mwe_index:
                    mwe_index[token_lower] = []
                if not any(m["expression"] == expr for m in mwe_index[token_lower]):
                    mwe_index[token_lower].append({
                        "expression": expr,
                        "translation": translation,
                    })
        mwe_count = 0
        for entry in bb_data:
            w_lower = entry["word"].lower()
            if w_lower in mwe_index:
                entry["mwe_memberships"] = mwe_index[w_lower]
                mwe_count += 1
            else:
                entry.pop("mwe_memberships", None)
        print(f"\n  MWE annotation: {len(mwe_data.get('mwes', []))} MWEs -> {mwe_count} entries annotated")

    # Write back
    print(f"\nWriting to {BB_VOCAB_PATH}...")
    with open(BB_VOCAB_PATH, "w", encoding="utf-8") as f:
        json.dump(bb_data, f, ensure_ascii=False, indent=2)

    # Generate split files for two-tier front-end loading
    write_split_files(bb_data, BB_VOCAB_PATH)
    print("Done!")


if __name__ == "__main__":
    main()
