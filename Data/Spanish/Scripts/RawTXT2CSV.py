import pandas as pd

# ---- CONFIG ----
INPUT_TXT = "Data/Spanish/SpanishRawWiki.txt"
OUTPUT_CSV = "Data/Spanish/SpanishRawWiki.csv"

# ---- LOAD TXT (with header) ----
df = pd.read_csv(
    INPUT_TXT,
    sep="\t",
    engine="python"
)

# Normalize column names (optional but helpful)
df.columns = ["rank", "word", "occurrences", "lemmas"]

# ---- CLEAN RANK COLUMN ----
df["rank"] = (
    df["rank"]
    .astype(str)
    .str.replace(".", "", regex=False)
)

# Drop rows where rank is not numeric (e.g. header junk)
df = df[df["rank"].str.isnumeric()]

df["rank"] = df["rank"].astype(int)

# ---- CLEAN OCCURRENCES ----
df["occurrences"] = pd.to_numeric(df["occurrences"], errors="coerce")

# Drop rows with missing occurrences
df = df.dropna(subset=["occurrences"])

# ---- EXPAND LEMMAS ----
rows = []
new_rank = 1

for _, row in df.iterrows():
    lemma_list = str(row["lemmas"]).split()
    n = len(lemma_list)
    occ_per_lemma = row["occurrences"] / n

    for lemma in lemma_list:
        rows.append({
            "rank": new_rank,
            "word": row["word"],
            "lemma": lemma,
            "occurrences": occ_per_lemma
        })
        new_rank += 1

expanded_df = pd.DataFrame(rows)

# ---- SAVE ----
expanded_df.to_csv(OUTPUT_CSV, index=False)

print(f"Saved {len(expanded_df)} rows to {OUTPUT_CSV}")

