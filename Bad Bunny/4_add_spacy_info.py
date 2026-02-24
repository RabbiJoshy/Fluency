#!/usr/bin/env python3
"""
Build preview entries for the first n vocab_evidence items:
ONE top-level entry per (word, lemma) pairing, with a sense scaffold
and an English flag.

Input : Bad Bunny/intermediates/3_vocab_evidence_merged.json
Output: Bad Bunny/intermediates/4_spacy_output.json

Requires:
  pip install spacy
  python -m spacy download es_core_news_lg
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
import spacy
from wordfreq import word_frequency

n = None  # process all entries

IN_PATH = Path("Bad Bunny/intermediates/3_vocab_evidence_merged.json")
OUT_PATH = Path("Bad Bunny/intermediates/4_spacy_output.json")


# ---- Irregular Spanish verb lemma table --------------------------------------
# spaCy's es_core_news_lg is trained on news text. It doesn't know the
# future/conditional stems of irregular verbs (pondr-, podr-, tendr- …),
# so it invents lemmas like pondrar, podrar, tendrar.  These 12 verbs have
# suppletive future stems that cannot be derived by suffix rules — they need
# a hard lookup.  The table maps every surface prefix that uniquely identifies
# the verb to its infinitive.
#
# Pattern: if word starts with one of these stems AND the suffix is a
# future/conditional inflection (-é,-ás,-á,-emos,-éis,-án,-ía,-ías,…),
# override spaCy's lemma with the correct infinitive.

_IRREG_FUTURE_STEMS: list[tuple[str, str]] = [
    # stem (after stripping accent-normalised prefix)  →  infinitive
    ("pondr",  "poner"),
    ("podr",   "poder"),
    ("saldr",  "salir"),
    ("tendr",  "tener"),
    ("vendr",  "venir"),
    ("valdr",  "valer"),
    ("querr",  "querer"),
    ("cabr",   "caber"),
    ("sabr",   "saber"),
    ("habr",   "haber"),
    ("har",    "hacer"),   # haré, harás … (har- is unambiguous; "harar" ≠ real)
    ("dir",    "decir"),   # diré, dirás … (but NOT "dis-" forms)
]

# Future/conditional personal suffixes (with and without written accent)
_FUTURE_COND_SUFFIXES = (
    "é", "ás", "á", "emos", "éis", "án",          # future
    "ía", "ías", "íamos", "íais", "ían",           # conditional
    "e", "as", "a", "an",                          # same without accents
)

import unicodedata as _ud

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in _ud.normalize("NFD", s)
        if _ud.category(c) != "Mn"
    )

def correct_irregular_future_lemma(word: str, spacy_lemma: str) -> str:
    """
    If `word` is a future/conditional form of one of the 12 irregular Spanish
    verbs, return the correct infinitive.  Otherwise return `spacy_lemma`
    unchanged.
    """
    w = _strip_accents(word.lower())
    for stem, infinitive in _IRREG_FUTURE_STEMS:
        if not w.startswith(stem):
            continue
        suffix = w[len(stem):]
        if suffix in _FUTURE_COND_SUFFIXES:
            return infinitive
    return spacy_lemma


# ---- Clitic-attached verb lemma correction -----------------------------------
# Spanish infinitives, gerunds and imperatives can have pronoun clitics
# appended: ponerla (poner+la), darte (dar+te), verte (ver+te),
# enamorarme (enamorar+me), hacerlos (hacer+los).
# spaCy misidentifies the clitic as a feminine noun suffix and converts it to
# masculine form: ponerla → ponerel, darte → darel, etc.
# Solution: if spaCy produces a self-lemma (or the wordfreq quality gate fires),
# try stripping a clitic and checking whether the remainder is a real Spanish verb.

# Sorted longest-first so compound clitics (melo, telo) are tried before single.
_CLITICS: list[str] = sorted(
    ["melo", "telo", "sela", "selo",
     "me", "te", "se", "le", "la", "lo", "nos", "os",
     "les", "las", "los"],
    key=len, reverse=True,
)

_VERB_ENDINGS: tuple[str, ...] = ("ar", "er", "ir", "ár", "ér", "ír")

# Nouns/adverbs whose suffix accidentally matches a verb+clitic pattern.
# e.g. "parte" → base "par" (ends in -ar, wordfreq > 0) → would wrongly return "par".
_CLITIC_NOUN_EXCEPTIONS: frozenset[str] = frozenset({
    "muerte", "suerte", "parte", "marte", "arte", "fuerte", "frente",
    "gente", "mente", "madre", "padre", "libre", "sobre", "nombre",
    "entre", "siempre", "antes", "lunes", "martes",
})


def strip_clitic_for_lemma(word: str):
    """
    If `word` looks like <verb-infinitive/gerund/imperative> + <clitic>,
    return the base verb string.  Otherwise return None.

    Examples: ponerla → poner, darte → dar, verte → ver,
              hacerlos → hacer, enamorarme → enamorar.
    """
    w = word.strip().lower()
    if w in _CLITIC_NOUN_EXCEPTIONS:
        return None
    for clitic in _CLITICS:
        if not w.endswith(clitic):
            continue
        base = w[: len(w) - len(clitic)]
        if len(base) < 3:
            continue
        if not base.endswith(_VERB_ENDINGS):
            continue
        if word_frequency(base, "es") >= 1e-6:
            return base
    return None


# ---- English flagging (wordfreq-based, non-destructive) ----------------------

SPANISH_DIACRITICS_RE = re.compile(r"[áéíóúüñ]", re.IGNORECASE)

# Threshold: en/(en+es) ratio above this → flag as English.
# 0.85 is intentionally high to avoid nuking Spanish/English homographs.
EN_RATIO_THRESHOLD = 0.85

def english_flag(word: str) -> dict:
    w = word.strip().lower()

    # Strong Spanish signal — diacritics always win regardless of frequency data.
    if SPANISH_DIACRITICS_RE.search(w):
        return {"is_english": False, "confidence": 0.01, "reason": "spanish_diacritic"}

    en_freq = word_frequency(w, "en")
    es_freq = word_frequency(w, "es")

    # Word unknown to wordfreq entirely (e.g. novel slang, elisions)
    if en_freq == 0 and es_freq == 0:
        return {"is_english": False, "confidence": 0.20, "reason": "wordfreq_unknown"}

    total = en_freq + es_freq
    en_ratio = en_freq / total

    if en_ratio >= EN_RATIO_THRESHOLD:
        return {"is_english": True, "confidence": round(en_ratio, 3), "reason": "wordfreq_ratio"}
    else:
        return {"is_english": False, "confidence": round(1 - en_ratio, 3), "reason": "wordfreq_ratio"}


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
    data = json.loads(IN_PATH.read_text(encoding="utf-8"))
    first10 = data[:n]

    # spaCy Spanish model — disable heavy components
    nlp = spacy.load("es_core_news_lg", disable=["ner", "parser"])
    # Ensure sentence segmentation isn’t required; we just need tokens/lemmas/POS.

    outputs = []

    for idx, entry in enumerate(first10, start=1):
        word_raw = entry["word"]
        word = normalize_for_match(word_raw)
        display_form = entry.get("display_form")
        display_norm = normalize_for_match(display_form) if display_form else None
        match_forms = {word}
        if display_norm and display_norm != word:
            match_forms.add(display_norm)
        occ_count = entry.get("occurrences_ppm") or entry.get("corpus_count")
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
            # If this entry was merged from an elided form, replace the
            # elided spelling with the full word so spaCy can lemmatize it.
            # e.g. "tú ere' mala" -> "tú eres mala"
            sub_pattern = None
            if display_form and display_form != word_raw:
                escaped = re.escape(display_form)
                sub_pattern = re.compile(
                    r"(?<![A-Za-zÁÉÍÓÚÜÑáéíóúüñ])"
                    + escaped
                    + r"(?![A-Za-zÁÉÍÓÚÜÑáéíóúüñ])",
                    re.IGNORECASE,
                )

            def prep_line(line):
                line = clean_line_for_nlp(line)
                if sub_pattern:
                    line = sub_pattern.sub(word_raw, line)
                return line

            lines = [prep_line(ex["line"]) for ex in examples]
            docs = nlp.pipe(lines)

            # Change this section (around line 113-129):
            for ex, doc in zip(examples, docs):
                ex_id = ex["id"]
                raw_line = ex["line"]
                song_name = ex.get("title", "")  # ADD THIS LINE

                for tok in doc:
                    tok_norm = normalize_for_match(tok.text)

                    # match against word and its elided display form
                    if tok_norm not in match_forms:
                        continue

                    lemma = (tok.lemma_ or tok.text).lower()
                    lemma = normalize_for_match(lemma) or word  # fallback

                    # Pass 1 — irregular future/conditional override (must run
                    # before the wordfreq gate, which would otherwise accept the
                    # bad spaCy lemma if it happens to have non-zero frequency).
                    lemma = correct_irregular_future_lemma(word_raw, lemma)

                    # Pass 2 — quality gate: spaCy sometimes invents non-existent
                    # lemmas for slang and clitic-attached forms it doesn't recognise
                    # (e.g. dime→dimir, dale→dalar, perreo→perreir).
                    # If the lemma has zero frequency in both languages it's invented
                    # — fall back to the surface form instead.
                    if (word_frequency(lemma, "es") == 0
                            and word_frequency(lemma, "en") == 0):
                        lemma = word

                    # Pass 3 — clitic-attached verb correction.
                    # If the lemma still equals the surface word (spaCy self-lemmatised
                    # or Pass 2 fell back), check whether the word is an
                    # infinitive/gerund/imperative + pronoun clitic and recover the
                    # base verb.  e.g. ponerla → poner, darte → dar, verte → ver.
                    if lemma == word:
                        base = strip_clitic_for_lemma(word_raw)
                        if base:
                            lemma = base

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

            out_entry = {
                "key": f"{word_raw}|{lemma}",
                "word": word_raw,
                "lemma": lemma,
                "corpus_count": occ_count,
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
            }
            if display_form:
                out_entry["display_form"] = display_form
            outputs.append(out_entry)

    OUT_PATH.write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(outputs)} (word, lemma) entries to {OUT_PATH}")


if __name__ == "__main__":
    main()
