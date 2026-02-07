import json
import unicodedata
import re
from pathlib import Path
from typing import Optional

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

    # Try all suffix rules
    for es_suffix, en_suffix in SUFFIX_RULES:
        result = apply_suffix(s0, es_suffix, en_suffix)
        if result is not None and result == e0:
            return True

    return False


# ---------------- main updater ----------------

def add_transparent_flag(path: str):
    p = Path(path)
    if not p.exists():
        print(f"⚠ Skipping (not found): {path}")
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    count_before = sum(1 for e in data if e.get("is_transparent_cognate"))
    count_after = 0

    for entry in data:
        # Check both word AND lemma against translations
        candidates = set()
        word = entry.get("word", "")
        lemma = entry.get("lemma", "")
        if word:
            candidates.add(word)
        if lemma and lemma != word:
            candidates.add(lemma)

        entry["is_transparent_cognate"] = False

        if not candidates:
            continue

        for meaning in entry.get("meanings", []):
            translation = meaning.get("translation", "")
            for eng in split_english_glosses(translation):
                for sp in candidates:
                    if is_transparent_cognate(sp, eng):
                        entry["is_transparent_cognate"] = True
                        break
                if entry["is_transparent_cognate"]:
                    break
            if entry["is_transparent_cognate"]:
                break

        if entry["is_transparent_cognate"]:
            count_after += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ {path}: {count_after} cognates flagged (was {count_before})")


# ---------------- run on both files ----------------

add_transparent_flag("Data/Spanish/vocabulary.json")
add_transparent_flag("Bad Bunny/BadBunnyvocabulary.json")
