# merge_existing_with_6001_10000.py
# Merge existing vocabulary.json (1..6000) with your already-generated 6001..10000 JSON.
# Recompute most_frequent_lemma_instance for 6001..10000 entries using lemma preference learned from top 6000.

import json
import os
from collections import defaultdict

# --------- EDIT THESE PATHS ----------
EXISTING_JSON = "Data/Spanish/vocabulary.json"             # ranks 1..6000 (source of truth for preferred lemma)
NEW_6001_10000_JSON = "Data/Spanish/vocab_6001_10000.json" # <-- set this to the file you already generated earlier
OUTPUT_JSON = "Data/Spanish/vocabulary_merged_10000.json"
# ------------------------------------


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def build_preferred_lemma_map(existing_vocab: list, top_n_rank: int = 6000) -> dict:
    """
    Build word -> preferred lemma using the existing vocab up to rank 6000.
    Preference rule: for each word, take lemma where most_frequent_lemma_instance == True (first seen).
    """
    preferred = {}

    for e in existing_vocab:
        try:
            r = int(e.get("rank", 10**9))
        except Exception:
            continue
        if r > top_n_rank:
            continue

        word = str(e.get("word", "")).strip()
        lemma = str(e.get("lemma", "")).strip()
        if not word or not lemma:
            continue

        if e.get("most_frequent_lemma_instance") is True and word not in preferred:
            preferred[word] = lemma

    return preferred


def fix_most_frequent_flags_for_new_entries(new_entries: list, preferred_lemma_by_word: dict) -> list:
    """
    For each word in new_entries:
      - If word exists in preferred_lemma_by_word, mark ONLY the entry with that lemma as True, others False.
      - If word not in preferred map:
          - Keep existing flags if any True exists for that word in new_entries,
            otherwise set the first occurrence per word to True.
    """
    grouped = defaultdict(list)
    for idx, e in enumerate(new_entries):
        word = str(e.get("word", "")).strip()
        grouped[word].append((idx, e))

    for word, items in grouped.items():
        preferred = preferred_lemma_by_word.get(word)

        if preferred is not None:
            # Set exactly one True: lemma == preferred
            found_true = False
            for _, e in items:
                lemma = str(e.get("lemma", "")).strip()
                is_true = (lemma == preferred) and (not found_true)
                e["most_frequent_lemma_instance"] = is_true
                if is_true:
                    found_true = True

            # If preferred lemma wasn't present in new entries, fall back:
            if not found_true:
                # Make first entry True, rest False
                for j, (_, e) in enumerate(items):
                    e["most_frequent_lemma_instance"] = (j == 0)

        else:
            # No preference known from top-6000.
            # If any entry already True, keep as-is. Otherwise set first to True.
            any_true = any(e.get("most_frequent_lemma_instance") is True for _, e in items)
            if not any_true:
                for j, (_, e) in enumerate(items):
                    e["most_frequent_lemma_instance"] = (j == 0)

    return new_entries


def main():
    existing = load_json(EXISTING_JSON)
    new_entries = load_json(NEW_6001_10000_JSON)

    preferred_lemma_by_word = build_preferred_lemma_map(existing, top_n_rank=6000)

    # Only adjust flags in the new set
    new_entries = fix_most_frequent_flags_for_new_entries(new_entries, preferred_lemma_by_word)

    merged = list(existing) + list(new_entries)

    # Stable sort
    merged.sort(key=lambda x: (int(x.get("rank", 10**9)), str(x.get("word", "")), str(x.get("lemma", ""))))

    save_json(OUTPUT_JSON, merged)

    print("✅ Merge complete")
    print(f"   Existing entries: {len(existing)}")
    print(f"   New entries:      {len(new_entries)}")
    print(f"   Total merged:     {len(merged)}")
    print(f"   Wrote:            {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
