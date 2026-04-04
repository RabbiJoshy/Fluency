import difflib
import json
import os
import unicodedata
import re
from pathlib import Path
from typing import Optional

# Minimum similarity (after normalize + strip_plural) for near-identical fallback.
# 0.85 is intentionally conservative to avoid false positives on short words.
_NEAR_IDENTICAL_THRESHOLD = 0.85

# ---------------- helpers ----------------

def normalize(s: str) -> str:
    """Lowercase + strip accents."""
    s = s.lower().strip()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def strip_plural(w: str) -> str:
    """Remove common plural suffixes (Spanish & English)."""
    # Spanish -ces → -z  (voces→voz, veces→vez)
    if len(w) >= 4 and w.endswith("ces"):
        return w[:-3] + "z"
    if len(w) >= 5 and w.endswith("es"):
        return w[:-2]
    if len(w) >= 4 and w.endswith("s"):
        return w[:-1]
    return w


def apply_suffix(w: str, src: str, dst: str) -> Optional[str]:
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


def split_english_glosses(translation: str) -> list[str]:
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


def is_transparent_cognate(spanish: str, english: str) -> bool:
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
    # where no suffix rule produces an exact match but the words are visually
    # close enough that a learner would immediately recognise them as the same.
    ratio = difflib.SequenceMatcher(None, s0, e0).ratio()
    if ratio >= _NEAR_IDENTICAL_THRESHOLD:
        return True

    return False


# ---------------- main updater ----------------

def _suffix_rule_says_cognate(entry):
    """Check if suffix rules / similarity detect a cognate."""
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


def add_transparent_flag(path: str, intersection_mode: bool = False):
    """
    Flag transparent cognates.

    intersection_mode=False (default): suffix rules are authoritative (for non-LLM vocab).
    intersection_mode=True: only flag if BOTH LLM and suffix rules agree (for LLM-processed vocab).
    """
    p = Path(path)
    if not p.exists():
        print(f"  Skipping (not found): {path}")
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    count_before = sum(1 for e in data if e.get("is_transparent_cognate"))
    count_after = 0
    llm_only = 0
    suffix_only = 0

    for entry in data:
        llm_flag = entry.get("is_transparent_cognate", False)
        suffix_flag = _suffix_rule_says_cognate(entry)

        if intersection_mode:
            # Both must agree
            entry["is_transparent_cognate"] = llm_flag and suffix_flag
            if llm_flag and not suffix_flag:
                llm_only += 1
            if suffix_flag and not llm_flag:
                suffix_only += 1
        else:
            # Suffix rules only (no LLM data)
            entry["is_transparent_cognate"] = suffix_flag

        if entry["is_transparent_cognate"]:
            count_after += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  {path}: {count_after} cognates flagged (was {count_before})")
    if intersection_mode:
        print(f"    LLM-only (dropped): {llm_only}, suffix-only (dropped): {suffix_only}")


# ---------------- main ----------------

def main():
    import argparse
    from _artist_config import add_artist_arg, load_artist_config

    parser = argparse.ArgumentParser(description="Step 7: Flag transparent cognates")
    add_artist_arg(parser)
    args = parser.parse_args()

    artist_dir = os.path.abspath(args.artist_dir)
    config = load_artist_config(artist_dir)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    print("=== Suffix rules only (no LLM data) ===")
    add_transparent_flag(os.path.join(project_root, "Data", "Spanish", "vocabulary.json"), intersection_mode=False)
    print("\n=== Intersection mode (LLM + suffix rules must agree) ===")
    add_transparent_flag(os.path.join(artist_dir, config["vocabulary_file"]), intersection_mode=True)


if __name__ == "__main__":
    main()
