#!/usr/bin/env python3
"""
Throwaway script: expand examples in BadBunnyvocabulary.json to up to 3
per POS, pulling extra examples from the spaCy output and reusing any
existing translations from the old vocabulary cache.

No API calls. Just cache lookups and data reshuffling.

Run AFTER 6_fill_translation_gaps.py (or any time after step 5).
"""

import json
from collections import defaultdict
from pathlib import Path

VOCAB_PATH = Path("Bad Bunny/BadBunnyvocabulary.json")
SPACY_PATH = Path("Bad Bunny/intermediates/4_spacy_output.json")
OLD_VOCAB_PATH = Path("Bad Bunny/intermediates/old_vocabulary_cache.json")

MAX_EXAMPLES_PER_POS = 3


def build_line_cache(old_vocab: list[dict]) -> dict[str, str]:
    """Build spanish_line -> english_translation cache from old vocab."""
    cache = {}
    for entry in old_vocab:
        for m in entry.get("meanings", []):
            for ex in m.get("examples", []):
                sp = ex.get("spanish", "")
                en = ex.get("english", "")
                if sp and en and sp not in cache:
                    cache[sp] = en
    return cache


def build_spacy_lookup(spacy_data: list[dict]) -> dict[str, dict]:
    """Build word -> spacy_entry lookup. If multiple entries per word,
    keep the one with most evidence examples."""
    lookup: dict[str, dict] = {}
    for entry in spacy_data:
        word = entry.get("word", "")
        if not word:
            continue
        existing = lookup.get(word)
        if existing is None:
            lookup[word] = entry
        else:
            # Keep entry with more evidence
            old_count = len((existing.get("evidence") or {}).get("examples") or [])
            new_count = len((entry.get("evidence") or {}).get("examples") or [])
            if new_count > old_count:
                lookup[word] = entry
    return lookup


def get_available_examples(spacy_entry: dict, pos: str) -> list[dict]:
    """Get all example lines for a given POS from a spaCy entry."""
    evidence = (spacy_entry.get("evidence") or {}).get("examples") or []
    id2line = {}
    for ex in evidence:
        ex_id = ex.get("id")
        line = ex.get("line")
        if ex_id and line:
            id2line[ex_id] = line

    matches = spacy_entry.get("matches") or []
    id2songname = {}
    for m in matches:
        ex_id = m.get("example_id")
        song_name = m.get("example_song_name", "")
        if ex_id and song_name:
            id2songname[ex_id] = song_name

    # Collect examples for this POS
    results = []
    seen_lines = set()
    for m in matches:
        if (m.get("pos") or "X") != pos:
            continue
        ex_id = m.get("example_id")
        if not ex_id:
            continue
        line = (id2line.get(ex_id) or "").strip()
        if not line or line in seen_lines:
            continue
        seen_lines.add(line)

        song_id = ex_id.split(":")[0].strip() if ":" in ex_id else ""
        results.append({
            "song": song_id,
            "song_name": id2songname.get(ex_id, ""),
            "spanish": line,
        })

    # If no POS-specific matches, fall back to all evidence
    if not results:
        for ex in evidence:
            line = (ex.get("line") or "").strip()
            if not line or line in seen_lines:
                continue
            seen_lines.add(line)
            ex_id = ex.get("id", "")
            song_id = ex_id.split(":")[0].strip() if ":" in ex_id else ""
            results.append({
                "song": song_id,
                "song_name": id2songname.get(ex_id, ""),
                "spanish": line,
            })

    return results


def main():
    vocab = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    spacy_data = json.loads(SPACY_PATH.read_text(encoding="utf-8"))

    line_cache: dict[str, str] = {}
    if OLD_VOCAB_PATH.exists():
        old_vocab = json.loads(OLD_VOCAB_PATH.read_text(encoding="utf-8"))
        line_cache = build_line_cache(old_vocab)
        # Also pull translations from current vocab (step 6 may have filled some)
        for entry in vocab:
            for m in entry.get("meanings", []):
                for ex in m.get("examples", []):
                    sp = ex.get("spanish", "")
                    en = ex.get("english", "")
                    if sp and en and sp not in line_cache:
                        line_cache[sp] = en
        print(f"Loaded {len(line_cache)} cached line translations")
        del old_vocab

    spacy_lookup = build_spacy_lookup(spacy_data)
    print(f"Loaded {len(spacy_lookup)} spaCy entries")
    del spacy_data

    expanded = 0
    translations_recovered = 0
    already_full = 0

    for entry in vocab:
        word = entry.get("word", "")
        spacy_entry = spacy_lookup.get(word)

        for meaning in entry.get("meanings", []):
            existing = meaning.get("examples", [])
            pos = meaning.get("pos", "X")

            # Already have enough?
            if len(existing) >= MAX_EXAMPLES_PER_POS:
                already_full += 1
                continue

            # Also fill in any missing translations on existing examples
            for ex in existing:
                if not ex.get("english") and ex.get("spanish") in line_cache:
                    ex["english"] = line_cache[ex["spanish"]]
                    translations_recovered += 1

            # Try to add more examples from spaCy
            if spacy_entry is None:
                continue

            available = get_available_examples(spacy_entry, pos)
            existing_lines = {ex.get("spanish", "") for ex in existing}

            for candidate in available:
                if len(existing) >= MAX_EXAMPLES_PER_POS:
                    break
                if candidate["spanish"] in existing_lines:
                    continue

                # Build the example object
                ex_obj = {
                    "song": candidate["song"],
                    "song_name": candidate["song_name"],
                    "spanish": candidate["spanish"],
                    "english": line_cache.get(candidate["spanish"], ""),
                }

                if ex_obj["english"]:
                    translations_recovered += 1

                existing.append(ex_obj)
                existing_lines.add(candidate["spanish"])
                expanded += 1

            meaning["examples"] = existing

    VOCAB_PATH.write_text(
        json.dumps(vocab, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n✅ Done")
    print(f"   Added {expanded} new examples")
    print(f"   Recovered {translations_recovered} translations from cache")
    print(f"   {already_full} meanings already had {MAX_EXAMPLES_PER_POS}+ examples")


if __name__ == "__main__":
    main()
