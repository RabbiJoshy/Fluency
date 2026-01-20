import json
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================
LANGUAGE = "Polish"  # Change this for other languages
# ============================================================

# Target directory is Data/{LANGUAGE} relative to current directory
# If already in Data/{LANGUAGE}, use current directory
# Otherwise look for Data/{LANGUAGE} subdirectory
current_dir = Path.cwd()

if current_dir.name == LANGUAGE and current_dir.parent.name == 'Data':
    # Already in the right place
    script_dir = current_dir
elif (current_dir / 'Data' / LANGUAGE).exists():
    # Running from parent directory (e.g., Fluency)
    script_dir = current_dir / 'Data' / LANGUAGE
else:
    # Try to find Data/{LANGUAGE}
    script_dir = current_dir

print(f"Language: {LANGUAGE}")
print(f"Working directory: {script_dir}")

# Define the main vocabulary file
vocab_file = script_dir / "vocabulary.json"

# Check if vocabulary.json exists
if not vocab_file.exists():
    print(f"ERROR: {vocab_file} not found!")
    exit()

# Load the vocabulary file
print(f"Loading vocabulary file: {vocab_file}")
with open(vocab_file, 'r', encoding='utf-8') as f:
    vocabulary = json.load(f)

print(f"Loaded {len(vocabulary)} total entries")

# Track entries with missing lemmas
empty_lemmas_with_data = []  # Has word and meanings, but lemma is empty
completely_empty = []  # Missing word or meanings entirely

# Track seen lemmas and create deduplicated list
seen_lemmas = set()
deduplicated_vocabulary = []
duplicates_removed = 0

for entry in vocabulary:
    lemma = entry.get("lemma", "")
    word = entry.get("word", "")
    meanings = entry.get("meanings", [])
    rank = entry.get("rank", "")

    # Check for entries with empty lemmas
    if lemma == "":
        # Check if this is a completely empty entry or just missing lemma
        if not word or not meanings:
            completely_empty.append({
                "rank": rank,
                "word": word,
                "has_meanings": bool(meanings)
            })
        else:
            empty_lemmas_with_data.append({
                "rank": rank,
                "word": word
            })

        # Treat entries with empty lemmas as unique by their word
        unique_key = f"__word__{word}"
    else:
        unique_key = lemma

    # Keep only the first occurrence of each unique lemma
    if unique_key not in seen_lemmas:
        seen_lemmas.add(unique_key)
        deduplicated_vocabulary.append(entry)
    else:
        duplicates_removed += 1

# Define the output directory and create it if it doesn't exist
output_dir = script_dir / "lemma_deduplicated"
output_dir.mkdir(exist_ok=True)

# Define the output file
output_file = output_dir / "vocabulary.json"

# Save the deduplicated vocabulary
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(deduplicated_vocabulary, f, ensure_ascii=False, indent=2)

print(f"\n✓ Deduplication complete!")
print(f"  Original entries: {len(vocabulary)}")
print(f"  Unique lemmas kept: {len(deduplicated_vocabulary)}")
print(f"  Duplicate forms removed: {duplicates_removed}")
print(f"  Output saved to: {output_dir / 'vocabulary.json'}")

# Print report on entries with missing lemmas
if empty_lemmas_with_data or completely_empty:
    print(f"\n{'=' * 60}")
    print("ENTRIES WITH MISSING LEMMAS - NEED FIXING")
    print(f"{'=' * 60}")

    if empty_lemmas_with_data:
        print(f"\n1. EMPTY LEMMA BUT HAS DATA ({len(empty_lemmas_with_data)} entries):")
        print("   (These have word and meanings, just missing lemma field)")
        print("   " + "-" * 56)
        for item in empty_lemmas_with_data:
            print(f"   Rank {item['rank']:>5}: {item['word']}")

    if completely_empty:
        print(f"\n2. COMPLETELY EMPTY OR MISSING DATA ({len(completely_empty)} entries):")
        print("   (These are missing word and/or meanings - likely data gaps)")
        print("   " + "-" * 56)
        for item in completely_empty:
            word_status = f"word: '{item['word']}'" if item['word'] else "word: MISSING"
            meanings_status = "has meanings" if item['has_meanings'] else "meanings: MISSING"
            print(f"   Rank {item['rank']:>5}: {word_status}, {meanings_status}")

    print(f"\n{'=' * 60}")
else:
    print("\n✓ All entries have lemmas - no missing data!")
