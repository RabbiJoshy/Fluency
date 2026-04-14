#!/usr/bin/env python3
"""Benchmark WSD models on Spanish lyric sense classification.

Tests whether local models can replace Gemini Flash Lite for classifying
Spanish example sentences to Wiktionary senses. The key idea: disambiguate
the Spanish word IN the Spanish sentence against sense definitions, making
this standard monolingual WSD.

Models tested:
  1. mDeBERTa NLI cross-encoder (Spanish premise + hypothesis)
  2. Bi-encoder (existing paraphrase-multilingual-mpnet)
  3. ConSeC (if installable)

Ground truth: Gemini Flash Lite classifications (established 100% accuracy).

Run from project root:
    .venv/bin/python3 pipeline/artist/bench/bench_wsd.py
    .venv/bin/python3 pipeline/artist/bench/bench_wsd.py --generate-ground-truth
    .venv/bin/python3 pipeline/artist/bench/bench_wsd.py --model nli
    .venv/bin/python3 pipeline/artist/bench/bench_wsd.py --model biencoder
    .venv/bin/python3 pipeline/artist/bench/bench_wsd.py --model all
"""
import json, os, sys, time, argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "artist"))
from step_5c_build_senses import (load_wiktionary, lookup_senses, clean_translation,
                          merge_similar_senses)
from util_artist_config import load_dotenv_from_project_root
load_dotenv_from_project_root()

from bench_gapfill import (load_eswiktionary, build_combined_senses,
                           load_translation_cache, TEST_WORDS,
                           ESWIKT_FILE, DIALECT_TAGS)

GROUND_TRUTH_FILE = Path(__file__).resolve().parent / ".wsd_ground_truth.json"
VOCAB_FILE = PROJECT_ROOT / "Artists/Bad Bunny/BadBunnyvocabulary.json"
WIKT_FILE = PROJECT_ROOT / "Data/Spanish/Senses/wiktionary/kaikki-spanish.jsonl.gz"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_test_data():
    """Load vocabulary, Wiktionary senses, and examples for all 28 test words.

    Returns dict: word -> {lemma, senses: [{pos, translation, source, gloss_es?}],
                           examples: [{spanish, english, song_name}]}
    """
    with open(VOCAB_FILE) as f:
        entry_by_word = {e["word"]: e for e in json.load(f)}

    print("Loading English Wiktionary...")
    wikt_index, redirects = load_wiktionary(WIKT_FILE)

    print("Loading Spanish Wiktionary (dialect: %s)..." % ", ".join(sorted(DIALECT_TAGS)))
    eswikt_index = load_eswiktionary(ESWIKT_FILE, DIALECT_TAGS)
    print("  %d words with dialect senses" % len(eswikt_index))

    translation_cache = load_translation_cache()

    test_data = {}
    for word in TEST_WORDS:
        e = entry_by_word.get(word)
        if not e:
            print("  WARNING: %s not in vocabulary" % word)
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
            print("  WARNING: %s has no Wiktionary senses" % word)
            continue

        examples = []
        for m in e.get("meanings", []):
            for ex in m.get("examples", []):
                if ex.get("spanish") and ex not in examples:
                    examples.append(ex)

        if not examples:
            print("  WARNING: %s has no examples" % word)
            continue

        test_data[word] = {
            "lemma": lemma,
            "senses": combined,
            "examples": examples[:15],  # cap at 15 for speed
        }

    print("\nLoaded %d test words with senses and examples" % len(test_data))
    return test_data


# ---------------------------------------------------------------------------
# Ground truth: Gemini Flash Lite classification
# ---------------------------------------------------------------------------

def generate_ground_truth(test_data):
    """Classify each example with Gemini Flash Lite and save as ground truth.

    Saves partial progress after each word so interrupted runs can resume.
    """
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY env var")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Resume from partial progress
    ground_truth = {}
    if GROUND_TRUTH_FILE.exists():
        with open(GROUND_TRUTH_FILE) as f:
            ground_truth = json.load(f)
        print("Resuming from %d previously classified words" % len(ground_truth))

    t_start = time.time()

    for word, data in test_data.items():
        if word in ground_truth:
            print("  %s: already classified (skipping)" % word)
            continue
        senses = data["senses"]
        examples = data["examples"]

        # Build sense menu
        menu_lines = []
        for i, s in enumerate(senses):
            label = "[ES] " if s.get("is_spanish") else ""
            menu_lines.append("%d. %s[%s] %s" % (i, label, s["pos"], s["translation"]))
        menu = "\n".join(menu_lines)

        # Build example list
        ex_lines = []
        for i, ex in enumerate(examples):
            ex_lines.append('%d. %s | %s' % (i, ex["spanish"], ex.get("english", "")))

        prompt = """Classify each Spanish example sentence to the best matching sense.
The word is "%s" (lemma: %s).

Sense menu (0-indexed):
%s

Examples:
%s

For each example, return the 0-indexed sense number that best matches how "%s" is used.
If no sense fits at all, return -1.

Return JSON array of objects: [{"example_idx": 0, "sense_idx": <int>, "confidence": "high"|"medium"|"low"}]""" % (word, data["lemma"], menu, "\n".join(ex_lines), word)

        # Retry with backoff on transient errors
        for attempt in range(5):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=prompt,
                    config={"temperature": 0.0, "response_mime_type": "application/json"},
                )
                break
            except Exception as e:
                if attempt < 4 and ("503" in str(e) or "429" in str(e) or "UNAVAILABLE" in str(e)):
                    wait = 2 ** (attempt + 1)
                    print("  %s: retrying in %ds (%s)" % (word, wait, type(e).__name__))
                    time.sleep(wait)
                else:
                    print("  %s: API ERROR: %s" % (word, e))
                    response = None
                    break

        if not response:
            continue

        try:
            assignments = json.loads(response.text)
            ground_truth[word] = {
                "assignments": assignments,
                "senses": [{"pos": s["pos"], "translation": s["translation"],
                            "source": s.get("source", "?")} for s in senses],
            }
            assigned = [a["sense_idx"] for a in assignments if a.get("sense_idx", -1) >= 0]
            print("  %s: %d/%d classified (senses: %s)" % (
                word, len(assigned), len(examples), sorted(set(assigned))))
        except (json.JSONDecodeError, TypeError) as e:
            print("  %s: PARSE ERROR: %s" % (word, e))

        # Save partial progress
        with open(GROUND_TRUTH_FILE, "w") as f:
            json.dump(ground_truth, f, ensure_ascii=False, indent=2)

        time.sleep(1)  # Rate limit courtesy

    elapsed = time.time() - t_start
    print("\nGemini ground truth generated in %.1fs" % elapsed)

    with open(GROUND_TRUTH_FILE, "w") as f:
        json.dump(ground_truth, f, ensure_ascii=False, indent=2)
    print("Saved to %s" % GROUND_TRUTH_FILE)
    return ground_truth


def load_ground_truth():
    """Load previously generated ground truth."""
    if not GROUND_TRUTH_FILE.exists():
        return None
    with open(GROUND_TRUTH_FILE) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Model 1: mDeBERTa NLI cross-encoder
# ---------------------------------------------------------------------------

def classify_nli(test_data, ground_truth, gloss_lang="en"):
    """Classify examples using multilingual NLI (entailment scoring).

    For each (sentence, candidate_sense), compute P(entailment) where:
      premise = Spanish sentence
      hypothesis = "En esta oración, '{word}' significa: {gloss}"
    Pick sense with highest entailment score.

    gloss_lang: "en" uses English glosses, "es" uses Spanish glosses (from eswikt).
    """
    from transformers import pipeline as hf_pipeline
    import torch

    model_name = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
    print("\nLoading NLI model: %s ..." % model_name)
    t_load = time.time()
    nli = hf_pipeline("zero-shot-classification",
                      model=model_name,
                      device="mps" if torch.backends.mps.is_available() else "cpu")
    print("  Loaded in %.1fs (device: %s)" % (time.time() - t_load, nli.device))

    results = {}
    t_start = time.time()
    total_examples = 0
    total_correct = 0

    for word, data in test_data.items():
        gt = ground_truth.get(word, {}).get("assignments", [])
        if not gt:
            continue

        senses = data["senses"]
        examples = data["examples"]

        # Build candidate labels based on gloss language
        labels = []
        for s in senses:
            if gloss_lang == "es" and s.get("gloss_es"):
                labels.append("%s: %s" % (s["pos"], s["gloss_es"]))
            else:
                labels.append("%s: %s" % (s["pos"], s["translation"]))

        if not labels:
            continue

        word_correct = 0
        word_total = 0
        per_example = []

        for assignment in gt:
            ex_idx = assignment["example_idx"]
            gt_sense = assignment["sense_idx"]
            if gt_sense < 0 or ex_idx >= len(examples):
                continue

            ex = examples[ex_idx]
            sentence = ex["spanish"]

            # NLI zero-shot classification
            result = nli(sentence, labels, hypothesis_template=
                         "En esta oración, '%s' significa: {}." % word,
                         multi_label=True)

            # Map predicted label back to sense index
            pred_label = result["labels"][0]
            pred_sense = labels.index(pred_label) if pred_label in labels else -1

            correct = pred_sense == gt_sense
            word_correct += int(correct)
            word_total += 1

            per_example.append({
                "example_idx": ex_idx,
                "sentence": sentence[:80],
                "gt_sense": gt_sense,
                "pred_sense": pred_sense,
                "correct": correct,
                "top_score": result["scores"][0],
                "gt_label": labels[gt_sense] if 0 <= gt_sense < len(labels) else "?",
                "pred_label": pred_label[:60],
            })

        acc = word_correct / word_total if word_total else 0
        results[word] = {
            "accuracy": acc,
            "correct": word_correct,
            "total": word_total,
            "details": per_example,
        }
        total_correct += word_correct
        total_examples += word_total

        status = "OK" if acc >= 0.8 else "WEAK" if acc >= 0.5 else "BAD"
        print("  %s: %d/%d (%.0f%%) %s" % (word, word_correct, word_total, acc * 100, status))

    elapsed = time.time() - t_start
    overall_acc = total_correct / total_examples if total_examples else 0
    print("\nNLI (%s glosses): %d/%d overall (%.1f%%) in %.1fs" % (
        gloss_lang, total_correct, total_examples, overall_acc * 100, elapsed))

    return results, overall_acc, elapsed


# ---------------------------------------------------------------------------
# Model 2: Bi-encoder (sentence similarity)
# ---------------------------------------------------------------------------

def classify_biencoder(test_data, ground_truth, gloss_lang="en"):
    """Classify examples using bi-encoder cosine similarity.

    Encode Spanish sentence and each candidate gloss, pick highest similarity.
    """
    from sentence_transformers import SentenceTransformer
    import numpy as np

    model_name = "paraphrase-multilingual-mpnet-base-v2"
    print("\nLoading bi-encoder: %s ..." % model_name)
    t_load = time.time()
    model = SentenceTransformer(model_name)
    print("  Loaded in %.1fs" % (time.time() - t_load))

    results = {}
    t_start = time.time()
    total_examples = 0
    total_correct = 0

    for word, data in test_data.items():
        gt = ground_truth.get(word, {}).get("assignments", [])
        if not gt:
            continue

        senses = data["senses"]
        examples = data["examples"]

        # Build candidate texts
        gloss_texts = []
        for s in senses:
            if gloss_lang == "es" and s.get("gloss_es"):
                gloss_texts.append("%s: %s" % (s["pos"], s["gloss_es"]))
            else:
                gloss_texts.append("%s: %s" % (s["pos"], s["translation"]))

        if not gloss_texts:
            continue

        # Encode all glosses once
        gloss_embeddings = model.encode(gloss_texts, normalize_embeddings=True)

        word_correct = 0
        word_total = 0
        per_example = []

        for assignment in gt:
            ex_idx = assignment["example_idx"]
            gt_sense = assignment["sense_idx"]
            if gt_sense < 0 or ex_idx >= len(examples):
                continue

            ex = examples[ex_idx]
            sentence = ex["spanish"]

            # Encode sentence and compute similarities
            sent_emb = model.encode([sentence], normalize_embeddings=True)
            sims = np.dot(sent_emb, gloss_embeddings.T)[0]
            pred_sense = int(np.argmax(sims))

            correct = pred_sense == gt_sense
            word_correct += int(correct)
            word_total += 1

            per_example.append({
                "example_idx": ex_idx,
                "sentence": sentence[:80],
                "gt_sense": gt_sense,
                "pred_sense": pred_sense,
                "correct": correct,
                "top_score": float(sims[pred_sense]),
                "gt_label": gloss_texts[gt_sense] if 0 <= gt_sense < len(gloss_texts) else "?",
                "pred_label": gloss_texts[pred_sense][:60],
            })

        acc = word_correct / word_total if word_total else 0
        results[word] = {
            "accuracy": acc,
            "correct": word_correct,
            "total": word_total,
            "details": per_example,
        }
        total_correct += word_correct
        total_examples += word_total

        status = "OK" if acc >= 0.8 else "WEAK" if acc >= 0.5 else "BAD"
        print("  %s: %d/%d (%.0f%%) %s" % (word, word_correct, word_total, acc * 100, status))

    elapsed = time.time() - t_start
    overall_acc = total_correct / total_examples if total_examples else 0
    print("\nBi-encoder (%s glosses): %d/%d overall (%.1f%%) in %.1fs" % (
        gloss_lang, total_correct, total_examples, overall_acc * 100, elapsed))

    return results, overall_acc, elapsed


# ---------------------------------------------------------------------------
# Focus word analysis
# ---------------------------------------------------------------------------

FOCUS_WORDS = ["gata", "meto", "pone", "vivo", "loca"]

def print_focus_analysis(all_results):
    """Print detailed analysis for the hardest words."""
    print("\n" + "=" * 70)
    print("FOCUS WORD ANALYSIS (hardest cases)")
    print("=" * 70)

    for word in FOCUS_WORDS:
        print("\n--- %s ---" % word)
        for model_name, (results, _, _) in all_results.items():
            r = results.get(word, {})
            if not r:
                continue
            acc = r["accuracy"]
            print("  %s: %.0f%% (%d/%d)" % (model_name, acc * 100, r["correct"], r["total"]))
            # Show first few misclassifications
            for d in r.get("details", []):
                if not d["correct"]:
                    print("    MISS: \"%s...\"" % d["sentence"][:60])
                    print("          gt=%d (%s)" % (d["gt_sense"], d["gt_label"][:50]))
                    print("          pred=%d (%s) score=%.3f" % (
                        d["pred_sense"], d["pred_label"][:50], d["top_score"]))


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary(all_results):
    """Print comparison table."""
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("%-30s %8s %8s %8s" % ("Model", "Accuracy", "Time", "Cost"))
    print("-" * 60)
    print("%-30s %7.1f%% %7.1fs %8s" % ("Gemini Flash Lite (ref)", 100.0, 0, "$0.05"))
    for model_name, (_, acc, elapsed) in all_results.items():
        print("%-30s %7.1f%% %7.1fs %8s" % (model_name, acc * 100, elapsed, "free"))
    print()

    # Per-word breakdown
    print("\n%-12s" % "Word", end="")
    for model_name in all_results:
        print(" %12s" % model_name[:12], end="")
    print()
    print("-" * (12 + 13 * len(all_results)))

    all_words = set()
    for _, (results, _, _) in all_results.items():
        all_words.update(results.keys())

    for word in sorted(all_words):
        print("%-12s" % word, end="")
        for model_name, (results, _, _) in all_results.items():
            r = results.get(word, {})
            if r:
                print(" %11.0f%%" % (r["accuracy"] * 100), end="")
            else:
                print(" %12s" % "-", end="")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Benchmark WSD models on Spanish lyrics")
    parser.add_argument("--generate-ground-truth", action="store_true",
                        help="Generate Gemini ground truth (requires GEMINI_API_KEY)")
    parser.add_argument("--model", default="all",
                        choices=["nli", "biencoder", "all"],
                        help="Which model(s) to benchmark")
    parser.add_argument("--gloss-lang", default="both",
                        choices=["en", "es", "both"],
                        help="Gloss language for sense definitions")
    args = parser.parse_args()

    test_data = load_test_data()

    if args.generate_ground_truth:
        ground_truth = generate_ground_truth(test_data)
    else:
        ground_truth = load_ground_truth()
        if not ground_truth:
            print("\nNo ground truth found. Run with --generate-ground-truth first.")
            sys.exit(1)
        print("\nLoaded ground truth for %d words" % len(ground_truth))

    if args.generate_ground_truth and args.model == "all" and not args.model:
        return  # Just generated ground truth, stop here

    all_results = {}

    gloss_langs = ["en", "es"] if args.gloss_lang == "both" else [args.gloss_lang]

    for lang in gloss_langs:
        if args.model in ("nli", "all"):
            print("\n" + "=" * 70)
            print("mDeBERTa NLI (%s glosses)" % lang)
            print("=" * 70)
            all_results["NLI-%s" % lang] = classify_nli(test_data, ground_truth, lang)

        if args.model in ("biencoder", "all"):
            print("\n" + "=" * 70)
            print("Bi-encoder (%s glosses)" % lang)
            print("=" * 70)
            all_results["BiEnc-%s" % lang] = classify_biencoder(test_data, ground_truth, lang)

    if all_results:
        print_focus_analysis(all_results)
        print_summary(all_results)


if __name__ == "__main__":
    main()
