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

    prompt = """You are helping build a Spanish vocabulary flashcard app. The word is "%s" (lemma: %s).

Step 1: Read these example lyrics and determine what "%s" actually means in this artist's usage:
%s

Step 2: Check whether any of these dictionary senses captures that meaning:
%s

Step 3: If the dictionary senses DON'T cover the actual meaning (e.g., the word is used figuratively, as slang, or with a regional meaning a learner couldn't guess from the dictionary), propose ONE short reusable sense definition that would work as a flashcard translation for all the unmatched examples.

Return JSON:
{
  "actual_meaning": "<what the word means in these lyrics, 2-5 words>",
  "covered_by_existing": <true if any dictionary sense adequately captures it, false if not>,
  "proposed_sense": "<short flashcard-friendly translation if not covered, else null>",
  "proposed_pos": "<POS tag if proposing: NOUN/VERB/ADJ/ADV/INTJ, else null>",
  "examples_needing_new_sense": <count of examples that need the new sense, 0 if covered>
}

Be conservative: only propose if the existing senses would genuinely confuse a learner. Figurative extensions of a listed sense (e.g., "fire" covering slang "heat") are usually fine.""" % (word, lemma, word, "\n".join(lines), menu)

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

        print("\n%s (lemma=%s, %d senses, %d examples):" % (word, lemma, len(senses), len(examples)))
        print("  Menu: %s" % " | ".join("[%s] %s" % (s["pos"], s["translation"]) for s in senses))
        print("  Gemini says it means: \"%s\"" % result.get("actual_meaning", "?"))

        if not result.get("covered_by_existing") and result.get("proposed_sense"):
            n = result.get("examples_needing_new_sense", "?")
            pos = result.get("proposed_pos", "?")
            print("  → PROPOSED: [%s] %s (%s examples)" % (pos, result["proposed_sense"], n))
            proposals.append((word, result["proposed_sense"], pos, n))
        else:
            no_proposals.append(word)
            print("  ✓ Covered by existing senses")

    elapsed = time.time() - t_start

    print("\n" + "=" * 70)
    print("SUMMARY (%.1fs, %d words)" % (elapsed, len(TEST_WORDS)))
    print("=" * 70)
    print("No Wiktionary entry:    %d  %s" % (len(no_wiktionary), no_wiktionary))
    print("Proposed new senses:    %d  %s" % (len(proposals), [w for w, p, _, _ in proposals]))
    print("All senses sufficient:  %d  %s" % (len(no_proposals), no_proposals))
    print()
    if proposals:
        print("PROPOSALS:")
        for word, sense, pos, n in proposals:
            print("  %s → [%s] \"%s\" (%s examples)" % (word, pos, sense, n))


if __name__ == "__main__":
    main()
