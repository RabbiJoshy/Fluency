import json
import re
from pathlib import Path
from collections import Counter
import pandas as pd

# ---------- CONFIG ----------
INPUT_DIR = "genius_Bad_Bunny"
OUTPUT_CSV = "bad_bunny_vocab_artist.csv"
# ----------------------------

# Load all batch JSON files
lyrics = []
for path in Path(INPUT_DIR).glob("batch_*.json"):
    with open(path, "r", encoding="utf-8") as f:
        batch = json.load(f)
        for song in batch:
            if song.get("lyrics"):
                lyrics.append(song["lyrics"])

print(f"Loaded lyrics from {len(lyrics)} songs")

# Combine lyrics
text = "\n".join(lyrics).lower()

# Remove section labels like [intro], [coro], etc.
text = re.sub(r"\[.*?\]", " ", text)

# Tokenize (Spanish + slang friendly)
words = re.findall(r"[a-záéíóúñü']+", text)

# Count words
counts = Counter(words)

total_words = sum(counts.values())

# Build rows
rows = []
for word, count in counts.items():
    rows.append({
        "word": word,
        "lemma": word,  # placeholder
        "occurrences_ppm": (count / total_words) * 1_000_000
    })

# Create DataFrame
df = pd.DataFrame(rows)

# Rank
df = df.sort_values("occurrences_ppm", ascending=False).reset_index(drop=True)
df["rank"] = df.index + 1

# Match SpanishRawWiki.csv layout
df = df[["rank", "word", "lemma", "occurrences_ppm"]]

# Save
df.to_csv(OUTPUT_CSV, index=False)
print(f"Saved {len(df)} words → {OUTPUT_CSV}")
