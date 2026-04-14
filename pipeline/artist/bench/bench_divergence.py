#!/usr/bin/env python3
"""Test self-checking classifier for gap-fill detection.

Single Flash Lite call that classifies examples to Wiktionary senses AND
checks whether the English translations match the assigned sense. If the
translations consistently use a different word than the sense definition,
the model flags it.

The key insight: the translations are already in the classifier prompt.
The model sees "Mi gata salvaje | My wild girl" and assigns to sense "cat".
We just ask it to notice that "girl" ≠ "cat".

Uses the same 28 test words as bench_gapfill.py for direct comparison.

Run from project root:
    .venv/bin/python3 pipeline/artist/bench/bench_divergence.py
"""
import json, os, sys, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
sys.path.insert(0, str(PROJECT_ROOT / "pipeline" / "artist"))
from step_5c_build_senses import (load_wiktionary, lookup_senses, clean_translation,
                          merge_similar_senses, content_word_overlap)
from util_artist_config import load_dotenv_from_project_root
load_dotenv_from_project_root()

# Reuse eswiktionary loader + combined senses builder from bench_gapfill
from bench_gapfill import (load_eswiktionary, build_combined_senses,
                           load_translation_cache, TEST_WORDS,
                           ESWIKT_FILE, DIALECT_TAGS)

# Ground truth: words that SHOULD be flagged (need new senses)
SHOULD_FLAG = {
    "gata",      # cat → girlfriend/woman
    "meto",      # to put → to have sex
    "pone",      # to put → to become / to make feel
    "loca",      # borderline: crazy → wild/hyped
    "vivo",      # alive → alert, streetwise
}

# Words that should NOT be flagged (existing senses are fine)
SHOULD_SKIP = {
    "fuego", "duro", "candela", "rico", "tiempo", "noche", "corazón",
    "ojos", "nombre", "sola", "gente", "bellaca", "prende", "perreo",
    "carajo", "corillo", "bicho", "disco", "bruja", "cabrones", "real",
}


def classify_with_self_check(words_data, api_key):
    """Single Flash Lite call: classify + self-check against translations.

    The model assigns examples to senses, then checks whether the English
    translations actually match the sense it picked. If the translations
    consistently use a different word, it flags needs_new_sense=true and
    reports what the translations actually say.

    words_data: list of {word, lemma, senses, examples}
    Returns: list of per-word result dicts
    """
    from google import genai

    client = genai.Client(api_key=api_key)

    prompt_parts = [
        "You are classifying Spanish vocabulary from song lyrics.",
        "For each word below, you have a numbered sense menu and example lyrics"
        " with English translations.",
        "",
        "Do TWO things:",
        "1. Assign each numbered example to the best sense (0-indexed).",
        "2. Self-check: look at the English translations of the examples.",
        "   What English word or phrase do the translations actually use for"
        " this Spanish word? Does it match the sense you assigned?",
        "   If the translations consistently use a DIFFERENT English word than"
        " the sense definition, set needs_new_sense to true and report what"
        " the translations say.",
        "   Common figurative extensions are fine (fire→passion) — only flag"
        " when the translations use a genuinely different word (cat→girlfriend).",
        "",
    ]

    for wi, wd in enumerate(words_data):
        prompt_parts.append("--- Word %d: \"%s\" (lemma: %s) ---" % (
            wi + 1, wd["word"], wd["lemma"]))
        prompt_parts.append("Senses:")
        for si, s in enumerate(wd["senses"]):
            label = "[ES] " if s.get("is_spanish") else ""
            prompt_parts.append("  %d. %s[%s] %s" % (si, label, s["pos"],
                                                      s["translation"]))
        prompt_parts.append("Examples:")
        for ei, ex in enumerate(wd["examples"]):
            eng = ex.get("english", "")
            spa = ex.get("spanish", "")
            prompt_parts.append("  %d. %s | %s" % (ei + 1, spa, eng))
        prompt_parts.append("")

    prompt_parts.append("Return a JSON array with one object per word:")
    prompt_parts.append(json.dumps([{
        "word": "example",
        "assignments": {"1": 0, "2": 1},
        "translation_uses": "the English word(s) the translations actually use",
        "sense_says": "the sense definition you assigned most examples to",
        "needs_new_sense": False,
        "proposed_translation": None,
    }], indent=2))

    prompt = "\n".join(prompt_parts)

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config={"temperature": 0.0, "response_mime_type": "application/json"},
    )

    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, TypeError):
        print("WARNING: parse error")
        print("  Raw: %s" % (response.text[:500] if response.text else "None"))
        return None


def classify_with_extraction(words_data, api_key):
    """Flash Lite call: classify + extract per-example translation word.

    The model assigns examples to senses AND extracts the 1-3 English words
    each translation uses for the Spanish word. No judgment — code counts.

    words_data: list of {word, lemma, senses, examples}
    Returns: list of per-word result dicts
    """
    from google import genai

    client = genai.Client(api_key=api_key)

    prompt_parts = [
        "You are classifying Spanish vocabulary from song lyrics.",
        "For each word below, you have a numbered sense menu and example lyrics"
        " with English translations.",
        "",
        "Do TWO things for each word:",
        "1. Assign each numbered example to the best sense (0-indexed).",
        "2. For each example, look at the English translation and extract the"
        " 1-3 English words used to translate this specific Spanish word."
        " Just the translation word(s), not a full phrase.",
        '   Example: "Mi gata salvaje | My wild girl" → extract "girl" for "gata"',
        '   Example: "Tengo un gato negro | I have a black cat" → extract "cat"'
        ' for "gato"',
        "",
    ]

    for wi, wd in enumerate(words_data):
        prompt_parts.append("--- Word %d: \"%s\" (lemma: %s) ---" % (
            wi + 1, wd["word"], wd["lemma"]))
        prompt_parts.append("Senses:")
        for si, s in enumerate(wd["senses"]):
            label = "[ES] " if s.get("is_spanish") else ""
            prompt_parts.append("  %d. %s[%s] %s" % (si, label, s["pos"],
                                                      s["translation"]))
        prompt_parts.append("Examples:")
        for ei, ex in enumerate(wd["examples"]):
            eng = ex.get("english", "")
            spa = ex.get("spanish", "")
            prompt_parts.append("  %d. %s | %s" % (ei + 1, spa, eng))
        prompt_parts.append("")

    prompt_parts.append("Return a JSON array with one object per word:")
    prompt_parts.append(json.dumps([{
        "word": "example",
        "assignments": {"1": 0, "2": 1},
        "per_example": {"1": "girl", "2": "cat", "3": "fire"},
    }], indent=2))

    prompt = "\n".join(prompt_parts)

    response = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config={"temperature": 0.0, "response_mime_type": "application/json"},
    )

    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, TypeError):
        print("WARNING: parse error")
        print("  Raw: %s" % (response.text[:500] if response.text else "None"))
        return None


_STOP_WORDS = {
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "is", "it",
    "be", "as", "or", "by", "and", "not", "with", "from", "that", "this",
    "but", "are", "was", "were", "been", "has", "have", "had", "do", "does",
    "did", "will", "would", "can", "could", "may", "might", "shall", "should",
    "up", "out", "if", "so", "no", "into", "over", "also", "its", "one",
    "i", "me", "my", "we", "you", "your", "he", "she", "her", "his", "they",
    "them", "their", "who", "what", "when", "where", "how", "all", "each",
    "am", "like", "just", "about", "more", "some", "than", "very",
}

_nlp = None

def _get_nlp():
    global _nlp
    if _nlp is None:
        import spacy
        _nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    return _nlp


def lemmatized_content_words(text):
    """Extract lemmatized content words from English text using spacy."""
    nlp = _get_nlp()
    doc = nlp(text.lower())
    return {t.lemma_ for t in doc
            if t.lemma_ not in _STOP_WORDS and len(t.lemma_) > 1
            and t.is_alpha}


def score_programmatic(words_data, all_results):
    """Check translations against dominant sense using lemmatized keywords.

    No model extraction — directly check if lemmatized sense words appear
    in lemmatized English translation sentences. Uses spacy lemmatizer.
    """
    from collections import Counter

    scored = []
    for i, wd in enumerate(words_data):
        word = wd["word"]
        senses = wd["senses"]
        examples = wd["examples"]

        if i >= len(all_results) or all_results[i] is None:
            scored.append((word, False, 0.0, 0, 0, "?", {}))
            continue

        r = all_results[i]
        assignments = r.get("assignments", {})

        # Find dominant sense
        sense_counts = Counter(int(v) for v in assignments.values()
                               if str(v).lstrip("-").isdigit())
        if not sense_counts:
            scored.append((word, False, 0.0, 0, 0, "?", {}))
            continue
        dominant_idx = sense_counts.most_common(1)[0][0]
        if dominant_idx < 0 or dominant_idx >= len(senses):
            dominant_idx = 0

        sense_trans = senses[dominant_idx]["translation"]
        # Skip Spanish glosses — can't compare with English translations
        if senses[dominant_idx].get("is_spanish"):
            scored.append((word, False, 0.0, 0, 0, sense_trans + " [ES-skip]", {}))
            continue

        sense_lemmas = lemmatized_content_words(sense_trans)
        if not sense_lemmas:
            scored.append((word, False, 0.0, 0, 0, sense_trans, {}))
            continue

        # Check each example's English translation
        n_match = 0
        n_diverge = 0
        details = {}

        for ei, ex in enumerate(examples):
            eng = ex.get("english", "")
            if not eng:
                continue
            trans_lemmas = lemmatized_content_words(eng)
            overlap = sense_lemmas & trans_lemmas
            if overlap:
                n_match += 1
                details[str(ei + 1)] = "match (%s)" % ", ".join(sorted(overlap))
            else:
                n_diverge += 1
                details[str(ei + 1)] = "diverge"

        total = n_match + n_diverge
        diverge_ratio = n_diverge / total if total > 0 else 0.0
        flagged = diverge_ratio > 0.5

        scored.append((word, flagged, diverge_ratio, n_match, n_diverge,
                       sense_trans, details))

    return scored


def score_extraction_results(words_data, all_results):
    """Count per-example extractions vs assigned sense, flag divergence.

    For each word: find dominant sense, check if each extraction overlaps
    with that sense's translation. Flag if majority diverges (>50%).

    Returns list of (word, flagged, diverge_ratio, n_match, n_diverge,
                     sense_translation, per_example_dict)
    """
    from collections import Counter

    scored = []
    for i, wd in enumerate(words_data):
        word = wd["word"]
        senses = wd["senses"]

        if i >= len(all_results) or all_results[i] is None:
            scored.append((word, False, 0.0, 0, 0, "?", {}))
            continue

        r = all_results[i]
        assignments = r.get("assignments", {})
        per_example = r.get("per_example", {})

        # Find dominant sense
        sense_counts = Counter(int(v) for v in assignments.values()
                               if str(v).lstrip("-").isdigit())
        if not sense_counts:
            scored.append((word, False, 0.0, 0, 0, "?", per_example))
            continue
        dominant_idx = sense_counts.most_common(1)[0][0]
        if dominant_idx < 0 or dominant_idx >= len(senses):
            dominant_idx = 0
        sense_translation = senses[dominant_idx]["translation"]

        # Count match vs diverge
        n_match = 0
        n_diverge = 0
        for ex_key, extracted in per_example.items():
            if not extracted or not isinstance(extracted, str):
                continue
            if content_word_overlap(extracted, sense_translation):
                n_match += 1
            else:
                n_diverge += 1

        total = n_match + n_diverge
        diverge_ratio = n_diverge / total if total > 0 else 0.0
        flagged = diverge_ratio > 0.5

        scored.append((word, flagged, diverge_ratio, n_match, n_diverge,
                       sense_translation, per_example))

    return scored


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

    # --- Build word data ---
    words_data = []

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

        combined = build_combined_senses(word, lemma, en_senses, eswikt_index,
                                         translation_cache)
        if not combined:
            print("%s: NO WIKTIONARY ENTRY" % word)
            continue

        examples = []
        for m in e.get("meanings", []):
            for ex in m.get("examples", []):
                if ex not in examples:
                    examples.append(ex)
        if not examples:
            continue

        words_data.append({
            "word": word,
            "lemma": lemma,
            "senses": combined,
            "examples": examples[:20],
        })

    # --- Run self-checking classifier ---
    print("\n" + "=" * 70)
    print("SELF-CHECKING CLASSIFIER (%d words)" % len(words_data))
    print("=" * 70)

    BATCH_SIZE = 15
    all_results = []
    t_start = time.time()

    for batch_start in range(0, len(words_data), BATCH_SIZE):
        batch = words_data[batch_start:batch_start + BATCH_SIZE]
        batch_words = [wd["word"] for wd in batch]
        print("\nBatch %d: %s" % (batch_start // BATCH_SIZE + 1, batch_words))

        results = classify_with_self_check(batch, api_key)
        if results:
            all_results.extend(results)
        else:
            print("  ERROR: batch failed")
            all_results.extend([None] * len(batch))

    elapsed = time.time() - t_start

    # --- Report ---
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    flagged = []
    skipped = []

    for i, wd in enumerate(words_data):
        word = wd["word"]
        senses = wd["senses"]

        if i >= len(all_results) or all_results[i] is None:
            print("\n%s: NO RESULT" % word)
            continue

        r = all_results[i]
        needs_new = r.get("needs_new_sense", False)
        trans_uses = r.get("translation_uses", "?")
        sense_says = r.get("sense_says", "?")
        proposed = r.get("proposed_translation")

        en_count = sum(1 for s in senses if s["source"] == "en-wikt")
        es_count = sum(1 for s in senses if s["source"] == "es-wikt")

        print("\n%s (lemma=%s, %d en + %d es senses):" % (
            word, wd["lemma"], en_count, es_count))
        for si, s in enumerate(senses):
            tag = "[ES] " if s.get("is_spanish") else ""
            print("  %d. %s[%s] %s" % (si, tag, s["pos"], s["translation"]))
        print("  translations use: \"%s\"" % trans_uses)
        print("  sense says:       \"%s\"" % sense_says)

        if needs_new:
            flagged.append(word)
            print("  -> FLAG: needs new sense")
            if proposed:
                print("     proposed: \"%s\"" % proposed)
        else:
            skipped.append(word)
            print("  -> SKIP: sense covers usage")

    # --- Summary ---
    print("\n" + "=" * 70)
    print("SUMMARY (%.1fs, 1 Flash Lite call per batch)" % elapsed)
    print("=" * 70)

    true_pos = [w for w in flagged if w in SHOULD_FLAG]
    false_pos = [w for w in flagged if w in SHOULD_SKIP]
    true_neg = [w for w in skipped if w in SHOULD_SKIP]
    false_neg = [w for w in skipped if w in SHOULD_FLAG]
    borderline_flagged = [w for w in flagged if w not in SHOULD_FLAG and w not in SHOULD_SKIP]
    borderline_skipped = [w for w in skipped if w not in SHOULD_FLAG and w not in SHOULD_SKIP]

    print("Flagged:  %d  %s" % (len(flagged), flagged))
    print("Skipped:  %d  %s" % (len(skipped), skipped))
    print()
    print("True positives (correctly flagged):  %d  %s" % (len(true_pos), true_pos))
    print("False positives (wrongly flagged):   %d  %s" % (len(false_pos), false_pos))
    print("True negatives (correctly skipped):  %d  %s" % (len(true_neg), true_neg))
    print("False negatives (missed):            %d  %s" % (len(false_neg), false_neg))
    if borderline_flagged:
        print("Borderline (flagged):                %d  %s" % (
            len(borderline_flagged), borderline_flagged))
    if borderline_skipped:
        print("Borderline (skipped):                %d  %s" % (
            len(borderline_skipped), borderline_skipped))

    total_known = len(SHOULD_FLAG | SHOULD_SKIP)
    correct = len(true_pos) + len(true_neg)
    print("\nAccuracy (excl borderline): %d/%d = %.0f%%" % (
        correct, total_known, 100 * correct / total_known if total_known else 0))

    selfcheck_correct = correct
    selfcheck_total = total_known

    # --- Programmatic keyword approach (no model extraction) ---
    print("\n\n" + "=" * 70)
    print("PROGRAMMATIC KEYWORD CHECK (lemmatized, no extra API call)")
    print("=" * 70)
    print("Loading spacy English model...")

    prog_scored = score_programmatic(words_data, all_results)

    prog_flagged = []
    prog_skipped = []

    for (word, pflag, div_ratio, n_match, n_diverge,
         sense_trans, details) in prog_scored:
        wd = next(w for w in words_data if w["word"] == word)
        print("\n%s:" % word)
        print("  sense: \"%s\"" % sense_trans)
        print("  match=%d  diverge=%d  ratio=%.2f" % (n_match, n_diverge, div_ratio))
        for k in sorted(details, key=lambda x: int(x)):
            eng = wd["examples"][int(k) - 1].get("english", "")[:50]
            print("    ex %s: %-50s  %s" % (k, eng, details[k]))

        if pflag:
            prog_flagged.append(word)
            print("  -> FLAG")
        else:
            prog_skipped.append(word)
            print("  -> SKIP")

    print("\n" + "=" * 70)
    print("PROGRAMMATIC SUMMARY")
    print("=" * 70)

    prog_tp = [w for w in prog_flagged if w in SHOULD_FLAG]
    prog_fp = [w for w in prog_flagged if w in SHOULD_SKIP]
    prog_tn = [w for w in prog_skipped if w in SHOULD_SKIP]
    prog_fn = [w for w in prog_skipped if w in SHOULD_FLAG]
    prog_bl_f = [w for w in prog_flagged if w not in SHOULD_FLAG and w not in SHOULD_SKIP]
    prog_bl_s = [w for w in prog_skipped if w not in SHOULD_FLAG and w not in SHOULD_SKIP]

    print("Flagged:  %d  %s" % (len(prog_flagged), prog_flagged))
    print("Skipped:  %d  %s" % (len(prog_skipped), prog_skipped))
    print()
    print("True positives (correctly flagged):  %d  %s" % (len(prog_tp), prog_tp))
    print("False positives (wrongly flagged):   %d  %s" % (len(prog_fp), prog_fp))
    print("True negatives (correctly skipped):  %d  %s" % (len(prog_tn), prog_tn))
    print("False negatives (missed):            %d  %s" % (len(prog_fn), prog_fn))
    if prog_bl_f:
        print("Borderline (flagged):                %d  %s" % (
            len(prog_bl_f), prog_bl_f))
    if prog_bl_s:
        print("Borderline (skipped):                %d  %s" % (
            len(prog_bl_s), prog_bl_s))

    prog_correct = len(prog_tp) + len(prog_tn)
    prog_total = len(SHOULD_FLAG | SHOULD_SKIP)
    print("\nAccuracy (excl borderline): %d/%d = %.0f%%" % (
        prog_correct, prog_total,
        100 * prog_correct / prog_total if prog_total else 0))

    # --- Per-example extraction approach ---
    print("\n\n" + "=" * 70)
    print("PER-EXAMPLE EXTRACTION CLASSIFIER (%d words)" % len(words_data))
    print("=" * 70)

    all_results_ext = []
    t_start2 = time.time()

    for batch_start in range(0, len(words_data), BATCH_SIZE):
        batch = words_data[batch_start:batch_start + BATCH_SIZE]
        batch_words = [wd["word"] for wd in batch]
        print("\nBatch %d: %s" % (batch_start // BATCH_SIZE + 1, batch_words))

        results = classify_with_extraction(batch, api_key)
        if results:
            all_results_ext.extend(results)
        else:
            print("  ERROR: batch failed")
            all_results_ext.extend([None] * len(batch))

    elapsed2 = time.time() - t_start2

    scored = score_extraction_results(words_data, all_results_ext)

    print("\n" + "=" * 70)
    print("EXTRACTION RESULTS")
    print("=" * 70)

    ext_flagged = []
    ext_skipped = []

    for (word, flagged_ext, div_ratio, n_match, n_diverge,
         sense_trans, per_ex) in scored:
        wd = next(w for w in words_data if w["word"] == word)
        en_count = sum(1 for s in wd["senses"] if s["source"] == "en-wikt")
        es_count = sum(1 for s in wd["senses"] if s["source"] == "es-wikt")

        print("\n%s (lemma=%s, %d en + %d es senses):" % (
            word, wd["lemma"], en_count, es_count))
        print("  dominant sense: \"%s\"" % sense_trans)
        print("  extractions: %s" % dict(per_ex))
        print("  match=%d  diverge=%d  ratio=%.2f" % (
            n_match, n_diverge, div_ratio))

        if flagged_ext:
            ext_flagged.append(word)
            print("  -> FLAG: majority diverges from sense")
        else:
            ext_skipped.append(word)
            print("  -> SKIP: extractions match sense")

    # --- Extraction summary ---
    print("\n" + "=" * 70)
    print("EXTRACTION SUMMARY (%.1fs, 1 Flash Lite call per batch)" % elapsed2)
    print("=" * 70)

    ext_tp = [w for w in ext_flagged if w in SHOULD_FLAG]
    ext_fp = [w for w in ext_flagged if w in SHOULD_SKIP]
    ext_tn = [w for w in ext_skipped if w in SHOULD_SKIP]
    ext_fn = [w for w in ext_skipped if w in SHOULD_FLAG]
    ext_bl_f = [w for w in ext_flagged if w not in SHOULD_FLAG and w not in SHOULD_SKIP]
    ext_bl_s = [w for w in ext_skipped if w not in SHOULD_FLAG and w not in SHOULD_SKIP]

    print("Flagged:  %d  %s" % (len(ext_flagged), ext_flagged))
    print("Skipped:  %d  %s" % (len(ext_skipped), ext_skipped))
    print()
    print("True positives (correctly flagged):  %d  %s" % (len(ext_tp), ext_tp))
    print("False positives (wrongly flagged):   %d  %s" % (len(ext_fp), ext_fp))
    print("True negatives (correctly skipped):  %d  %s" % (len(ext_tn), ext_tn))
    print("False negatives (missed):            %d  %s" % (len(ext_fn), ext_fn))
    if ext_bl_f:
        print("Borderline (flagged):                %d  %s" % (
            len(ext_bl_f), ext_bl_f))
    if ext_bl_s:
        print("Borderline (skipped):                %d  %s" % (
            len(ext_bl_s), ext_bl_s))

    ext_correct = len(ext_tp) + len(ext_tn)
    ext_total = len(SHOULD_FLAG | SHOULD_SKIP)
    print("\nAccuracy (excl borderline): %d/%d = %.0f%%" % (
        ext_correct, ext_total,
        100 * ext_correct / ext_total if ext_total else 0))

    # --- Combined comparison ---
    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)
    print("  v2 gap-fill prompt:          27/28 correct, misses gata")
    print("  v4 chain-of-thought:         19/28 correct, catches gata but 9 FPs")
    print("  Blind extraction+embedding:  23/26 = 88%% (misses gata, catches meto/loca/pone)")
    print("  Self-checking classifier:    %d/%d = %.0f%%" % (
        selfcheck_correct, selfcheck_total,
        100 * selfcheck_correct / selfcheck_total if selfcheck_total else 0))
    print("  Per-example extraction:      %d/%d = %.0f%%" % (
        ext_correct, ext_total,
        100 * ext_correct / ext_total if ext_total else 0))
    print("  Programmatic keyword+lemma:  %d/%d = %.0f%%" % (
        prog_correct, prog_total,
        100 * prog_correct / prog_total if prog_total else 0))


if __name__ == "__main__":
    main()
