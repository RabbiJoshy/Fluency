"""
Shared cognate detection logic used by both artist and normal-mode pipelines.

Detects transparent Spanish-English cognates via:
1. Suffix transformation rules (ción→tion, dad→ty, etc.)
2. Near-identical string similarity fallback (≥0.85)

Two modes:
- Suffix-only: for normal mode (no LLM data available)
- Intersection: for artist mode (both LLM flag and suffix rules must agree)
"""

import difflib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Optional

# Minimum similarity (after normalize + strip_plural) for near-identical fallback.
# 0.85 is intentionally conservative to avoid false positives on short words.
_NEAR_IDENTICAL_THRESHOLD = 0.85

# ---------------- helpers ----------------

def normalize(s):
    # type: (str) -> str
    """Lowercase + strip accents."""
    s = s.lower().strip()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def strip_plural(w):
    # type: (str) -> str
    """Remove common plural suffixes (Spanish & English)."""
    # Spanish -ces → -z  (voces→voz, veces→vez)
    if len(w) >= 4 and w.endswith("ces"):
        return w[:-3] + "z"
    if len(w) >= 5 and w.endswith("es"):
        return w[:-2]
    if len(w) >= 4 and w.endswith("s"):
        return w[:-1]
    return w


def apply_suffix(w, src, dst):
    # type: (str, str, str) -> Optional[str]
    if w.endswith(src) and len(w) > len(src):
        return w[:-len(src)] + dst
    return None


# Suffix mapping: (spanish_suffix, english_suffix)
# Order matters — more specific suffixes first to avoid partial matches
SUFFIX_RULES = [
    # -ción / -sión → -tion / -sion
    ("cion", "tion"),
    ("sion", "sion"),
    # -ancia / -encia → -ance / -ence
    ("ancia", "ance"),
    ("encia", "ence"),
    # -mente → -ly
    ("mente", "ly"),
    # -ismo → -ism
    ("ismo", "ism"),
    # -ista → -ist
    ("ista", "ist"),
    # -ivo / -iva → -ive
    ("ivo", "ive"),
    ("iva", "ive"),
    # -oso / -osa → -ous
    ("oso", "ous"),
    ("osa", "ous"),
    # -ico / -ica → -ic
    ("ico", "ic"),
    ("ica", "ic"),
    # -dad → -ty  (universidad→university, realidad→reality)
    ("idad", "ity"),
    ("dad", "ty"),
    # -ente / -ante → -ent / -ant
    ("ente", "ent"),
    ("ante", "ant"),
    # -ia / -ía → -y  (democracia→democracy, energía→energy)
    ("ia", "y"),
    # -ario / -aria → -ary
    ("ario", "ary"),
    ("aria", "ary"),
    # -ura → -ure  (cultura→culture, estructura→structure)
    ("ura", "ure"),
    # -or → -or  (exact, but catches actor, color, etc.)
    ("or", "or"),
    # -al → -al  (usually exact after plural strip, but just in case)
    ("al", "al"),
    # -ble → -ble  (usually exact)
    ("ble", "ble"),
]


def split_english_glosses(translation):
    # type: (str) -> list
    """
    Extract candidate English words/phrases from a translation string.
    Returns both individual tokens AND multi-word phrases.
    e.g. "ice cream / gelato" → ["ice cream", "gelato", "ice", "cream"]
    """
    if not translation:
        return []

    t = translation.lower()
    # Strip parenthetical notes like "(informal)"
    t = re.sub(r"\([^)]*\)", "", t)
    # Split on / and , as gloss separators
    parts = [p.strip() for p in re.split(r"[/,]", t) if p.strip()]

    out = []
    for p in parts:
        # Add the full phrase first (for multi-word cognates)
        clean = " ".join(tok for tok in p.split() if tok.isalpha())
        if clean:
            out.append(clean)
        # Then add individual tokens
        for tok in p.split():
            if tok.isalpha() and tok not in out:
                out.append(tok)
    return out


def is_transparent_cognate(spanish, english):
    # type: (str, str) -> bool
    s = normalize(spanish)
    e = normalize(english)

    if len(s) < 4 or len(e) < 4:
        return False

    s0 = strip_plural(s)
    e0 = strip_plural(e)

    # exact / plural match
    if s0 == e0:
        return True

    # Try all suffix rules (exact stem transform).
    # Check against both e (original) and e0 (de-pluraled) because strip_plural
    # can incorrectly strip a terminal 's' that's part of the word itself
    # (e.g. "famous" → "famou"), so we need to also compare against the
    # pre-strip form to catch cases like famoso → famous.
    for es_suffix, en_suffix in SUFFIX_RULES:
        result = apply_suffix(s0, es_suffix, en_suffix)
        if result is not None and (result == e0 or result == e):
            return True

    # Near-identical fallback: catches cases like espectacular → spectacular,
    # imposible → impossible, profesión → profession (double-s mismatch), etc.
    ratio = difflib.SequenceMatcher(None, s0, e0).ratio()
    if ratio >= _NEAR_IDENTICAL_THRESHOLD:
        return True

    return False


# ---------------- entry-level detection ----------------

def suffix_rule_says_cognate(entry):
    """Check if suffix rules / similarity detect a cognate for a vocab entry.

    Entry must have 'word', optionally 'lemma', and 'meanings' list
    where each meaning has a 'translation' field.
    """
    candidates = set()
    word = entry.get("word", "")
    lemma = entry.get("lemma", "")
    if word:
        candidates.add(word)
    if lemma and lemma != word:
        candidates.add(lemma)

    if not candidates:
        return False

    for meaning in entry.get("meanings", []):
        translation = meaning.get("translation", "")
        for eng in split_english_glosses(translation):
            for sp in candidates:
                if is_transparent_cognate(sp, eng):
                    return True
    return False


# ---------------- layer writers ----------------

def detect_cognates_from_senses(senses_data, output_path):
    """Detect cognates from a senses layer (Wiktionary or Gemini), write cognates.json.

    Uses suffix rules only (no intersection mode). Suitable for normal mode
    or any pipeline without LLM cognate flags.

    Args:
        senses_data: dict keyed by "word|lemma" with list of sense dicts
        output_path: where to write the cognates.json layer
    """
    cognate_layer = {}

    for key, sense_list in senses_data.items():
        word, lemma = key.split("|", 1) if "|" in key else (key, key)
        entry = {
            "word": word,
            "lemma": lemma,
            "meanings": [{"translation": s.get("translation", "")} for s in sense_list],
        }
        if suffix_rule_says_cognate(entry):
            cognate_layer[key] = True

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cognate_layer, f, ensure_ascii=False)

    print("  %d cognates flagged (suffix rules only)" % len(cognate_layer))
    print("  -> %s" % output_path)
    return cognate_layer


def detect_cognates_from_layers(layers_dir, master_path=None):
    """Detect cognates from senses_gemini.json layer, write cognates.json layer.

    Uses intersection mode: both LLM flag (from master) and suffix rules must agree.
    Used by artist pipeline.

    Args:
        layers_dir: path to the artist's data/layers/ directory
        master_path: path to vocabulary_master.json (auto-detected if None)
    """
    senses_path = os.path.join(layers_dir, "senses_gemini.json")
    if not os.path.isfile(senses_path):
        print("  Skipping (senses_gemini.json not found)")
        return

    with open(senses_path, "r", encoding="utf-8") as f:
        senses_data = json.load(f)

    # Load master for LLM flags
    if master_path is None:
        # Default: Artists/vocabulary_master.json relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        master_path = os.path.join(project_root, "Artists", "vocabulary_master.json")

    master = {}
    if os.path.isfile(master_path):
        with open(master_path, "r", encoding="utf-8") as f:
            master = json.load(f)
    # Build word|lemma -> master entry lookup
    wl_to_master = {}
    for mid, m in master.items():
        wl_to_master["%s|%s" % (m["word"], m["lemma"])] = m

    cognate_layer = {}
    llm_only = 0
    suffix_only = 0

    for key, sense_list in senses_data.items():
        word, lemma = key.split("|", 1) if "|" in key else (key, key)

        # Build a fake entry for suffix_rule_says_cognate
        entry = {
            "word": word,
            "lemma": lemma,
            "meanings": [{"translation": s.get("translation", "")} for s in sense_list],
        }
        suffix_flag = suffix_rule_says_cognate(entry)

        # LLM flag from master
        m = wl_to_master.get(key)
        llm_flag = m.get("is_transparent_cognate", False) if m else False

        # Intersection: both must agree
        is_cognate = llm_flag and suffix_flag
        if llm_flag and not suffix_flag:
            llm_only += 1
        if suffix_flag and not llm_flag:
            suffix_only += 1

        if is_cognate:
            cognate_layer[key] = True

    os.makedirs(layers_dir, exist_ok=True)
    layer_path = os.path.join(layers_dir, "cognates.json")
    with open(layer_path, "w", encoding="utf-8") as f:
        json.dump(cognate_layer, f, ensure_ascii=False)

    print("  %d cognates flagged (intersection mode)" % len(cognate_layer))
    print("    LLM-only (dropped): %d, suffix-only (dropped): %d" % (llm_only, suffix_only))
    print("  -> %s" % layer_path)
    return cognate_layer
