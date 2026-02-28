import os, json

fpath = "aws_builder_likes.json"
size = os.path.getsize(fpath)
print(f"File size: {size} bytes")

with open(fpath, "r", encoding="utf-8") as f:
    raw = f.read()

print(f"Total chars: {len(raw)}")
print(f"First 100: {repr(raw[:100])}")
print(f"Last 100: {repr(raw[-100:])}")

# Try to parse
try:
    data = json.loads(raw)
    print(f"\nParsed OK: {len(data)} items")
except json.JSONDecodeError as e:
    print(f"\nJSON error at position {e.pos}: {e.msg}")
    # Show context around error
    start = max(0, e.pos - 100)
    end = min(len(raw), e.pos + 100)
    print(f"Context: ...{repr(raw[start:end])}...")
