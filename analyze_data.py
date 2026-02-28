import json

d = json.load(open('aws_builder_likes.json', 'r', encoding='utf-8'))

# Find all posts with "aideas" in the title (case insensitive)
aideas = [p for p in d if 'aideas' in (p.get('title','') or '').lower() 
          or 'ai ideas' in (p.get('title','') or '').lower()
          or '10000' in (p.get('title','') or '').lower()
          or 'aideas' in (p.get('id','') or '').lower()
          or 'aideas' in (p.get('uri','') or '').lower()]

aideas_s = sorted(aideas, key=lambda x: x['likes_count'], reverse=True)
print(f"AIdeas competition posts: {len(aideas_s)}")
for i, p in enumerate(aideas_s, 1):
    hl = ">>>" if '3AAMRb7l' in p.get('id','') else "   "
    print(f"  {hl} #{i}: {p['likes_count']:>4} likes | {p['title'][:65]}")

# Also check what is_competition flagged
comp = [p for p in d if p.get('is_competition')]
print(f"\nis_competition flagged: {len(comp)}")
