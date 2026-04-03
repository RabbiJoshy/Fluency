#!/usr/bin/env python3
"""
Translation quality checker for BadBunnyvocabulary.json.

Scans for:
  1. Empty word translations (missing meanings)
  2. Empty sentence translations (missing example translations)
  3. Content word mismatches — where the word's English translation
     doesn't appear in any of its example sentence translations
  4. Suspected hallucinations — English sentences that don't seem
     related to their Spanish counterparts

Outputs a report to stdout and optionally writes flagged entries
to a JSON file for batch re-translation.

Usage (from project root):
    .venv/bin/python3 "Bad Bunny/check_translations.py"
    .venv/bin/python3 "Bad Bunny/check_translations.py" --output bad_translations.json
"""

import json
import os
import re
import argparse
from typing import Dict, List, Set, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VOCAB_PATH = os.path.join(SCRIPT_DIR, "BadBunnyvocabulary.json")

# Words to skip mismatch checking — function words and highly polysemous words
# produce too many false positives because they translate idiomatically
SKIP_MISMATCH_CHECK = frozenset({
    # Articles / determiners
    "el", "la", "los", "las", "un", "una", "unos", "unas",
    # Prepositions
    "a", "de", "en", "con", "por", "para", "sin", "sobre", "entre",
    "desde", "hasta", "hacia", "contra", "del", "al",
    "pa'", "pa", "pal",
    # Conjunctions
    "y", "o", "pero", "ni", "que", "porque", "aunque", "como",
    "si", "cuando", "donde", "mientras", "pues",
    # Pronouns
    "yo", "tú", "él", "ella", "nosotros", "ellos", "ellas",
    "usted", "ustedes", "vos",
    "me", "te", "se", "nos", "le", "les", "lo", "la",
    "mi", "tu", "su", "mis", "tus", "sus",
    "mí", "ti", "sí", "conmigo", "contigo",
    "esto", "eso", "este", "esta", "ese", "esa",
    "qué", "quién", "cuál", "cómo", "dónde", "cuándo",
    # Adverbs
    "no", "ya", "más", "muy", "bien", "mal", "aquí", "ahora",
    "hoy", "nunca", "siempre", "también", "solo", "sólo",
    "así", "tan", "tanto", "todavía", "aún",
    # Common verbs (too polysemous for literal matching)
    "es", "ser", "estar", "hay", "haber", "ir", "tener",
    "hacer", "dar", "ver", "saber", "poder", "querer",
    "decir", "venir", "poner", "salir", "pasar", "dejar",
    "quedar", "llevar", "tomar", "meter", "echar",
    # Common verb forms
    "tengo", "tienes", "tiene", "tienen",
    "quiero", "quieres", "quiere", "quieren",
    "puedo", "puede", "pueden",
    "voy", "vas", "va", "vamos", "van",
    "soy", "eres", "ere'", "somos", "son",
    "estoy", "estás", "está", "están",
    "digo", "dice", "dicen",
    "sé", "sabes", "sabe", "sabe'", "saben",
    "hago", "haces", "hace", "hacen",
    "doy", "das", "da", "dan",
    # Caribbean elisions of above
    "tamo'", "vamo'", "va'", "vo'", "e'",
    # Other high-frequency words that translate too variably
    "cosa", "tipo", "mano", "vez", "día", "noche",
    "todo", "toda", "todos", "todas", "to'", "toa'", "to'a",
    "nada", "algo", "alguien", "nadie",
    "otro", "otra", "otros", "otras",
    "mismo", "misma", "mucho", "mucha", "poco", "poca",
})

# Short English words that are too ambiguous for overlap checking
MIN_TRANSLATION_LEN = 4  # skip translation words shorter than this


def extract_check_words(translation):
    # type: (str) -> Set[str]
    """Extract English words from a translation string for overlap checking."""
    if not translation:
        return set()

    t = translation.lower()
    # Strip parenthetical notes like "(informal)", "(PR slang)"
    t = re.sub(r"\([^)]*\)", "", t)
    # Split on common separators
    words = set()
    for part in re.split(r"[/,;]", t):
        for w in part.split():
            clean = w.strip(".,!?'\"")
            if clean.isalpha() and len(clean) >= MIN_TRANSLATION_LEN:
                words.add(clean)
    return words


def check_overlap(translation_words, english_sentence):
    # type: (Set[str], str) -> bool
    """Check if any translation word appears in the English sentence."""
    if not translation_words or not english_sentence:
        return True  # can't check, assume OK

    eng_lower = english_sentence.lower()
    # Check each translation word
    for tw in translation_words:
        # Word boundary match to avoid partial matches
        if re.search(r'\b' + re.escape(tw) + r'\w*\b', eng_lower):
            return True
    return False


def check_sentence_coherence(spanish, english):
    # type: (str, str) -> bool
    """
    Basic coherence check: does the English sentence look like a translation?
    Flags obvious problems like identical text, empty results, or
    English that's way too short/long relative to Spanish.
    """
    if not spanish or not english:
        return True  # can't check

    # Identical text (not translated)
    if spanish.strip().lower() == english.strip().lower():
        return False

    # Extreme length mismatch (translation is <20% or >300% of original)
    sp_len = len(spanish)
    en_len = len(english)
    if sp_len > 10:
        ratio = en_len / sp_len
        if ratio < 0.2 or ratio > 3.0:
            return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Translation quality checker")
    parser.add_argument("--output", type=str, default="",
                        help="Write flagged entries to this JSON file")
    parser.add_argument("--verbose", action="store_true",
                        help="Show all issues (not just summary)")
    args = parser.parse_args()

    print("Loading %s..." % VOCAB_PATH)
    with open(VOCAB_PATH, "r", encoding="utf-8") as f:
        vocab = json.load(f)
    print("  %d entries" % len(vocab))

    # --- Collect issues ---
    empty_word_trans = []    # type: List[Dict]
    empty_sentence_trans = []  # type: List[Dict]
    content_mismatches = []  # type: List[Dict]
    coherence_issues = []    # type: List[Dict]

    for entry in vocab:
        word = entry.get("word", "")
        w_lower = word.lower()

        # Skip flagged entries
        if entry.get("is_english") or entry.get("is_propernoun") or entry.get("is_interjection"):
            continue

        for m_idx, meaning in enumerate(entry.get("meanings", [])):
            word_trans = meaning.get("translation", "")

            # Issue 1: Empty word translation
            if not word_trans:
                empty_word_trans.append({
                    "word": word,
                    "lemma": entry.get("lemma", ""),
                    "pos": meaning.get("pos", ""),
                    "corpus_count": entry.get("corpus_count", 0),
                    "issue": "empty_word_translation",
                })
                continue

            examples_with_english = []
            for ex in meaning.get("examples", []):
                spanish = ex.get("spanish", "")
                english = ex.get("english", "")

                # Issue 2: Empty sentence translation
                if spanish and not english:
                    empty_sentence_trans.append({
                        "word": word,
                        "spanish": spanish[:80],
                        "issue": "empty_sentence_translation",
                    })
                    continue

                # Issue 4: Coherence check
                if spanish and english and not check_sentence_coherence(spanish, english):
                    coherence_issues.append({
                        "word": word,
                        "spanish": spanish[:80],
                        "english": english[:80],
                        "issue": "coherence_problem",
                    })

                if english:
                    examples_with_english.append(ex)

            # Issue 3: Content word mismatch (per-word, not per-example)
            # Only flag if NONE of the examples contain the translation word.
            # A single match across any example means the translation is plausible.
            if (w_lower not in SKIP_MISMATCH_CHECK and word_trans
                    and examples_with_english):
                check_words = extract_check_words(word_trans)
                if check_words:
                    any_match = False
                    for ex in examples_with_english:
                        if check_overlap(check_words, ex.get("english", "")):
                            any_match = True
                            break
                    if not any_match:
                        best_ex = examples_with_english[0]
                        content_mismatches.append({
                            "word": word,
                            "translation": word_trans,
                            "spanish": best_ex.get("spanish", "")[:80],
                            "english": best_ex.get("english", "")[:80],
                            "check_words": sorted(check_words),
                            "corpus_count": entry.get("corpus_count", 0),
                            "issue": "translation_not_in_sentence",
                        })

    # --- Report ---
    print("\n" + "=" * 60)
    print("Translation Quality Report")
    print("=" * 60)

    print("\n1. Empty word translations: %d" % len(empty_word_trans))
    if args.verbose and empty_word_trans:
        for item in empty_word_trans[:30]:
            print("   %s (lemma=%s, pos=%s, count=%d)" %
                  (item["word"], item["lemma"], item["pos"], item["corpus_count"]))
        if len(empty_word_trans) > 30:
            print("   ... +%d more" % (len(empty_word_trans) - 30))

    print("\n2. Empty sentence translations: %d" % len(empty_sentence_trans))
    if args.verbose and empty_sentence_trans:
        for item in empty_sentence_trans[:10]:
            print("   %s: %s" % (item["word"], item["spanish"]))

    # Sort mismatches by corpus count (highest-impact first)
    content_mismatches.sort(key=lambda x: -x.get("corpus_count", 0))

    print("\n3. Content word mismatches: %d" % len(content_mismatches))
    if content_mismatches:
        print("   (word translation doesn't appear in ANY example sentence)")
        print("   (sorted by corpus frequency — review high-count words first)")
        shown = content_mismatches[:20] if args.verbose else content_mismatches[:5]
        for item in shown:
            print("   %s (%s)" % (item["word"], item["translation"]))
            print("     ES: %s" % item["spanish"])
            print("     EN: %s" % item["english"])
            print()
        if len(content_mismatches) > len(shown):
            print("   ... +%d more (use --verbose to see all)" % (len(content_mismatches) - len(shown)))

    print("\n4. Sentence coherence issues: %d" % len(coherence_issues))
    if coherence_issues:
        shown = coherence_issues[:10] if args.verbose else coherence_issues[:3]
        for item in shown:
            print("   %s:" % item["word"])
            print("     ES: %s" % item["spanish"])
            print("     EN: %s" % item["english"])
            print()

    # --- Summary ---
    total_issues = (len(empty_word_trans) + len(empty_sentence_trans) +
                    len(content_mismatches) + len(coherence_issues))
    print("\n" + "=" * 60)
    print("Total issues: %d" % total_issues)
    print("  Empty word translations:    %4d  (need step 6 or manual fill)" % len(empty_word_trans))
    print("  Empty sentence translations: %4d  (need re-translation)" % len(empty_sentence_trans))
    print("  Content word mismatches:    %4d  (review for accuracy)" % len(content_mismatches))
    print("  Coherence issues:           %4d  (likely hallucinations)" % len(coherence_issues))

    # --- Optional JSON output ---
    if args.output:
        all_issues = {
            "empty_word_translations": empty_word_trans,
            "empty_sentence_translations": empty_sentence_trans,
            "content_mismatches": content_mismatches,
            "coherence_issues": coherence_issues,
            "summary": {
                "total_entries": len(vocab),
                "total_issues": total_issues,
            },
        }
        out_path = os.path.join(SCRIPT_DIR, args.output) if not os.path.isabs(args.output) else args.output
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_issues, f, ensure_ascii=False, indent=2)
        print("\nWrote detailed report to %s" % out_path)


if __name__ == "__main__":
    main()
