"""
AWS Builder Center Post Likes Scraper
=====================================
Scrapes https://builder.aws.com to find all posts and their like counts,
displaying them sorted from highest to lowest likes.

Uses Selenium to load the page, intercept network requests to capture
the API session token, then calls the internal REST API directly.
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

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
except ImportError:
    print("Installing selenium...")
    os.system(f"{sys.executable} -m pip install selenium")
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

try:
    from seleniumwire import webdriver as wire_webdriver
    WIRE_AVAILABLE = True
except ImportError:
    WIRE_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
BASE_URL = "https://builder.aws.com"
FEED_ENDPOINT = "/cs/content/feed"
CONTENT_TYPES = ["article", "post", "wish"]  # Types of content to scrape
PAGE_SIZE = 50
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
    if HIGHLIGHT_POST_URI and (HIGHLIGHT_POST_URI.lower() in uri or post.get("id", "") in HIGHLIGHT_POST_URI):
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
    AWS Builder Center - Post Likes Scraper
    https://builder.aws.com
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
# Step 1: Get Session Token via Selenium
# ──────────────────────────────────────────────────────────────────────────────
def get_session_token_selenium():
    """
    Opens builder.aws.com in a headless browser and captures the
    builder-session-token from network requests / local storage.
    """
    print_step(1, "Launching browser to capture session token...")

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Enable performance logging to capture network requests
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = None
    session_token = None

    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(30)

        print_info("Navigating to builder.aws.com...")
        driver.get(BASE_URL)

        # Wait for the page to fully load (React app)
        time.sleep(8)
        print_info("Page loaded, waiting for API calls...")

        # Try to trigger feed content loading by scrolling
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(3)

        # Extract session token from performance logs
        logs = driver.get_log("performance")

        for log in logs:
            try:
                msg = json.loads(log["message"])["message"]
                if msg["method"] == "Network.requestWillBeSent":
                    headers = msg.get("params", {}).get("request", {}).get("headers", {})
                    url = msg.get("params", {}).get("request", {}).get("url", "")

                    # Check for the session token in request headers
                    for key, value in headers.items():
                        if key.lower() == "builder-session-token" and value:
                            session_token = value
                            print_success(f"Captured session token: {value[:20]}...")
                            break

                    if session_token:
                        break
            except (json.JSONDecodeError, KeyError):
                continue

        if not session_token:
            print_info("No session token found in network logs (anonymous browsing)")
            print_info("Will attempt API calls without authentication...")

        # Also try to get cookies
        cookies = driver.get_cookies()
        cookie_dict = {c['name']: c['value'] for c in cookies}

        return session_token, cookie_dict

    except Exception as e:
        print_error(f"Browser error: {e}")
        return None, {}
    finally:
        if driver:
            driver.quit()


# ──────────────────────────────────────────────────────────────────────────────
# Step 2: Fetch Posts via API
# ──────────────────────────────────────────────────────────────────────────────
def create_session(session_token=None, cookies=None):
    """Create a requests session with proper headers."""
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
    })

    if session_token:
        session.headers["builder-session-token"] = session_token

    if cookies:
        for name, value in cookies.items():
            session.cookies.set(name, value)

    return session


def fetch_feed_content(session, content_type, page_size=PAGE_SIZE, next_token=None):
    """Fetch a page of feed content from the API."""
    url = f"{BASE_URL}{FEED_ENDPOINT}"

    payload = {
        "contentType": content_type,
        "pageSize": page_size,
    }

    if next_token:
        payload["nextToken"] = next_token

    try:
        response = session.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            print_error("Access denied (403) - May need authentication")
        elif e.response.status_code == 429:
            print_info("Rate limited - waiting 5 seconds...")
            time.sleep(5)
            return fetch_feed_content(session, content_type, page_size, next_token)
        else:
            print_error(f"HTTP Error {e.response.status_code}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print_error(f"Request error: {e}")
        return None


def fetch_all_posts(session, content_type):
    """Fetch all posts of a given type using pagination."""
    all_posts = []
    next_token = None
    page = 0

    print_info(f"Fetching '{content_type}' posts...")

    while True:
        page += 1
        result = fetch_feed_content(session, content_type, next_token=next_token)

        if not result:
            break

        feed_contents = result.get("feedContents", [])
        if not feed_contents:
            break

        for item in feed_contents:
            content_id = item.get("contentId", "N/A")
            uri = item.get("uri", "")
            
            # Construct robust URL: check uri first, then contentId, then fallback
            if uri:
                final_url = f"{BASE_URL}{uri}"
            elif content_id and content_id != "N/A":
                # Some items only have contentId, which needs to be prefixed for direct access
                final_url = f"{BASE_URL}/content/{content_id.split('/')[-1]}"
            else:
                final_url = BASE_URL

            post_data = {
                "id": content_id,
                "content_id": content_id,
                "title": item.get("title", "Untitled"),
                "content_type": item.get("contentType", content_type),
                "likes_count": item.get("likesCount", 0),
                "comments_count": item.get("commentsCount", 0),
                "views_count": item.get("viewsCount", 0) if "viewsCount" in item else None,
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
                "content_group_id": item.get("contentGroupId"),
                "raw_item": item # Keep for debugging
            }
            post_data["is_competition"] = is_competition_post(post_data)
            all_posts.append(post_data)

        print_progress(len(all_posts), len(all_posts), f"Page {page}")

        next_token = result.get("nextToken")
        if not next_token:
            break

        # Small delay to be respectful
        time.sleep(0.5)

    print()  # New line after progress bar
    print_success(f"  Fetched {len(all_posts)} '{content_type}' posts")
    return all_posts


def format_timestamp(ts):
    """Convert epoch timestamp (seconds) to readable date string."""
    if ts is None:
        return "N/A"
    try:
        if isinstance(ts, (int, float)):
            # Could be in seconds or milliseconds
            if ts > 1e12:
                ts = ts / 1000
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        return str(ts)
    except (ValueError, OSError):
        return str(ts)


# ──────────────────────────────────────────────────────────────────────────────
# Step 3: Alternative - Scrape directly from HTML via Selenium
# ──────────────────────────────────────────────────────────────────────────────
def scrape_via_selenium_direct():
    """
    Fallback: Use Selenium to scroll through the page and capture content
    directly from the rendered DOM + intercept network responses.
    """
    print_step("2b", "Using Selenium to scrape content directly from the page...")

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    all_posts = []
    driver = None

    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(60)

        # Inject a script to intercept fetch/XHR responses
        driver.execute_cdp_cmd("Network.enable", {})

        # Visit the posts/articles pages
        for content_type in CONTENT_TYPES:
            page_url = f"{BASE_URL}/posts" if content_type == "post" else BASE_URL
            print_info(f"Loading page for '{content_type}' content...")

            driver.get(page_url)
            time.sleep(5)

            # Scroll down multiple times to trigger lazy loading
            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_count = 0
            max_scrolls = 20

            while scroll_count < max_scrolls:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    # Try clicking "load more" button if present
                    try:
                        load_more = driver.find_elements(By.XPATH, "//button[contains(text(), 'Load more')]")
                        if load_more:
                            load_more[0].click()
                            time.sleep(2)
                        else:
                            break
                    except Exception:
                        break
                last_height = new_height
                scroll_count += 1
                print_progress(scroll_count, max_scrolls, "Scrolling")

            print()

            # Now extract API responses from performance logs
            logs = driver.get_log("performance")
            for log_entry in logs:
                try:
                    msg = json.loads(log_entry["message"])["message"]
                    if msg["method"] == "Network.responseReceived":
                        resp_url = msg["params"]["response"]["url"]
                        if "/cs/content" in resp_url:
                            request_id = msg["params"]["requestId"]
                            try:
                                body = driver.execute_cdp_cmd(
                                    "Network.getResponseBody",
                                    {"requestId": request_id}
                                )
                                data = json.loads(body.get("body", "{}"))
                                feed_contents = data.get("feedContents", [])

                                for item in feed_contents:
                                    post = {
                                        "id": item.get("contentId", "N/A"),
                                        "title": item.get("title", "Untitled"),
                                        "content_type": item.get("contentType", content_type),
                                        "likes_count": item.get("likesCount", 0),
                                        "comments_count": item.get("commentsCount", 0),
                                        "views_count": item.get("viewsCount"),
                                        "created_at": format_timestamp(item.get("createdAt")),
                                        "last_published_at": format_timestamp(item.get("lastPublishedAt")),
                                        "uri": item.get("uri", ""),
                                        "url": f"{BASE_URL}{item.get('uri', '')}",
                                        "status": item.get("status", ""),
                                        "locale": item.get("locale", ""),
                                        "author_alias": (item.get("author", {}) or {}).get("alias", "N/A"),
                                        "author_name": (item.get("author", {}) or {}).get("preferredName", "N/A"),
                                        "follow_count": item.get("followCount", 0),
                                    }
                                    # Avoid duplicates
                                    if not any(p["id"] == post["id"] for p in all_posts):
                                        all_posts.append(post)

                            except Exception:
                                pass
                except (json.JSONDecodeError, KeyError):
                    continue

            print_success(f"Captured {len(all_posts)} posts so far")

    except Exception as e:
        print_error(f"Selenium scraping error: {e}")
    finally:
        if driver:
            driver.quit()

    return all_posts


# ──────────────────────────────────────────────────────────────────────────────
# Step 4: Display & Save Results
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
    print(f"  {Colors.DIM}Note: All posts are shown, competition posts are highlighted.{Colors.RESET}")
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

        # Color code by likes
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
        if HIGHLIGHT_POST_URI and (
            HIGHLIGHT_POST_URI in uri
            or HIGHLIGHT_POST_URI.rstrip("/") == uri.rstrip("/")
            or post.get("id", "") in HIGHLIGHT_POST_URI
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
        print(f"  {Colors.BOLD}Top:{Colors.RESET}      {Colors.GREEN}{pct_top:.1f}%{Colors.RESET} (top {pct_top:.1f}% of all posts)")
        print(f"  {Colors.BOLD}ID:{Colors.RESET}       {highlight_post.get('id', 'N/A')}")
        print(f"  {Colors.BOLD}URL:{Colors.RESET}      {highlight_post.get('url', 'N/A')}")
        print(f"  {Colors.BOLD}Date:{Colors.RESET}     {highlight_post.get('created_at', 'N/A')}")
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
        print(f"    It may not have been loaded in the current feed pages.")

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

    # Save JSON
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_JSON)
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(sorted_posts, f, indent=2, ensure_ascii=False)
        print_success(f"JSON saved to: {json_path}")
    except Exception as e:
        print_error(f"Failed to save JSON: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    print_banner()

    all_posts = []

    # ── Method 1: Try API-based approach ──
    print_step(1, "Attempting to fetch session token and use the REST API...")
    session_token, cookies = get_session_token_selenium()

    session = create_session(session_token, cookies)

    print_step(2, "Fetching posts from all content types via API...")

    api_success = False
    for content_type in CONTENT_TYPES:
        posts = fetch_all_posts(session, content_type)
        if posts:
            all_posts.extend(posts)
            api_success = True

    # ── Method 2: Fallback to direct Selenium scraping ──
    if not api_success:
        print_info("API approach didn't return results. Falling back to Selenium scraping...")
        selenium_posts = scrape_via_selenium_direct()
        all_posts.extend(selenium_posts)

    # ── Display & Save ──
    if all_posts:
        print_step(3, "Processing and displaying results...")
        sorted_posts = display_results(all_posts)

        print_step(4, "Saving results to files...")
        save_results(sorted_posts)
    else:
        print_error("No posts could be retrieved.")
        print_info("This may be because:")
        print_info("  1. Chrome/ChromeDriver is not installed")
        print_info("  2. The website requires login for API access")
        print_info("  3. The website structure has changed")
        print_info("")
        print_info("To fix: Make sure Chrome is installed, or try logging into")
        print_info("builder.aws.com in your browser first.")

    print(f"\n{Colors.CYAN}{'=' * 100}{Colors.RESET}")
    print(f"{Colors.BOLD}  Done!{Colors.RESET}\n")


if __name__ == "__main__":
    main()