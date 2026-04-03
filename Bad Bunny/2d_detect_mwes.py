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
import math
import os
import re
from collections import Counter, defaultdict
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

# MWEs to exclude — literal article+noun phrases, proper nouns, not real idioms
SKIP_MWES = frozenset({
    # Article + noun (literal, not idiomatic)
    "la noche", "la calle", "el mundo", "un beso", "un día",
    "la vida", "la cama", "la luna", "la boca", "la cara",
    "la mano", "la gente", "la casa", "la playa", "la mañana",
    "el sol", "el tiempo", "el día", "el amor", "el dinero",
    "el cielo", "el corazón", "el pelo", "el culo",
    "la canción", "la primera", "la nueva", "la cartera",
    # Proper nouns
    "bad bunny", "puerto rico",
})

# Conjugation families: map expression to a canonical form.
# Only the highest-frequency member of each family survives.
CONJUGATION_FAMILIES = {
    # ir a (going to)
    "voy a": "ir a",
    "va a": "ir a",
    "vas a": "ir a",
    "van a": "ir a",
    "iba a": "ir a",
    "vamo' a": "ir a",
    "va' a": "ir a",
    "vo' a": "ir a",
    # gustar
    "me gusta": "gustar",
    "te gusta": "gustar",
    "le gusta": "gustar",
    "me gustan": "gustar",
    # ir a + pronoun (these are just "ir a" with a pronoun)
    "te vo'a": "ir a + te",
    "te voy a": "ir a + te",
    "me voy a": "ir a + me",
    "se va a": "ir a + se",
    # saber que
    "sé que": "saber que",
    "yo sé que": "saber que",
    "tú sabe'": "saber que",
    "tú sabe' que": "saber que",
    # decir que
    "dice que": "decir que",
    "dicen que": "decir que",
    "dijo que": "decir que",
    # querer que
    "quiero que": "querer que",
    "quiere que": "querer que",
    # tener que
    "tienen que": "tener que",
    # todo/a elision variants
    "toa' las": "to' (elision)",
    "to'as las": "to' (elision)",
    "to'a la": "to' (elision)",
    "to' lo que": "to' (elision)",
    # otra vez variants
    "otra vez": "otra vez",
    "otra ve'": "otra vez",
    # a veces variants
    "a veces": "a veces",
    "a vece'": "a veces",
}


def dedup_conjugation_families(confirmed):
    # type: (List[Dict]) -> List[Dict]
    """Keep only the highest-frequency member of each conjugation family."""
    # Group by family
    family_best = {}  # type: Dict[str, Dict]
    no_family = []

    for m in confirmed:
        family = CONJUGATION_FAMILIES.get(m["expression"])
        if family:
            if family not in family_best or m["count"] > family_best[family]["count"]:
                family_best[family] = m
        else:
            no_family.append(m)

    return no_family + list(family_best.values())


# Minimum frequency for auto-detected candidates
MIN_BIGRAM_FREQ = 20
MIN_TRIGRAM_FREQ = 12


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

_PHRASE_SPLIT_RE = re.compile(r'[,;:!?¡¿()"—\-]+')

# PMI thresholds
MIN_PMI = 8.0           # minimum PMI score to consider an n-gram a real expression
MIN_PMI_COUNT = 5       # minimum raw count for PMI candidates
MIN_PMI_SONGS = 3       # must appear in at least this many distinct songs


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


def collect_lines_with_songs(vocab_data):
    # type: (list) -> List[Tuple[str, str]]
    """Collect unique lyric lines with song IDs for song-spread filtering."""
    seen = set()
    lines = []  # type: List[Tuple[str, str]]
    for entry in vocab_data:
        for ex in entry.get("examples", []):
            line = ex.get("line", "")
            song_id = ex.get("id", "unknown").split(":")[0]
            key = line + "|" + song_id
            if line and key not in seen:
                seen.add(key)
                lines.append((line, song_id))
    return lines


def count_ngrams(lines):
    # type: (List[str]) -> Tuple[Counter, Counter]
    """Count bigrams and trigrams across all lines (legacy, for curated matching)."""
    bigrams = Counter()  # type: Counter
    trigrams = Counter()  # type: Counter

    for line in lines:
        tokens = tokenize(line)
        for i in range(len(tokens) - 1):
            bigrams[tokens[i] + " " + tokens[i + 1]] += 1
        for i in range(len(tokens) - 2):
            trigrams[tokens[i] + " " + tokens[i + 1] + " " + tokens[i + 2]] += 1

    return bigrams, trigrams


def count_ngrams_pmi(lines_with_songs, max_n=5):
    # type: (List[Tuple[str, str]], int) -> Tuple[Counter, Dict[str, Counter], Dict[str, set]]
    """Count n-grams (2..max_n) within phrase boundaries, tracking song spread.

    Returns: (unigrams, ngram_counts_by_n, ngram_songs_by_ng)
    """
    unigrams = Counter()  # type: Counter
    ngram_counts = {}     # type: Dict[str, Counter]
    ngram_songs = defaultdict(set)  # type: Dict[str, set]

    for n in range(2, max_n + 1):
        ngram_counts[n] = Counter()

    for line, song_id in lines_with_songs:
        # Split on punctuation to get clean phrase chunks
        chunks = _PHRASE_SPLIT_RE.split(line)
        for chunk in chunks:
            tokens = tokenize(chunk)
            for t in tokens:
                unigrams[t] += 1
            for n in range(2, max_n + 1):
                for i in range(len(tokens) - n + 1):
                    ng = " ".join(tokens[i:i + n])
                    ngram_counts[n][ng] += 1
                    ngram_songs[ng].add(song_id)

    return unigrams, ngram_counts, ngram_songs


def compute_pmi_expressions(unigrams, ngram_counts, ngram_songs, curated_keys, skip_keys):
    # type: (Counter, Dict[str, Counter], Dict[str, set], set, set) -> List[Dict]
    """Find high-PMI n-grams that aren't already curated.

    Returns list of dicts with expression, count, pmi, num_songs — no translation.
    """
    total_tokens = sum(unigrams.values())
    results = []

    for n, counts in ngram_counts.items():
        total_ngrams = sum(counts.values())
        if total_ngrams == 0:
            continue
        for ng, count in counts.items():
            if count < MIN_PMI_COUNT:
                continue
            if ng in curated_keys or ng in skip_keys:
                continue
            num_songs = len(ngram_songs.get(ng, set()))
            if num_songs < MIN_PMI_SONGS:
                continue
            if is_all_function_words(ng):
                continue
            if is_repetition(ng):
                continue

            # Compute PMI
            p_ngram = count / total_ngrams
            p_independent = 1.0
            for w in ng.split():
                p_independent *= unigrams[w] / total_tokens
            if p_independent == 0:
                continue
            pmi = math.log2(p_ngram / p_independent)
            if pmi < MIN_PMI:
                continue

            results.append({
                "expression": ng,
                "count": count,
                "pmi": round(pmi, 1),
                "num_songs": num_songs,
            })

    # Deduplicate overlapping n-grams: if a shorter n-gram is a substring of a
    # longer one with equal or higher PMI, drop the shorter one.
    results.sort(key=lambda x: (-len(x["expression"].split()), -x["pmi"]))
    kept = []
    kept_exprs = []  # type: List[str]
    for r in results:
        # Check if this is a substring of an already-kept longer expression
        is_sub = False
        for longer in kept_exprs:
            if r["expression"] in longer:
                is_sub = True
                break
        if not is_sub:
            kept.append(r)
            kept_exprs.append(r["expression"])

    kept.sort(key=lambda x: -x["pmi"])
    return kept


def is_all_function_words(ngram):
    # type: (str) -> bool
    return all(w in FUNCTION_WORDS for w in ngram.split())


def is_repetition(ngram):
    # type: (str) -> bool
    """Detect pure repetition like 'ey ey', 'oh oh oh', 'prr prr prr'."""
    words = ngram.split()
    return len(set(words)) == 1


def detect_mwes(vocab_data):
    # type: (list) -> Tuple[List[Dict], List[Dict], List[Dict]]
    """
    Detect multi-word expressions.

    Returns:
        (confirmed, candidates, pmi_detected) —
        confirmed have translations from CURATED_MWES,
        candidates are frequent n-grams not in the curated list,
        pmi_detected are high-PMI expressions (no translations).
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

    # Find auto-detected candidates not in curated list (legacy frequency-based)
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

    # PMI-based detection: find statistically significant collocations
    # across 2-5 grams, filtered by song spread
    lines_with_songs = collect_lines_with_songs(vocab_data)
    unigrams, ngram_counts, ngram_songs = count_ngrams_pmi(lines_with_songs, max_n=5)
    pmi_detected = compute_pmi_expressions(
        unigrams, ngram_counts, ngram_songs,
        curated_keys=matched_keys, skip_keys=SKIP_MWES,
    )
    print("  %d PMI-detected expressions (min PMI=%.1f, min %d songs)"
          % (len(pmi_detected), MIN_PMI, MIN_PMI_SONGS))

    # Post-process: remove skipped entries and dedup conjugation families
    confirmed = [m for m in confirmed if m["expression"] not in SKIP_MWES]
    confirmed = dedup_conjugation_families(confirmed)

    # Sort by count descending
    confirmed.sort(key=lambda x: -x["count"])
    candidates.sort(key=lambda x: -x["count"])

    return confirmed, candidates, pmi_detected


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading %s..." % INPUT_PATH)
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        vocab_data = json.load(f)
    print("  %d vocabulary entries" % len(vocab_data))

    confirmed, candidates, pmi_detected = detect_mwes(vocab_data)

    # Build output — strip internal 'tokens' field from confirmed
    # PMI-detected expressions go into mwes list too, but without translations
    mwes_output = [
        {
            "expression": m["expression"],
            "translation": m["translation"],
            "count": m["count"],
        }
        for m in confirmed
    ]
    for p in pmi_detected:
        mwes_output.append({
            "expression": p["expression"],
            "translation": None,
            "count": p["count"],
            "pmi": p["pmi"],
            "num_songs": p["num_songs"],
        })

    output = {
        "mwes": mwes_output,
        "candidates": candidates,
        "stats": {
            "confirmed_count": len(confirmed),
            "pmi_detected_count": len(pmi_detected),
            "candidate_count": len(candidates),
        },
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\nDone! %d curated MWEs, %d PMI-detected, %d candidates for review" %
          (len(confirmed), len(pmi_detected), len(candidates)))
    print("  Wrote %s" % OUTPUT_PATH)

    print("\n=== Top 20 curated MWEs ===")
    for m in confirmed[:20]:
        print("  %4d  %-25s  %s" % (m["count"], m["expression"], m["translation"]))

    print("\n=== Top 20 PMI-detected (no translation yet) ===")
    for p in pmi_detected[:20]:
        print("  %4d  PMI=%5.1f  songs=%2d  %s" %
              (p["count"], p["pmi"], p["num_songs"], p["expression"]))

    print("\n=== Top 20 frequency candidates (not yet curated) ===")
    for c in candidates[:20]:
        print("  %4d  %s" % (c["count"], c["expression"]))


if __name__ == "__main__":
    main()
