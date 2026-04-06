import json
from pathlib import Path
from typing import Any, Dict, Tuple

# ============================================================
# CONFIGURATION
# ============================================================
LANGUAGE = "Dutch"  # Change this for other languages
IN_FILENAME = "vocabulary.json"
OUT_FILENAME = "vocabulary.json"
OUT_SUBDIR = "with_most_frequent_lemma_instance"
# ============================================================

current_dir = Path.cwd()

if current_dir.name == LANGUAGE and current_dir.parent.name == "Data":
    script_dir = current_dir
elif (current_dir / "Data" / LANGUAGE).exists():
    script_dir = current_dir / "Data" / LANGUAGE
else:
    script_dir = current_dir

print(f"Language: {LANGUAGE}")
print(f"Working directory: {script_dir}")

in_path = script_dir / IN_FILENAME
if not in_path.exists():
    print(f"ERROR: {in_path} not found!")
    raise SystemExit(1)

print(f"Loading: {in_path}")
with open(in_path, "r", encoding="utf-8") as f:
    vocab = json.load(f)

if not isinstance(vocab, list):
    raise ValueError("Expected vocabulary.json to be a JSON list of entries.")

print(f"Loaded {len(vocab):,} entries")

def norm_lemma(word: str, lemma: str) -> str:
    """If lemma is blank, treat lemma as word (your convention)."""
    word = (word or "").strip()
    lemma = (lemma or "").strip()
    return lemma if lemma else word

def meanings_count(entry: Dict[str, Any]) -> int:
    m = entry.get("meanings")
    return len(m) if isinstance(m, list) else 0

def rank_value(entry: Dict[str, Any]) -> int:
    r = entry.get("rank")
    return r if isinstance(r, int) else 10**12

# ---- Pick the most frequent instance per lemma ----
# Winner = lowest rank; tie-breaker = more meanings; then earliest entry.
winner_by_lemma: Dict[str, Tuple[int, int, int]] = {}  # lemma -> (rank, -meanings, index)

for idx, entry in enumerate(vocab):
    w = (entry.get("word") or "").strip()
    l = norm_lemma(w, entry.get("lemma") or "")
    key = (rank_value(entry), -meanings_count(entry), idx)

    if l not in winner_by_lemma or key < winner_by_lemma[l]:
        winner_by_lemma[l] = key

# ---- Annotate and delete legacy field ----
deleted_duplicate_field = 0
missing_word = 0

for idx, entry in enumerate(vocab):
    if "duplicate" in entry:
        del entry["duplicate"]
        deleted_duplicate_field += 1

    w = (entry.get("word") or "").strip()
    if not w:
        missing_word += 1

    l = norm_lemma(w, entry.get("lemma") or "")
    entry["most_frequent_lemma_instance"] = (winner_by_lemma.get(l) == (rank_value(entry), -meanings_count(entry), idx))

# ---- Write output ----
out_dir = script_dir / OUT_SUBDIR
out_dir.mkdir(exist_ok=True)

out_path = out_dir / OUT_FILENAME
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(vocab, f, ensure_ascii=False, indent=2)

true_count = sum(1 for e in vocab if e.get("most_frequent_lemma_instance") is True)

print("\n✓ Done!")
print(f"  Input entries: {len(vocab):,}")
print(f"  Distinct lemmas: {len(winner_by_lemma):,}")
print(f"  most_frequent_lemma_instance == true: {true_count:,}")
print(f"  Deleted legacy 'duplicate' field from: {deleted_duplicate_field:,} entries")
if missing_word:
    print(f"  WARNING: entries missing 'word': {missing_word:,}")
print(f"  Output saved to: {out_path}")
