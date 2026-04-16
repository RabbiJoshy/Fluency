#!/usr/bin/env python3
"""POS-based sense-menu filtering helpers for both pipelines.

These helpers narrow a word's candidate sense menu before expensive
classification runs. The filter is conservative:

- If spaCy cannot tag the target reliably, keep the full menu.
- If tagged examples span multiple POS values, keep any sense whose POS was
  observed in context.
- If all tagged examples point to one POS, only keep senses with that POS.
"""

import re
from collections import Counter

_SPACY_POS_MAP = {
    "NOUN": "NOUN", "VERB": "VERB", "ADJ": "ADJ", "ADV": "ADV",
    "ADP": "ADP", "DET": "DET", "PRON": "PRON", "CCONJ": "CCONJ",
    "SCONJ": "CCONJ", "INTJ": "INTJ", "NUM": "NUM", "PART": "PART",
    "AUX": "VERB",
}

_TRUSTED_FILTER_POS = {"VERB", "NOUN", "ADJ", "ADV", "INTJ"}
TRUSTED_FILTER_POS = _TRUSTED_FILTER_POS  # public alias for per-example filtering

# POS labels that are orthogonal to grammatical categories — they are never
# filtered out by observed-POS narrowing because senses of these types (e.g.
# idiomatic phrases, contractions) can apply regardless of the surface word's
# POS in context.
_ORTHOGONAL_POS = {"PHRASE", "CONTRACTION"}

_NLP = None
_NLP_MODEL = None
_NLP_FAILED = False


def load_spacy(preferred_models=None):
    """Load spaCy lazily. Returns None if no Spanish model is installed."""
    global _NLP, _NLP_MODEL, _NLP_FAILED
    preferred_models = preferred_models or [
        "es_dep_news_trf",
        "es_core_news_md",
        "es_core_news_lg",
        "es_core_news_sm",
    ]
    if _NLP is not None:
        if _NLP_MODEL in preferred_models:
            return _NLP
        _NLP = None
        _NLP_MODEL = None
    if _NLP_FAILED:
        return None
    try:
        import spacy
        for model in preferred_models:
            try:
                _NLP = spacy.load(model, disable=["ner"])
                _NLP_MODEL = model
                return _NLP
            except OSError:
                continue
    except Exception:
        pass
    _NLP_FAILED = True
    return None


def tag_examples(nlp, word, lemma, examples):
    """Return example-index -> mapped POS for occurrences of the target word."""
    results = {}
    word_lower = word.lower()
    lemma_lower = lemma.lower()

    texts = []
    idx_map = []
    for ei, ex in enumerate(examples):
        text = ex.get("target", ex.get("spanish", ""))
        if text:
            # Replace elided surface form with canonical word for better spaCy tagging
            surface = ex.get("surface")
            if surface and surface.lower() != word_lower:
                text = re.sub(re.escape(surface), word, text, count=1, flags=re.IGNORECASE)
            texts.append(text)
            idx_map.append(ei)

    for doc, ei in zip(nlp.pipe(texts, batch_size=64), idx_map):
        for token in doc:
            tok_lower = token.text.lower()
            lem_lower = token.lemma_.lower()
            if tok_lower == word_lower or lem_lower == lemma_lower or lem_lower == word_lower:
                mapped = _SPACY_POS_MAP.get(token.pos_)
                if mapped:
                    results[ei] = mapped
                break
    return results


def filter_senses_by_pos(word, lemma, senses, examples):
    """Return (keep_indices, stats_dict) after POS-based menu narrowing."""
    keep_indices = list(range(len(senses)))
    nlp = load_spacy()
    if not nlp or len(senses) < 2 or not examples:
        return keep_indices, {"used": False}

    pos_tags = tag_examples(nlp, word, lemma, examples)
    if not pos_tags:
        return keep_indices, {"used": False, "tagged_examples": 0}

    observed = {pos for pos in pos_tags.values() if pos}
    if not observed:
        return keep_indices, {"used": False, "tagged_examples": len(pos_tags)}

    trusted_observed = observed & _TRUSTED_FILTER_POS
    trusted_menu = {sense.get("pos") for sense in senses if sense.get("pos") in _TRUSTED_FILTER_POS}
    if not trusted_observed or not trusted_menu:
        return keep_indices, {
            "used": True,
            "tagged_examples": len(pos_tags),
            "observed_pos": sorted(observed),
            "reduced": False,
            "reason": "untrusted_pos_family",
        }

    # Keep senses whose POS was observed, and always keep orthogonal POS
    # tags like PHRASE (they are not tied to a grammatical category).
    filtered = [i for i, sense in enumerate(senses)
                if sense.get("pos") in trusted_observed
                or sense.get("pos") in _ORTHOGONAL_POS]
    if not filtered:
        return keep_indices, {
            "used": True,
            "tagged_examples": len(pos_tags),
            "observed_pos": sorted(observed),
            "reduced": False,
        }

    pos_counts = Counter(pos_tags.values())
    return filtered, {
        "used": True,
        "tagged_examples": len(pos_tags),
        "observed_pos": sorted(observed),
        "dominant_pos": pos_counts.most_common(1)[0][0],
        "reduced": len(filtered) < len(senses),
    }


def filter_senses_by_precomputed_pos(senses, example_pos):
    """Return (keep_indices, stats_dict) using precomputed example POS tags."""
    keep_indices = list(range(len(senses)))
    if len(senses) < 2 or not example_pos:
        return keep_indices, {"used": False}

    observed = {pos for pos in example_pos.values() if pos}
    if not observed:
        return keep_indices, {"used": False, "tagged_examples": len(example_pos)}

    trusted_observed = observed & _TRUSTED_FILTER_POS
    trusted_menu = {sense.get("pos") for sense in senses if sense.get("pos") in _TRUSTED_FILTER_POS}
    if not trusted_observed or not trusted_menu:
        return keep_indices, {
            "used": True,
            "tagged_examples": len(example_pos),
            "observed_pos": sorted(observed),
            "reduced": False,
            "reason": "untrusted_pos_family",
        }

    # Keep senses whose POS was observed, and always keep orthogonal POS
    # tags like PHRASE (they are not tied to a grammatical category).
    filtered = [i for i, sense in enumerate(senses)
                if sense.get("pos") in trusted_observed
                or sense.get("pos") in _ORTHOGONAL_POS]
    if not filtered:
        return keep_indices, {
            "used": True,
            "tagged_examples": len(example_pos),
            "observed_pos": sorted(observed),
            "reduced": False,
        }

    pos_counts = Counter(example_pos.values())
    return filtered, {
        "used": True,
        "tagged_examples": len(example_pos),
        "observed_pos": sorted(observed),
        "dominant_pos": pos_counts.most_common(1)[0][0],
        "reduced": len(filtered) < len(senses),
    }
