#!/usr/bin/env python3
"""Evaluate whether the biencoder can match translated lyrics to Wiktionary senses.

Tests the cascade hypothesis: can we replace Gemini word-level translation (Pass B)
with Wiktionary sense lookup + biencoder classification using existing sentence
translations?

Compares sense classification accuracy across translation sources:
  - Gemini sentence translations (highest quality)
  - Genius community translations (human, free)
  - Google Translate (machine, free)
  - Spanish only (no translation, baseline)

Usage:
    .venv/bin/python3 Artists/scripts/eval_wiktionary_cascade.py --artist-dir "Artists/Bad Bunny"
    .venv/bin/python3 Artists/scripts/eval_wiktionary_cascade.py --artist-dir "Artists/Bad Bunny" --skip-google
"""

import argparse
import gzip
import json
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup: project root, artist config
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "Data" / "Spanish" / "Scripts"))

from _artist_config import add_artist_arg, load_artist_config

WIKTIONARY_GZ = PROJECT_ROOT / "Data" / "Spanish" / "corpora" / "wiktionary" / "kaikki-spanish.jsonl.gz"
CLASSIFY_MODEL = "paraphrase-multilingual-mpnet-base-v2"

# ---------------------------------------------------------------------------
# Wiktionary loading (adapted from build_senses.py)
# ---------------------------------------------------------------------------

POS_MAP = {
    "noun": "NOUN", "verb": "VERB", "adj": "ADJ", "adv": "ADV",
    "pron": "PRON", "prep": "ADP", "postp": "ADP", "conj": "CCONJ",
    "det": "DET", "intj": "INTJ", "name": "PROPN",
    "num": "NUM", "particle": "PART", "phrase": "PHRASE",
    "contraction": "CONTRACTION",
}

SKIP_TAGS = {"archaic", "obsolete", "rare", "historical", "dated",
             "abbreviation", "ellipsis"}

_ALT_OF_PATTERNS = [
    re.compile(r'literally\s+[\u0022\u201c]([^\u0022\u201c\u201d]+)[\u0022\u201d]'),
    re.compile(r'form of\s+\S+\s*;\s*(.+)'),
    re.compile(r'form of\s+\S+\s+(.+)'),
    re.compile(r'[\u0022\u201c]([^\u0022\u201c\u201d]+)[\u0022\u201d]'),
]

_FORM_OF_PATTERNS = [
    re.compile(r'[\u0022\u201c\u201d]([^\u0022\u201c\u201d]+)[\u0022\u201c\u201d]'),
    re.compile(r'\bof\s+.{1,30}?:\s*(.+)'),
    re.compile(r'\bof\s+.{1,30}?;\s*(.+)'),
    re.compile(r'equivalent of\s+\w+,\s*(.+)'),
]

MAX_SENSES_PER_POS = 5
MAX_SENSES_TOTAL = 8

_POS_LABELS = {
    "VERB": "verb", "NOUN": "noun", "ADJ": "adjective",
    "ADV": "adverb", "ADP": "preposition",
    "CCONJ": "conjunction", "PRON": "pronoun",
    "DET": "determiner", "INTJ": "interjection",
    "NUM": "numeral", "PART": "particle",
    "PHRASE": "phrase", "CONTRACTION": "contraction",
}


def strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def load_wiktionary_index(path):
    """Load raw Wiktionary JSONL into lookup index."""
    print("Loading raw Wiktionary from %s..." % path)
    index = defaultdict(list)
    redirects = {}
    total = 0

    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            total += 1
            item = json.loads(line)
            word = item.get("word", "").lower()
            raw_pos = item.get("pos", "")
            mapped_pos = POS_MAP.get(raw_pos)

            if not word or not mapped_pos:
                continue

            senses = item.get("senses", [])
            real_senses = []
            for s in senses:
                tags = set(s.get("tags", []))
                glosses = s.get("glosses", [])
                if not glosses:
                    continue
                gloss = glosses[0]

                if "alt-of" in tags:
                    extracted = None
                    for pattern in _ALT_OF_PATTERNS:
                        m = pattern.search(gloss)
                        if m:
                            extracted = m.group(1).strip()
                            break
                    if extracted:
                        gloss = extracted
                        tags = tags - SKIP_TAGS
                    else:
                        continue

                if tags & SKIP_TAGS:
                    continue

                if "form-of" in tags:
                    extracted = None
                    for pattern in _FORM_OF_PATTERNS:
                        m = pattern.search(gloss)
                        if m:
                            extracted = m.group(1).strip()
                            break
                    if extracted:
                        gloss = extracted
                    else:
                        continue

                if len(gloss) < 2:
                    continue

                real_senses.append({"gloss": gloss, "tags": sorted(tags - {"form-of"}) if tags else []})

            if not real_senses:
                for s in senses:
                    for fo in s.get("form_of", []):
                        base = fo.get("word", "").lower()
                        if base and base != word:
                            redirects[word] = base
                            norm = strip_accents(word)
                            if norm != word:
                                redirects[norm] = base
                continue

            entry = {"pos": mapped_pos, "senses": real_senses}
            index[word].append(entry)
            norm = strip_accents(word)
            if norm != word:
                index[norm].append(entry)

    print("  %d entries, %d unique keys, %d redirects" % (total, len(index), len(redirects)))
    return dict(index), dict(redirects)


def lookup_senses(word, lemma, wikt_index, redirects):
    """Look up Wiktionary senses for a word|lemma pair."""
    groups = []
    lemma_forms = [lemma.lower(), strip_accents(lemma.lower())]
    for f in list(lemma_forms):
        if f in redirects:
            lemma_forms.append(redirects[f])
    groups.append(lemma_forms)

    if word.lower() != lemma.lower():
        word_forms = [word.lower(), strip_accents(word.lower())]
        for f in list(word_forms):
            if f in redirects:
                word_forms.append(redirects[f])
        groups.append(word_forms)

    all_candidates = []
    for group in groups:
        for form in group:
            candidates = wikt_index.get(form)
            if candidates:
                all_candidates.extend(candidates)
                break

    if not all_candidates:
        return []

    results = []
    seen = set()
    for entry in all_candidates:
        pos = entry["pos"]
        count_for_pos = sum(1 for r in results if r["pos"] == pos)
        for sense in entry["senses"]:
            if count_for_pos >= MAX_SENSES_PER_POS:
                break
            gloss = sense["gloss"]
            norm_key = (pos, gloss.lower().split("(")[0].strip())
            if norm_key in seen:
                continue
            seen.add(norm_key)
            results.append({"pos": pos, "translation": gloss, "source": "wiktionary"})
            count_for_pos += 1

    return results[:MAX_SENSES_TOTAL]


# ---------------------------------------------------------------------------
# Google Translate (with caching)
# ---------------------------------------------------------------------------

def generate_google_translations(lines, cache_path, batch_save=50):
    """Translate lines via Google Translate, with file-level caching."""
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cached = json.load(f)
        remaining = [l for l in lines if l not in cached]
        if not remaining:
            print("  Google Translate: %d lines cached, 0 remaining" % len(cached))
            return cached
        print("  Google Translate: %d cached, %d remaining" % (len(cached), len(remaining)))
    else:
        cached = {}
        remaining = lines
        print("  Google Translate: 0 cached, %d to translate" % len(remaining))

    from deep_translator import GoogleTranslator
    translator = GoogleTranslator(source="es", target="en")

    for i, line in enumerate(remaining):
        try:
            result = translator.translate(line)
            cached[line] = result or ""
        except Exception as e:
            print("    [WARN] Google Translate failed for line %d: %s" % (i, e))
            cached[line] = ""
            time.sleep(1)

        if (i + 1) % batch_save == 0:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cached, f, ensure_ascii=False, indent=2)
            print("    Saved progress: %d / %d" % (i + 1, len(remaining)))

        if (i + 1) % 10 == 0:
            time.sleep(0.5)  # rate limiting

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cached, f, ensure_ascii=False, indent=2)
    print("  Google Translate complete: %d lines" % len(cached))
    return cached


# ---------------------------------------------------------------------------
# Biencoder classification (simplified from match_artist_senses.py)
# ---------------------------------------------------------------------------

def classify_words(words_data, translations, model):
    """Classify lyric examples to Wiktionary senses using biencoder.

    words_data: list of (word_key, senses, examples) tuples
    translations: dict mapping Spanish line -> English translation
    model: loaded SentenceTransformer

    Returns: dict of word_key -> [(sense_idx, [example_indices])]
    """
    import numpy as np

    # Collect all example texts
    example_texts = []
    example_map = []  # (word_idx, example_idx)

    for wi, (word_key, senses, examples) in enumerate(words_data):
        for ei, ex in enumerate(examples):
            spanish = ex.get("spanish", "")
            english = translations.get(spanish, "")
            if english and spanish:
                text = "%s [Spanish: %s]" % (english, spanish)
            elif spanish:
                text = spanish
            else:
                continue
            example_texts.append(text)
            example_map.append((wi, ei))

    # Collect all sense texts
    sense_texts = []
    sense_map = []  # (word_idx, sense_idx)
    for wi, (word_key, senses, examples) in enumerate(words_data):
        for si, s in enumerate(senses):
            label = _POS_LABELS.get(s["pos"], s["pos"])
            sense_texts.append("%s: %s" % (label, s["translation"]))
            sense_map.append((wi, si))

    if not example_texts or not sense_texts:
        return {}

    # Embed
    example_embs = model.encode(example_texts, normalize_embeddings=True,
                                show_progress_bar=False, batch_size=64)
    sense_embs = model.encode(sense_texts, normalize_embeddings=True,
                              show_progress_bar=False, batch_size=64)

    # Build per-word lookups
    word_ex_embs = defaultdict(list)
    for flat_idx, (wi, ei) in enumerate(example_map):
        word_ex_embs[wi].append((ei, example_embs[flat_idx]))

    word_sn_embs = defaultdict(list)
    for flat_idx, (wi, si) in enumerate(sense_map):
        word_sn_embs[wi].append((si, sense_embs[flat_idx]))

    # Classify
    results = {}
    for wi, (word_key, senses, examples) in enumerate(words_data):
        ex_pairs = word_ex_embs.get(wi, [])
        sn_pairs = word_sn_embs.get(wi, [])

        assignments = [[] for _ in senses]

        if ex_pairs and sn_pairs:
            ex_indices, ex_vecs = zip(*ex_pairs)
            sn_indices, sn_vecs = zip(*sn_pairs)
            sims = np.dot(np.array(ex_vecs), np.array(sn_vecs).T)

            for row, ei in enumerate(ex_indices):
                best_col = int(np.argmax(sims[row]))
                best_si = sn_indices[best_col]
                assignments[best_si].append(ei)

        results[word_key] = [(si, idxs) for si, idxs in enumerate(assignments) if idxs]

    return results


# ---------------------------------------------------------------------------
# Main eval
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Eval: Wiktionary cascade sense classification")
    add_artist_arg(parser)
    parser.add_argument("--skip-google", action="store_true",
                        help="Skip Google Translate (run Gemini/Genius/Spanish-only only)")
    parser.add_argument("--focus-words", type=str, default=None,
                        help="Comma-separated list of words to focus on (e.g. 'bicho,perro,gata')")
    args = parser.parse_args()

    artist_dir = Path(args.artist_dir)
    cfg_path = artist_dir / "artist.json"
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        artist_name = cfg.get("name", artist_dir.name)
    else:
        artist_name = artist_dir.name

    print("=" * 70)
    print("WIKTIONARY CASCADE EVAL: %s" % artist_name)
    print("=" * 70)

    # ------------------------------------------------------------------
    # Step 1: Load artist data
    # ------------------------------------------------------------------
    print("\n--- Step 1: Loading artist data ---")

    senses_gemini_path = artist_dir / "data" / "layers" / "senses_gemini.json"
    examples_raw_path = artist_dir / "data" / "layers" / "examples_raw.json"
    example_trans_path = artist_dir / "data" / "layers" / "example_translations.json"

    with open(senses_gemini_path, encoding="utf-8") as f:
        senses_gemini = json.load(f)
    with open(examples_raw_path, encoding="utf-8") as f:
        examples_raw = json.load(f)
    with open(example_trans_path, encoding="utf-8") as f:
        example_trans = json.load(f)

    print("  Post-filter words (senses_gemini): %d" % len(senses_gemini))
    print("  Words with examples: %d" % len(examples_raw))
    print("  Translated lines: %d" % len(example_trans))

    # Split translations by source
    gemini_trans = {}
    genius_trans = {}
    for line, info in example_trans.items():
        eng = info.get("english", "")
        src = info.get("source", "")
        if eng:
            if src == "genius":
                genius_trans[line] = eng
            gemini_trans[line] = eng  # all translations go to gemini pool (it's the full set)

    print("  Genius translations: %d" % len(genius_trans))
    print("  All translations (Gemini+Genius): %d" % len(gemini_trans))

    # ------------------------------------------------------------------
    # Step 2: Load Wiktionary and look up senses
    # ------------------------------------------------------------------
    print("\n--- Step 2: Wiktionary lookup ---")

    wikt_index, redirects = load_wiktionary_index(WIKTIONARY_GZ)

    # Look up senses for each post-filter word
    wikt_senses = {}  # word_key -> [senses]
    no_wikt = []
    single_sense = []

    for key in senses_gemini:
        parts = key.split("|")
        word = parts[0]
        lemma = parts[1] if len(parts) > 1 else word
        senses = lookup_senses(word, lemma, wikt_index, redirects)
        if not senses:
            no_wikt.append(key)
        elif len(senses) == 1:
            single_sense.append(key)
            wikt_senses[key] = senses
        else:
            wikt_senses[key] = senses

    multi_sense = {k: v for k, v in wikt_senses.items() if len(v) >= 2}

    print("  Wiktionary match: %d / %d (%.1f%%)" % (
        len(wikt_senses), len(senses_gemini), 100 * len(wikt_senses) / len(senses_gemini)))
    print("  Multi-sense (2+): %d (interesting for classification)" % len(multi_sense))
    print("  Single-sense: %d (nothing to classify)" % len(single_sense))
    print("  No Wiktionary match: %d" % len(no_wikt))

    # ------------------------------------------------------------------
    # Step 3: Google Translate (optional)
    # ------------------------------------------------------------------
    google_trans = {}
    if not args.skip_google:
        print("\n--- Step 3: Google Translate ---")
        all_lines = []
        seen = set()
        for word_examples in examples_raw.values():
            for ex in word_examples:
                line = ex.get("spanish", "")
                if line and line not in seen:
                    seen.add(line)
                    all_lines.append(line)

        cache_path = str(artist_dir / "data" / "eval" / "google_translations.json")
        google_trans = generate_google_translations(all_lines, cache_path)
    else:
        print("\n--- Step 3: Skipping Google Translate (--skip-google) ---")

    # ------------------------------------------------------------------
    # Step 4: Build classification work items
    # ------------------------------------------------------------------
    print("\n--- Step 4: Building work items ---")

    # Focus on multi-sense words that have examples
    focus_set = None
    if args.focus_words:
        focus_set = set(w.strip().lower() for w in args.focus_words.split(","))

    work_items = []
    for key, senses in multi_sense.items():
        word = key.split("|")[0]
        if focus_set and word.lower() not in focus_set:
            continue
        examples = examples_raw.get(word, [])
        if not examples:
            continue
        work_items.append((key, senses, examples))

    print("  Multi-sense words with examples: %d" % len(work_items))

    if not work_items:
        print("\nNo multi-sense words to classify. Exiting.")
        return

    # ------------------------------------------------------------------
    # Step 5: Run biencoder classification with different translation sources
    # ------------------------------------------------------------------
    print("\n--- Step 5: Biencoder classification ---")

    from sentence_transformers import SentenceTransformer
    print("Loading model '%s'..." % CLASSIFY_MODEL)
    model = SentenceTransformer(CLASSIFY_MODEL)

    # Run A: Gemini translations (all available)
    print("\n  Run A: Gemini/full translations...")
    t0 = time.time()
    results_gemini = classify_words(work_items, gemini_trans, model)
    print("    Done in %.1fs" % (time.time() - t0))

    # Run B: Genius translations only
    print("  Run B: Genius translations only...")
    t0 = time.time()
    results_genius = classify_words(work_items, genius_trans, model)
    print("    Done in %.1fs" % (time.time() - t0))

    # Run C: Google Translate
    results_google = {}
    if google_trans:
        print("  Run C: Google Translate...")
        t0 = time.time()
        results_google = classify_words(work_items, google_trans, model)
        print("    Done in %.1fs" % (time.time() - t0))

    # Run D: Spanish only (empty translations)
    print("  Run D: Spanish only (no translations)...")
    t0 = time.time()
    results_spanish = classify_words(work_items, {}, model)
    print("    Done in %.1fs" % (time.time() - t0))

    # ------------------------------------------------------------------
    # Step 6: Compare results
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    # Helper: get the dominant sense for a word from classification results
    def dominant_sense(word_result):
        """Return (dominant_sense_idx, total_examples, distribution)."""
        if not word_result:
            return -1, 0, {}
        total = sum(len(idxs) for _, idxs in word_result)
        dist = {si: len(idxs) / total if total else 0 for si, idxs in word_result}
        best = max(word_result, key=lambda x: len(x[1]))
        return best[0], total, dist

    # Helper: per-example agreement
    def example_assignments(word_result, n_examples):
        """Return list mapping example_idx -> assigned_sense_idx."""
        mapping = [-1] * n_examples
        for si, idxs in word_result:
            for ei in idxs:
                if ei < n_examples:
                    mapping[ei] = si
        return mapping

    # Compare each source against Gemini (reference)
    comparisons = [
        ("Genius", results_genius),
        ("Spanish-only", results_spanish),
    ]
    if results_google:
        comparisons.insert(1, ("Google", results_google))

    for label, results_other in comparisons:
        total_examples = 0
        agree_examples = 0
        dominant_agree = 0
        dominant_total = 0
        disagree_words = []

        for key, senses, examples in work_items:
            word = key.split("|")[0]
            n_ex = len(examples)

            gem_result = results_gemini.get(key, [])
            other_result = results_other.get(key, [])

            # Per-example agreement
            gem_map = example_assignments(gem_result, n_ex)
            other_map = example_assignments(other_result, n_ex)

            for ei in range(n_ex):
                if gem_map[ei] >= 0 and other_map[ei] >= 0:
                    total_examples += 1
                    if gem_map[ei] == other_map[ei]:
                        agree_examples += 1

            # Dominant sense agreement
            gem_dom, _, _ = dominant_sense(gem_result)
            other_dom, _, _ = dominant_sense(other_result)
            if gem_dom >= 0 and other_dom >= 0:
                dominant_total += 1
                if gem_dom == other_dom:
                    dominant_agree += 1
                else:
                    gem_tr = senses[gem_dom]["translation"][:40] if gem_dom < len(senses) else "?"
                    other_tr = senses[other_dom]["translation"][:40] if other_dom < len(senses) else "?"
                    disagree_words.append((word, gem_tr, other_tr))

        ex_pct = 100 * agree_examples / total_examples if total_examples else 0
        dom_pct = 100 * dominant_agree / dominant_total if dominant_total else 0

        print("\n%s vs Gemini (reference):" % label)
        print("  Per-example agreement: %d / %d (%.1f%%)" % (agree_examples, total_examples, ex_pct))
        print("  Dominant-sense agreement: %d / %d (%.1f%%)" % (dominant_agree, dominant_total, dom_pct))

        if disagree_words:
            print("  Top disagreements (dominant sense differs):")
            for word, gem_tr, other_tr in sorted(disagree_words)[:20]:
                print("    %-20s Gemini=%-30s %s=%s" % (word, gem_tr, label, other_tr))

    # ------------------------------------------------------------------
    # Step 7: Focus word deep dive
    # ------------------------------------------------------------------
    interesting = ["bicho", "gata", "perro", "rico", "tiempo", "palo",
                   "tipo", "duro", "loco", "pega", "mala", "candela"]
    if focus_set:
        interesting = list(focus_set)

    print("\n" + "=" * 70)
    print("FOCUS WORD DEEP DIVE")
    print("=" * 70)

    for key, senses, examples in work_items:
        word = key.split("|")[0]
        if word.lower() not in [w.lower() for w in interesting]:
            continue

        print("\n--- %s (%d Wiktionary senses, %d examples) ---" % (word, len(senses), len(examples)))
        for si, s in enumerate(senses):
            print("  [%d] %s: %s" % (si, s["pos"], s["translation"][:60]))

        # Show classification from each source
        for label, result_set in [("Gemini", results_gemini),
                                   ("Genius", results_genius),
                                   ("Google", results_google),
                                   ("Spanish", results_spanish)]:
            if not result_set:
                continue
            wr = result_set.get(key, [])
            total = sum(len(idxs) for _, idxs in wr)
            if total == 0:
                print("  %s: no classifications" % label)
                continue
            parts = []
            for si, idxs in sorted(wr, key=lambda x: -len(x[1])):
                pct = 100 * len(idxs) / total
                tr = senses[si]["translation"][:25] if si < len(senses) else "?"
                parts.append("[%d] %s (%.0f%%)" % (si, tr, pct))
            print("  %-10s %s" % (label + ":", "  ".join(parts)))

        # Show a couple example sentences with their translations from different sources
        print("  Sample examples:")
        for ex in examples[:3]:
            sp = ex.get("spanish", "")[:70]
            gem_en = gemini_trans.get(ex.get("spanish", ""), "")[:70]
            goo_en = google_trans.get(ex.get("spanish", ""), "")[:70] if google_trans else ""
            print("    ES: %s" % sp)
            if gem_en:
                print("    Gemini: %s" % gem_en)
            if goo_en:
                print("    Google: %s" % goo_en)

    # ------------------------------------------------------------------
    # Step 8: Wiktionary coverage summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("WIKTIONARY COVERAGE SUMMARY")
    print("=" * 70)
    print("  Total post-filter words: %d" % len(senses_gemini))
    print("  Wiktionary match (any senses): %d (%.1f%%)" % (
        len(wikt_senses), 100 * len(wikt_senses) / len(senses_gemini)))
    print("  Multi-sense (classifiable): %d (%.1f%%)" % (
        len(multi_sense), 100 * len(multi_sense) / len(senses_gemini)))
    print("  Single-sense (trivial): %d" % len(single_sense))
    print("  No match: %d (%.1f%%)" % (
        len(no_wikt), 100 * len(no_wikt) / len(senses_gemini)))

    # Show sample of no-match words (non-propn, non-intj, has translation)
    real_missing = []
    for key in no_wikt:
        senses = senses_gemini.get(key, [])
        if not senses:
            continue
        pos = senses[0].get("pos", "")
        tr = senses[0].get("translation", "")
        word = key.split("|")[0]
        if pos not in ("PROPN", "INTJ") and tr and len(word) > 2 and "'" not in word:
            real_missing.append((key, pos, tr))

    print("\n  Genuinely missing (sample of 20):")
    for key, pos, tr in sorted(real_missing)[:20]:
        print("    %-35s %s: %s" % (key, pos, tr))

    print("\nDone.")


if __name__ == "__main__":
    main()
