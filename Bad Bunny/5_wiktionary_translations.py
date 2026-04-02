#!/usr/bin/env python3
"""
Phase 3: Dictionary-based translations using Wiktionary glosses.

Replaces steps 5 + 6 (cache-based translation + Google Translate gap-filling).
Uses Wiktionary sense glosses matched on (lemma, POS) for context-aware
translations that don't suffer from bare-word ambiguity.

Input : Bad Bunny/intermediates/4_wiktionary_output.json
Output: Bad Bunny/intermediates/phase3_vocabulary.json
Also:   Bad Bunny/intermediates/phase3_diff_report.json

Requires:
  Wiktionary dump at /tmp/kaikki_spanish.jsonl.gz
"""

import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
IN_PATH = SCRIPT_DIR / "intermediates" / "4_wiktionary_output.json"
OUT_PATH = SCRIPT_DIR / "intermediates" / "phase3_vocabulary.json"
DIFF_PATH = SCRIPT_DIR / "intermediates" / "phase3_diff_report.json"
OLD_VOCAB_PATH = SCRIPT_DIR / "BadBunnyvocabulary.json"
WIKT_DUMP = Path("/tmp/kaikki_spanish.jsonl.gz")

# ── Curated translations for high-frequency function words ───────────────────
# These are words where Wiktionary glosses are too verbose, wrong POS-matched,
# or missing. Flashcard translations should be short and practical.
CURATED_TRANSLATIONS = {
    # Articles / determiners
    "el": "the", "la": "the", "los": "the", "las": "the",
    "un": "a, an", "una": "a, an", "unos": "some", "unas": "some",
    # Possessives
    "mi": "my", "tu": "your", "su": "his/her/their",
    "mis": "my", "tus": "your", "sus": "his/her/their",
    "nuestro": "our", "nuestra": "our", "nuestros": "our", "nuestras": "our",
    # Personal pronouns
    "yo": "I", "tú": "you", "él": "he", "ella": "she",
    "nosotros": "we", "nosotras": "we", "ellos": "they", "ellas": "they",
    "usted": "you (formal)", "ustedes": "you all",
    # Object / reflexive pronouns
    "me": "me", "te": "you", "se": "oneself/himself/herself",
    "lo": "it/him", "la": "her/it", "le": "him/her (indirect)",
    "nos": "us", "les": "them (indirect)", "los": "them",
    # Prepositional pronouns
    "mí": "me", "ti": "you", "sí": "oneself/himself",
    "conmigo": "with me", "contigo": "with you",
    # Prepositions
    "a": "to, at", "de": "of, from", "en": "in, at, on",
    "con": "with", "por": "for, by", "para": "for, to",
    "sin": "without", "sobre": "on, about", "entre": "between",
    "desde": "from, since", "hasta": "until, up to",
    "hacia": "toward", "contra": "against",
    # Contractions
    "del": "of the", "al": "to the",
    # Conjunctions
    "y": "and", "o": "or", "pero": "but", "ni": "nor, not even",
    "que": "that, which", "porque": "because",
    "aunque": "although", "como": "as, like",
    "si": "if", "cuando": "when", "donde": "where",
    "mientras": "while",
    # Adverbs
    "no": "no, not", "ya": "already, now", "más": "more",
    "muy": "very", "bien": "well", "mal": "badly",
    "hoy": "today", "aquí": "here", "ahora": "now",
    "siempre": "always", "nunca": "never",
    "también": "also", "después": "after, later",
    "antes": "before", "así": "like this, so",
    "tan": "so, such", "tanto": "so much",
    # Demonstratives
    "este": "this", "esta": "this", "ese": "that", "esa": "that",
    "esto": "this", "eso": "that",
    # Interrogatives
    "qué": "what", "quién": "who", "cómo": "how",
    "dónde": "where", "cuándo": "when",
    # Caribbean elisions
    "pa'": "for, to", "na'": "nothing", "to'": "all, every",
    "pa": "for, to", "na": "nothing",
    "toy": "I am", "tá": "is",
    "vo'a": "I'm going to", "pa'l": "to the",
    # Other high-frequency
    "hay": "there is/are", "sé": "I know",
    "mucho": "a lot, much", "poco": "little, few",
    "sí": "yes",
    # Common words where Wiktionary's first sense is misleading
    "hacer": "to do, to make",
    "gustar": "to like, to please",
    "gusta": "to like, to please",
    "cabrón": "bastard, badass",
    "cabrones": "bastards, badasses",
    "arriba": "up, above",
    "panas": "friends, buddies",
    "claro": "of course, clear",
    "dale": "go ahead, do it",
    "duro": "hard, tough",
    "mami": "baby, babe",
    "papi": "daddy, babe",
    "loco": "crazy",
    "loca": "crazy",
    "bellaco": "horny, turned on",
    "bellaca": "horny, turned on",
    "perreo": "reggaeton dancing",
    "perrear": "to dance reggaeton",
    "janguear": "to hang out",
    "jangueo": "hanging out, partying",
    "bicho": "thing, dude",
    "bichote": "big shot, boss",
    "gata": "girl, babe",
    "gato": "cat, dude",
    "pana": "friend, buddy",
}

# POS mapping: Wiktionary → Universal Dependencies
WIKT_TO_UD = {
    "verb": "VERB", "noun": "NOUN", "adj": "ADJ", "adv": "ADV",
    "pron": "PRON", "prep": "ADP", "conj": "CCONJ", "det": "DET",
    "article": "DET", "num": "NUM", "intj": "INTJ", "particle": "PART",
    "contraction": "ADP", "name": "PROPN", "prefix": "X", "suffix": "X",
    "phrase": "X", "abbrev": "X",
}

UD_TO_WIKT = defaultdict(list)
for wikt, ud in WIKT_TO_UD.items():
    UD_TO_WIKT[ud].append(wikt)
# Add extra mappings for common UD tags
UD_TO_WIKT["SCONJ"].extend(["conj"])
UD_TO_WIKT["CCONJ"].extend(["conj"])
UD_TO_WIKT["ADP"].extend(["prep"])


def clean_gloss(gloss: str) -> str:
    """
    Clean a Wiktionary gloss for use as a flashcard translation.
    Remove parenthetical notes, clean up formatting.
    """
    if not gloss:
        return ""

    # Skip glosses that are just form-of references
    if any(gloss.startswith(p) for p in (
        "inflection of", "plural of", "feminine of", "masculine of",
        "Alternative spelling", "Alternative form", "Obsolete",
        "Misspelling", "Dated form", "abbreviation of",
    )):
        return ""

    # Remove parenthetical qualifiers but keep the main meaning
    # e.g. "to make (someone) happy" → "to make happy"
    # But keep short ones: "(music) record" → "record"
    result = gloss

    # Remove leading context labels in parentheses: "(colloquial) to eat" → "to eat"
    result = re.sub(r"^\([^)]{0,30}\)\s*", "", result)

    # Remove trailing parenthetical notes
    result = re.sub(r"\s*\([^)]*\)\s*$", "", result)

    # Clean up "used with..." and similar trailing notes
    result = re.sub(r"\s*[;,]\s*used (?:with|to|in|as).*$", "", result, flags=re.IGNORECASE)

    # Strip wiki formatting artifacts
    result = result.strip(" ,;.")

    # Truncate very long glosses (keep first clause)
    if len(result) > 40:
        # Try splitting on semicolons first
        parts = result.split(";")
        result = parts[0].strip()
    if len(result) > 40:
        # Try splitting on commas
        parts = result.split(",")
        result = ", ".join(parts[:2]).strip()

    return result


def load_wiktionary_glosses(dump_path: Path) -> dict:
    """
    Parse Wiktionary dump into: word → {wikt_pos: [cleaned glosses]}
    Only keeps true lemma entries (not form-of entries).
    """
    print("Loading Wiktionary glosses...")
    glosses = defaultdict(lambda: defaultdict(list))

    with gzip.open(dump_path, "rt", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            word = entry.get("word", "").lower().strip()
            wikt_pos = entry.get("pos", "")
            if not word:
                continue

            for sense in entry.get("senses", []):
                # Skip form-of senses
                if "form_of" in sense:
                    continue
                raw_glosses = sense.get("glosses", [])
                for g in raw_glosses:
                    cleaned = clean_gloss(g)
                    if cleaned and cleaned not in glosses[word][wikt_pos]:
                        glosses[word][wikt_pos].append(cleaned)

    print(f"  {len(glosses):,} words with glosses")
    return dict(glosses)


def get_translation(word: str, lemma: str, ud_pos: str,
                    glosses: dict) -> str:
    """
    Get the best translation for a word given its lemma and POS.

    Strategy:
      0. Check curated translations table (highest priority)
      1. Look up lemma + matching POS in Wiktionary glosses
      2. Fall back to lemma + any POS
      3. Fall back to word (surface form) + matching POS
      4. Fall back to word + any POS
      5. Return empty string (will need claude -p or manual fill)
    """
    w = word.lower()

    # 0. Curated translations (short, flashcard-ready)
    if w in CURATED_TRANSLATIONS:
        return CURATED_TRANSLATIONS[w]
    if lemma in CURATED_TRANSLATIONS:
        return CURATED_TRANSLATIONS[lemma]

    # Map UD POS to possible Wiktionary POS values
    wikt_pos_options = UD_TO_WIKT.get(ud_pos, [])

    # 1. Lemma + matching POS
    if lemma in glosses:
        for wp in wikt_pos_options:
            if wp in glosses[lemma]:
                gs = glosses[lemma][wp]
                if gs:
                    return gs[0]  # First (most common) sense

    # 2. Lemma + any POS
    if lemma in glosses:
        for wp in glosses[lemma]:
            gs = glosses[lemma][wp]
            if gs:
                return gs[0]

    # 3. Word + matching POS
    w = word.lower()
    if w != lemma and w in glosses:
        for wp in wikt_pos_options:
            if wp in glosses[w]:
                gs = glosses[w][wp]
                if gs:
                    return gs[0]

    # 4. Word + any POS
    if w != lemma and w in glosses:
        for wp in glosses[w]:
            gs = glosses[w][wp]
            if gs:
                return gs[0]

    return ""


def get_all_pos_translations(word: str, lemma: str, pos_counts: dict,
                             glosses: dict) -> list[dict]:
    """
    Build a meanings list: one entry per POS with the best translation.
    """
    meanings = []
    total_count = sum(pos_counts.values())

    for ud_pos, count in sorted(pos_counts.items(), key=lambda x: -x[1]):
        trans = get_translation(word, lemma, ud_pos, glosses)
        if not trans:
            # Try without POS constraint
            trans = get_translation(word, lemma, "X", glosses)

        freq = f"{count / total_count:.2f}" if total_count > 0 else "1.00"

        meanings.append({
            "pos": ud_pos,
            "translation": trans,
            "frequency": freq,
        })

    return meanings


def main():
    # Load inputs
    with open(IN_PATH) as f:
        wikt_output = json.load(f)
    print(f"Loaded {len(wikt_output)} entries from Phase 1 output")

    glosses = load_wiktionary_glosses(WIKT_DUMP)

    # Load old vocabulary for comparison and stable IDs
    old_vocab = {}
    old_ids = {}
    if OLD_VOCAB_PATH.exists():
        with open(OLD_VOCAB_PATH) as f:
            for entry in json.load(f):
                key = (entry.get("word", ""), entry.get("lemma", ""))
                old_vocab[entry.get("word", "")] = entry
                if "id" in entry:
                    old_ids[key] = entry["id"]

    # Build output
    output = []
    next_id = max((int(v, 16) for v in old_ids.values()), default=0) + 1

    stats = {
        "total": 0, "translated": 0, "empty_translation": 0,
        "from_wiktionary": 0, "from_old_cache": 0,
    }
    diff_report = {"translation_changes": [], "new_translations": [],
                   "still_empty": [], "stats": {}}

    for idx, entry in enumerate(wikt_output):
        word = entry["word"]
        lemma = entry["lemma"]
        corpus_count = entry.get("corpus_count", 0)
        pos_counts = entry.get("pos_summary", {}).get("pos_counts", {})
        lang_flags = entry.get("language_flags", {})
        display_form = entry.get("display_form")
        examples = entry.get("evidence", {}).get("examples", [])

        # Stable ID assignment
        key = (word, lemma)
        if key in old_ids:
            hex_id = old_ids[key]
        else:
            # Try word-only match from old vocab
            old_entry = old_vocab.get(word)
            if old_entry and "id" in old_entry:
                hex_id = old_entry["id"]
            else:
                hex_id = format(next_id, "04x")
                next_id += 1

        # Determine flags
        is_english = lang_flags.get("is_english", False)
        is_interjection = "INTJ" in pos_counts and (
            pos_counts.get("INTJ", 0) / max(sum(pos_counts.values()), 1) > 0.5
        )
        is_propernoun = "PROPN" in pos_counts and (
            pos_counts.get("PROPN", 0) / max(sum(pos_counts.values()), 1) > 0.5
        )

        # Get translations
        if is_english:
            # English words get themselves as translation
            meanings = [{"pos": "X", "translation": word, "frequency": "1.00"}]
        elif is_interjection or is_propernoun:
            meanings = [{"pos": list(pos_counts.keys())[0] if pos_counts else "X",
                         "translation": "", "frequency": "1.00"}]
        else:
            meanings = get_all_pos_translations(word, lemma, pos_counts, glosses)

        # Add examples to meanings
        for i, meaning in enumerate(meanings):
            meaning_examples = []
            # Assign examples round-robin across meanings
            for j, ex in enumerate(examples[:10]):
                if j % len(meanings) == i:
                    meaning_examples.append({
                        "song": ex.get("id", "").split(":")[0] if ":" in ex.get("id", "") else "",
                        "song_name": ex.get("title", ""),
                        "spanish": ex.get("line", ""),
                        "english": "",  # Example translations need Phase 3b (claude -p)
                    })
            meaning["examples"] = meaning_examples

        # Track stats
        stats["total"] += 1
        word_trans = meanings[0]["translation"] if meanings else ""
        if word_trans:
            stats["translated"] += 1
            stats["from_wiktionary"] += 1
        else:
            stats["empty_translation"] += 1
            if not is_english and not is_interjection and not is_propernoun:
                diff_report["still_empty"].append({
                    "word": word, "lemma": lemma, "corpus_count": corpus_count,
                })

        # Compare with old vocabulary
        old = old_vocab.get(word)
        if old:
            old_trans = old.get("meanings", [{}])[0].get("translation", "") if old.get("meanings") else ""
            if word_trans and old_trans and word_trans != old_trans:
                diff_report["translation_changes"].append({
                    "word": word, "old": old_trans, "new": word_trans,
                    "corpus_count": corpus_count,
                })
            elif word_trans and not old_trans:
                diff_report["new_translations"].append({
                    "word": word, "translation": word_trans,
                    "corpus_count": corpus_count,
                })

        # Build output entry
        out_entry = {
            "id": hex_id,
            "word": word,
            "lemma": lemma,
            "meanings": meanings,
            "most_frequent_lemma_instance": True,  # Will be recomputed in Phase 4
            "is_english": is_english,
            "is_interjection": is_interjection,
            "is_propernoun": is_propernoun,
            "is_transparent_cognate": False,  # Step 8 is authoritative
            "corpus_count": corpus_count,
        }
        if display_form:
            out_entry["display_form"] = display_form

        output.append(out_entry)

    # Stats
    diff_report["stats"] = stats
    diff_report["stats"]["translation_changes"] = len(diff_report["translation_changes"])
    diff_report["stats"]["new_translations"] = len(diff_report["new_translations"])
    diff_report["stats"]["still_empty"] = len(diff_report["still_empty"])

    # Write output
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(output)} entries to {OUT_PATH}")

    with open(DIFF_PATH, "w", encoding="utf-8") as f:
        json.dump(diff_report, f, ensure_ascii=False, indent=2)
    print(f"Wrote diff report to {DIFF_PATH}")

    # Summary
    print(f"\n{'='*60}")
    print(f"TRANSLATION STATS:")
    print(f"  Total entries:        {stats['total']}")
    print(f"  With translation:     {stats['translated']} ({stats['translated']/stats['total']*100:.1f}%)")
    print(f"  Empty translation:    {stats['empty_translation']} ({stats['empty_translation']/stats['total']*100:.1f}%)")
    print(f"  Still empty (non-junk): {len(diff_report['still_empty'])}")

    print(f"\nTRANSLATION CHANGES vs old vocab (top 20 by count):")
    changes = sorted(diff_report["translation_changes"], key=lambda x: -x["corpus_count"])
    for c in changes[:20]:
        print(f"  {c['word']:15s}  \"{c['old']:20s}\" → \"{c['new'][:30]}\"  (count={c['corpus_count']})")

    print(f"\nNEW TRANSLATIONS (top 20 — previously empty):")
    new = sorted(diff_report["new_translations"], key=lambda x: -x["corpus_count"])
    for n in new[:20]:
        print(f"  {n['word']:15s}  \"{n['translation'][:30]}\"  (count={n['corpus_count']})")

    print(f"\nSTILL EMPTY (top 20 — need claude -p):")
    empty = sorted(diff_report["still_empty"], key=lambda x: -x["corpus_count"])
    for e in empty[:20]:
        print(f"  {e['word']:15s}  (lemma={e['lemma']}, count={e['corpus_count']})")


if __name__ == "__main__":
    main()
