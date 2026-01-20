import csv
import re
from striprtf.striprtf import rtf_to_text

input_file = "Data/Swedish/Swedish Frequency.rtf"
output_file = "Data/Swedish/swedish_frequency.csv"

# Read and convert RTF to plain text
with open(input_file, "r", encoding="utf-8") as f:
    rtf_content = f.read()

text = rtf_to_text(rtf_content)

# Remove numeric range headers like "1-200"
text = re.sub(r"\b\d+\s*-\s*\d+\b", " ", text)

# Remove bracketed duplicates like "(Dag)", "(Inga)", etc.
text = re.sub(r"\([^)]*\)", " ", text)

# Normalize whitespace
text = re.sub(r"\s+", " ", text).strip()

# Extract words (keeps Swedish characters)
words = re.findall(r"[A-Za-zÅÄÖåäö]+", text)

# ---- DEBUG PRINTS ----
print("Debug checkpoints:")
for i in range(200, len(words) + 1, 200):
    print(f"{i}: {words[i - 1]}")

# Write CSV with rank and word
with open(output_file, "w", encoding="utf-8", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["rank", "word"])

    for rank, word in enumerate(words, start=1):
        writer.writerow([rank, word.lower()])

print(f"\nCSV written to {output_file} with {len(words)} entries.")
