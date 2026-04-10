#!/usr/bin/env python3
"""Quick classifier benchmark on problem words. Run from project root:
    .venv/bin/python3 pipeline/artist/bench_nli.py --gemini
    .venv/bin/python3 pipeline/artist/bench_nli.py --model facebook/bart-large-mnli
    .venv/bin/python3 pipeline/artist/bench_nli.py
"""
import argparse, json, os, sys, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "artist"))
from build_senses import load_wiktionary, lookup_senses, clean_translation, merge_similar_senses
from _artist_config import load_dotenv_from_project_root
load_dotenv_from_project_root()

TEST_WORDS = ['nombre', 'entera', 'está', 'vez', 'real', 'pone', 'paso',
              'fui', 'duro', 'cojones', 'bicho', 'rico', 'dar', 'arriba']


def classify_gemini(examples, senses, api_key):
    """Classify examples to senses using Gemini Flash Lite as menu-picker."""
    from google import genai

    client = genai.Client(api_key=api_key)

    # Build sense menu
    menu = "\n".join("%d. %s: %s" % (i + 1, s["pos"], s["translation"])
                     for i, s in enumerate(senses))

    # Batch all examples in one prompt
    lines = []
    for i, ex in enumerate(examples):
        eng = ex.get("english", "")
        spa = ex.get("spanish", "")
        lines.append("%d. %s | %s" % (i + 1, spa, eng))

    prompt = """You are a Spanish word sense classifier. Given a word's possible senses and example sentences, pick the best-matching sense for each sentence.

SENSES:
%s

EXAMPLES:
%s

For each example, return the sense number (1-indexed). Return as a JSON array of integers, one per example. Example: [1, 2, 1, 3]""" % (menu, "\n".join(lines))

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config={"temperature": 0.0, "response_mime_type": "application/json"},
    )

    try:
        assignments = json.loads(response.text)
        # Convert 1-indexed to 0-indexed
        return [max(0, min(a - 1, len(senses) - 1)) for a in assignments]
    except (json.JSONDecodeError, TypeError):
        print("    WARNING: Gemini parse error, defaulting to sense 0")
        return [0] * len(examples)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gemini", action="store_true",
                      help="Gemini Flash Lite classifier (pick from menu)")
    mode.add_argument("--model", default="valhalla/distilbart-mnli-12-1",
                      help="NLI model name")
    args = parser.parse_args()

    with open(PROJECT_ROOT / "Artists/Bad Bunny/BadBunnyvocabulary.json") as f:
        entry_by_word = {e["word"]: e for e in json.load(f)}

    # Cache cleaned senses so subsequent runs skip Wiktionary load
    cache_path = PROJECT_ROOT / "pipeline" / "artist" / ".bench_sense_cache.json"
    if cache_path.exists():
        with open(cache_path) as f:
            word_senses = json.load(f)
        print("Loaded sense cache (%d words)" % len(word_senses))
    else:
        print("Loading Wiktionary (first run — caching senses for next time)...")
        wikt_index, redirects = load_wiktionary(
            PROJECT_ROOT / "Data/Spanish/corpora/wiktionary/kaikki-spanish.jsonl.gz")
        word_senses = {}
        for word in TEST_WORDS:
            e = entry_by_word.get(word)
            if not e: continue
            senses = lookup_senses(word, e.get("lemma", word), wikt_index, redirects)
            if not senses: continue
            for s in senses:
                s["translation"] = clean_translation(s["translation"])
            senses = merge_similar_senses(senses)
            if len(senses) >= 2:
                word_senses[word] = senses
        with open(cache_path, "w") as f:
            json.dump(word_senses, f, ensure_ascii=False)
        print("  Cached %d words to %s" % (len(word_senses), cache_path.name))

    # Set up classifier
    if args.gemini:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("ERROR: Set GEMINI_API_KEY env var")
            sys.exit(1)
        method = "gemini-flash-lite"
        print("Classifier: Gemini 2.5 Flash Lite (menu picker)")
    else:
        method = args.model
        print("Loading model: %s" % args.model)
        t0 = time.time()
        from transformers import pipeline as hf_pipeline
        classifier = hf_pipeline("zero-shot-classification", model=args.model)
        print("  Loaded in %.1fs" % (time.time() - t0))

    total_examples = 0
    t_start = time.time()

    print("\n" + "=" * 70)
    for word in TEST_WORDS:
        e = entry_by_word.get(word)
        if not e: continue
        senses = word_senses.get(word)
        if not senses: continue

        examples = []
        for m in e.get("meanings", []):
            for ex in m.get("examples", []):
                if ex not in examples: examples.append(ex)

        labels = ["%s: %s" % (s["pos"], s["translation"]) for s in senses]
        sense_counts = [0] * len(senses)

        if args.gemini:
            # Gemini classifies all examples in one batch call
            assignments = classify_gemini(examples, senses, api_key)
            for idx in assignments:
                sense_counts[idx] += 1
            total_examples += len(examples)
        else:
            for ex in examples:
                eng = ex.get("english", "")
                spa = ex.get("spanish", "")
                text = "%s [Spanish: %s]" % (eng, spa) if eng else spa
                result = classifier(text, candidate_labels=labels, multi_label=False)
                best_idx = labels.index(result["labels"][0])
                sense_counts[best_idx] += 1
                total_examples += 1

        total = sum(sense_counts)
        print("\n%s (%d senses, %d ex):" % (word, len(senses), total))
        for i, s in enumerate(senses):
            if sense_counts[i] > 0:
                print("  %s: %s -- %d/%d (%.0f%%)" % (
                    s["pos"], s["translation"], sense_counts[i], total,
                    100 * sense_counts[i] / total))

    elapsed = time.time() - t_start
    print("\n" + "=" * 70)
    print("Classifier: %s" % method)
    print("Total: %d examples in %.1fs (%.1f ex/s)" % (
        total_examples, elapsed, total_examples / elapsed if elapsed > 0 else 0))
    if not args.gemini:
        print("Projected full run (19K examples): %.0f min" % (
            19000 / (total_examples / elapsed) / 60))
    else:
        print("Projected full run (6640 words): ~%d Gemini calls, ~$0.05" % (
            6640 // 10))  # ~10 words per batch in production

if __name__ == "__main__":
    main()
