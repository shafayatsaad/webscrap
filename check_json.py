import json

# Read with errors='replace' to find the problem
with open('aws_builder_likes.json', 'r', encoding='utf-8', errors='replace') as f:
    raw = f.read()

# Find exact problem area
pos = 6549
print(f"Around position {pos}:")
print(repr(raw[pos-50:pos+50]))

# Check if it's just a display issue or actual bad JSON
# Try fixing and re-parsing
try:
    data = json.loads(raw)
    print(f"\nParsed OK: {len(data)} items")
except json.JSONDecodeError as e:
    print(f"\nJSON error at {e.pos}: {e.msg}")
    print(f"Around error: {repr(raw[e.pos-50:e.pos+50])}")
