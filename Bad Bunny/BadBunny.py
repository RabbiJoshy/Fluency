import pandas as pd
import re
from collections import Counter

# ---------- CONFIG ----------
INPUT_LYRICS_CSV = "bad_bunny_lyrics.csv"
OUTPUT_CSV = "bad_bunny_album_vocab.csv"
TARGET_ALBUM = "X 100pre"   # change if needed
# ----------------------------

# Load lyrics
df = pd.read_csv(INPUT_LYRICS_CSV)

df["album"].value_counts()

# Filter album
album_df = df[df["album"] == TARGET_ALBUM]

# Combine lyrics
text = "\n".join(album_df["lyrics"].astype(str)).lower()

# Remove section labels like [intro], [coro], etc.
text = re.sub(r"\[.*?\]", " ", text)

# Tokenize (Spanish + slang-friendly)
words = re.findall(r"[a-záéíóúñü']+", text)

# Count words
counts = Counter(words)

# Total word count (for ppm)
total_words = sum(counts.values())

# Build rows
rows = []
for word, count in counts.items():
    occurrences_ppm = (count / total_words) * 1_000_000
    rows.append({
        "word": word,
        "lemma": word,              # placeholder (same as word for now)
        "occurrences_ppm": occurrences_ppm
    })

# Create DataFrame
out_df = pd.DataFrame(rows)

# Rank by frequency
out_df = out_df.sort_values("occurrences_ppm", ascending=False).reset_index(drop=True)
out_df["rank"] = out_df.index + 1

# Reorder columns to match SpanishRawWiki.csv
out_df = out_df[["rank", "word", "lemma", "occurrences_ppm"]]

# Save
out_df.to_csv(OUTPUT_CSV, index=False)

print(f"Saved {len(out_df)} words to {OUTPUT_CSV}")
