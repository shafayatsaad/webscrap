import json

d = json.load(open('aws_builder_likes.json', 'r', encoding='utf-8'))
print(f"Total posts: {len(d)}")

# Count by type
from collections import Counter
types = Counter(p.get('content_type', '?') for p in d)
for t, c in types.most_common():
    print(f"  {t}: {c}")

# Top 15
s = sorted(d, key=lambda x: x['likes_count'], reverse=True)
print(f"\nTop 15 by likes:")
for i, p in enumerate(s[:15], 1):
    print(f"  #{i}: {p['likes_count']} likes [{p['content_type']}] {p['title'][:55]}")

# Our post
hl = [p for p in d if '3AAMRb7l' in p.get('id', '')]
if hl:
    rank = s.index(hl[0]) + 1
    print(f"\nOur post: {hl[0]['likes_count']} likes, rank #{rank}/{len(d)}")
else:
    print("\nOur post not found")

# Competition posts
comp = [p for p in d if p.get('is_competition')]
print(f"\nCompetition posts: {len(comp)}")
comp_s = sorted(comp, key=lambda x: x['likes_count'], reverse=True)
for i, p in enumerate(comp_s[:10], 1):
    print(f"  #{i}: {p['likes_count']} likes - {p['title'][:50]}")
