#!/usr/bin/env python3
"""
Shared sense classifiers used by both normal-mode and artist-mode pipelines.

Three classifiers, same interface: given sense texts and example texts,
assign each example to the best-matching sense.

  - biencoder:  local sentence-transformers model (free, ~3 min)
  - gemini:     Gemini Flash Lite API (costs money, higher quality)
  - keyword:    keyword overlap (instant, ~70% accuracy)
"""

import json
import re
import time

DEFAULT_MODEL = "paraphrase-multilingual-mpnet-base-v2"

# Frequency threshold: senses with < 5% of examples are dropped
MIN_SENSE_FREQUENCY = 0.05

# POS labels for bi-encoder sense text formatting
_POS_LABELS = {
    "NOUN": "noun",
    "VERB": "verb",
    "ADJ": "adjective",
    "ADV": "adverb",
    "PRON": "pronoun",
    "DET": "determiner",
    "ADP": "preposition",
    "CCONJ": "conjunction",
    "SCONJ": "conjunction",
    "INTJ": "interjection",
    "NUM": "numeral",
    "PART": "particle",
    "X": "other",
}


def format_sense_text(sense):
    """Format a sense dict as text for embedding: 'noun: house'."""
    label = _POS_LABELS.get(sense.get("pos", "X"), sense.get("pos", ""))
    return "%s: %s" % (label, sense.get("translation", ""))


def format_example_text(spanish, english=""):
    """Format an example for embedding. Bilingual when possible."""
    if english and spanish:
        return "%s [Spanish: %s]" % (english, spanish)
    return spanish or english or ""


# ---------------------------------------------------------------------------
# Bi-encoder classifier
# ---------------------------------------------------------------------------

def classify_biencoder(work_items, model_name=None):
    """Classify examples to senses using bi-encoder cosine similarity.

    Args:
        work_items: list of dicts, each with:
            - sense_texts: list of formatted sense strings
            - example_texts: list of formatted example strings
            - keep_indices: which sense indices to consider (optional,
              defaults to all)
        model_name: sentence-transformers model (default: multilingual mpnet)

    Returns:
        list of assignments per work item. Each assignment is a list of
        (sense_idx, [example_indices]) tuples.
    """
    from sentence_transformers import SentenceTransformer
    import numpy as np

    model_name = model_name or DEFAULT_MODEL
    print("Loading classifier model '%s'..." % model_name)
    model = SentenceTransformer(model_name)

    # Collect all texts for batch embedding
    example_texts_flat = []
    example_map = []  # (work_idx, example_idx)
    sense_texts_flat = []
    sense_map = []  # (work_idx, sense_position)

    for wi, item in enumerate(work_items):
        for ei, text in enumerate(item["example_texts"]):
            if text:
                example_texts_flat.append(text)
                example_map.append((wi, ei))
        keep = item.get("keep_indices", list(range(len(item["sense_texts"]))))
        for ki in keep:
            sense_texts_flat.append(item["sense_texts"][ki])
            sense_map.append((wi, ki))

    print("  %d examples, %d senses to embed" %
          (len(example_texts_flat), len(sense_texts_flat)))

    if not example_texts_flat:
        return [[] for _ in work_items]

    # Batch embed
    print("Embedding...")
    t0 = time.time()
    example_embs = model.encode(example_texts_flat, normalize_embeddings=True,
                                show_progress_bar=False, batch_size=64)
    sense_embs = model.encode(sense_texts_flat, normalize_embeddings=True,
                              show_progress_bar=False, batch_size=64)
    print("  Done in %.1fs" % (time.time() - t0))

    # Group embeddings by work item
    from collections import defaultdict
    word_example_embs = defaultdict(list)
    for flat_idx, (wi, ei) in enumerate(example_map):
        word_example_embs[wi].append((ei, example_embs[flat_idx]))

    word_sense_embs = defaultdict(list)
    for flat_idx, (wi, ki) in enumerate(sense_map):
        word_sense_embs[wi].append((ki, sense_embs[flat_idx]))

    # Classify
    print("Classifying %d words..." % len(work_items))
    t0 = time.time()
    results = []

    for wi, item in enumerate(work_items):
        n_senses = len(item["sense_texts"])
        n_examples = len(item["example_texts"])
        buckets = [[] for _ in range(n_senses)]

        ex_pairs = word_example_embs.get(wi, [])
        sn_pairs = word_sense_embs.get(wi, [])

        if ex_pairs and sn_pairs:
            ex_indices, ex_vecs = zip(*ex_pairs)
            sn_indices, sn_vecs = zip(*sn_pairs)
            sims = np.dot(np.array(ex_vecs), np.array(sn_vecs).T)

            for row, ei in enumerate(ex_indices):
                best_col = int(np.argmax(sims[row]))
                best_si = sn_indices[best_col]
                buckets[best_si].append(ei)

        # Unembedded examples go to first kept sense
        embedded = {ei for ei, _ in ex_pairs}
        keep = item.get("keep_indices", list(range(n_senses)))
        first = keep[0] if keep else 0
        for ei in range(n_examples):
            if ei not in embedded:
                buckets[first].append(ei)

        # Frequency filter
        total = sum(len(b) for b in buckets)
        assignments = []
        for si, indices in enumerate(buckets):
            if not indices:
                continue
            if total >= 5 and len(indices) / total < MIN_SENSE_FREQUENCY:
                continue
            assignments.append((si, sorted(indices)))

        if not assignments:
            assignments = [(first, list(range(n_examples)))]

        results.append(assignments)

    print("  Done in %.1fs" % (time.time() - t0))
    return results


# ---------------------------------------------------------------------------
# Keyword classifier
# ---------------------------------------------------------------------------

_KEYWORD_RE = re.compile(r"[a-z]+")
_KEYWORD_STOP = frozenset({
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "is",
    "it", "be", "as", "or", "by", "and", "not", "with", "from",
    "that", "this", "but", "are", "was", "were", "i", "me", "my",
    "you", "he", "she", "we", "they", "do", "does", "did", "has",
    "have", "had", "will", "would", "can", "could", "may", "might",
    "shall", "should", "up", "out", "if", "so", "no", "into", "over",
    "also", "its", "one", "e", "g", "etc", "very", "just", "about",
    "more", "some", "than",
})


def _tokenize(text):
    return {w for w in _KEYWORD_RE.findall(text.lower())
            if w not in _KEYWORD_STOP and len(w) > 1}


def classify_keyword(sense_texts, example_texts):
    """Assign each example to the best-matching sense by keyword overlap.

    Args:
        sense_texts: list of sense description strings
        example_texts: list of example strings (English preferred)

    Returns:
        list of sense indices, one per example.
    """
    sense_words = [_tokenize(s) for s in sense_texts]
    assignments = []
    for text in example_texts:
        ex_words = _tokenize(text)
        best_idx = 0
        best_score = 0
        for si, sw in enumerate(sense_words):
            score = len(ex_words & sw) if sw else 0
            if score > best_score:
                best_score = score
                best_idx = si
        assignments.append(best_idx)
    return assignments


# ---------------------------------------------------------------------------
# Gemini Flash Lite classifier
# ---------------------------------------------------------------------------

def classify_gemini_batch(words_data, api_key):
    """Classify examples to senses for a batch of words using Gemini.

    Args:
        words_data: list of dicts with {word, lemma, senses, examples}.
            senses: [{pos, translation, source?, is_spanish?}]
            examples: [{spanish, english}]
        api_key: Gemini API key

    Returns:
        list of per-word dicts mapping example number (str) → sense index,
        or None on failure.
    """
    from google import genai
    client = genai.Client(api_key=api_key)

    prompt_parts = [
        "You are classifying Spanish vocabulary from song lyrics.",
        "For each word below, assign each numbered example to the best-matching"
        " sense (0-indexed). If both an English sense and a Spanish [ES] sense"
        " cover the same meaning, prefer the English one.",
        "",
        "Substitution test: for each example, mentally substitute the sense"
        " definition into the English translation. Does it still convey the"
        " right meaning? If not, try other senses. Pick the sense whose"
        " definition makes the substituted sentence make sense, even if the"
        " translator used a different English word.",
        "",
    ]

    for wi, wd in enumerate(words_data):
        prompt_parts.append('--- Word %d: "%s" (lemma: %s) ---' % (
            wi + 1, wd["word"], wd["lemma"]))
        prompt_parts.append("Senses:")
        for si, s in enumerate(wd["senses"]):
            label = "[ES] " if s.get("is_spanish") else ""
            prompt_parts.append("  %d. %s[%s] %s" % (
                si, label, s["pos"], s["translation"]))
        prompt_parts.append("Examples:")
        for ei, ex in enumerate(wd["examples"]):
            spa = ex.get("spanish", "")
            eng = ex.get("english", "")
            prompt_parts.append("  %d. %s | %s" % (ei + 1, spa, eng))
        prompt_parts.append("")

    prompt_parts.append("Return a JSON array with one object per word:")
    prompt_parts.append(json.dumps([{
        "word": "example",
        "assignments": {"1": 0, "2": 1},
    }], indent=2))

    prompt = "\n".join(prompt_parts)

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
                config={"temperature": 0.0,
                        "response_mime_type": "application/json"},
            )
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            print("    WARNING: batch parse error")
            print("    Raw: %s" % (
                response.text[:500] if response.text else "None"))
            return None
        except Exception as e:
            wait = 2 ** attempt * 5
            print("    API error (attempt %d/5): %s" % (
                attempt + 1, str(e)[:100]))
            print("    Retrying in %ds..." % wait)
            time.sleep(wait)
    print("    FAILED after 5 retries")
    return None


def gap_fill_gemini(word, lemma, senses, examples, api_key):
    """Ask Gemini to propose a sense for a word not in Wiktionary.

    Args:
        word: the word form
        lemma: the lemma
        senses: existing senses (may be empty)
        examples: [{spanish, english}]
        api_key: Gemini API key

    Returns:
        dict with proposed_sense, proposed_pos, etc. or None.
    """
    from google import genai
    client = genai.Client(api_key=api_key)

    menu_lines = []
    for i, s in enumerate(senses):
        label = "[ES] " if s.get("is_spanish") else ""
        menu_lines.append("%d. %s[%s] %s" % (
            i + 1, label, s["pos"], s["translation"]))

    lines = []
    for i, ex in enumerate(examples):
        lines.append("%d. %s | %s" % (
            i + 1, ex.get("spanish", ""), ex.get("english", "")))

    prompt = (
        'You are helping build a Spanish vocabulary flashcard app for learners.'
        ' The word is "%s" (lemma: %s).\n\n'
        'Step 1: Read these example lyrics and determine what "%s" actually'
        ' means in this artist\'s usage:\n%s\n\n'
        'Step 2: Check whether any of these dictionary senses is close enough'
        ' that a learner reading it on a flashcard would understand the word'
        ' in these lyrics.\n'
        'If both an English sense and a Spanish [ES] sense cover the same'
        ' meaning, prefer the English one.\n%s\n\n'
        'Test each sense: take the English translation of one example lyric'
        ' and substitute the dictionary definition for the word. Write out'
        ' the substituted sentence. Does it still convey what the artist'
        ' means?\n\n'
        'If the best sense passes this test, the word is covered — even if'
        ' the usage is more figurative or intense. Flashcard space is limited,'
        ' so don\'t propose new senses when existing ones work.\n\n'
        'Step 3: If NO sense passes the substitution test, propose ONE short'
        ' flashcard translation.\n\n'
        'Return JSON:\n'
        '{\n'
        '  "actual_meaning": "<what the word means in these lyrics>",\n'
        '  "covered_by_existing": <true/false>,\n'
        '  "best_sense_index": <1-indexed or null>,\n'
        '  "proposed_sense": "<short English translation if not covered>",\n'
        '  "proposed_pos": "<NOUN/VERB/ADJ/ADV/INTJ if proposing>"\n'
        '}'
    ) % (word, lemma, word, "\n".join(lines), "\n".join(menu_lines))

    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
                config={"temperature": 0.0,
                        "response_mime_type": "application/json"},
            )
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            print("    WARNING: gap-fill parse error")
            return None
        except Exception as e:
            wait = 2 ** attempt * 5
            print("    API error (attempt %d/5): %s" % (
                attempt + 1, str(e)[:100]))
            print("    Retrying in %ds..." % wait)
            time.sleep(wait)
    print("    FAILED after 5 retries")
    return None
