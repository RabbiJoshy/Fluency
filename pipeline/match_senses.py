#!/usr/bin/env python3
"""
match_senses.py — Step 5: Assign example sentences to word senses.

Three classification modes:
  --gemini       Gemini Flash Lite (best accuracy, ~$0.50, ~30s) [default]
  --biencoder    Bi-encoder cosine similarity (free, ~4 min)
  --keyword-only Keyword overlap (instant, ~70% accuracy)

Gemini mode uses async parallelism (10 concurrent workers) for ~10x speedup.

Options:
  --merge / --no-merge   Override sense merging (default: on for biencoder, off for gemini)
  --english-only         Drop Spanish from Gemini prompts (saves ~40% input tokens)
  --limit N              Only classify first N words (by frequency rank)

Usage:
    python3 pipeline/match_senses.py                      # gemini, no merge
    python3 pipeline/match_senses.py --gemini --merge     # gemini + merge
    python3 pipeline/match_senses.py --english-only       # gemini, English-only
    python3 pipeline/match_senses.py --biencoder          # bi-encoder + merge
    python3 pipeline/match_senses.py --keyword-only       # instant fallback
    python3 pipeline/match_senses.py --limit 1000         # first 1000 words

Inputs:
    Data/Spanish/layers/word_inventory.json
    Data/Spanish/layers/examples_raw.json
    Data/Spanish/layers/sense_menu.json

Outputs:
    Data/Spanish/layers/sense_assignments.json
    Data/Spanish/layers/sense_merges.json (cached, when merge is used)
"""

import argparse
import json
import os
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path

from method_priority import (METHOD_PRIORITY, best_method_priority,
                              assign_sense_ids)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAYERS = PROJECT_ROOT / "Data" / "Spanish" / "layers"
INVENTORY_FILE = LAYERS / "word_inventory.json"
EXAMPLES_FILE = LAYERS / "examples_raw.json"
SENSES_FILE = LAYERS / "sense_menu.json"
OUTPUT_FILE = LAYERS / "sense_assignments.json"

MAX_EXAMPLES_PER_MEANING = None  # keep all classified examples; downstream selects best
MAX_CLASSIFY_EXAMPLES = 20
MIN_SENSE_FREQUENCY = 0.05
SENSE_MERGE_THRESHOLD = 0.70
BIENCODER_MODEL = "paraphrase-multilingual-mpnet-base-v2"  # sense merge (multilingual)
CLASSIFY_MODEL = "all-MiniLM-L6-v2"  # example classification (fast, English)

# ---------------------------------------------------------------------------
# POS enrichment
# ---------------------------------------------------------------------------
_POS_LABELS = {
    "VERB": "verb", "NOUN": "noun", "ADJ": "adjective",
    "ADV": "adverb", "ADP": "preposition",
    "CCONJ": "conjunction", "PRON": "pronoun",
    "DET": "determiner", "INTJ": "interjection",
    "NUM": "numeral", "PART": "particle",
    "PHRASE": "phrase", "CONTRACTION": "contraction",
}


def _first_translation(translation):
    """Extract first translation before comma (respecting parentheses).
    'to know, to understand (a fact), to realize' -> 'to know'
    'to taste (i.e. have a flavour)' -> 'to taste (i.e. have a flavour)'
    """
    depth = 0
    for i, ch in enumerate(translation):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            return translation[:i].strip()
    return translation


def enrich_sense_text(sense):
    """Build text for cross-encoder sense classification.
    Uses first translation only (avoids length bias in IR-style models)
    and 'Definition (pos):' framing for NLI models."""
    label = _POS_LABELS.get(sense["pos"], sense["pos"])
    trans = _first_translation(sense["translation"])
    return "Definition ({}): {}".format(label, trans)


def bilingual_text(ex):
    eng = ex.get("english", "")
    spa = ex.get("target", "")
    if eng and spa:
        return "{} [Spanish: {}]".format(eng, spa)
    return eng


# ---------------------------------------------------------------------------
# Gemini classification
# ---------------------------------------------------------------------------

def classify_with_gemini(work_items, output, english_only=False):
    """Classify examples using Gemini Flash Lite.  Groups examples by word
    (senses listed once per word) and batches multiple words per API call.
    Uses async parallelism for ~10x speedup over sequential calls."""
    import asyncio
    import os
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        env_path = Path(__file__).resolve().parents[1] / ".env"
        if env_path.exists():
            for line in open(env_path):
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found in environment or .env")

    client = genai.Client(api_key=api_key)
    model_name = "gemini-2.5-flash-lite"
    MAX_CONCURRENT = 10
    MAX_RETRIES = 2

    # Pre-compute sense signatures so conjugations sharing the same lemma
    # senses get a single ID.  Cuts prompt tokens by ~54%.
    sense_sig_to_id = {}
    sense_id_to_text = {}
    word_sense_ids = {}  # work_item index -> sense_list_id

    for wi, (key, senses, examples, keep_indices) in enumerate(work_items):
        reduced = [senses[i] for i in keep_indices]
        sig = tuple((s["pos"], s["translation"]) for s in reduced)
        if sig not in sense_sig_to_id:
            sid = "S{}".format(len(sense_sig_to_id) + 1)
            sense_sig_to_id[sig] = sid
            sense_id_to_text[sid] = " | ".join(
                "[{}] {}: {}".format(j, s["pos"], s["translation"])
                for j, s in enumerate(reduced)
            )
        word_sense_ids[wi] = sense_sig_to_id[sig]

    print("  {:,} unique sense lists (from {:,} words)".format(
        len(sense_sig_to_id), len(work_items)))

    WORDS_PER_BATCH = 50  # 100 causes format inconsistency in long outputs

    # Build all batches up front
    batches = []
    for batch_start in range(0, len(work_items), WORDS_PER_BATCH):
        batch = work_items[batch_start:batch_start + WORDS_PER_BATCH]
        batch_indices = list(range(batch_start, batch_start + len(batch)))

        # Collect sense lists used in this batch
        batch_sids = {}
        for wi in batch_indices:
            sid = word_sense_ids[wi]
            if sid not in batch_sids:
                batch_sids[sid] = sense_id_to_text[sid]

        prompt_lines = [
            "Word sense disambiguation. Sense lists are defined first, then referenced by ID per word.",
            "For each sentence, reply with the sense index (0-based).",
            "Format: WORD_NUM.SENTENCE_NUM: SENSE_INDEX",
            "",
            "Sense lists:",
        ]
        for sid, text in batch_sids.items():
            prompt_lines.append("  {}: {}".format(sid, text))
        prompt_lines.append("")

        batch_info = []
        batch_example_count = 0

        for wi_offset, (key, senses, examples, keep_indices) in enumerate(batch):
            word_num = wi_offset + 1
            sid = word_sense_ids[batch_indices[wi_offset]]

            prompt_lines.append("Word {} (senses={}):".format(word_num, sid))

            examples_with_eng = []
            for ei, ex in enumerate(examples):
                eng = ex.get("english", "")
                if eng:
                    examples_with_eng.append((ei, eng, ex.get("target", "")))

            for sent_num, (ei, eng, spa) in enumerate(examples_with_eng, 1):
                if english_only:
                    prompt_lines.append("  {}.{}: {}".format(
                        word_num, sent_num, eng[:120]))
                else:
                    prompt_lines.append("  {}.{}: {} [ES: {}]".format(
                        word_num, sent_num, eng[:120], spa[:80]))
                batch_example_count += 1

            batch_info.append((key, word_num, senses, keep_indices, examples_with_eng))
            prompt_lines.append("")

        prompt = "\n".join(prompt_lines)
        batches.append((batch_start, prompt, batch_info, batch_example_count))

    total_examples = sum(b[3] for b in batches)
    total_classified = 0
    batches_done = 0
    errors = 0

    print("\nClassifying {:,} words in {:,} batches ({} concurrent, {})...".format(
        len(work_items), len(batches), MAX_CONCURRENT,
        "English-only" if english_only else "bilingual"))
    t0 = time.time()

    # Multiple regexes to handle Gemini's inconsistent response formats:
    #   "1.1: 0"         — standard
    #   "1.1: S1:0"      — with sense list ID prefix
    #   "1.1.0"           — all dots, no colon
    #   "1.1.S54:0"       — dot before sense list ID
    #   "1.1. S281:1"     — dot+space before sense list ID
    _PARSE_PATTERNS = [
        # Standard: WORD.SENT: [S#:]SENSE (colon separator)
        re.compile(r"[*\-\s]*(\d+)\.(\d+)[*\s]*:\s*(?:S\d+\s*:\s*)?(\d+)"),
        # Dot separator: WORD.SENT.[S#:]SENSE or WORD.SENT.SENSE
        re.compile(r"[*\-\s]*(\d+)\.(\d+)\.\s*(?:S\d+\s*:\s*)?(\d+)"),
    ]

    def _parse_response(resp_text, batch_info, batch_idx=0):
        """Parse Gemini response and return list of (key, senses, orig_idx, ei)."""
        results = []
        # Strip markdown code fences
        text = resp_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Gemini sometimes returns pipe-separated single-line responses
        if "|" in text and text.count("\n") < 5:
            text = text.replace(" | ", "\n").replace("|", "\n")

        for line in text.split("\n"):
            m = None
            for pat in _PARSE_PATTERNS:
                m = pat.search(line)
                if m:
                    break
            if not m:
                continue
            word_num = int(m.group(1))
            sent_num = int(m.group(2))
            chosen_sense = int(m.group(3))

            for key, wn, senses, keep_indices, examples_with_eng in batch_info:
                if wn != word_num:
                    continue
                if sent_num < 1 or sent_num > len(examples_with_eng):
                    break
                ei = examples_with_eng[sent_num - 1][0]
                if 0 <= chosen_sense < len(keep_indices):
                    orig_idx = keep_indices[chosen_sense]
                else:
                    orig_idx = keep_indices[0]
                results.append((word_id, senses, orig_idx, ei))
                break

        if not results and text:
            # Debug: show first few lines of unparseable response
            preview = text[:300].replace("\n", " | ")
            print("  WARNING: batch {} returned 0 parseable lines. Preview: {}".format(
                batch_idx, preview))

        return results

    async def _process_batch(sem, batch_idx, prompt, batch_info):
        """Process a single batch with retry logic."""
        nonlocal total_classified, batches_done, errors
        async with sem:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    response = await client.aio.models.generate_content(
                        model=model_name, contents=prompt)
                    resp_text = response.text
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES:
                        wait = 2 ** attempt
                        await asyncio.sleep(wait)
                    else:
                        errors += 1
                        print("  Batch {} failed after {} retries: {}".format(
                            batch_idx, MAX_RETRIES, e))
                        batches_done += 1
                        return

            results = _parse_response(resp_text, batch_info, batch_idx)
            for key, senses, orig_idx, ei in results:
                if key not in output or not isinstance(output[key], dict):
                    output[key] = {"_indices": [[] for _ in senses]}
                output[key]["_indices"][orig_idx].append(ei)
                total_classified += 1

            batches_done += 1
            if batches_done % 5 == 0 or batches_done == len(batches):
                elapsed = time.time() - t0
                print("  {:,}/{:,} batches ({:,} examples, {:.1f}s)".format(
                    batches_done, len(batches), total_classified, elapsed), flush=True)

    async def _run_all():
        sem = asyncio.Semaphore(MAX_CONCURRENT)
        tasks = [
            _process_batch(sem, i, prompt, batch_info)
            for i, (batch_start, prompt, batch_info, _) in enumerate(batches)
        ]
        await asyncio.gather(*tasks)

    asyncio.run(_run_all())

    if errors:
        print("  {} batches failed (words fell back to first-sense default)".format(errors))

    # Convert _indices dicts to assignment format with frequency filtering
    for key, senses, examples, keep_indices in work_items:
        raw = output.get(key, {})
        if isinstance(raw, dict) and "_indices" in raw:
            sense_example_indices = raw["_indices"]
        else:
            # Not classified (error?) — first-sense fallback already in output
            continue

        total_cls = sum(len(idx) for idx in sense_example_indices)
        assignments = []
        for i, indices in enumerate(sense_example_indices):
            if not indices:
                continue
            if total_cls >= 5:
                freq = len(indices) / total_cls
                if freq < MIN_SENSE_FREQUENCY:
                    continue
            assignments.append({
                "sense_idx": i,
                "examples": indices[:MAX_EXAMPLES_PER_MEANING] if MAX_EXAMPLES_PER_MEANING else indices,
                "method": "gemini",
            })

        if not assignments:
            indices = list(range(min(len(examples), MAX_EXAMPLES_PER_MEANING)
                                 if MAX_EXAMPLES_PER_MEANING else len(examples)))
            assignments = [{"sense_idx": 0, "examples": indices, "method": "gemini"}]

        output[key] = assignments

    elapsed = time.time() - t0
    print("\n  Done: {:,} examples classified in {:.1f}s (~${:.2f})".format(
        total_classified, elapsed,
        total_examples * 70 * 0.075 / 1_000_000 + total_classified * 6 * 0.30 / 1_000_000))


# ---------------------------------------------------------------------------
# Bi-encoder classification
# ---------------------------------------------------------------------------

def classify_with_biencoder(work_items, output):
    """Classify all multi-sense words using bi-encoder cosine similarity.

    Embeds all example sentences and sense texts in batch, then assigns each
    example to the highest-similarity sense.  Much faster than cross-encoder
    (~6 min total vs ~4.5 hours) with comparable accuracy.
    """
    from sentence_transformers import SentenceTransformer
    import numpy as np

    print("Loading classifier model '{}'...".format(CLASSIFY_MODEL))
    model = SentenceTransformer(CLASSIFY_MODEL)

    # Collect all example texts that need embedding
    print("\nPreparing example texts...")
    example_texts = []   # flat list of bilingual texts
    example_map = []     # (work_idx, example_idx) for each text
    for wi, (key, senses, examples, keep_indices) in enumerate(work_items):
        for ei, ex in enumerate(examples):
            if ex.get("english", ""):
                example_texts.append(bilingual_text(ex))
                example_map.append((wi, ei))
    print("  {:,} example sentences to embed".format(len(example_texts)))

    # Collect all sense texts (raw "pos: translation" — best for bi-encoder)
    sense_texts = []
    sense_map = []       # (work_idx, sense_original_idx) for each text
    for wi, (key, senses, examples, keep_indices) in enumerate(work_items):
        for ki in keep_indices:
            s = senses[ki]
            label = _POS_LABELS.get(s["pos"], s["pos"])
            sense_texts.append("{}: {}".format(label, s["translation"]))
            sense_map.append((wi, ki))
    print("  {:,} sense texts to embed".format(len(sense_texts)))

    # Embed in batch
    print("\nEmbedding examples...")
    t0 = time.time()
    example_embs = model.encode(example_texts, normalize_embeddings=True,
                                show_progress_bar=True, batch_size=64)
    print("  Done in {:.1f}s".format(time.time() - t0))

    print("Embedding senses...")
    t0 = time.time()
    sense_embs = model.encode(sense_texts, normalize_embeddings=True,
                              show_progress_bar=False, batch_size=64)
    print("  Done in {:.1f}s".format(time.time() - t0))

    # Build per-word sense embedding lookup
    # word_sense_embs[wi] = [(original_sense_idx, embedding), ...]
    word_sense_embs = defaultdict(list)
    for flat_idx, (wi, ki) in enumerate(sense_map):
        word_sense_embs[wi].append((ki, sense_embs[flat_idx]))

    # Build per-word example embedding lookup
    # word_example_embs[wi] = [(example_idx, embedding), ...]
    word_example_embs = defaultdict(list)
    for flat_idx, (wi, ei) in enumerate(example_map):
        word_example_embs[wi].append((ei, example_embs[flat_idx]))

    # Classify each word
    print("\nClassifying {:,} words by cosine similarity...".format(len(work_items)))
    t0 = time.time()
    for wi, (key, senses, examples, keep_indices) in enumerate(work_items):
        n_senses = len(senses)
        sense_example_indices = [[] for _ in senses]

        ex_pairs = word_example_embs.get(wi, [])
        sn_pairs = word_sense_embs.get(wi, [])

        if ex_pairs and sn_pairs:
            # Stack embeddings for vectorized cosine similarity
            ex_indices, ex_vecs = zip(*ex_pairs)
            sn_indices, sn_vecs = zip(*sn_pairs)
            # similarities: (n_examples, n_kept_senses)
            sims = np.dot(np.array(ex_vecs), np.array(sn_vecs).T)

            for row, ei in enumerate(ex_indices):
                best_col = int(np.argmax(sims[row]))
                best_sense_idx = sn_indices[best_col]
                sense_example_indices[best_sense_idx].append(ei)
        else:
            # No English examples — assign all to first sense
            for ei in range(len(examples)):
                sense_example_indices[0].append(ei)

        # Frequency filter
        total_classified = sum(len(idx) for idx in sense_example_indices)
        assignments = []
        for i, indices in enumerate(sense_example_indices):
            if not indices:
                continue
            if total_classified >= 5:
                freq = len(indices) / total_classified
                if freq < MIN_SENSE_FREQUENCY:
                    continue
            assignments.append({
                "sense_idx": i,
                "examples": indices[:MAX_EXAMPLES_PER_MEANING] if MAX_EXAMPLES_PER_MEANING else indices,
                "method": "biencoder",
            })

        if not assignments:
            indices = list(range(min(len(examples), MAX_EXAMPLES_PER_MEANING) if MAX_EXAMPLES_PER_MEANING else len(examples)))
            assignments = [{"sense_idx": 0, "examples": indices, "method": "biencoder"}]

        output[key] = assignments

    elapsed = time.time() - t0
    print("  Done in {:.1f}s".format(elapsed))


# ---------------------------------------------------------------------------
# Bi-encoder: sense merge (pre-classification)
# ---------------------------------------------------------------------------

MERGE_CACHE_FILE = LAYERS / "sense_merges.json"


def _merge_fingerprint():
    """Fingerprint for sense merge cache: senses file + threshold + model."""
    import hashlib
    data = "{}-{}-{}-{}".format(
        os.path.getsize(SENSES_FILE),
        SENSE_MERGE_THRESHOLD,
        BIENCODER_MODEL,
        2,  # bump when merge logic changes
    )
    return hashlib.md5(data.encode()).hexdigest()[:12]


def load_or_compute_sense_merges(senses_data, inventory):
    """Load cached sense merges or compute and cache them."""
    fingerprint = _merge_fingerprint()

    # Try cache
    if MERGE_CACHE_FILE.exists():
        try:
            with open(MERGE_CACHE_FILE, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("fingerprint") == fingerprint:
                merge_map = cached["merge_map"]
                total_merged = sum(
                    len(senses_data.get(k, [])) - len(v)
                    for k, v in merge_map.items()
                )
                print("  Loaded cached merge map ({:,} merges across {:,} words)".format(
                    total_merged,
                    sum(1 for k, v in merge_map.items()
                        if len(v) < len(senses_data.get(k, [])))))
                return merge_map
            else:
                print("  Stale merge cache, recomputing...")
        except (json.JSONDecodeError, KeyError):
            print("  Corrupt merge cache, recomputing...")

    # Compute from scratch
    merge_map = _compute_sense_merges(senses_data, inventory)

    # Save cache
    with open(MERGE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "fingerprint": fingerprint,
            "threshold": SENSE_MERGE_THRESHOLD,
            "model": BIENCODER_MODEL,
            "merge_map": merge_map,
        }, f, ensure_ascii=False, indent=2)
    print("  Saved merge cache to {}".format(MERGE_CACHE_FILE.name))

    return merge_map


def _compute_sense_merges(senses_data, inventory):
    """Compute which senses to merge for each word using bi-encoder similarity."""
    from sentence_transformers import SentenceTransformer
    import numpy as np

    # Collect unique sense texts
    unique_texts = {}
    text_list = []
    for entry in inventory:
        key = "{}|{}".format(entry["word"], entry["lemma"])
        senses = senses_data.get(key, [])
        if len(senses) < 2:
            continue
        for s in senses:
            t = enrich_sense_text(s)
            if t not in unique_texts:
                unique_texts[t] = len(text_list)
                text_list.append(t)

    if not text_list:
        return {}

    print("  Loading bi-encoder '{}' (sense merge)...".format(BIENCODER_MODEL))
    model = SentenceTransformer(BIENCODER_MODEL)
    print("  Embedding {:,} unique sense texts...".format(len(text_list)))
    start = time.time()
    embeddings = model.encode(text_list, normalize_embeddings=True, show_progress_bar=False)
    print("  Done in {:.1f}s".format(time.time() - start))

    # Compute merges per word
    merge_map = {}
    total_merged = 0
    for entry in inventory:
        key = "{}|{}".format(entry["word"], entry["lemma"])
        senses = senses_data.get(key, [])
        if len(senses) < 2:
            continue

        merged_into = {}
        for i in range(len(senses)):
            if i in merged_into:
                continue
            si_text = enrich_sense_text(senses[i])
            si_idx = unique_texts.get(si_text)
            if si_idx is None:
                continue
            for j in range(i + 1, len(senses)):
                if j in merged_into:
                    continue
                if senses[i]["pos"] != senses[j]["pos"]:
                    continue
                sj_text = enrich_sense_text(senses[j])
                sj_idx = unique_texts.get(sj_text)
                if sj_idx is None:
                    continue
                sim = float(np.dot(embeddings[si_idx], embeddings[sj_idx]))
                if sim >= SENSE_MERGE_THRESHOLD:
                    merged_into[j] = i
                    total_merged += 1

        keep = [i for i in range(len(senses)) if i not in merged_into]
        merge_map[key] = keep

    print("  Pre-merged {:,} senses across {:,} words".format(
        total_merged, sum(1 for k in merge_map if len(merge_map[k]) < len(senses_data.get(k, [])))))

    return merge_map


# ---------------------------------------------------------------------------
# Keyword overlap classifier (fallback)
# ---------------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-z]+")
_STOP_WORDS = {
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "is", "it",
    "be", "as", "or", "by", "and", "not", "with", "from", "that", "this",
    "but", "are", "was", "were", "been", "has", "have", "had", "do", "does",
    "did", "will", "would", "can", "could", "may", "might", "shall", "should",
    "up", "out", "if", "so", "no", "into", "over", "also", "its", "one",
    "e", "g", "etc", "very", "just", "about", "more", "some", "than",
}


def tokenize_english(text):
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP_WORDS
            and len(w) > 1}


def classify_example_keyword(sentence_english, senses):
    sentence_words = tokenize_english(sentence_english)
    scores = []
    for s in senses:
        sense_words = tokenize_english(s["translation"])
        scores.append(len(sentence_words & sense_words) if sense_words else 0)
    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    sorted_scores = sorted(scores, reverse=True)
    confidence = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) >= 2 else 0
    return best_idx, confidence


# ---------------------------------------------------------------------------
# Output format conversion
# ---------------------------------------------------------------------------

def _write_new_format(output, existing_assigns, senses_data, sense_id_maps):
    """Convert internal output to method-keyed format, merge with existing, and write.

    Internal format: {key: [{sense_idx, examples, method?}]}
    New format:      {key: {method: [{sense: id, examples: [...]}]}}
    """
    for key, assigns in output.items():
        if not isinstance(assigns, list):
            continue  # already converted or intermediate _indices dict

        senses = senses_data.get(key, [])
        id_map_list = list(sense_id_maps.get(key, {}).keys())

        # Determine method from assignments (all should agree, use first)
        method_name = "keyword"
        if assigns and isinstance(assigns[0], dict):
            method_name = assigns[0].get("method", "keyword")

        items = []
        for a in assigns:
            idx = a.get("sense_idx", 0)
            if idx < len(id_map_list):
                items.append({"sense": id_map_list[idx],
                              "examples": a.get("examples", [])})
            elif id_map_list:
                # Fallback to first sense
                items.append({"sense": id_map_list[0],
                              "examples": a.get("examples", [])})

        if items:
            if key not in existing_assigns or not isinstance(existing_assigns.get(key), dict):
                existing_assigns[key] = {}
            existing_assigns[key][method_name] = items

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_assigns, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Assign examples to senses")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gemini", action="store_true",
                      help="Gemini Flash Lite classification (best accuracy, ~$1)")
    mode.add_argument("--biencoder", action="store_true",
                      help="Bi-encoder cosine similarity (free, ~4 min)")
    mode.add_argument("--keyword-only", action="store_true",
                      help="Keyword overlap (instant, ~70%% accuracy)")
    parser.add_argument("--merge", action="store_true",
                        help="Enable sense merging (default for biencoder, off for gemini)")
    parser.add_argument("--no-merge", action="store_true",
                        help="Disable sense merging")
    parser.add_argument("--limit", type=int, default=0,
                        help="Only classify first N words (by frequency rank)")
    parser.add_argument("--english-only", action="store_true",
                        help="Gemini: drop Spanish from examples (saves ~40%% input tokens)")
    parser.add_argument("--force", action="store_true",
                        help="Bypass priority checking — reclassify all words")
    args = parser.parse_args()

    # Default mode is gemini
    use_gemini = args.gemini or (not args.biencoder and not args.keyword_only)
    use_biencoder = args.biencoder
    use_keyword = args.keyword_only

    # Merge: on by default for biencoder, off by default for gemini/keyword
    if args.merge and args.no_merge:
        parser.error("Cannot use both --merge and --no-merge")
    if args.no_merge:
        do_merge = False
    elif args.merge:
        do_merge = True
    else:
        do_merge = use_biencoder  # default: merge for biencoder only

    if use_gemini:
        method = "gemini" + (" + merge" if do_merge else "")
    elif use_biencoder:
        method = "bi-encoder + merge"
    else:
        method = "keyword overlap"
    print("Sense matching method: {}".format(method))

    print("\nLoading word inventory...")
    with open(INVENTORY_FILE, encoding="utf-8") as f:
        inventory = json.load(f)
    print("  {:,} entries".format(len(inventory)))

    print("Loading examples...")
    with open(EXAMPLES_FILE, encoding="utf-8") as f:
        examples_data = json.load(f)
    print("  {:,} entries with examples".format(len(examples_data)))

    print("Loading senses...")
    with open(SENSES_FILE, encoding="utf-8") as f:
        senses_data = json.load(f)
    print("  {:,} sense entries".format(len(senses_data)))

    # Determine current method and its priority
    if use_gemini:
        my_method = "gemini"
    elif use_biencoder:
        my_method = "biencoder"
    else:
        my_method = "keyword"
    my_priority = METHOD_PRIORITY.get(my_method, 0)

    # Build sense ID maps for new-format output
    sense_id_maps = {}
    for skey, senses_list in senses_data.items():
        if isinstance(senses_list, list):
            sense_id_maps[skey] = assign_sense_ids(senses_list)

    # Build word_id -> word|lemma lookup for migrating old-format assignments
    id_to_key = {}
    for entry in inventory:
        id_to_key[entry["id"]] = "{}|{}".format(entry["word"], entry["lemma"])

    # Load existing assignments (with auto-migration from old format)
    existing_assigns = {}
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            raw_assigns = json.load(f)
        if raw_assigns:
            first_val = next(iter(raw_assigns.values()))
            if isinstance(first_val, list):
                # Old format (keyed by hex ID with sense_idx) — migrate
                print("  Migrating old-format assignments to method-keyed format...")
                backup_path = OUTPUT_FILE.with_suffix(".json.bak")
                if not backup_path.exists():
                    shutil.copy2(OUTPUT_FILE, backup_path)
                    print("  Backed up old file to {}".format(backup_path.name))
                migrated = 0
                for wid, assigns in raw_assigns.items():
                    key = id_to_key.get(wid)
                    if not key:
                        continue
                    senses = senses_data.get(key, [])
                    id_map_list = list(sense_id_maps.get(key, {}).keys())
                    old_method = "biencoder"
                    if assigns and isinstance(assigns[0], dict):
                        old_method = assigns[0].get("method", "biencoder")
                    items = []
                    for a in assigns:
                        idx = a.get("sense_idx", 0)
                        if idx < len(id_map_list):
                            items.append({"sense": id_map_list[idx],
                                          "examples": a.get("examples", [])})
                    if items:
                        existing_assigns[key] = {old_method: items}
                        migrated += 1
                print("  Migrated {:,} entries".format(migrated))
            else:
                # Already new format
                existing_assigns = raw_assigns
        print("  Loaded {:,} existing assignments".format(len(existing_assigns)))

    # Apply --limit (inventory is sorted by frequency rank)
    if args.limit > 0:
        inventory = inventory[:args.limit]
        print("  Limited to first {:,} words".format(len(inventory)))

    # Sense merges (cached)
    merge_map = {}
    if do_merge:
        print("\nSense merging...")
        merge_map = load_or_compute_sense_merges(senses_data, inventory)

    # Build a fingerprint of inputs so we can detect stale checkpoints.
    # If senses, examples, or merge config change, old checkpoints are invalid.
    import hashlib
    _CODE_VERSION = 9  # bump when classification logic changes
    fingerprint_data = "{}-{}-{}-{}-{}-{}-{}".format(
        _CODE_VERSION,
        os.path.getsize(SENSES_FILE),
        os.path.getsize(EXAMPLES_FILE),
        method,
        "merged" if do_merge else "unmerged",
        len(merge_map),
        "en-only" if args.english_only else "bilingual",
    )
    run_fingerprint = hashlib.md5(fingerprint_data.encode()).hexdigest()[:12]

    # Load partial progress (only if fingerprint matches)
    partial_file = OUTPUT_FILE.with_suffix(".partial.json")
    output = {}
    done_keys = set()
    if partial_file.exists():
        try:
            with open(partial_file, encoding="utf-8") as f:
                saved = json.load(f)
            if saved.get("fingerprint") == run_fingerprint:
                output = saved.get("assignments", {})
                done_keys = set(output.keys())
                print("\nResuming: {:,} assignments loaded from checkpoint".format(len(output)))
            else:
                print("\nStale checkpoint detected (inputs changed), starting fresh")
                partial_file.unlink()
        except (json.JSONDecodeError, KeyError):
            print("\nCorrupt partial file, starting fresh")
            partial_file.unlink()

    # Load spaCy for POS pre-filtering (cheap, avoids classifying easy cases)
    _nlp = None
    def get_nlp():
        nonlocal _nlp
        if _nlp is None:
            import spacy
            for model in ["es_core_news_sm", "es_core_news_md"]:
                try:
                    _nlp = spacy.load(model, disable=["ner"])
                    print("  POS pre-filter: loaded {}".format(model))
                    break
                except OSError:
                    continue
            if _nlp is None:
                print("  POS pre-filter: no spaCy model, skipping")
        return _nlp

    # Build work items for multi-sense words
    print("\nPreparing work items...")
    work_items = []  # (key, senses, examples, keep_indices)
    single_sense_count = 0
    no_senses_count = 0
    no_examples_count = 0
    skipped_priority = 0
    pos_resolved = 0

    for entry in inventory:
        word_id = entry["id"]
        key = "{}|{}".format(entry["word"], entry["lemma"])
        senses = senses_data.get(key, [])
        examples = examples_data.get(word_id, [])

        if not senses:
            no_senses_count += 1
            continue

        # Priority check: skip words with equal-or-higher priority assignments
        if not args.force and key in existing_assigns:
            existing_priority = best_method_priority(existing_assigns[key])
            if existing_priority >= my_priority:
                skipped_priority += 1
                continue

        if not examples:
            no_examples_count += 1
            if key not in done_keys:
                output[key] = [{"sense_idx": 0, "examples": []}]
            continue

        if len(senses) == 1:
            single_sense_count += 1
            if key not in done_keys:
                indices = list(range(min(len(examples), MAX_EXAMPLES_PER_MEANING) if MAX_EXAMPLES_PER_MEANING else len(examples)))
                output[key] = [{"sense_idx": 0, "examples": indices}]
            continue

        if key in done_keys:
            continue

        keep_indices = merge_map.get(key, list(range(len(senses))))

        # POS pre-filtering: if senses split by POS, tag examples and assign
        # directly for words where POS fully disambiguates.
        sense_poses = [senses[i]["pos"] for i in keep_indices]
        unique_pos = set(sense_poses)
        if len(unique_pos) >= 2 and len(unique_pos) == len(keep_indices):
            # Every kept sense has a unique POS — POS alone disambiguates
            nlp = get_nlp()
            if nlp is not None:
                word_lower = entry["word"].lower()
                lemma_lower = entry["lemma"].lower()
                pos_map = {senses[i]["pos"]: i for i in keep_indices}
                sense_example_indices = [[] for _ in senses]
                for ei, ex in enumerate(examples):
                    text = ex.get("target", ex.get("spanish", ""))
                    if not text:
                        sense_example_indices[keep_indices[0]].append(ei)
                        continue
                    doc = nlp(text)
                    tagged_pos = None
                    for tok in doc:
                        tl = tok.text.lower()
                        ll = tok.lemma_.lower()
                        if tl == word_lower or ll == lemma_lower or ll == word_lower:
                            spacy_pos = {"AUX": "VERB", "SCONJ": "CCONJ"}.get(tok.pos_, tok.pos_)
                            if spacy_pos in pos_map:
                                tagged_pos = spacy_pos
                            break
                    if tagged_pos:
                        sense_example_indices[pos_map[tagged_pos]].append(ei)
                    else:
                        # Couldn't find word or POS not in menu — first sense
                        sense_example_indices[keep_indices[0]].append(ei)

                assignments_list = []
                total_cls = sum(len(idx) for idx in sense_example_indices)
                for i, indices in enumerate(sense_example_indices):
                    if not indices:
                        continue
                    if total_cls >= 5 and len(indices) / total_cls < MIN_SENSE_FREQUENCY:
                        continue
                    assignments_list.append({"sense_idx": i, "examples": indices, "method": my_method})
                if assignments_list:
                    output[key] = assignments_list
                    pos_resolved += 1
                    continue

        if use_gemini or use_biencoder:
            work_items.append((key, senses, examples, keep_indices))
        else:
            # Keyword fallback — process inline
            sense_example_indices = [[] for _ in senses]
            for ex_idx, ex in enumerate(examples):
                eng = ex.get("english", "")
                if not eng:
                    sense_example_indices[0].append(ex_idx)
                    continue
                best_idx, _ = classify_example_keyword(eng, senses)
                sense_example_indices[best_idx].append(ex_idx)
            total_classified = sum(len(idx) for idx in sense_example_indices)
            assignments = []
            for i, indices in enumerate(sense_example_indices):
                if not indices:
                    continue
                if total_classified >= 5 and len(indices) / total_classified < MIN_SENSE_FREQUENCY:
                    continue
                assignments.append({"sense_idx": i, "examples": indices[:MAX_EXAMPLES_PER_MEANING] if MAX_EXAMPLES_PER_MEANING else indices, "method": "keyword"})
            if not assignments:
                assignments = [{"sense_idx": 0, "examples": list(range(min(len(examples), MAX_EXAMPLES_PER_MEANING) if MAX_EXAMPLES_PER_MEANING else len(examples))), "method": "keyword"}]
            output[key] = assignments

    if skipped_priority:
        print("  Skipped {:,} words (existing priority >= {})".format(
            skipped_priority, my_method))
    if pos_resolved:
        print("  POS pre-filter resolved {:,} words (no classifier needed)".format(
            pos_resolved))

    # Seed first-sense fallback for unprocessed multi-sense words so that
    # sense_assignments.json is always complete even after Ctrl+C.
    # Real cross-encoder results overwrite these as they complete.
    seeded = 0
    for key, senses, examples, keep_indices in work_items:
        if key not in done_keys:
            indices = list(range(
                min(len(examples), MAX_EXAMPLES_PER_MEANING)
                if MAX_EXAMPLES_PER_MEANING else len(examples)))
            output[key] = [{"sense_idx": 0, "examples": indices}]
            seeded += 1

    # Write initial assignments so sense_assignments.json is usable immediately
    _write_new_format(output, existing_assigns, senses_data, sense_id_maps)
    if seeded:
        print("  Seeded {:,} multi-sense words with first-sense fallback".format(seeded))
    print("  Wrote initial assignments ({:,} entries) to {}".format(
        len(existing_assigns), OUTPUT_FILE.name))

    skipped = len(done_keys & {wi[0] for wi in work_items}) if done_keys else 0
    print("  Single-sense (no classification): {:,}".format(single_sense_count))
    print("  Multi-sense to classify: {:,}".format(len(work_items)))
    if done_keys:
        print("  Already done (checkpoint): {:,}".format(len(done_keys)))

    if not work_items:
        print("\nNo work to do!")
    elif use_gemini:
        classify_with_gemini(work_items, output, english_only=args.english_only)
    elif use_biencoder:
        classify_with_biencoder(work_items, output)
    else:
        print("\nKeyword classification done (instant)")

    # Write final output — convert internal format to method-keyed with sense IDs
    print("\nWriting {}...".format(OUTPUT_FILE))
    _write_new_format(output, existing_assigns, senses_data, sense_id_maps)

    if partial_file.exists():
        partial_file.unlink()
        print("  Removed partial checkpoint")

    # Report
    from collections import Counter
    method_counts = Counter()
    for key, methods in existing_assigns.items():
        if isinstance(methods, dict):
            for m in methods:
                method_counts[m] += 1
    print("\n{}".format("=" * 55))
    print("SENSE ASSIGNMENT RESULTS ({})".format(method))
    print("{}".format("=" * 55))
    print("Total assignments:         {:>6,}".format(len(existing_assigns)))
    print("No Wiktionary senses:      {:>6,}".format(no_senses_count))
    print("Single sense:              {:>6,}".format(single_sense_count))
    print("Multi-sense (classified):  {:>6,}".format(len(work_items)))
    print("No examples:               {:>6,}".format(no_examples_count))
    if skipped_priority:
        print("Skipped (higher priority):  {:>5,}".format(skipped_priority))
    if method_counts:
        print("\nMethods in output:")
        for m, cnt in method_counts.most_common():
            print("  {:25s} {:>6,}  (priority={})".format(
                m, cnt, METHOD_PRIORITY.get(m, "?")))
    print()
    print("Active senses per word:")
    active = Counter()
    for key, methods in existing_assigns.items():
        if isinstance(methods, dict):
            # Count senses from the best method
            best_m = max(methods.keys(), key=lambda m: METHOD_PRIORITY.get(m, -1))
            active[len(methods[best_m])] += 1
    for n in sorted(active):
        print("  {} senses: {:>6,} words".format(n, active[n]))


if __name__ == "__main__":
    main()
