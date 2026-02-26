from dashboard import scrape_once, tag_comp
posts = scrape_once()
comp = [p for p in posts if tag_comp(p).get('is_competition')]
print(f"Total: {len(posts)}, Comp: {len(comp)}")
if posts:
    print(f"Top: {posts[0].get('likes_count')}")
