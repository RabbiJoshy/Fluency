#!/usr/bin/env python3
"""Test Gemini gap-fill: does it propose useful missing senses, or false positives?

Takes ~28 words — mix of known slang candidates and normal words (false positive check).
For each word, shows Gemini the Wiktionary senses + lyric examples and asks:
"Pick the best sense, or propose a new one if none fit."

Run from project root:
    .venv/bin/python3 pipeline/artist/bench_gapfill.py
"""
import json, os, sys, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "artist"))
from build_senses import load_wiktionary, lookup_senses, clean_translation, merge_similar_senses
from _artist_config import load_dotenv_from_project_root
load_dotenv_from_project_root()

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
    """Ask Gemini: for each example, pick a sense or propose a new one."""
    from google import genai

    client = genai.Client(api_key=api_key)

    menu = "\n".join("%d. [%s] %s" % (i + 1, s["pos"], s["translation"])
                     for i, s in enumerate(senses))

    lines = []
    for i, ex in enumerate(examples):
        eng = ex.get("english", "")
        spa = ex.get("spanish", "")
        lines.append("%d. %s | %s" % (i + 1, spa, eng))

    prompt = """You are a Spanish word sense classifier for the word "%s" (lemma: %s).
Your goal is to help language learners understand what this word means in context.

AVAILABLE SENSES:
%s

EXAMPLE LYRICS (Spanish | English translation):
%s

For EACH example, decide:
- If one of the available senses would help a learner understand the meaning, return its number.
- If the word is being used with a slang, figurative, or regional meaning that a learner could NOT guess from any of the listed senses, return 0 and propose the actual contextual meaning.

Think from a learner's perspective: if a student saw only the dictionary definition on a flashcard, would they understand what the artist means? If not, propose the real meaning.

Return JSON: an array of objects, one per example:
{"sense": <number 1-N or 0>, "proposed": "<short English translation if sense=0, else null>"}""" % (word, lemma, menu, "\n".join(lines))

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

    print("Loading Wiktionary...")
    wikt_index, redirects = load_wiktionary(
        PROJECT_ROOT / "Data/Spanish/corpora/wiktionary/kaikki-spanish.jsonl.gz")

    print("\n" + "=" * 70)
    print("GAP-FILL TEST: Does Gemini propose useful missing senses?")
    print("=" * 70)

    proposals = []
    no_proposals = []
    no_wiktionary = []
    t_start = time.time()

    for word in TEST_WORDS:
        e = entry_by_word.get(word)
        if not e:
            continue
        lemma = e.get("lemma", word)

        senses = lookup_senses(word, lemma, wikt_index, redirects)
        if not senses:
            no_wiktionary.append(word)
            print("\n%s: NO WIKTIONARY ENTRY" % word)
            continue

        for s in senses:
            s["translation"] = clean_translation(s["translation"])
        senses = merge_similar_senses(senses)

        examples = []
        for m in e.get("meanings", []):
            for ex in m.get("examples", []):
                if ex not in examples:
                    examples.append(ex)
        if not examples:
            continue

        result = gap_fill_gemini(word, lemma, senses, examples, api_key)
        if not result:
            continue

        # Check for proposals
        word_proposals = [r for r in result if r.get("sense") == 0 and r.get("proposed")]
        unique_proposals = list(set(r["proposed"] for r in word_proposals))

        print("\n%s (lemma=%s, %d senses, %d examples):" % (word, lemma, len(senses), len(examples)))
        print("  Menu: %s" % " | ".join("[%s] %s" % (s["pos"], s["translation"]) for s in senses))

        if unique_proposals:
            existing_picks = sum(1 for r in result if r.get("sense", 0) > 0)
            print("  Existing senses used: %d/%d examples" % (existing_picks, len(result)))
            print("  PROPOSED NEW SENSES:")
            for p in unique_proposals:
                count = sum(1 for r in word_proposals if r["proposed"] == p)
                print("    → \"%s\" (%d examples)" % (p, count))
            proposals.append((word, unique_proposals))
        else:
            no_proposals.append(word)
            print("  ✓ All examples covered by existing senses")

    elapsed = time.time() - t_start

    print("\n" + "=" * 70)
    print("SUMMARY (%.1fs, %d words)" % (elapsed, len(TEST_WORDS)))
    print("=" * 70)
    print("No Wiktionary entry:    %d  %s" % (len(no_wiktionary), no_wiktionary))
    print("Proposed new senses:    %d  %s" % (len(proposals), [w for w, _ in proposals]))
    print("All senses sufficient:  %d  %s" % (len(no_proposals), no_proposals))
    print()
    if proposals:
        print("PROPOSALS:")
        for word, props in proposals:
            for p in props:
                print("  %s → \"%s\"" % (word, p))


if __name__ == "__main__":
    main()
