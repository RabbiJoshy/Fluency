import json
import re

with open('Data/Spanish/spanish_4011-4110.json', 'r', encoding='utf-8') as f:
    content = f.read()

# Step 1: Add opening bracket if needed
if not content.strip().startswith('['):
    content = '[' + content
    print("✓ Added opening bracket")

# Step 2: Fix missing commas between objects
content = re.sub(r'}\s*\n\s*{', '},\n  {', content)
print("✓ Fixed missing commas")

# Step 3: Merge split arrays
content = re.sub(r']\s*\n\s*{', ',\n  {', content)
print("✓ Merged split arrays")

# Step 4: Add closing bracket if needed
if not content.strip().endswith(']'):
    content = content.rstrip() + '\n]'
    print("✓ Added closing bracket")

# Step 5: Try to parse
try:
    data = json.loads(content)
    print(f"\n✓ SUCCESS! Loaded {len(data)} entries")

    # Save fixed version
    with open('Data/Spanish/spanish_4011-4110_fixed.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✓ Saved to Data/Spanish/spanish_4011-4110_fixed.json")
    print(f"  Rank range: {data[0]['rank']} - {data[-1]['rank']}")
    print(f"  First word: {data[0]['word']}")
    print(f"  Last word: {data[-1]['word']}")

except json.JSONDecodeError as e:
    print(f"\n✗ Still an error at line {e.lineno}, col {e.colno}: {e.msg}")
    lines = content.split('\n')
    start = max(0, e.lineno - 3)
    end = min(len(lines), e.lineno + 2)

    print("\nProblematic area:")
    for i in range(start, end):
        marker = ">>> " if i == e.lineno - 1 else "    "
        print(f"{marker}Line {i + 1}: {lines[i]}")