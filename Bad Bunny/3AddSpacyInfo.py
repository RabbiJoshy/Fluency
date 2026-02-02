#!/usr/bin/env python3
"""
Build preview entries for the first n vocab_evidence items:
ONE top-level entry per (word, lemma) pairing, with a sense scaffold
and an English flag.

Input : /mnt/data/vocab_evidence.json
Output: /mnt/data/vocab_word_lemma_preview.json

Requires:
  pip install spacy
  python -m spacy download es_core_news_sm
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
import spacy

n = 10000

IN_PATH = Path("Bad Bunny/vocab_evidence.json")
OUT_PATH = Path("Bad Bunny/vocab_word_lemma_preview.json")


# ---- English flagging (fast, heuristic, non-destructive) ----------------------

EN_COMMON = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "with",
    "you", "me", "my", "your", "we", "they", "he", "she", "it",
    "yeah", "yea", "nah", "nope", "baby", "love", "i", "im", "i'm", "dont", "don't",
    "know", "like", "want", "got", "get", "up", "down", "all", "one", "two",
}

SPANISH_DIACRITICS_RE = re.compile(r"[áéíóúüñ]", re.IGNORECASE)

def english_flag(word: str) -> dict:
    w = word.strip().lower()

    # strong Spanish signal
    if SPANISH_DIACRITICS_RE.search(w):
        return {"is_english": False, "confidence": 0.01, "reason": "spanish_diacritic"}

    # common English tokens / chat spellings
    if w in EN_COMMON:
        return {"is_english": True, "confidence": 0.95, "reason": "common_english_token"}

    # typical English orthography hints (keep weak; don’t nuke slang)
    if w.endswith("ing") and len(w) >= 5:
        return {"is_english": True, "confidence": 0.75, "reason": "endswith_ing"}
    if "th" in w and len(w) >= 4:
        return {"is_english": True, "confidence": 0.70, "reason": "contains_th"}

    # default: unknown -> assume not English
    return {"is_english": False, "confidence": 0.20, "reason": "no_strong_english_signal"}


# ---- Matching helpers --------------------------------------------------------

KEEP_APOS = {"'", "’"}

def normalize_for_match(s: str) -> str:
    """
    Learner-oriented normalization:
    - lowercase
    - keep letters and internal apostrophes (', ’)
    - strip everything else
    - collapse multiple apostrophes
    - strip leading/trailing apostrophes
    """
    s = s.lower()
    out = []
    for ch in s:
        if ch.isalpha() or ch in KEEP_APOS:
            out.append(ch)
    s = "".join(out)
    s = re.sub(r"[’']", "'", s)          # normalize curly apostrophes -> straight
    s = re.sub(r"'+", "'", s)            # collapse
    s = s.strip("'")                     # no leading/trailing apostrophes
    return s

READ_MORE_RE = re.compile(r"\s*read more\s*$", re.IGNORECASE)

def clean_line_for_nlp(line: str) -> str:
    # keep raw evidence elsewhere; this is just for spaCy robustness
    return READ_MORE_RE.sub("", line).strip()


# ---- Main transform ----------------------------------------------------------

def main():
    # Load first 10 entries
    data = json.loads(IN_PATH.read_text(encoding="utf-8"))
    first10 = data[:n]

    # spaCy Spanish model — disable heavy components
    nlp = spacy.load("es_core_news_sm", disable=["ner", "parser"])
    # Ensure sentence segmentation isn’t required; we just need tokens/lemmas/POS.

    outputs = []

    for idx, entry in enumerate(first10, start=1):
        word_raw = entry["word"]
        word = normalize_for_match(word_raw)
        occ_ppm = entry.get("occurrences_ppm")
        examples = entry.get("examples", [])

        lang = english_flag(word_raw)

        # If it’s confidently English, you might want to skip spaCy work entirely.
        # But we’ll still *try* to extract (word, lemma) pairings unless confidence is very high.
        do_spacy = not (lang["is_english"] and lang["confidence"] >= 0.90)

        # Collect occurrences grouped by lemma
        # lemma_key -> list of match records
        lemma_matches = defaultdict(list)
        # lemma_key -> Counter of POS tags
        lemma_pos = defaultdict(Counter)
        # lemma_key -> set of example_ids where we matched
        lemma_example_ids = defaultdict(set)

        if do_spacy and examples:
            lines = [clean_line_for_nlp(ex["line"]) for ex in examples]
            docs = nlp.pipe(lines)

            # Change this section (around line 113-129):
            for ex, doc in zip(examples, docs):
                ex_id = ex["id"]
                raw_line = ex["line"]
                song_name = ex.get("title", "")  # ADD THIS LINE

                for tok in doc:
                    tok_norm = normalize_for_match(tok.text)

                    # straightforward match
                    if tok_norm != word:
                        continue

                    lemma = (tok.lemma_ or tok.text).lower()
                    lemma = normalize_for_match(lemma) or word  # fallback

                    pos = tok.pos_ or "X"

                    lemma_matches[lemma].append({
                        "example_id": ex_id,
                        "example_song_name": song_name,  # ADD THIS LINE
                        "token_text": tok.text,
                        "lemma": lemma,
                        "pos": pos,
                    })
                    lemma_pos[lemma][pos] += 1
                    lemma_example_ids[lemma].add(ex_id)

        # If spaCy found nothing (tokenization mismatch etc), keep a fallback lemma = word
        if not lemma_matches:
            lemma_matches[word].append({
                "example_id": examples[0]["id"] if examples else "",
                "example_song_name": examples[0].get("title", "") if examples else "",  # ADD THIS LINE
                "token_text": word_raw,
                "lemma": word,
                "pos": "X",
            })
            lemma_pos[word]["X"] += 1
            if examples:
                lemma_example_ids[word].add(examples[0]["id"])

        # Build one output entry per lemma
        for lemma, matches in lemma_matches.items():
            pos_counts = dict(lemma_pos[lemma])
            example_ids = sorted(lemma_example_ids[lemma])

            outputs.append({
                "key": f"{word_raw}|{lemma}",
                "word": word_raw,
                "lemma": lemma,
                "occurrences_ppm": occ_ppm,
                "source_rank_in_preview": idx,

                "language_flags": lang,

                "pos_summary": {
                    "match_count": len(matches),
                    "pos_counts": pos_counts,
                },

                # Traceability: why this lemma exists
                "matches": matches,

                # Sense scaffold (no clustering yet)
                "senses": [
                    {
                        "sense_id": f"{word_raw}|{lemma}|0",
                        "label": "",
                        "notes": "",
                        "example_ids": example_ids,  # start with all lemma-supported examples in sense 0
                    }
                ],

                # Immutable evidence carried through unchanged
                "evidence": {
                    "examples": examples,
                },
            })

    OUT_PATH.write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(outputs)} (word, lemma) entries to {OUT_PATH}")


if __name__ == "__main__":
    main()
