"""
AWS Builder Center Post Likes Scraper (v2 - Pure Requests)
===========================================================
Scrapes https://builder.aws.com to find all posts and their like counts,
displaying them sorted from highest to lowest likes.

Uses the public API directly with requests — no Selenium or Chrome needed.
The API at api.builder.aws.com accepts builder-session-token: dummy and
supports pagination via nextToken.

Usage:
    python aws_scraper.py
"""

import json
import time
import csv
import os
import sys
from datetime import datetime

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system(f"{sys.executable} -m pip install requests")
    import requests


# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
BASE_URL = "https://builder.aws.com"
API_URL = "https://api.builder.aws.com/cs/content/feed"
CONTENT_TYPES = ["ARTICLE"]  # Competition posts are articles
PAGE_SIZE = 50  # Max items per API request
OUTPUT_CSV = "aws_builder_likes.csv"
OUTPUT_JSON = "aws_builder_likes.json"

# The post to highlight/compare ranking for
HIGHLIGHT_POST_URI = "/content/3AAMRb7lRzAJnleldfYBBtfM1WG/aideas-transforming-healthcare-into-ai-powered-wellness-companion"

# Competition keywords to identify related posts
COMPETITION_KEYWORDS = [
    "AIdeas", "AI ideas", "healthcare", "wellness", "competition",
    "Kiro", "Mimamori", "wellness companion", "AI-powered wellness",
    "wellness avatar", "health AI", "medical AI"
]


def is_competition_post(post):
    """Determine if a post is related to the competition."""
    title = post.get("title", "").lower()
    uri = post.get("id", "").lower()

    # Check highlight post first
    if HIGHLIGHT_POST_URI and (
        HIGHLIGHT_POST_URI.lower() in uri
        or post.get("id", "") in HIGHLIGHT_POST_URI
    ):
        return True

    # Check keywords in title
    for kw in COMPETITION_KEYWORDS:
        if kw.lower() in title:
            return True

    return False


# ──────────────────────────────────────────────────────────────────────────────
# Color Output Helpers
# ──────────────────────────────────────────────────────────────────────────────
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


def print_banner():
    banner = f"""
{Colors.CYAN}{Colors.BOLD}
================================================================
    AWS Builder Center - Post Likes Scraper v2
    https://builder.aws.com
    (Pure requests — no Selenium needed)
================================================================
{Colors.RESET}"""
    print(banner)


def print_step(step_num, message):
    print(f"\n{Colors.YELLOW}[Step {step_num}]{Colors.RESET} {Colors.BOLD}{message}{Colors.RESET}")


def print_success(message):
    print(f"  {Colors.GREEN}[OK]{Colors.RESET} {message}")


def print_info(message):
    print(f"  {Colors.BLUE}[i]{Colors.RESET} {message}")


def print_error(message):
    print(f"  {Colors.RED}[X]{Colors.RESET} {message}")


def print_progress(current, total, prefix=""):
    bar_len = 30
    filled = int(bar_len * current / max(total, 1))
    bar = '#' * filled + '-' * (bar_len - filled)
    print(f"\r  {prefix} [{bar}] {current}/{total}", end="", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# API Client
# ──────────────────────────────────────────────────────────────────────────────
def create_api_session():
    """Create a requests session with the headers the API expects."""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        # The API accepts 'dummy' as session token for public/anonymous access
        "builder-session-token": "dummy",
        "x-amz-user-agent": "aws-sdk-js/1.0.0 ua/2.1 os/Windows lang/js md/browser api/bingocontent#1.0.0 m/N,E",
    })
    return session


def fetch_feed_page(session, content_type, next_token=None):
    """Fetch a single page of feed content from the API."""
    payload = {
        "contentType": content_type,
        "pageSize": PAGE_SIZE,
    }

    if next_token:
        payload["nextToken"] = next_token

    try:
        response = session.post(API_URL, json=payload, timeout=15)

        if response.status_code == 429:
            print_info("Rate limited — waiting 5 seconds...")
            time.sleep(5)
            return fetch_feed_page(session, content_type, next_token)

        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print_error(f"HTTP Error {e.response.status_code}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print_error(f"Request error: {e}")
        return None


def format_timestamp(ts):
    """Convert epoch timestamp (seconds or ms) to readable date string."""
    if ts is None:
        return "N/A"
    try:
        if isinstance(ts, (int, float)):
            if ts > 1e12:
                ts = ts / 1000
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        return str(ts)
    except (ValueError, OSError):
        return str(ts)


def fetch_all_posts(session, content_type):
    """Fetch ALL posts of a given type by following pagination tokens."""
    all_posts = []
    next_token = None
    page = 0

    print_info(f"Fetching '{content_type}' posts...")

    while True:
        page += 1
        result = fetch_feed_page(session, content_type, next_token)

        if not result:
            break

        feed_contents = result.get("feedContents", [])
        if not feed_contents:
            break

        for item in feed_contents:
            content_id = item.get("contentId", "N/A")
            uri = item.get("uri", "")

            # Construct URL
            if uri:
                final_url = f"{BASE_URL}{uri}"
            elif content_id and content_id != "N/A":
                final_url = f"{BASE_URL}/content/{content_id.split('/')[-1]}"
            else:
                final_url = BASE_URL

            post_data = {
                "id": content_id,
                "title": item.get("title", "Untitled"),
                "content_type": item.get("contentType", content_type),
                "likes_count": item.get("likesCount", 0),
                "comments_count": item.get("commentsCount", 0),
                "views_count": item.get("viewsCount") if "viewsCount" in item else None,
                "created_at": format_timestamp(item.get("createdAt")),
                "last_published_at": format_timestamp(item.get("lastPublishedAt")),
                "uri": uri,
                "url": final_url,
                "status": item.get("status", ""),
                "locale": item.get("locale", ""),
                "author_alias": (item.get("author", {}) or {}).get("alias", "N/A"),
                "author_name": (item.get("author", {}) or {}).get("preferredName", "N/A"),
                "follow_count": item.get("followCount", 0),
                "space_id": item.get("spaceId"),
                "space_name": item.get("spaceName"),
            }
            post_data["is_competition"] = is_competition_post(post_data)
            all_posts.append(post_data)

        print_info(f"  Page {page}: {len(feed_contents)} items (total: {len(all_posts)})")

        next_token = result.get("nextToken")
        if not next_token:
            break

        # Small delay to be respectful
        time.sleep(0.3)

    print_success(f"Fetched {len(all_posts)} '{content_type}' posts across {page} page(s)")
    return all_posts


# ──────────────────────────────────────────────────────────────────────────────
# Display & Save Results
# ──────────────────────────────────────────────────────────────────────────────
def display_results(posts):
    """Display results sorted by likes from highest to lowest."""
    if not posts:
        print_error("No posts found!")
        return

    # Sort by likes count (highest to lowest)
    sorted_posts = sorted(posts, key=lambda x: x.get("likes_count", 0), reverse=True)

    # Remove duplicates by ID
    seen_ids = set()
    unique_posts = []
    for p in sorted_posts:
        if p["id"] not in seen_ids:
            seen_ids.add(p["id"])
            unique_posts.append(p)
    sorted_posts = unique_posts

    print(f"\n{Colors.CYAN}{'=' * 100}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  RESULTS: {len(sorted_posts)} Posts Sorted by Likes (Highest -> Lowest){Colors.RESET}")
    print(f"{Colors.CYAN}{'=' * 100}{Colors.RESET}\n")

    # Header
    print(f"  {Colors.BOLD}{'#':<5} {'Likes':<8} {'Type':<10} {'Date':<12} {'Competition':<12} {'Title'}{Colors.RESET}")
    print(f"  {'-' * 100}")

    for idx, post in enumerate(sorted_posts, 1):
        likes = post.get("likes_count", 0)
        title = post.get("title", "Untitled")
        if len(title) > 40:
            title = title[:37] + "..."

        content_type = post.get("content_type", "")
        is_comp = post.get("is_competition", False)
        comp_str = "[COMP]" if is_comp else ""

        date_str = post.get("created_at", "N/A")
        if date_str and len(date_str) > 10:
            date_str = date_str[:10]

        # Color code
        if is_comp:
            color = Colors.CYAN if likes < 20 else Colors.GREEN
        else:
            color = Colors.DIM

        print(f"  {color}{idx:<5} {likes:<8} {content_type:<10} {date_str:<12} {comp_str:<12} {title}{Colors.RESET}")

    print(f"\n  {'-' * 95}")

    # Summary stats
    total_likes = sum(p.get("likes_count", 0) for p in sorted_posts)
    avg_likes = total_likes / len(sorted_posts) if sorted_posts else 0
    max_likes = max(p.get("likes_count", 0) for p in sorted_posts) if sorted_posts else 0

    print(f"\n{Colors.BOLD}  Summary:{Colors.RESET}")
    print(f"     Total Posts:  {len(sorted_posts)}")
    print(f"     Total Likes:  {total_likes}")
    print(f"     Avg Likes:    {avg_likes:.1f}")
    print(f"     Max Likes:    {max_likes}")
    print(f"     Posts >=50:   {sum(1 for p in sorted_posts if p.get('likes_count', 0) >= 50)}")
    print(f"     Posts >=20:   {sum(1 for p in sorted_posts if p.get('likes_count', 0) >= 20)}")

    # ── Highlight specific post ranking ──
    highlight_post = None
    highlight_rank = None
    for idx, post in enumerate(sorted_posts, 1):
        uri = post.get("uri", "")
        pid = post.get("id", "")
        if HIGHLIGHT_POST_URI and (
            HIGHLIGHT_POST_URI in uri
            or HIGHLIGHT_POST_URI.rstrip("/") == uri.rstrip("/")
            or pid in HIGHLIGHT_POST_URI
        ):
            highlight_post = post
            highlight_rank = idx
            break

    if highlight_post:
        likes = highlight_post.get("likes_count", 0)
        title = highlight_post.get("title", "Untitled")
        pct_top = (highlight_rank / len(sorted_posts)) * 100 if sorted_posts else 0

        print(f"\n{Colors.CYAN}{'=' * 100}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.GREEN}  >>> YOUR POST RANKING <<<{Colors.RESET}")
        print(f"{Colors.CYAN}{'=' * 100}{Colors.RESET}")
        print(f"  {Colors.BOLD}Title:{Colors.RESET}    {title}")
        print(f"  {Colors.BOLD}Rank:{Colors.RESET}     {Colors.GREEN}#{highlight_rank}{Colors.RESET} out of {len(sorted_posts)} posts")
        print(f"  {Colors.BOLD}Likes:{Colors.RESET}    {Colors.GREEN}{likes}{Colors.RESET}")
        print(f"  {Colors.BOLD}Top:{Colors.RESET}      {Colors.GREEN}{pct_top:.1f}%{Colors.RESET}")
        print(f"  {Colors.BOLD}ID:{Colors.RESET}       {highlight_post.get('id', 'N/A')}")
        print(f"  {Colors.BOLD}URL:{Colors.RESET}      {highlight_post.get('url', 'N/A')}")
        print(f"  {Colors.BOLD}Author:{Colors.RESET}   {highlight_post.get('author_name', 'N/A')} (@{highlight_post.get('author_alias', 'N/A')})")

        # Show nearby posts for context
        print(f"\n  {Colors.BOLD}Nearby posts in ranking:{Colors.RESET}")
        start = max(0, highlight_rank - 4)
        end = min(len(sorted_posts), highlight_rank + 3)
        for i in range(start, end):
            p = sorted_posts[i]
            rank = i + 1
            marker = f"{Colors.GREEN}  >> " if rank == highlight_rank else "    "
            t = p.get('title', 'Untitled')
            if len(t) > 50:
                t = t[:47] + "..."
            print(f"{marker}#{rank:<5} {p.get('likes_count', 0):<6} likes  {t}{Colors.RESET}")
    else:
        print(f"\n  {Colors.YELLOW}[!] Target post not found in results.{Colors.RESET}")
        print(f"    URI: {HIGHLIGHT_POST_URI}")

    return sorted_posts


def save_results(sorted_posts):
    """Save results to CSV and JSON files."""
    if not sorted_posts:
        return

    # Save CSV
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_CSV)
    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "rank", "id", "title", "content_type", "likes_count",
                "comments_count", "created_at", "last_published_at",
                "author_alias", "author_name", "url"
            ])
            writer.writeheader()
            for idx, post in enumerate(sorted_posts, 1):
                writer.writerow({
                    "rank": idx,
                    "id": post.get("id", ""),
                    "title": post.get("title", ""),
                    "content_type": post.get("content_type", ""),
                    "likes_count": post.get("likes_count", 0),
                    "comments_count": post.get("comments_count", 0),
                    "created_at": post.get("created_at", ""),
                    "last_published_at": post.get("last_published_at", ""),
                    "author_alias": post.get("author_alias", ""),
                    "author_name": post.get("author_name", ""),
                    "url": post.get("url", ""),
                })
        print_success(f"CSV saved to: {csv_path}")
    except Exception as e:
        print_error(f"Failed to save CSV: {e}")

    # Save JSON (clean, no debug data)
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_JSON)
    try:
        clean_posts = []
        for p in sorted_posts:
            clean = {k: v for k, v in p.items() if k != "raw_item"}
            clean_posts.append(clean)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(clean_posts, f, indent=2, ensure_ascii=False)
        print_success(f"JSON saved to: {json_path}")
    except Exception as e:
        print_error(f"Failed to save JSON: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    print_banner()

    all_posts = []

    # Create API session (no Selenium needed!)
    print_step(1, "Creating API session...")
    session = create_api_session()

    # Fetch all content types
    print_step(2, f"Fetching posts from all content types via API...")

    for content_type in CONTENT_TYPES:
        posts = fetch_all_posts(session, content_type)
        if posts:
            all_posts.extend(posts)

    # Display & Save
    if all_posts:
        print_step(3, "Processing and displaying results...")
        sorted_posts = display_results(all_posts)

        print_step(4, "Saving results to files...")
        save_results(sorted_posts)
    else:
        print_error("No posts could be retrieved.")
        print_info("The API may have changed or be temporarily unavailable.")

    print(f"\n{Colors.CYAN}{'=' * 100}{Colors.RESET}")
    print(f"{Colors.BOLD}  Done!{Colors.RESET}\n")


if __name__ == "__main__":
    main()