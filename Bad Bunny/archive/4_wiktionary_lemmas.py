#!/usr/bin/env python3
"""
Phase 1 replacement for 4_add_spacy_info.py: dictionary-based lemmatization.

Uses Wiktionary (kaikki.org dump) as primary source, with simplemma as fallback.
Produces output in the SAME schema as 4_spacy_output.json so step 5 can consume
it unchanged.

Input : Bad Bunny/intermediates/3_vocab_evidence_merged.json
Output: Bad Bunny/intermediates/4_wiktionary_output.json
Also:   Bad Bunny/intermediates/phase1_diff_report.json  (comparison vs spaCy)

Requires:
  pip install simplemma wordfreq
  Wiktionary dump at /tmp/kaikki_spanish.jsonl.gz
    curl -o /tmp/kaikki_spanish.jsonl.gz https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl.gz
"""

import gzip
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from wordfreq import word_frequency

SCRIPT_DIR = Path(__file__).resolve().parent
IN_PATH = SCRIPT_DIR / "intermediates" / "3_vocab_evidence_merged.json"
OUT_PATH = SCRIPT_DIR / "intermediates" / "4_wiktionary_output.json"
DIFF_PATH = SCRIPT_DIR / "intermediates" / "phase1_diff_report.json"
SPACY_PATH = SCRIPT_DIR / "intermediates" / "4_spacy_output.json"
WIKT_DUMP = Path("/tmp/kaikki_spanish.jsonl.gz")

# ── POS tag mapping: Wiktionary POS → Universal Dependencies POS ────────────
WIKT_TO_UD = {
    "verb": "VERB",
    "noun": "NOUN",
    "adj": "ADJ",
    "adv": "ADV",
    "pron": "PRON",
    "prep": "ADP",
    "conj": "CCONJ",
    "det": "DET",
    "article": "DET",
    "num": "NUM",
    "intj": "INTJ",
    "particle": "PART",
    "contraction": "ADP",  # del=de+el, al=a+el
    "name": "PROPN",
    "prefix": "X",
    "suffix": "X",
    "phrase": "X",
    "abbrev": "X",
}

# ── Function words that are their own lemma ──────────────────────────────────
# These are high-frequency words that Wiktionary lists as lemma entries (not
# form-of entries), so the form→lemma lookup won't find them. We hardcode
# them with their canonical lemma and POS.
FUNCTION_WORDS = {
    # Prepositions
    "a": ("a", "ADP"), "ante": ("ante", "ADP"), "bajo": ("bajo", "ADP"),
    "con": ("con", "ADP"), "contra": ("contra", "ADP"), "de": ("de", "ADP"),
    "desde": ("desde", "ADP"), "en": ("en", "ADP"), "entre": ("entre", "ADP"),
    "hacia": ("hacia", "ADP"), "hasta": ("hasta", "ADP"), "para": ("para", "ADP"),
    "por": ("por", "ADP"), "sin": ("sin", "ADP"), "sobre": ("sobre", "ADP"),
    "tras": ("tras", "ADP"),
    # Contractions
    "del": ("de", "ADP"), "al": ("a", "ADP"),
    # Conjunctions
    "y": ("y", "CCONJ"), "o": ("o", "CCONJ"), "pero": ("pero", "CCONJ"),
    "ni": ("ni", "CCONJ"), "que": ("que", "SCONJ"), "porque": ("porque", "SCONJ"),
    "aunque": ("aunque", "SCONJ"), "como": ("como", "SCONJ"),
    "si": ("si", "SCONJ"), "cuando": ("cuando", "SCONJ"),
    "donde": ("donde", "ADV"), "mientras": ("mientras", "SCONJ"),
    # Determiners / articles
    "el": ("el", "DET"), "la": ("el", "DET"), "los": ("el", "DET"),
    "las": ("el", "DET"), "un": ("uno", "DET"), "una": ("uno", "DET"),
    "unos": ("uno", "DET"), "unas": ("uno", "DET"),
    # Possessives
    "mi": ("mi", "DET"), "tu": ("tu", "DET"), "su": ("su", "DET"),
    "mis": ("mi", "DET"), "tus": ("tu", "DET"), "sus": ("su", "DET"),
    "nuestro": ("nuestro", "DET"), "nuestra": ("nuestro", "DET"),
    "nuestros": ("nuestro", "DET"), "nuestras": ("nuestro", "DET"),
    # Personal pronouns — each is its OWN lemma (not collapsed to yo/él)
    "yo": ("yo", "PRON"), "tú": ("tú", "PRON"), "él": ("él", "PRON"),
    "ella": ("ella", "PRON"), "nosotros": ("nosotros", "PRON"),
    "nosotras": ("nosotras", "PRON"), "ellos": ("ellos", "PRON"),
    "ellas": ("ellas", "PRON"), "usted": ("usted", "PRON"),
    "ustedes": ("ustedes", "PRON"),
    # Object / reflexive pronouns — own lemma
    "me": ("me", "PRON"), "te": ("te", "PRON"), "se": ("se", "PRON"),
    "lo": ("lo", "PRON"), "la": ("la", "PRON"),  # note: la is DET or PRON
    "le": ("le", "PRON"), "nos": ("nos", "PRON"),
    "les": ("les", "PRON"), "los": ("los", "PRON"),
    # Demonstratives
    "este": ("este", "DET"), "esta": ("este", "DET"),
    "ese": ("ese", "DET"), "esa": ("ese", "DET"),
    "esto": ("esto", "PRON"), "eso": ("eso", "PRON"),
    "aquí": ("aquí", "ADV"), "ahí": ("ahí", "ADV"), "allí": ("allí", "ADV"),
    # Common adverbs
    "no": ("no", "ADV"), "ya": ("ya", "ADV"), "más": ("más", "ADV"),
    "muy": ("muy", "ADV"), "bien": ("bien", "ADV"), "mal": ("mal", "ADV"),
    "hoy": ("hoy", "ADV"), "aquí": ("aquí", "ADV"), "ahora": ("ahora", "ADV"),
    "siempre": ("siempre", "ADV"), "nunca": ("nunca", "ADV"),
    "también": ("también", "ADV"), "después": ("después", "ADV"),
    "antes": ("antes", "ADV"), "así": ("así", "ADV"),
    "tan": ("tan", "ADV"), "tanto": ("tanto", "ADV"),
    # Relative / interrogative
    "qué": ("qué", "PRON"), "quién": ("quién", "PRON"),
    "cuándo": ("cuándo", "ADV"), "dónde": ("dónde", "ADV"),
    "cómo": ("cómo", "ADV"),
    # Ambiguous high-frequency words that need manual disambiguation
    "sé": ("saber", "VERB"),     # "I know" (not imperative of ser)
    "hay": ("haber", "VERB"),    # "there is/are"
    "mucho": ("mucho", "ADV"),   # "a lot" (not muy)
    "conmigo": ("conmigo", "PRON"),  # "with me" (prepositional pronoun)
    "contigo": ("contigo", "PRON"),
    # Caribbean elisions that step 3 didn't fully resolve
    "to'": ("todo", "DET"),      # todo
    "pa'": ("para", "ADP"),      # para
    "na'": ("nada", "PRON"),     # nada
    "to": ("todo", "DET"),       # sometimes written without apostrophe
    "pa": ("para", "ADP"),
    "na": ("nada", "PRON"),
    "vo'a": ("ir", "VERB"),      # voy a
    "pa'l": ("para", "ADP"),     # para el
    "tá": ("estar", "VERB"),     # está
    "toy": ("estar", "VERB"),    # estoy
}

# ── English detection (reused from step 4) ───────────────────────────────────
ENGLISH_ONLY_WORDS = frozenset({
    "the", "and", "is", "are", "was", "were", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "shall", "should", "may",
    "might", "must", "can", "could", "i", "you", "he", "she", "it", "we",
    "they", "what", "which", "who", "whom", "this", "that", "these", "those",
    "am", "been", "being", "its", "my", "your", "his", "her", "our", "their",
    "myself", "yourself", "himself", "herself", "itself", "ourselves",
    "themselves", "just", "don't", "not", "very", "also", "back", "even",
    "still", "than", "then", "too", "into", "through", "during", "before",
    "after", "above", "below", "between", "under", "again", "further", "once",
    "here", "there", "when", "where", "why", "how", "all", "each", "every",
    "both", "few", "more", "most", "other", "some", "such", "only", "own",
    "same", "so", "up", "out", "off", "over", "about", "any", "if",
    "or", "because", "as", "until", "while", "of", "at", "by", "for",
    "with", "from", "but", "to", "on", "in", "an", "a",
    "shit", "fuck", "fuckin", "nigga", "niggas", "bitch", "bitches",
    "baby", "daddy", "money", "gang", "gangsta", "trap",
    "flow", "freestyle", "featuring", "feat", "remix", "yeah", "yeh",
    "okay", "ok", "oh", "yo", "damn", "like", "go", "let", "come",
    "get", "got", "know", "make", "see", "look", "take", "give",
    "keep", "tell", "think", "call", "feel", "try", "leave", "put",
    "run", "say", "turn", "bring", "play", "move", "live", "believe",
    "hold", "happen", "write", "read", "spend", "grow", "begin",
    "walk", "show", "hear", "world", "big", "new", "old", "first",
    "last", "long", "little", "good", "bad", "right", "man", "life",
    "day", "time", "way", "thing", "people", "down", "now", "never",
    "always", "around", "together", "away", "tonight", "much",
    "real", "true", "sure", "free", "high", "low", "hard", "easy",
    "fast", "best", "girl", "boy", "love", "want",
    "skrt", "brr", "ice", "chain", "drip", "lit", "fire",
    "grind", "hustle", "flex", "vibe", "squad",
    "wuh", "uh", "huh", "nah", "yah",
})

# Words that look English but are valid Spanish
SPANISH_PROTECTED = frozenset({
    "no", "me", "te", "se", "la", "lo", "le", "a", "en", "con", "de",
    "mi", "tu", "su", "yo", "el", "ya", "si", "un", "por", "sin",
    "solo", "real", "come", "pan", "fin", "son", "don", "mal", "sal",
    "bar", "plan", "van", "dan", "tan", "gas", "par", "ven", "den",
    # Caribbean elisions that look English
    "to'", "to", "pa'", "pa", "na'", "na", "toy", "tá",
})


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def has_spanish_diacritics(word: str) -> bool:
    """True if word has ñ or accented vowels (strong Spanish signal)."""
    return bool(re.search(r"[áéíóúüñ]", word.lower()))


def english_flag(word: str) -> dict:
    """Detect whether a word is English. Returns {is_english, confidence, reason}."""
    w = word.lower()

    # Spanish diacritics → definitely not English
    if has_spanish_diacritics(w):
        return {"is_english": False, "confidence": 0.99, "reason": "spanish_diacritics"}

    # Protected Spanish words
    if w in SPANISH_PROTECTED:
        return {"is_english": False, "confidence": 0.95, "reason": "spanish_protected"}

    # Known English words
    if w in ENGLISH_ONLY_WORDS:
        return {"is_english": True, "confidence": 0.99, "reason": "english_wordlist"}

    # wordfreq ratio
    en_freq = word_frequency(w, "en")
    es_freq = word_frequency(w, "es")
    if en_freq == 0 and es_freq == 0:
        return {"is_english": False, "confidence": 0.5, "reason": "unknown_word"}
    total = en_freq + es_freq
    if total > 0:
        en_ratio = en_freq / total
        if en_ratio >= 0.85:
            return {"is_english": True, "confidence": en_ratio, "reason": "wordfreq_ratio"}
    return {"is_english": False, "confidence": 1 - (en_freq / total if total else 0), "reason": "wordfreq_ratio"}


# ── Wiktionary dump parser ───────────────────────────────────────────────────

def load_wiktionary_lookup(dump_path: Path) -> tuple[dict, dict]:
    """
    Parse the Wiktextract JSONL dump into two lookups:
      form_lookup: surface_form → [(lemma, ud_pos)]
      lemma_senses: (word, wikt_pos) → [gloss strings]

    form_lookup is populated from two sources:
      1. "forms" arrays on lemma entries (e.g. ser → forms: [{form: "eres", ...}])
      2. "form_of" in senses of inflected-form entries (e.g. eres → form_of: [{word: "ser"}])
    """
    print("Loading Wiktionary dump...")
    form_lookup = defaultdict(list)  # surface → [(lemma, ud_pos)]
    lemma_set = set()                # (word, wikt_pos) pairs that are TRUE lemma headwords

    with gzip.open(dump_path, "rt", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            word = entry.get("word", "").lower().strip()
            wikt_pos = entry.get("pos", "")
            ud_pos = WIKT_TO_UD.get(wikt_pos, "X")
            if not word:
                continue

            # Check if this is a form-of entry (inflected form pointing to a lemma)
            is_form_of = any(
                "form_of" in sense
                for sense in entry.get("senses", [])
            )

            # Only true lemma headwords go in lemma_set (NOT form-of entries)
            # e.g. "ser" (verb) is a headword; "es" (verb, form-of ser) is not
            if not is_form_of:
                lemma_set.add((word, wikt_pos))

            # 1. Lemma entry with forms array → each form maps back to this word
            for form_entry in entry.get("forms", []):
                form = form_entry.get("form", "").lower().strip()
                tags = form_entry.get("tags", [])
                if form and form != word and "table-tags" not in tags:
                    form_lookup[form].append((word, ud_pos))

            # 2. Form-of entry → senses point back to lemma
            for sense in entry.get("senses", []):
                for fo in sense.get("form_of", []):
                    if isinstance(fo, dict):
                        lemma = fo.get("word", "").lower().strip()
                        if lemma and lemma != word:
                            # Wiktionary uses phrases for multi-clitic forms:
                            # "decir combined with indirect object me and direct object lo"
                            # Extract just the verb infinitive.
                            if " " in lemma:
                                first_word = lemma.split()[0]
                                if first_word.endswith(("ar", "er", "ir", "ír")):
                                    lemma = first_word
                                else:
                                    continue  # skip unparseable phrase lemma
                            form_lookup[word].append((lemma, ud_pos))

    # Deduplicate
    form_lookup = {k: list(set(v)) for k, v in form_lookup.items()}

    print(f"  {len(form_lookup):,} surface forms → lemma mappings")
    print(f"  {len(lemma_set):,} lemma headwords")
    return dict(form_lookup), lemma_set


def _lemma_score(word: str, lemma: str, pos: str) -> tuple:
    """
    Score a (lemma, pos) candidate for disambiguation.
    Higher score = better candidate. Returns a tuple for lexicographic comparison.

    Primary signal: Spanish frequency of the LEMMA. A more frequent lemma is
    more likely the correct interpretation. This correctly handles:
      - es → ser (1.86e-3) over e (8.51e-4)
      - nada → nada (1.05e-3) over nadar (6.31e-6)
      - calle → calle (1.86e-4) over callar (7.59e-6)
      - dime → decir (6.03e-4) over dime (2.75e-5)

    For verb conjugations where the surface form is also common (e.g. "va" is
    more frequent than "ir"), we add a small boost for verb infinitives since
    learners need the infinitive to look up conjugation tables.
    """
    # 1. Penalise lemmas that are full phrases (Wiktionary gloss leaking through)
    is_clean = 0 if " " in lemma else 1

    # 2. Spanish frequency of the LEMMA — primary disambiguation signal
    freq = word_frequency(lemma, "es")

    # 3. Verb infinitive boost: if the lemma is a verb and not the surface form,
    #    it's a conjugated form → boost slightly so "va"→"ir" beats "va"→"va"
    #    The boost (2x) is small enough that truly more-frequent noun lemmas
    #    still win (nada >> nadar even with 2x boost)
    is_verb_infinitive = (pos == "VERB" and lemma != word and
                          lemma.endswith(("ar", "er", "ir", "ír")))
    if is_verb_infinitive:
        freq = freq * 2.0

    # 4. Penalise PROPN and X — these are usually noise
    pos_penalty = 1.0
    if pos in ("PROPN", "X"):
        pos_penalty = 0.01

    return (is_clean, freq * pos_penalty)


def resolve_lemma(word: str, form_lookup: dict, lemma_set: set) -> list[tuple[str, str]]:
    """
    Resolve a surface word to (lemma, ud_pos) pairs.

    Strategy (in order):
      1. Function word table (hardcoded, highest priority)
      2. Wiktionary form→lemma lookup + headword check, disambiguated by score
      3. simplemma fallback
      4. Identity (word = lemma, pos = X)
    """
    w = word.lower().strip()

    # 1. Function words
    if w in FUNCTION_WORDS:
        lemma, pos = FUNCTION_WORDS[w]
        return [(lemma, pos)]

    # 2. Collect ALL candidates from Wiktionary
    candidates = []

    # 2a. From form→lemma lookup (inflected forms)
    if w in form_lookup:
        candidates.extend(form_lookup[w])

    # 2b. Word is itself a Wiktionary headword (already a lemma)
    for wikt_pos in ("verb", "noun", "adj", "adv", "pron", "prep", "conj",
                     "det", "article", "num", "intj", "particle", "contraction"):
        if (w, wikt_pos) in lemma_set:
            ud = WIKT_TO_UD.get(wikt_pos, "X")
            candidates.append((w, ud))

    if candidates:
        # Deduplicate
        candidates = list(set(candidates))
        # Score and sort — best candidate first
        candidates.sort(key=lambda c: _lemma_score(w, c[0], c[1]), reverse=True)
        return candidates

    # 3. simplemma fallback
    try:
        from simplemma import lemmatize
        sm_lemma = lemmatize(w, lang="es")
        if sm_lemma != w:
            # Determine POS from Wiktionary if possible
            sm_pos = "X"
            for wikt_pos in ("verb", "noun", "adj", "adv"):
                if (sm_lemma, wikt_pos) in lemma_set:
                    sm_pos = WIKT_TO_UD.get(wikt_pos, "X")
                    break
            return [(sm_lemma, sm_pos)]
    except ImportError:
        pass

    # 4. Identity fallback
    return [(w, "X")]


# ── POS counting from Wiktionary results ─────────────────────────────────────

def count_pos_from_examples(word: str, results: list[tuple[str, str]],
                            num_examples: int) -> Counter:
    """
    Build a POS counter. Since we don't run NLP on every example line,
    we distribute counts proportionally based on how many lemma+POS
    candidates Wiktionary gives us, weighted by example count.
    """
    pos_counts = Counter()
    if len(results) == 1:
        pos_counts[results[0][1]] = num_examples
    else:
        # Multiple candidates — assign equal weight
        per = max(1, num_examples // len(results))
        for _, pos in results:
            pos_counts[pos] += per
    return pos_counts


# ── Main pipeline ────────────────────────────────────────────────────────────

def main():
    # Load inputs
    with open(IN_PATH) as f:
        vocab = json.load(f)
    print(f"Loaded {len(vocab)} entries from step 3 output")

    form_lookup, lemma_set = load_wiktionary_lookup(WIKT_DUMP)

    # Load spaCy output for comparison (if available)
    spacy_data = {}
    if SPACY_PATH.exists():
        with open(SPACY_PATH) as f:
            for entry in json.load(f):
                spacy_data.setdefault(entry["word"], []).append(entry)
        print(f"Loaded {sum(len(v) for v in spacy_data.values())} spaCy entries for comparison")

    output = []
    diff_report = {"changed_lemmas": [], "changed_pos": [], "new_entries": [],
                   "removed_entries": [], "stats": {}}
    resolution_sources = Counter()

    for idx, entry in enumerate(vocab):
        word = entry["word"]
        corpus_count = entry.get("corpus_count", 0)
        examples = entry.get("examples", [])
        display_form = entry.get("display_form")

        # Resolve lemma
        results = resolve_lemma(word, form_lookup, lemma_set)

        # Track resolution source
        w = word.lower().strip()
        if w in FUNCTION_WORDS:
            resolution_sources["function_word_table"] += 1
        elif w in form_lookup:
            resolution_sources["wiktionary_form"] += 1
        elif any((w, p) in lemma_set for p in
                 ("verb", "noun", "adj", "adv", "pron", "prep", "conj",
                  "det", "article", "num", "intj", "particle", "contraction")):
            resolution_sources["wiktionary_headword"] += 1
        else:
            try:
                from simplemma import lemmatize
                sm = lemmatize(w, lang="es")
                if sm != w:
                    resolution_sources["simplemma"] += 1
                else:
                    resolution_sources["identity_fallback"] += 1
            except ImportError:
                resolution_sources["identity_fallback"] += 1

        # English detection
        lang_flags = english_flag(word)

        # For each (lemma, pos) candidate, produce one output entry
        # But: collapse to the BEST single lemma to avoid the duplication
        # problem that step 7 was created to fix.
        # Pick the best lemma: prefer verbs, then nouns, then others.
        # Group all POS candidates under that lemma.
        best_lemma = results[0][0]
        all_pos = [pos for _, pos in results if _ == best_lemma]
        # If multiple lemmas, keep only the first (highest priority)
        if not all_pos:
            all_pos = [results[0][1]]

        pos_counts = Counter()
        for pos in all_pos:
            pos_counts[pos] += max(1, len(examples))

        # Build matches (synthetic — we haven't run NLP on each line)
        matches = []
        for i, ex in enumerate(examples[:10]):
            pos = all_pos[i % len(all_pos)]
            matches.append({
                "example_id": ex.get("id", ""),
                "example_song_name": ex.get("title", ""),
                "token_text": word,
                "lemma": best_lemma,
                "pos": pos,
            })

        out_entry = {
            "key": f"{word}|{best_lemma}",
            "word": word,
            "lemma": best_lemma,
            "corpus_count": corpus_count,
            "source_rank_in_preview": idx,
            "language_flags": lang_flags,
            "pos_summary": {
                "match_count": len(matches),
                "pos_counts": dict(pos_counts),
            },
            "matches": matches,
            "senses": [{
                "sense_id": f"{word}|{best_lemma}|0",
                "label": "",
                "notes": "",
                "example_ids": [ex.get("id", "") for ex in examples[:10]],
            }],
            "evidence": {
                "examples": examples[:10],
            },
        }
        if display_form:
            out_entry["display_form"] = display_form

        output.append(out_entry)

        # Diff against spaCy
        if word in spacy_data:
            spacy_entries = spacy_data[word]
            spacy_lemmas = {e["lemma"] for e in spacy_entries}
            if best_lemma not in spacy_lemmas:
                diff_report["changed_lemmas"].append({
                    "word": word,
                    "corpus_count": corpus_count,
                    "old_lemmas": sorted(spacy_lemmas),
                    "new_lemma": best_lemma,
                    "source": resolution_sources.most_common(1)[0][0] if resolution_sources else "unknown",
                })
            # Check POS changes
            spacy_pos = set()
            for e in spacy_entries:
                spacy_pos.update(e.get("pos_summary", {}).get("pos_counts", {}).keys())
            new_pos = set(pos_counts.keys())
            if new_pos != spacy_pos:
                diff_report["changed_pos"].append({
                    "word": word,
                    "old_pos": sorted(spacy_pos),
                    "new_pos": sorted(new_pos),
                })

    # Stats
    diff_report["stats"] = {
        "total_entries": len(output),
        "resolution_sources": dict(resolution_sources),
        "lemma_changes": len(diff_report["changed_lemmas"]),
        "pos_changes": len(diff_report["changed_pos"]),
    }

    # Write outputs
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {len(output)} entries to {OUT_PATH}")

    with open(DIFF_PATH, "w", encoding="utf-8") as f:
        json.dump(diff_report, f, ensure_ascii=False, indent=2)
    print(f"Wrote diff report to {DIFF_PATH}")

    # Summary
    print(f"\n{'='*60}")
    print("RESOLUTION SOURCES:")
    for source, count in resolution_sources.most_common():
        pct = count / len(vocab) * 100
        print(f"  {source:25s}  {count:5d}  ({pct:.1f}%)")

    print(f"\nLEMMA CHANGES vs spaCy: {len(diff_report['changed_lemmas'])}")
    # Show top 20 changes by corpus count
    changes = sorted(diff_report["changed_lemmas"], key=lambda x: -x["corpus_count"])
    for c in changes[:20]:
        print(f"  {c['word']:15s}  {','.join(c['old_lemmas']):15s} → {c['new_lemma']:15s}  (count={c['corpus_count']})")

    print(f"\nPOS CHANGES vs spaCy: {len(diff_report['changed_pos'])}")


if __name__ == "__main__":
    main()
