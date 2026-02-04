import json
import unicodedata
import re
from typing import Optional

# ---------------- helpers ----------------

def normalize(s: str) -> str:
    s = s.lower().strip()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

def strip_plural(w: str) -> str:
    if len(w) >= 5 and w.endswith("es"):
        return w[:-2]
    if len(w) >= 4 and w.endswith("s"):
        return w[:-1]
    return w

def apply_suffix(w: str, src: str, dst: str) -> Optional[str]:
    if w.endswith(src) and len(w) > len(src):
        return w[:-len(src)] + dst
    return None

def split_english_glosses(translation: str) -> list:
    if not translation:
        return []

    t = translation.lower()
    t = re.sub(r"\([^)]*\)", "", t)
    parts = [p.strip() for p in t.split("/") if p.strip()]

    out = []
    for p in parts:
        for tok in re.split(r"\s+", p):
            if tok.isalpha():
                out.append(tok)
    return out

def is_transparent_cognate(spanish: str, english: str) -> bool:
    s = normalize(spanish)
    e = normalize(english)

    if len(s) < 4 or len(e) < 4:
        return False

    s0 = strip_plural(s)
    e0 = strip_plural(e)

    # exact / plural
    if s0 == e0:
        return True

    # safe suffix rules
    if apply_suffix(s0, "cion", "tion") == e0:
        return True
    if apply_suffix(s0, "ista", "ist") == e0:
        return True

    # strong-but-safe rules
    if apply_suffix(s0, "dad", "ty") == e0:
        return True
    if apply_suffix(s0, "mente", "ly") == e0:
        return True
    if apply_suffix(s0, "oso", "ous") == e0:
        return True
    if apply_suffix(s0, "osa", "ous") == e0:
        return True

    return False

# ---------------- main updater ----------------

def add_transparent_flag(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for entry in data:
        spanish_word = entry.get("word", "") or entry.get("lemma", "")
        entry["is_transparent_cognate"] = False

        if not spanish_word:
            continue

        for meaning in entry.get("meanings", []):
            translation = meaning.get("translation", "")
            for eng in split_english_glosses(translation):
                if is_transparent_cognate(spanish_word, eng):
                    entry["is_transparent_cognate"] = True
                    break
            if entry["is_transparent_cognate"]:
                break

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Updated: {path}")

# ---------------- run on both files ----------------

add_transparent_flag("Data/Spanish/vocabulary.json")
add_transparent_flag("Bad Bunny/BadBunnyvocabulary.json")
