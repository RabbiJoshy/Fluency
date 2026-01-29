import json
import unicodedata
import re

# ---------- helpers ----------

def normalize(w):
    if not isinstance(w, str):
        return ""
    return "".join(
        c for c in unicodedata.normalize("NFD", w.lower())
        if unicodedata.category(c) != "Mn"
    )

COMMON_LATIN_SUFFIXES = (
    "tion", "sion", "al", "ico", "ica", "ismo", "ista",
    "mento", "able", "ible", "ante", "ente", "idad"
)

ENGLISHISH_PATTERN = re.compile(r"^[a-z]{4,}$")

def looks_englishish(word):
    w = normalize(word)

    if not ENGLISHISH_PATTERN.match(w):
        return False

    for suf in COMMON_LATIN_SUFFIXES:
        if w.endswith(suf):
            return True

    # very common transparent cognates
    if w in {
        "hotel", "doctor", "animal", "capital", "normal",
        "social", "legal", "final", "total", "natural",
        "hospital", "central", "general"
    }:
        return True

    return False

def is_probably_proper_noun(entry):
    # robust against missing fields
    cap = entry.get("capitalized_count", 0)
    low = entry.get("lowercase_count", 0)

    if cap > 5 and cap > 5 * low:
        return True

    word = entry.get("word", "")
    return isinstance(word, str) and word[:1].isupper()

# ---------- load data ----------

with open("Data/Spanish/vocabulary.json", "r", encoding="utf-8") as f:
    vocab = json.load(f)

# assume list of dicts
# higher frequency first
vocab = sorted(
    vocab,
    key=lambda x: x.get("occurrences_ppm", 0),
    reverse=True
)

# take top 1000
top = vocab[:]

# ---------- detect trivial words ----------

trivial = []

for entry in top:
    word = entry.get("word", "")

    proper = is_probably_proper_noun(entry)
    cognate = looks_englishish(word)

    if proper or cognate:
        trivial.append({
            "rank": entry.get("rank"),
            "word": word,
            "occurrences_ppm": entry.get("occurrences_ppm"),
            "proper": proper,
            "cognate": cognate
        })

# ---------- print examples ----------

print(f"Found {len(trivial)} trivial words in top 1000:\n")

for t in trivial[:1000]:
    flags = []
    if t["proper"]:
        flags.append("PROPER")
    if t["cognate"]:
        flags.append("COGNATE")

    print(
        f'{t["rank"]:>4} | {t["word"]:<15} '
        f'| {", ".join(flags)}'
    )
