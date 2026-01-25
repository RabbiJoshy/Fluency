import json

INPUT_JSON = "Data/Spanish/vocabulary.json"
OUT_TSV = "Data/Spanish/targets_nonfirst_missing_meanings_or_freqs_reverse.tsv"

def is_nonfirst(entry: dict) -> bool:
    return entry.get("most_frequent_lemma_instance") is not True

def meanings_missing_or_empty(entry: dict) -> bool:
    meanings = entry.get("meanings", None)
    return (meanings is None) or (isinstance(meanings, list) and len(meanings) == 0)

def has_missing_frequency_in_meanings(entry: dict) -> bool:
    meanings = entry.get("meanings", None)
    if not isinstance(meanings, list) or len(meanings) == 0:
        return False
    for m in meanings:
        freq = m.get("frequency", None)
        if freq is None:
            return True
        if isinstance(freq, str) and freq.strip() == "":
            return True
    return False

def needs_work(entry: dict) -> bool:
    return meanings_missing_or_empty(entry) or has_missing_frequency_in_meanings(entry)

with open(INPUT_JSON, "r", encoding="utf-8") as f:
    data = json.load(f)

rows = []
seen = set()
dupes = []

for e in data:
    if not is_nonfirst(e):
        continue
    if not needs_work(e):
        continue

    rank = e.get("rank", "")
    word = (e.get("word") or "").strip().replace("\t", " ")
    lemma = (e.get("lemma") or "").strip().replace("\t", " ")

    key = (str(rank).strip(), word, lemma)
    if key in seen:
        dupes.append(key)
        continue
    seen.add(key)
    rows.append(key)

# ---- REVERSE rank order ----
def rank_sort_key_desc(rwl):
    r = rwl[0]
    try:
        return (0, -int(r))   # numeric rank, descending
    except Exception:
        return (1, r)        # non-numeric ranks last

rows.sort(key=rank_sort_key_desc)

with open(OUT_TSV, "w", encoding="utf-8") as f:
    f.write("rank\tword\tlemma\n")
    for rank, word, lemma in rows:
        f.write(f"{rank}\t{word}\t{lemma}\n")

print(f"Exported {len(rows)} rows to {OUT_TSV} (reverse rank order)")
if dupes:
    print(f"WARNING: {len(dupes)} duplicate (rank,word,lemma) skipped. First 10:")
    for d in dupes[:10]:
        print("  DUP:", d)
