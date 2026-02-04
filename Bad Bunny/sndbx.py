import json
import unicodedata
import re
from collections import Counter, defaultdict
from typing import Optional

# Load the JSON file
with open('Data/Spanish/vocabulary.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# ---------------- helpers ----------------

def normalize(s: str) -> str:
    """Lowercase + remove accents/diacritics."""
    s = s.strip().lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")

def split_english_glosses(translation: str) -> list:
    """Split English glosses safely."""
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

def obvious_match(spanish: str, english: str):
    """
    Return (tier, rule) or (None, None)
    """
    s = normalize(spanish)
    e = normalize(english)

    if len(s) < 4 or len(e) < 4:
        return None, None

    s0 = strip_plural(s)
    e0 = strip_plural(e)

    # ---------- OBVIOUS ----------
    if s0 == e0:
        return "OBVIOUS", "exact_or_plural"

    s_cion = apply_suffix(s0, "cion", "tion")
    if s_cion and s_cion == e0:
        return "OBVIOUS", "cion->tion"

    s_ista = apply_suffix(s0, "ista", "ist")
    if s_ista and s_ista == e0:
        return "OBVIOUS", "ista->ist"

    # ---------- STRONG ----------
    s_dad = apply_suffix(s0, "dad", "ty")
    if s_dad and s_dad == e0:
        return "STRONG", "dad->ty"

    s_mente = apply_suffix(s0, "mente", "ly")
    if s_mente and s_mente == e0:
        return "STRONG", "mente->ly"

    s_oso = apply_suffix(s0, "oso", "ous")
    if s_oso and s_oso == e0:
        return "STRONG", "oso->ous"

    s_osa = apply_suffix(s0, "osa", "ous")
    if s_osa and s_osa == e0:
        return "STRONG", "osa->ous"

    return None, None

# ---------------- run ----------------

seen_pairs = set()
counts_by_tier = Counter()
counts_by_rule = Counter()

for entry in data:
    spanish_word = entry.get("word", "")
    if not spanish_word:
        continue

    for meaning in entry.get("meanings", []):
        translation = meaning.get("translation", "")
        for eng in split_english_glosses(translation):

            tier, rule = obvious_match(spanish_word, eng)
            if not tier:
                continue

            key = (normalize(spanish_word), normalize(eng))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)

            counts_by_tier[tier] += 1
            counts_by_rule[rule] += 1

            print(f"[{tier:7}] {spanish_word}  ->  {eng}   ({rule})")

print("\n" + "-" * 40)
print("TOTAL MATCHES:", sum(counts_by_tier.values()))

print("BY TIER:")
for t in ("OBVIOUS", "STRONG"):
    print(f"  {t:7}: {counts_by_tier[t]}")

print("BY RULE:")
for rule, c in counts_by_rule.most_common():
    print(f"  {rule:15}: {c}")
