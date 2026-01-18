import json
import os
from pathlib import Path

# Target directory is Data/Spanish relative to current directory
# If already in Data/Spanish, use current directory
# Otherwise look for Data/Spanish subdirectory
current_dir = Path.cwd()

if current_dir.name == 'Spanish' and current_dir.parent.name == 'Data':
    # Already in the right place
    script_dir = current_dir
elif (current_dir / 'Data' / 'Spanish').exists():
    # Running from parent directory (e.g., Fluency)
    script_dir = current_dir / 'Data' / 'Spanish'
else:
    # Try to find Data/Spanish
    script_dir = current_dir

print(f"Working directory: {script_dir}")

# Define the main vocabulary file
main_vocab_file = script_dir / "vocabulary.json"

# Check if vocabulary.json exists
if not main_vocab_file.exists():
    print(f"ERROR: {main_vocab_file} not found!")
    exit()

# Load the main vocabulary file
print(f"Loading main vocabulary file: {main_vocab_file}")
with open(main_vocab_file, 'r', encoding='utf-8') as f:
    main_vocabulary = json.load(f)

print(f"Current vocabulary has {len(main_vocabulary)} entries")

# Find all JSON files in the directory (excluding vocabulary.json and void_ files)
json_files = [f for f in script_dir.glob("*.json")
              if f.name != "vocabulary.json"
              and not f.name.startswith("void_")]

if not json_files:
    print("No additional JSON files found to merge")
else:
    print(f"\nFound {len(json_files)} file(s) to merge:")
    for file in json_files:
        print(f"  - {file.name}")

    # Merge all found JSON files
    for json_file in json_files:
        print(f"\nProcessing {json_file.name}...")

        # Load the file to merge
        with open(json_file, 'r', encoding='utf-8') as f:
            new_entries = json.load(f)

        print(f"  Loaded {len(new_entries)} entries")

        # Append to main vocabulary
        main_vocabulary.extend(new_entries)

        # Rename the merged file with 'void_' prefix
        void_filename = script_dir / f"void_{json_file.name}"
        os.rename(json_file, void_filename)
        print(f"  Renamed {json_file.name} to {void_filename.name}")

    # Rename the original vocabulary.json to void_vocabulary.json
    void_original = script_dir / "void_vocabulary.json"
    os.rename(main_vocab_file, void_original)
    print(f"\nRenamed original vocabulary.json to {void_original.name}")

    # Save the NEW merged vocabulary as vocabulary.json
    with open(main_vocab_file, 'w', encoding='utf-8') as f:
        json.dump(main_vocabulary, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Merge complete!")
    print(f"  Created NEW vocabulary.json with {len(main_vocabulary)} entries")
    print(f"  Original files preserved with 'void_' prefix:")
    print(f"    - void_vocabulary.json (original)")
    for file in json_files:
        print(f"    - void_{file.name}")