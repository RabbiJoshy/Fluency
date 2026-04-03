#!/usr/bin/env python3
"""
Step 2d: Multi-word expression (MWE) detection.

Scans lyric lines for frequent bigrams and trigrams, cross-references against
a curated dictionary of known Spanish multi-word expressions, and outputs a
JSON file consumed by step 4 to annotate vocabulary entries.

Reads:  intermediates/2_vocab_evidence.json
Writes: intermediates/2d_mwe_detected.json

Usage (from project root):
    .venv/bin/python3 "Bad Bunny/2d_detect_mwes.py"
"""

import json
import os
import re
from collections import Counter
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_PATH = os.path.join(SCRIPT_DIR, "intermediates", "2_vocab_evidence.json")
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "intermediates", "2d_mwe_detected.json")

# ---------------------------------------------------------------------------
# Tokenizer (same as step 2)
# ---------------------------------------------------------------------------
LETTER_CLASS = r"A-Za-zÁÉÍÓÚÜÑáéíóúüñ"
WORD_RE = re.compile(rf"[{LETTER_CLASS}]+(?:'[{LETTER_CLASS}]+)*'?")


def tokenize(line):
    # type: (str) -> List[str]
    return [m.group(0).lower() for m in WORD_RE.finditer(line)]


# ---------------------------------------------------------------------------
# Curated multi-word expressions
#
# Keys are lowercase tokenized forms (matching what tokenize() produces).
# Values are English translations.
# ---------------------------------------------------------------------------
CURATED_MWES = {
    # Verbal periphrases (ir a + inf, etc.)
    "voy a": "I'm going to",
    "va a": "is going to",
    "vas a": "you're going to",
    "van a": "they're going to",
    "iba a": "was going to",
    "vamo' a": "let's",
    "va' a": "let's (elided)",
    "vo' a": "I'm going to (elided)",
    "te vo'a": "I'm going to (you)",
    "me voy a": "I'm going to",
    "te voy a": "I'm going to (you)",
    "se va a": "is going to",

    # Fixed expressions / idioms
    "pa' que": "so that, in order to",
    "pa' qué": "what for",
    "por eso": "that's why, for that reason",
    "por qué": "why",
    "por ahí": "around there, out and about",
    "por más que": "no matter how much",
    "de verdad": "really, truly, for real",
    "de nuevo": "again",
    "de ti": "about you, of you",
    "de mí": "about me, of me",
    "a lo loco": "wildly, recklessly",
    "a vece'": "sometimes (elided)",
    "a veces": "sometimes",
    "a ver": "let's see",
    "a ver si": "let's see if",
    "un par de": "a couple of",
    "lo que sea": "whatever",
    "lo mismo": "the same thing",
    "lo nuestro": "our thing, what we have",
    "lo mío": "my thing, what's mine",
    "cada vez que": "every time that",
    "otra vez": "again",
    "otra ve'": "again (elided)",
    "hace tiempo": "a while ago",
    "hace tiempo que": "it's been a while since",
    "desde que": "since, ever since",
    "hasta que": "until",
    "así que": "so, therefore",
    "hay que": "one must, you have to",
    "no hay": "there isn't, there's no",
    "ya no hay": "there's no longer",
    "como si": "as if",
    "sin ti": "without you",
    "antes que": "before",
    "después de": "after",
    "encima de": "on top of",

    # Emphatic pronoun constructions
    "a mí me": "to me (emphatic)",
    "a ti te": "to you (emphatic)",
    "a mí no": "not me (emphatic)",
    "mí no me": "don't (emphatic negation)",

    # Common verb phrases
    "me gusta": "I like",
    "te gusta": "you like",
    "le gusta": "he/she likes",
    "me gustan": "I like (plural)",
    "me siento": "I feel",
    "me voy": "I'm leaving",
    "me dice": "tells me",
    "me llama": "calls me",
    "me llueven": "rain down on me",
    "me puse": "I put on / I got",
    "te juro": "I swear to you",
    "te juro que": "I swear that",
    "te quiero": "I love you / I want you",
    "se siente": "feels, it feels",
    "se va": "leaves, goes away",
    "se ve": "looks, appears",
    "se pone": "gets (emotional), puts on",
    "dile que": "tell him/her that",
    "dime si": "tell me if",
    "dime qu��": "tell me what",

    # Caribbean / reggaeton expressions
    "to' el mundo": "everybody",
    "to' lo que": "everything that (elided)",
    "toa' las": "all the (fem., elided)",
    "to'as las": "all the (fem., elided)",
    "to'a la": "all the (fem. sg., elided)",
    "tú sabe'": "you know (elided)",
    "tú sabe' que": "you know that (elided)",
    "tú ere'": "you are (elided)",
    "e' que": "it's that (elided)",
    "pa'l carajo": "to hell",
    "que se joda": "screw it, let it go to hell",
    "hijo e puta": "son of a bitch",
    "estoy puesto": "I'm ready, I'm down",
    "estoy puesto pa'": "I'm ready for",
    "no te haga'": "don't play dumb",

    # Named references
    "bad bunny": "Bad Bunny",
    "puerto rico": "Puerto Rico",

    # Noun phrases with idiomatic meaning
    "la calle": "the street, street life",
    "la noche": "the night, nightlife",
    "la disco": "the club",
    "la movie": "the vibe, the scene (PR slang)",
    "la nota": "the vibe, the high",
    "la gana": "the desire, the urge",
    "el mundo": "the world",
    "el perreo": "reggaeton grinding/dancing",
    "el bicho": "the beast (Bad Bunny's nickname)",
    "el conejo": "the rabbit (Bad Bunny's nickname)",
    "esta noche": "tonight",
    "un flow": "a style, a vibe",
    "un beso": "a kiss",
    "un día": "one day, someday",

    # Sentence-level fixed phrases
    "yo sé que": "I know that",
    "sé que": "I know that",
    "no sé": "I don't know",
    "no sé si": "I don't know if",
    "no sé qué": "I don't know what",
    "creo que": "I think that, I believe that",
    "dice que": "says that",
    "dicen que": "they say that",
    "dijo que": "said that",
    "quiero que": "I want (someone) to",
    "quiere que": "wants (someone) to",
    "tienen que": "they have to",
    "todo lo que": "everything that",
    "yo hago lo que": "I do what(ever)",
    "por eso es": "that's why it is",
}

# Function words — n-grams composed entirely of these are not interesting
FUNCTION_WORDS = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    "de", "del", "al", "a", "en", "con", "por", "para", "sin",
    "que", "y", "o", "e", "ni", "u",
    "me", "te", "se", "nos", "le", "les", "lo",
    "mi", "tu", "su", "mis", "tus", "sus",
    "es", "no", "ya", "si",
})

# Minimum frequency for auto-detected candidates
MIN_BIGRAM_FREQ = 20
MIN_TRIGRAM_FREQ = 12


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def collect_lines(vocab_data):
    # type: (list) -> List[str]
    """Collect unique lyric lines from vocabulary evidence."""
    seen = set()
    lines = []
    for entry in vocab_data:
        for ex in entry.get("examples", []):
            line = ex.get("line", "")
            if line and line not in seen:
                seen.add(line)
                lines.append(line)
    return lines


def count_ngrams(lines):
    # type: (List[str]) -> Tuple[Counter, Counter]
    """Count bigrams and trigrams across all lines."""
    bigrams = Counter()  # type: Counter
    trigrams = Counter()  # type: Counter

    for line in lines:
        tokens = tokenize(line)
        for i in range(len(tokens) - 1):
            bigrams[tokens[i] + " " + tokens[i + 1]] += 1
        for i in range(len(tokens) - 2):
            trigrams[tokens[i] + " " + tokens[i + 1] + " " + tokens[i + 2]] += 1

    return bigrams, trigrams


def is_all_function_words(ngram):
    # type: (str) -> bool
    return all(w in FUNCTION_WORDS for w in ngram.split())


def is_repetition(ngram):
    # type: (str) -> bool
    """Detect pure repetition like 'ey ey', 'oh oh oh', 'prr prr prr'."""
    words = ngram.split()
    return len(set(words)) == 1


def detect_mwes(vocab_data):
    # type: (list) -> Tuple[List[Dict], List[Dict]]
    """
    Detect multi-word expressions.

    Returns:
        (confirmed, candidates) — confirmed have translations from CURATED_MWES,
        candidates are frequent n-grams not in the curated list.
    """
    lines = collect_lines(vocab_data)
    print("  %d unique lines" % len(lines))

    bigrams, trigrams = count_ngrams(lines)

    # Match curated MWEs against actual corpus counts
    confirmed = []
    matched_keys = set()

    for expression, translation in CURATED_MWES.items():
        tokens = expression.split()
        if len(tokens) == 2:
            count = bigrams.get(expression, 0)
        elif len(tokens) == 3:
            count = trigrams.get(expression, 0)
        else:
            # For 4+ word expressions, skip frequency (they're manually curated)
            count = 0

        if count > 0 or len(tokens) >= 4:
            confirmed.append({
                "expression": expression,
                "translation": translation,
                "count": count,
                "tokens": tokens,
            })
            matched_keys.add(expression)

    # Find auto-detected candidates not in curated list
    candidates = []

    for bg, count in bigrams.most_common(300):
        if count < MIN_BIGRAM_FREQ:
            break
        if bg in matched_keys:
            continue
        if is_all_function_words(bg):
            continue
        if is_repetition(bg):
            continue
        candidates.append({
            "expression": bg,
            "count": count,
        })

    for tg, count in trigrams.most_common(200):
        if count < MIN_TRIGRAM_FREQ:
            break
        if tg in matched_keys:
            continue
        if is_all_function_words(tg):
            continue
        if is_repetition(tg):
            continue
        candidates.append({
            "expression": tg,
            "count": count,
        })

    # Sort by count descending
    confirmed.sort(key=lambda x: -x["count"])
    candidates.sort(key=lambda x: -x["count"])

    return confirmed, candidates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading %s..." % INPUT_PATH)
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        vocab_data = json.load(f)
    print("  %d vocabulary entries" % len(vocab_data))

    confirmed, candidates = detect_mwes(vocab_data)

    # Build output — strip internal 'tokens' field from confirmed
    output = {
        "mwes": [
            {
                "expression": m["expression"],
                "translation": m["translation"],
                "count": m["count"],
            }
            for m in confirmed
        ],
        "candidates": candidates,
        "stats": {
            "confirmed_count": len(confirmed),
            "candidate_count": len(candidates),
        },
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\nDone! %d confirmed MWEs, %d candidates for review" %
          (len(confirmed), len(candidates)))
    print("  Wrote %s" % OUTPUT_PATH)

    print("\n=== Top 20 confirmed MWEs ===")
    for m in confirmed[:20]:
        print("  %4d  %-25s  %s" % (m["count"], m["expression"], m["translation"]))

    print("\n=== Top 20 candidates (not yet curated) ===")
    for c in candidates[:20]:
        print("  %4d  %s" % (c["count"], c["expression"]))


if __name__ == "__main__":
    main()
