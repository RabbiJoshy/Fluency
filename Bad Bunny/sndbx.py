import json

# Load the JSON file
with open('Bad Bunny/vocab_evidence.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Extract all words
words = [entry['word'] for entry in data]

# Save to a text file (one word per line)
with open('words_only.txt', 'w', encoding='utf-8') as f:
    for word in words:
        f.write(word + '\n')

print(f"Extracted {len(words)} words")