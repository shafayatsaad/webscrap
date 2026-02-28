"""
AWS Builder Center Post Likes Scraper (v11 - JS WAF Bypass)
===========================================================
Scrapes https://builder.aws.com to find all posts and their like counts,
displaying them sorted from highest to lowest likes.

Uses native JavaScript injected into a headless Chrome browser
to bypass the 20-post restriction and WAF blocking API POST requests.
"""

import json
import time
import csv
import os
import sys
from datetime import datetime, timezone

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
BASE_URL = "https://builder.aws.com"
OUTPUT_CSV = "aws_builder_likes.csv"
OUTPUT_JSON = "dist/aws_builder_likes.json"

HIGHLIGHT_POST_URI = "/content/3AAMRb7lRzAJnleldfYBBtfM1WG/aideas-transforming-healthcare-into-ai-powered-wellness-companion"
COMPETITION_KEYWORDS = [
    "AIdeas", "AWS 10,000", "AWS 10000", "Ideathon", "aideas-2025"
]

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
    AWS Builder Center - Post Likes Scraper v11 (WAF Evasion)
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


def format_timestamp(ts):
    if not ts: return "N/A"
    try:
        if isinstance(ts, (int, float)):
            if ts > 1e12: ts = ts / 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        return str(ts)
    except:
        return str(ts)

def extract_region(item):
    regions = ["EMEA", "NAMER", "APJC", "LATAM", "GCR", "ANZ"]
    text_sources = [item.get("title", ""), str(item.get("spaceName", ""))]
    ad = item.get("contentTypeSpecificResponse", {}).get("article", {})
    text_sources.extend([ad.get("markdownDescription", "")] + list(ad.get("tags", [])))
    text = " ".join([str(t) for t in text_sources]).upper()
    for r in regions:
        if f"#{r}" in text or r in text: return r
    return "Global"

def is_competition_post(post, raw_item=None):
    uri = (post.get("uri", "") or "").lower()
    cid = (post.get("id", "") or "").lower()
    if HIGHLIGHT_POST_URI and (HIGHLIGHT_POST_URI.lower() in uri or HIGHLIGHT_POST_URI.lower() in cid or post.get("id", "").lower() in HIGHLIGHT_POST_URI.lower()):
        return True
    title = (post.get("title", "") or "").lower()
    for kw in COMPETITION_KEYWORDS:
        if kw.lower() in title: return True
    return False

# ──────────────────────────────────────────────────────────────────────────────
# Selenium Scrape Logic (Same as dashboard.py v10.4)
# ──────────────────────────────────────────────────────────────────────────────
def make_driver():
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--disable-gpu")
    o.add_argument("--disable-extensions")
    o.add_argument("--window-size=1280,720")
    o.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    o.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    d = webdriver.Chrome(options=o)
    d.set_page_load_timeout(60)
    d.set_script_timeout(60)
    return d

def extract_posts_from_logs(driver):
    posts = []
    try:
        logs = driver.get_log("performance")
    except Exception: return []

    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            if msg["method"] != "Network.responseReceived": continue
            url = msg["params"]["response"]["url"]
            if "/cs/content" not in url: continue
            rid = msg["params"]["requestId"]
            try:
                body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid})
                data = json.loads(body.get("body", "{}"))
                for item in data.get("feedContents", []):
                    cid = item.get("contentId", "")
                    uri = item.get("uri", "")
                    url_ = f"{BASE_URL}{uri}" if uri else (f"{BASE_URL}/content/{cid.split('/')[-1]}" if cid else BASE_URL)
                    
                    created_ts = item.get("createdAt")
                    if created_ts and created_ts > 1e12: 
                        created_ts = created_ts / 1000
                    
                    now_ts = datetime.now().timestamp()
                    days_since = max(1, (now_ts - (created_ts or now_ts)) / 86400)
                    likes = item.get("likesCount", 0)
                    velocity = round(likes / days_since, 2)

                    pdata = {
                        "id": cid, "content_id": cid,
                        "title": item.get("title", "Untitled"),
                        "content_type": item.get("contentType", ""),
                        "likes_count": likes,
                        "comments_count": item.get("commentsCount", 0),
                        "views_count": item.get("viewsCount"),
                        "velocity": velocity,
                        "created_ts": created_ts,
                        "created_at": format_timestamp(item.get("createdAt")),
                        "last_published_at": format_timestamp(item.get("lastPublishedAt")),
                        "uri": uri, "url": url_,
                        "status": item.get("status", ""),
                        "region": extract_region(item),
                        "author_alias": (item.get("author") or {}).get("alias", "N/A"),
                        "author_name": (item.get("author") or {}).get("preferredName", "N/A"),
                        "raw_item": item,
                    }
                    pdata["is_competition"] = is_competition_post(pdata, raw_item=item)
                    
                    if not any(p["id"] == pdata["id"] for p in posts):
                        posts.append(pdata)
            except Exception: pass
        except Exception: pass
    return posts

def scrape_feed():
    print_info("Booting Headless Chrome to bypass WAF...")
    driver = None
    all_posts = []
    try:
        driver = make_driver()
        driver.execute_cdp_cmd("Network.enable", {})
        
        url = BASE_URL
        print_info(f"Loading '{url}'...")
        driver.get(url)
        time.sleep(3)

        print_info("Executing JS injection infinite scroll array...")
        scroll_count = 0
        last_h = 0
        while scroll_count < 35:
            driver.execute_script("window.scrollBy(0, window.innerHeight * 0.6);")
            time.sleep(0.8)
            
            js_click = """Array.from(document.querySelectorAll('button')).filter(b => b.textContent.toLowerCase().includes('load more')).forEach(b => b.click());"""
            driver.execute_script(js_click)
            time.sleep(1.0)
            
            new_h = driver.execute_script("return document.body.scrollHeight")
            scroll_pos = driver.execute_script("return window.scrollY + window.innerHeight")
            if scroll_pos >= new_h - 100:
                time.sleep(1)
                if driver.execute_script("return document.body.scrollHeight") == new_h:
                    break
            last_h = new_h
            scroll_count += 1
            print(f"  [.] Scrolling page {scroll_count}/35...")
            
        print()
        all_posts = extract_posts_from_logs(driver)
        driver.execute_cdp_cmd("Network.clearBrowserCache", {})
    except Exception as e:
        print_error(f"Chrome error: {e}")
    finally:
        if driver:
            try: driver.quit()
            except: pass
            
    print_success(f"Intercepted {len(all_posts)} posts.")
    return all_posts

# ──────────────────────────────────────────────────────────────────────────────
def display_results(sorted_posts):
    if not sorted_posts:
        print_error("No posts found!")
        return sorted_posts
    print(f"\n{Colors.CYAN}{'=' * 100}{Colors.RESET}")
    print(f"  {Colors.BOLD}{'#':<5} {'Likes':<8} {'Title'}{Colors.RESET}")
    print(f"  {'-' * 100}")
    
    highlight_rank = None
    for idx, post in enumerate(sorted_posts, 1):
        uri = post.get("uri", "")
        pid = post.get("id", "")
        if HIGHLIGHT_POST_URI and (HIGHLIGHT_POST_URI in uri or pid in HIGHLIGHT_POST_URI):
            highlight_rank = idx
            
        color = Colors.GREEN if post.get('is_competition') else Colors.DIM
        t = post.get('title', 'Untitled')
        if len(t) > 60: t = t[:57] + "..."
        print(f"  {color}{idx:<5} {post.get('likes_count',0):<8} {t}{Colors.RESET}")

    if highlight_rank:
        p = sorted_posts[highlight_rank-1]
        print(f"\n{Colors.BOLD}{Colors.GREEN}  YOUR RANK: #{highlight_rank} out of {len(sorted_posts)} with {p.get('likes_count',0)} likes.{Colors.RESET}")
    return sorted_posts

def save_results(sorted_posts):
    if not sorted_posts: return
    scraped_at = format_timestamp(datetime.now().timestamp())
    os.makedirs("dist", exist_ok=True)
    
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_JSON)
    clean_posts = []
    for p in sorted_posts:
        clean = {k: v for k, v in p.items() if k != "raw_item"}
        clean_posts.append(clean)
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"scraped_at": scraped_at, "posts": clean_posts}, f, indent=2, ensure_ascii=False)
        print_success(f"JSON saved to: {json_path}")
    except Exception as e:
        print_error(f"JSON save error: {e}")

def main():
    print_banner()
    print_step(1, "Starting Selenium payload extraction...")
    posts = scrape_feed()
    
    # Sort and deduplicate
    print_step(2, "Sorting and displaying results...")
    sorted_posts = sorted(posts, key=lambda x: x.get("likes_count", 0), reverse=True)
    seen, unique = set(), []
    for p in sorted_posts:
        if p["id"] not in seen:
            seen.add(p["id"])
            unique.append(p)
            
    display_results(unique)
    
    print_step(3, "Saving out data for Vercel/Netlify dist folder...")
    save_results(unique)

if __name__ == "__main__":
    main()