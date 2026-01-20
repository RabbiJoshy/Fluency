import csv
import re

input_file = "Data/Swedish/Swedish Frequency.rtf"
output_file = "Data/Swedish/swedish_frequency.csv"

words = []

# Read RTF file
with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
    text = f.read()

# Remove basic RTF control words and braces
text = re.sub(r"{\\.*?}|\\[a-zA-Z]+\d*", " ", text)
text = re.sub(r"[{}]", " ", text)

# Split into tokens
tokens = re.split(r"\s+", text)

# Keep only real words (letters, incl Swedish chars)
for token in tokens:
    token = token.strip()
    if re.match(r"^[A-Za-zÅÄÖåäö]+$", token):
        words.append(token)

# Write CSV
with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["rank", "word"])

    for i, word in enumerate(words, start=1):
        writer.writerow([i, word])

print(f"Saved {len(words)} words to {output_file}")
