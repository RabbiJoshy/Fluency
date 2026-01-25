import json

INPUT_JSON = "Data/Spanish/vocabulary.json"
LLM_TSV = "Data/Spanish/caudeoutput.tsv"              # <- put the model TSV output here
OUT_JSON = "Data/Spanish/vocabulary2.json"

ALLOWED_POS = {
    "NOUN","VERB","ADJ","ADV","PREP","PRON","DET","CONJ","INTJ","PROPN","PART","AUX","NUM"
}

def is_target(entry: dict) -> bool:
    # Only non-first instances
    if entry.get("most_frequent_lemma_instance") is True:
        return False

    meanings = entry.get("meanings", None)

    # Missing meanings entirefly / empty
    if meanings is None or (isinstance(meanings, list) and len(meanings) == 0):
        return True

    # Meanings exist but some meaning has missing frequency
    if isinstance(meanings, list):
        for m in meanings:
            freq = m.get("frequency", None)
            if freq is None:
                return True
            if isinstance(freq, str) and freq.strip() == "":
                return True

    return False


def clean_cell(x: str) -> str:
    return (x or "").strip()

def parse_meanings_compact(s: str):
    """
    Parses: POS|translation|freq;POS|translation|freq
    Returns list[dict] in your schema, with empty examples.
    """
    s = (s or "").strip()
    if not s:
        return []

    out = []
    for chunk in s.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split("|")]
        if len(parts) != 3:
            continue
        pos, translation, freq = parts
        if pos not in ALLOWED_POS:
            continue
        if not translation or not freq:
            continue
        out.append({
            "pos": pos,
            "translation": translation,
            "frequency": freq,
            "example_spanish": "",
            "example_english": ""
        })
    return out

def load_llm_map(path: str):
    """
    Reads *space-separated* output with header:
      rank word lemma meanings
    Where meanings contains no spaces (uses ; and |).
    Returns dict[(rank,word,lemma)] -> meanings_list
    """
    mapping = {}
    dupes = []
    bad_lines = 0

    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            # Skip header (space-separated)
            if line_no == 1 and line.lower().startswith("rank "):
                continue

            # Split into 4 fields: rank, word, lemma, meanings
            parts = line.split(None, 3)  # split on ANY whitespace, at most 4 columns
            if len(parts) < 4:
                bad_lines += 1
                continue

            rank = clean_cell(parts[0])
            word = clean_cell(parts[1])
            lemma = clean_cell(parts[2])
            meanings_str = parts[3].strip()

            key = (rank, word, lemma)
            meanings = parse_meanings_compact(meanings_str)

            if key in mapping:
                dupes.append(key)
                continue
            mapping[key] = meanings

    return mapping, dupes, bad_lines


with open(INPUT_JSON, "r", encoding="utf-8") as f:
    data = json.load(f)

# Build an index of target entries by (rank,word,lemma).
# Note: rank in JSON might be int; we normalize to str for matching.
target_index = {}
collisions = []

for i, e in enumerate(data):
    if not is_target(e):
        continue
    rank = e.get("rank", "")
    key = (str(rank).strip(), (e.get("word") or "").strip(), (e.get("lemma") or "").strip())
    if key in target_index:
        collisions.append(key)
        # keep the first occurrence to avoid surprising writes
        continue
    target_index[key] = i

llm_map, llm_dupes, bad_lines = load_llm_map(LLM_TSV)
print("Loaded llm_map rows:", len(llm_map))
print("Bad/short lines skipped:", bad_lines)


updated = 0
not_found = 0
blank_meanings = 0

for key, meanings in llm_map.items():
    if key not in target_index:
        not_found += 1
        continue

    if not meanings:
        blank_meanings += 1
        continue

    i = target_index[key]
    # Only touch meanings.
    data[i]["meanings"] = meanings
    updated += 1

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Updated meanings for {updated} entries.")
print(f"LLM rows not found in targets (rank/word/lemma mismatch): {not_found}")
print(f"LLM rows with blank/malformed meanings (skipped): {blank_meanings}")
if collisions:
    print(f"WARNING: {len(collisions)} collisions in JSON target_index (same rank/word/lemma). First 10:")
    for c in collisions[:10]:
        print("  COLLISION:", c)
if llm_dupes:
    print(f"WARNING: {len(llm_dupes)} duplicate keys in LLM output (skipped). First 10:")
    for d in llm_dupes[:10]:
        print("  LLM_DUP:", d)
print(f"Wrote {OUT_JSON}")
