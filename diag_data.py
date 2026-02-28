import json
from datetime import datetime

with open('aws_builder_likes.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Total items in JSON: {len(data)}")

# Check dates
dates = [p['created_at'] for p in data]
min_date = min(dates)
max_date = max(dates)
print(f"Date range: {min_date} to {max_date}")

# Check how many are before Feb 11, 2026
comp_start = "2026-02-11 00:00:00"
count_before = sum(1 for d in dates if d < comp_start)
print(f"Items before {comp_start}: {count_before}")

if count_before > 0:
    print("\nSample items before start date:")
    for p in data:
        if p['created_at'] < comp_start:
            print(f"  {p['created_at']} - {p['title']}")
            # Let's break after 5
            count_before -= 1
            if count_before <= 0 or count_before < len(data) - 5: 
                # This logic is slightly flawed but fine for a quick look
                pass
            
# Check if any have velocity
vels = [p.get('velocity', 0) for p in data]
print(f"\nItems with velocity > 0: {sum(1 for v in vels if v > 0)}")
if any(vels):
    print(f"Max velocity: {max(vels)}")
