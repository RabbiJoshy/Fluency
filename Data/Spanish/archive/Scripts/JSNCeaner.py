import json
from pathlib import Path
from typing import Any, Dict, Tuple

IN_JSON_PATH = "Data/Spanish/vocabulary.filtered_deduped_prefer_meanings.json"
OUT_JSON_PATH = "Data/Spanish/vocabulary.with_most_frequent_lemma_instance.json"

def norm_lemma(word: str, lemma: str) -> str:
    word = (word or "").strip()
    lemma = (lemma or "").strip()
    return lemma if lemma else word

def meanings_count(entry: Dict[str, Any]) -> int:
    m = entry.get("meanings")
    return len(m) if isinstance(m, list) else 0

def rank_value(entry: Dict[str, Any]) -> int:
    r = entry.get("rank")
    # ranks should be ints; fall back high if missing/bad
    return r if isinstance(r, int) else 10**12

# ---- Load JSON ----
with open(IN_JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

if not isinstance(data, list):
    raise ValueError("Expected the JSON to be a list of entries.")

# ---- Choose winner per lemma ----
# winner_map[lemma] = (rank, -meanings_count, index, entry)
winner_map: Dict[str, Tuple[int, int, int, Dict[str, Any]]] = {}

for idx, entry in enumerate(data):
    w = (entry.get("word") or "").strip()
    l = norm_lemma(w, entry.get("lemma") or "")
    r = rank_value(entry)
    mc = meanings_count(entry)

    # Lower rank wins. If tie, more meanings wins. If tie, earlier index wins.
    key = (r, -mc, idx)

    if l not in winner_map:
        winner_map[l] = (r, -mc, idx, entry)
    else:
        if key < (winner_map[l][0], winner_map[l][1], winner_map[l][2]):
            winner_map[l] = (r, -mc, idx, entry)

# ---- Annotate all entries ----
for entry in data:
    # Optionally clear older fields to avoid confusion
    entry.pop("duplicate", None)
    entry.pop("duplicate_lemma", None)

    w = (entry.get("word") or "").strip()
    l = norm_lemma(w, entry.get("lemma") or "")
    entry["most_frequent_lemma_instance"] = (winner_map[l][3] is entry)

# ---- Write JSON ----
Path(OUT_JSON_PATH).parent.mkdir(parents=True, exist_ok=True)
with open(OUT_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

# ---- Basic summary ----
true_count = sum(1 for e in data if e.get("most_frequent_lemma_instance") is True)
print(f"Entries: {len(data):,}")
print(f"Lemmas (winners): {len(winner_map):,}")
print(f"most_frequent_lemma_instance == true: {true_count:,}")
print(f"Wrote: {OUT_JSON_PATH}")
