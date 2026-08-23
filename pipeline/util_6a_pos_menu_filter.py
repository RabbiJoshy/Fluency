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
import unicodedata
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


def sense_compatible_with_observed(sense_pos, observed):
    """Decide whether a sense (by POS tag) is compatible with observed example POSes.

    Design principle: trust spaCy to reliably tag POS values in
    ``_TRUSTED_FILTER_POS`` (VERB/NOUN/ADJ/ADV/INTJ). Absence of a trusted POS
    in observed evidence is itself evidence the sense isn't applicable here.
    Untrusted POSes (ADP/DET/PRON/CCONJ/SCONJ/...) can be mis-tagged among
    themselves, so we only rule them out when no untrusted POS was observed
    at all.
    """
    if sense_pos in _ORTHOGONAL_POS:
        return True
    if sense_pos in observed:
        return True
    if sense_pos in _TRUSTED_FILTER_POS:
        # spaCy would reliably tag this POS; it wasn't observed → drop.
        return False
    # sense_pos is untrusted (or unknown). Keep only if we observed at least
    # one untrusted POS — otherwise every example was trusted-tagged and we
    # can rule out untrusted readings too.
    return bool(observed - _TRUSTED_FILTER_POS)


def sense_compatible_with_example_pos(sense_pos, ex_pos):
    """Per-example compatibility: is a sense allowed for an example tagged ex_pos?

    - If ex_pos is trusted, we trust it fully: keep only senses matching
      ex_pos exactly (plus orthogonal POSes).
    - If ex_pos is untrusted, we use it only to rule out trusted-POS senses:
      keep senses matching ex_pos, orthogonal POSes, and any untrusted-POS
      senses (since spaCy may confuse among the untrusted family).
    """
    if sense_pos in _ORTHOGONAL_POS:
        return True
    if sense_pos == ex_pos:
        return True
    if ex_pos in _TRUSTED_FILTER_POS:
        # Trust ex_pos — drop anything else.
        return False
    # ex_pos untrusted: only drop trusted mismatches.
    return sense_pos not in _TRUSTED_FILTER_POS


# ---------------------------------------------------------------------------
# Tagset bridge: spaCy is Universal Dependencies, SpanishDict is not
# ---------------------------------------------------------------------------
# SpanishDict publishes 17 DET senses in 96,279 and files determiners,
# demonstratives and possessives as ADJ. UD tags every one of them DET. Because
# ADJ is a TRUSTED filter POS and DET is not, `sense_compatible_with_example_pos`
# reads "tagged DET, sense is ADJ" as a trusted mismatch and deletes the correct
# sense -- on `esta`, `este`, `otro`, `mío`, `nuestros`, which are among the
# commonest words in the corpus.
#
# Measured on the 144-item labelled OpenSubtitles panel: the raw filter fires on
# 70 items and deletes every acceptable sense on 7 of them (10%), and SIX of
# those seven are this mismatch, not a tagging error. With the bridge it fires on
# 63 and kills 1 (2%), and the v5 stack goes 84.0% -> 86.8% (card gloss
# 84.7% -> 87.5%).
#
# This is why the POS filter was abandoned once before as "not good enough when
# I most needed it": determiners are exactly when you need it.
#
# Deliberately a SEPARATE function. step_6b, step_6c and step_8b call
# sense_compatible_with_example_pos and are tuned against its current behaviour;
# widening that in place would change three shipped classifiers as a side effect
# of fixing one.
_TAGSET_BRIDGE = {
    "DET":   {"ADJ", "DET", "PRON"},      # esta, este, otro, mío, nuestros
    "PRON":  {"PRON", "ADJ", "DET"},      # ésta/esta, mío as a pronoun
    "NUM":   {"ADJ", "NOUN", "DET"},      # SpanishDict has no NUM at all
    "PART":  {"ADV", "ADP", "PRON"},      # no PART either
    "PROPN": {"PROPN", "NOUN"},
    "ADV":   {"ADV", "PRON", "ADJ"},      # `poco` ADV vs SpanishDict PRON
    "AUX":   {"VERB", "AUX", "PHRASE"},   # haber, ser, estar, deber, saber
}
# AUX is the same mismatch as DET and was missed when DET was fixed. SpanishDict
# has no AUX category and files every auxiliary and modal as VERB; UD tags them
# AUX. Unbridged, `sense_compatible_with_example_pos` sees "tagged AUX, sense is
# VERB" as a trusted mismatch and rejects it -- and since it rejects NOUN too,
# it deletes the WHOLE menu on 11 of the 12 AUX items in the hard panel, so the
# empty-keep-set fallback fires and the filter is a silent no-op on exactly the
# commonest verbs in speech.
#
# Measured on the 200-item hard panel (pipeline/wsd_harness/panels/hard_200):
# the POS filter over the menu prior goes 67.3% -> 74.4% with this entry, +14
# items of 199. The AUX stratum alone goes 80.0% -> 85.7%.
#
# It is worth ~0 on the older 144-item OpenSubtitles panel (-1 item), which is
# why it reads as noise there: that panel has 12 AUX items and cannot resolve
# a 7pp effect. Do not re-measure this on the 144.


def sense_compatible_bridged(sense_pos, ex_pos):
    """Per-example compatibility across the UD / SpanishDict tagset boundary.

    Same contract as sense_compatible_with_example_pos, but a tag whose category
    SpanishDict does not use cannot delete the category SpanishDict uses instead.
    """
    if sense_pos in _ORTHOGONAL_POS:
        return True
    allowed = _TAGSET_BRIDGE.get(ex_pos)
    if allowed is not None:
        return sense_pos in allowed
    return sense_compatible_with_example_pos(sense_pos, ex_pos)


def _normalise_name(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def example_matches_credited_artist(word, example):
    """Whether the target token exactly names the credited line performer.

    Exact full-name matching is intentionally narrower than token membership:
    ``Boza`` matches artist ``Boza`` while ``bad`` does not match ``Bad Bunny``.
    This makes the signal safe as a deterministic veto for common-noun menu
    senses without turning ordinary words inside multiword stage names into
    proper nouns.
    """
    if not isinstance(example, dict):
        return False
    word_name = _normalise_name(word)
    artist_name = _normalise_name(example.get("artist"))
    return bool(word_name and artist_name and word_name == artist_name)


def auto_sense_rejection_reason(word, sense, example, example_pos=None):
    """Return a high-precision reason a single-menu sense must not auto-win."""
    sense_pos = str((sense or {}).get("pos") or "").strip().upper()
    ex_pos = str(example_pos or "").strip().upper()
    if ex_pos and not sense_compatible_with_example_pos(sense_pos, ex_pos):
        return "sense_pos_%s_conflicts_with_evidence_%s" % (sense_pos or "X", ex_pos)
    if example_matches_credited_artist(word, example) and sense_pos != "PROPN":
        return "common_noun_conflicts_with_credited_artist"
    return None

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

    filtered = [i for i, sense in enumerate(senses)
                if sense_compatible_with_observed(sense.get("pos"), observed)]
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

    filtered = [i for i, sense in enumerate(senses)
                if sense_compatible_with_observed(sense.get("pos"), observed)]
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
