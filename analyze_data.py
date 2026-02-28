import json

d = json.load(open('aws_builder_likes.json', 'r', encoding='utf-8'))
print(f"Total articles: {len(d)}")

s = sorted(d, key=lambda x: x['likes_count'], reverse=True)
print(f"\nTop 20 by likes:")
for i, p in enumerate(s[:20], 1):
    comp = "[COMP]" if p.get('is_competition') else ""
    print(f"  #{i}: {p['likes_count']:>4} likes {comp:>6} | {p['title'][:60]}")

# Our post
hl = [p for p in d if '3AAMRb7l' in p.get('id', '')]
if hl:
    rank = s.index(hl[0]) + 1
    print(f"\n>>> Our post: '{hl[0]['title'][:50]}' = {hl[0]['likes_count']} likes, rank #{rank}/{len(d)}")
else:
    print("\nOur post not found!")

# Competition posts
comp = [p for p in d if p.get('is_competition')]
comp_s = sorted(comp, key=lambda x: x['likes_count'], reverse=True)
print(f"\nCompetition posts found: {len(comp)}")
for i, p in enumerate(comp_s[:10], 1):
    print(f"  Comp #{i}: {p['likes_count']:>4} likes | {p['title'][:55]}")

# Stats
likes = [p['likes_count'] for p in d]
print(f"\nStats:")
print(f"  200+ likes: {sum(1 for l in likes if l >= 200)}")
print(f"  100+ likes: {sum(1 for l in likes if l >= 100)}")
print(f"  50+ likes: {sum(1 for l in likes if l >= 50)}")
print(f"  10+ likes: {sum(1 for l in likes if l >= 10)}")
print(f"  Max: {max(likes)}, Avg: {sum(likes)/len(likes):.1f}")
