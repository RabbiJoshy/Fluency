#!/usr/bin/env python3
"""Test Gemini gap-fill: does it propose useful missing senses, or false positives?

Takes ~28 words — mix of known slang candidates and normal words (false positive check).
For each word, shows Gemini the Wiktionary senses + lyric examples and asks:
"Pick the best sense, or propose a new one if none fit."

Now includes Spanish Wiktionary (eswiktionary) dialect senses as supplement.
English Wiktionary senses come first; Spanish-only senses are appended.
When Gemini picks a Spanish sense, it translates it; translations are cached.

Run from project root:
    .venv/bin/python3 pipeline/artist/bench/bench_gapfill.py
"""
import gzip
import json, os, sys, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "artist"))
from step_5c_build_senses import load_wiktionary, lookup_senses, clean_translation, merge_similar_senses
from util_artist_config import load_dotenv_from_project_root
load_dotenv_from_project_root()

ESWIKT_FILE = PROJECT_ROOT / "Data/Spanish/corpora/wiktionary/kaikki-eswiktionary-raw.jsonl.gz"
TRANSLATION_CACHE_FILE = Path(__file__).resolve().parent / ".eswikt_translation_cache.json"
DIALECT_TAGS = {"Puerto-Rico", "Caribbean", "Cuba"}

# Map eswiktionary raw POS to our uppercase tags
_ESWIKT_POS_MAP = {
    "verb": "VERB", "noun": "NOUN", "adj": "ADJ", "adv": "ADV",
    "intj": "INTJ", "pron": "PRON", "prep": "ADP", "conj": "CCONJ",
    "num": "NUM", "phrase": "PHRASE", "participle": "VERB",
}

def load_eswiktionary(path, dialect_tags):
    """Load Spanish Wiktionary raw data, filtering to dialect-tagged senses.

    Returns: dict of word -> list of {pos, gloss_es, tags}
    Caches the parsed index as a pickle next to the JSONL for fast reloads.
    """
    import pickle
    cache_path = Path(str(path) + ".eswikt_dialect.cache.pkl")
    cache_key = tuple(sorted(dialect_tags))
    if cache_path.exists() and cache_path.stat().st_mtime >= path.stat().st_mtime:
        print("Loading eswiktionary from cache (%s)..." % cache_path.name)
        with open(cache_path, "rb") as f:
            cached_key, index = pickle.load(f)
        if cached_key == cache_key:
            print("  %d words with dialect senses" % len(index))
            return index

    index = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            if obj.get("lang_code") != "es":
                continue
            word = obj.get("word", "")
            raw_pos = obj.get("pos", "")
            pos = _ESWIKT_POS_MAP.get(raw_pos)
            if not pos:
                continue
            for s in obj.get("senses", []):
                tags = set(s.get("tags", []))
                if not (tags & dialect_tags):
                    continue
                glosses = s.get("glosses", [])
                if not glosses:
                    continue
                # Skip form-of entries (conjugation tables, feminine forms, etc.)
                if "form-of" in tags:
                    continue
                index.setdefault(word, []).append({
                    "pos": pos,
                    "gloss_es": glosses[0],
                    "tags": sorted(tags & dialect_tags),
                })
    print("  Caching to %s..." % cache_path.name)
    with open(cache_path, "wb") as f:
        pickle.dump((cache_key, index), f)
    return index


def load_translation_cache():
    """Load cached Spanish->English gloss translations."""
    if TRANSLATION_CACHE_FILE.exists():
        with open(TRANSLATION_CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_translation_cache(cache):
    """Save Spanish->English gloss translations."""
    with open(TRANSLATION_CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def build_combined_senses(word, lemma, en_senses, eswikt_index, translation_cache):
    """Build combined sense menu: English Wiktionary first, then Spanish dialect senses.

    Spanish senses that already have a cached English translation use that.
    Returns: list of {pos, translation, source, gloss_es?}
    """
    combined = []
    for s in en_senses:
        combined.append({
            "pos": s["pos"],
            "translation": s["translation"],
            "source": "en-wikt",
        })

    # Look up both word and lemma in Spanish Wiktionary
    es_senses = []
    for lookup in sorted(set([word, lemma])):
        for s in eswikt_index.get(lookup, []):
            es_senses.append(s)

    for s in es_senses:
        gloss_es = s["gloss_es"]
        cached = translation_cache.get(gloss_es)
        combined.append({
            "pos": s["pos"],
            "translation": cached if cached else gloss_es,
            "source": "es-wikt",
            "gloss_es": gloss_es,
            "is_spanish": cached is None,
        })

    return combined


# Mix of slang candidates + normal words for false positive check
TEST_WORDS = [
    # Known slang / idiolect candidates
    'gata', 'candela', 'bellaca', 'prende', 'perreo', 'flow', 'bruja',
    'loca', 'carajo', 'corillo', 'bicho', 'disco', 'fuego', 'duro',
    'meto', 'real', 'pone', 'cabrones', 'rico', 'vivo',
    # Normal words (should NOT propose new senses)
    'tiempo', 'noche', 'corazón', 'ojos', 'nombre', 'nuevo', 'sola',
    'gente',
]


def gap_fill_gemini(word, lemma, senses, examples, api_key):
    """Ask Gemini: for each example, pick a sense or propose a new one.

    Menu may contain English and Spanish glosses. If Gemini picks a Spanish
    gloss, it translates it. Senses marked [ES] are Spanish-language glosses.
    """
    from google import genai

    client = genai.Client(api_key=api_key)

    menu_lines = []
    for i, s in enumerate(senses):
        label = "[ES] " if s.get("is_spanish") else ""
        menu_lines.append("%d. %s[%s] %s" % (i + 1, label, s["pos"], s["translation"]))
    menu = "\n".join(menu_lines)

    lines = []
    for i, ex in enumerate(examples):
        eng = ex.get("english", "")
        spa = ex.get("spanish", "")
        lines.append("%d. %s | %s" % (i + 1, spa, eng))

    prompt = """You are helping build a Spanish vocabulary flashcard app for learners. The word is "%s" (lemma: %s).

Step 1: Read these example lyrics and determine what "%s" actually means in this artist's usage:
%s

Step 2: Check whether any of these dictionary senses is close enough that a learner reading it on a flashcard would understand the word in these lyrics.
If both an English sense and a Spanish [ES] sense cover the same meaning, prefer the English one.
%s

Test each sense: take the English translation of one example lyric and substitute the dictionary definition for the word. Write out the substituted sentence. Does it still convey what the artist means?

If the best sense passes this test, the word is covered — even if the usage is more figurative or intense. Flashcard space is limited, so don't propose new senses when existing ones work.

Step 3: If NO sense passes the substitution test, propose ONE short flashcard translation.

Return JSON:
{
  "actual_meaning": "<what the word means in these lyrics, 2-5 words>",
  "substitution_example": "<pick one English lyric and substitute the best dictionary definition — write the result>",
  "substitution_works": <true if the substituted sentence conveys the right meaning>,
  "covered_by_existing": <true if substitution works, false if not>,
  "best_sense_index": <1-indexed number of the best matching sense from the menu, or null if not covered>,
  "english_translation": "<if the best sense is a Spanish [ES] gloss, provide a short 2-5 word English flashcard translation for it; else null>",
  "proposed_sense": "<short flashcard-friendly English translation if not covered, else null>",
  "proposed_pos": "<POS tag if proposing: NOUN/VERB/ADJ/ADV/INTJ, else null>",
  "examples_needing_new_sense": <count of examples that need the new sense, 0 if covered>
}""" % (word, lemma, word, "\n".join(lines), menu)

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config={"temperature": 0.0, "response_mime_type": "application/json"},
    )

    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, TypeError):
        print("    WARNING: parse error")
        return None


def main():
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY env var")
        sys.exit(1)

    with open(PROJECT_ROOT / "Artists/Bad Bunny/BadBunnyvocabulary.json") as f:
        entry_by_word = {e["word"]: e for e in json.load(f)}

    print("Loading English Wiktionary...")
    wikt_index, redirects = load_wiktionary(
        PROJECT_ROOT / "Data/Spanish/corpora/wiktionary/kaikki-spanish.jsonl.gz")

    print("Loading Spanish Wiktionary (dialect: %s)..." % ", ".join(sorted(DIALECT_TAGS)))
    eswikt_index = load_eswiktionary(ESWIKT_FILE, DIALECT_TAGS)
    print("  %d words with dialect senses" % len(eswikt_index))

    translation_cache = load_translation_cache()
    print("  %d cached translations" % len(translation_cache))

    print("\n" + "=" * 70)
    print("GAP-FILL TEST: English + Spanish Wiktionary combined menu")
    print("=" * 70)

    proposals = []
    no_proposals = []
    no_wiktionary = []
    new_translations = 0
    t_start = time.time()

    for word in TEST_WORDS:
        e = entry_by_word.get(word)
        if not e:
            continue
        lemma = e.get("lemma", word)

        en_senses = lookup_senses(word, lemma, wikt_index, redirects)
        if en_senses:
            for s in en_senses:
                s["translation"] = clean_translation(s["translation"])
            en_senses = merge_similar_senses(en_senses)
        else:
            en_senses = []

        combined = build_combined_senses(word, lemma, en_senses, eswikt_index, translation_cache)

        if not combined:
            no_wiktionary.append(word)
            print("\n%s: NO WIKTIONARY ENTRY (either edition)" % word)
            continue

        examples = []
        for m in e.get("meanings", []):
            for ex in m.get("examples", []):
                if ex not in examples:
                    examples.append(ex)
        if not examples:
            continue

        result = gap_fill_gemini(word, lemma, combined, examples, api_key)
        if not result:
            continue

        # Count senses by source for display
        en_count = sum(1 for s in combined if s["source"] == "en-wikt")
        es_count = sum(1 for s in combined if s["source"] == "es-wikt")

        print("\n%s (lemma=%s, %d en + %d es senses, %d examples):" % (
            word, lemma, en_count, es_count, len(examples)))
        for i, s in enumerate(combined):
            tag = "[ES] " if s.get("is_spanish") else ""
            src = s["source"]
            print("  %d. %s[%s] %s  (%s)" % (i + 1, tag, s["pos"], s["translation"], src))
        print("  Gemini says it means: \"%s\"" % result.get("actual_meaning", "?"))
        if result.get("substitution_example"):
            works = "YES" if result.get("substitution_works") else "NO"
            print("  Substitution [%s]: %s" % (works, result["substitution_example"]))

        # Cache translation if Gemini picked a Spanish sense and translated it
        best_idx = result.get("best_sense_index")
        eng_trans = result.get("english_translation")
        if best_idx and eng_trans:
            idx = best_idx - 1  # 1-indexed to 0-indexed
            if 0 <= idx < len(combined) and combined[idx].get("is_spanish"):
                gloss_es = combined[idx]["gloss_es"]
                if gloss_es not in translation_cache:
                    translation_cache[gloss_es] = eng_trans
                    new_translations += 1
                    print("  ** Cached translation: \"%s\" → \"%s\"" % (gloss_es, eng_trans))

        if not result.get("covered_by_existing") and result.get("proposed_sense"):
            n = result.get("examples_needing_new_sense", "?")
            pos = result.get("proposed_pos", "?")
            print("  → PROPOSED: [%s] %s (%s examples)" % (pos, result["proposed_sense"], n))
            proposals.append((word, result["proposed_sense"], pos, n))
        else:
            picked = ""
            if best_idx and 0 < best_idx <= len(combined):
                s = combined[best_idx - 1]
                picked = " (picked #%d: [%s] %s)" % (best_idx, s["pos"], s["translation"])
            no_proposals.append(word)
            print("  ✓ Covered by existing senses%s" % picked)

    elapsed = time.time() - t_start

    # Save any new translations
    if new_translations:
        save_translation_cache(translation_cache)
        print("\n  Saved %d new translations to cache" % new_translations)

    print("\n" + "=" * 70)
    print("SUMMARY (%.1fs, %d words)" % (elapsed, len(TEST_WORDS)))
    print("=" * 70)
    print("No Wiktionary entry:    %d  %s" % (len(no_wiktionary), no_wiktionary))
    print("Proposed new senses:    %d  %s" % (len(proposals), [w for w, p, _, _ in proposals]))
    print("All senses sufficient:  %d  %s" % (len(no_proposals), no_proposals))
    print("New translations cached: %d" % new_translations)
    print()
    if proposals:
        print("PROPOSALS:")
        for word, sense, pos, n in proposals:
            print("  %s → [%s] \"%s\" (%s examples)" % (word, pos, sense, n))


if __name__ == "__main__":
    main()
