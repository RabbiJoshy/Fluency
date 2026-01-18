"""
Script to consolidate Spanish vocabulary files into a single JSON file.
Each rank has one entry with all meanings grouped together.
"""

import os
import json


def parse_line(line):
    """
    Parse a line from the format:
    rank|word|lemma|pos|translation|frequency|example_spanish|example_english

    Returns a dict with the parsed data or None if the line is empty/invalid.
    """
    line = line.strip()
    if not line:
        return None

    # Split by pipe
    fields = line.split('|')

    # We expect 8 fields: rank, word, lemma, pos, translation, frequency, example_es, example_en
    if len(fields) < 8:
        return None

    rank = fields[0].strip()
    if not rank:  # Empty rank means this is a blank line
        return None

    return {
        'rank': int(rank),
        'word': fields[1].strip(),
        'lemma': fields[2].strip(),
        'pos': fields[3].strip(),
        'translation': fields[4].strip(),
        'frequency': fields[5].strip(),
        'example_spanish': fields[6].strip(),
        'example_english': fields[7].strip()
    }


def get_all_txt_files(directory):
    """Get all .txt files in the directory."""
    return sorted([f for f in os.listdir(directory) if f.endswith('.txt')])


def parse_all_files(directory):
    """
    Parse all txt files and return a dictionary mapping rank to list of entries.
    """
    data_by_rank = {}

    txt_files = get_all_txt_files(directory)

    for filename in txt_files:
        filepath = os.path.join(directory, filename)
        print(f"Processing {filename}...")

        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                entry = parse_line(line)
                if entry:
                    rank = entry['rank']
                    if rank not in data_by_rank:
                        data_by_rank[rank] = []
                    data_by_rank[rank].append(entry)

    return data_by_rank


def create_blank_entry(rank):
    """Create a blank placeholder entry for a missing rank."""
    return {
        'rank': rank,
        'word': '',
        'meanings': []
    }


def consolidate_to_json(directory, output_filename='consolidated_vocabulary.json'):
    """
    Main function to consolidate all vocabulary files into a single JSON file.
    Groups multiple meanings for the same rank/word together.
    """
    # Parse all files
    data_by_rank = parse_all_files(directory)

    if not data_by_rank:
        print("No data found!")
        return

    # Find the maximum rank to determine range
    max_rank = max(data_by_rank.keys())
    print(f"\nFound data for ranks 1 to {max_rank}")
    print(f"Total ranks with data: {len(data_by_rank)}")

    # Build consolidated list
    vocabulary = []

    for rank in range(1, max_rank + 1):
        if rank in data_by_rank:
            entries = data_by_rank[rank]
            # Get the word from the first entry (should be same for all)
            word = entries[0]['word']
            lemma = entries[0]['lemma']

            # Group all meanings
            meanings = []
            for entry in entries:
                meanings.append({
                    'pos': entry['pos'],
                    'translation': entry['translation'],
                    'frequency': entry['frequency'],
                    'example_spanish': entry['example_spanish'],
                    'example_english': entry['example_english']
                })

            vocabulary.append({
                'rank': rank,
                'word': word,
                'lemma': lemma,
                'meanings': meanings
            })
        else:
            # Add blank placeholder for missing rank
            vocabulary.append(create_blank_entry(rank))

    # Write output file
    output_path = os.path.join(directory, output_filename)

    with open(output_path, 'w', encoding='utf-8') as outfile:
        json.dump(vocabulary, outfile, ensure_ascii=False, indent=2)

    print(f"\nConsolidation complete!")
    print(f"Output file: {output_path}")
    print(f"Total words: {len(vocabulary)}")


script_dir = 'Spanish'
print("Spanish Vocabulary Consolidation Script")
print("=" * 50)
print(f"Working directory: {script_dir}\n")

consolidate_to_json(script_dir)
