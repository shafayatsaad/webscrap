"""
AWS Builder Center - Live Dynamic Dashboard (v10.1 - Reliable + Full Data)
==========================================================================
Robust scraper with Chrome crash recovery, retries, and memory optimization.
Now scrapes all feed pages (/posts, /articles) to ensure 60+ posts are found.
Never shows empty state — always falls back to cached data.

Run locally:  python dashboard.py
Deploy:       gunicorn dashboard:app --bind 0.0.0.0:$PORT
"""

import json
import os
import sys
import time
import threading
import traceback
from datetime import datetime

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from flask import Flask, jsonify, render_template_string

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aws_scraper import (
    CONTENT_TYPES, HIGHLIGHT_POST_URI, BASE_URL,
    is_competition_post, format_timestamp,
)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

app = Flask(__name__)

scrape_data = {
    "posts": [], "last_updated": None,
    "is_scraping": False, "error": None, "logs": [],
}
data_lock = threading.Lock()
AUTO_INTERVAL = 300
JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aws_builder_likes.json")

COMP_KW = ["aideas", "ai ideas", "healthcare", "wellness", "competition",
           "kiro", "mimamori", "satya", "mindbridge", "fitlens",
           "vantedge", "preflight", "anukriti", "orpheus", "studybuddy",
           "renew", "nova", "serverless", "ai governance", "ai-powered"]


def tag_comp(p):
    if p.get("is_competition") is True:
        return p
    try:
        c = is_competition_post(p)
    except Exception:
        c = False
    if not c:
        t = (p.get("title") or "").lower()
        c = any(kw in t for kw in COMP_KW)
    p["is_competition"] = c
    return p


def load_cached():
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                posts = json.load(f)
            return [tag_comp(p) for p in posts], \
                   datetime.fromtimestamp(os.path.getmtime(JSON_PATH)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return [], None


def lg(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    with data_lock:
        scrape_data["logs"].append(f"[{ts}] {msg}")
        if len(scrape_data["logs"]) > 30:
            scrape_data["logs"] = scrape_data["logs"][-30:]
    print(f"[{ts}] {msg}")


def make_driver():
    """Create a lightweight Chrome driver optimized for low-memory environments."""
    o = Options()
    o.add_argument("--headless=new")
    o.add_argument("--no-sandbox")
    o.add_argument("--disable-dev-shm-usage")
    o.add_argument("--disable-gpu")
    o.add_argument("--disable-extensions")
    o.add_argument("--disable-software-rasterizer")
    o.add_argument("--disable-background-networking")
    o.add_argument("--disable-default-apps")
    o.add_argument("--disable-sync")
    o.add_argument("--disable-translate")
    o.add_argument("--no-first-run")
    o.add_argument("--disable-features=VizDisplayCompositor")
    o.add_argument("--blink-settings=imagesEnabled=false")
    o.add_argument("--window-size=1280,720")
    o.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    o.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    d = webdriver.Chrome(options=o)
    d.set_page_load_timeout(20)
    d.set_script_timeout(10)
    return d


def extract_posts_from_logs(driver):
    """Extract post data from Chrome network performance logs."""
    posts = []
    try:
        logs = driver.get_log("performance")
    except Exception:
        return posts

    for entry in logs:
        try:
            msg = json.loads(entry["message"])["message"]
            if msg["method"] != "Network.responseReceived":
                continue
            url = msg["params"]["response"]["url"]
            if "/cs/content" not in url:
                continue
            rid = msg["params"]["requestId"]
            try:
                body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid})
                data = json.loads(body.get("body", "{}"))
                for item in data.get("feedContents", []):
                    cid = item.get("contentId", "")
                    uri = item.get("uri", "")
                    url_ = f"{BASE_URL}{uri}" if uri else (f"{BASE_URL}/content/{cid.split('/')[-1]}" if cid else BASE_URL)
                    post = {
                        "id": cid, "title": item.get("title", "Untitled"),
                        "content_type": item.get("contentType", ""),
                        "likes_count": item.get("likesCount", 0),
                        "comments_count": item.get("commentsCount", 0),
                        "views_count": item.get("viewsCount"),
                        "created_at": format_timestamp(item.get("createdAt")),
                        "last_published_at": format_timestamp(item.get("lastPublishedAt")),
                        "uri": uri, "url": url_,
                        "status": item.get("status", ""),
                        "locale": item.get("locale", ""),
                        "author_alias": (item.get("author") or {}).get("alias", "N/A"),
                        "author_name": (item.get("author") or {}).get("preferredName", "N/A"),
                        "follow_count": item.get("followCount", 0),
                    }
                    if not any(p["id"] == post["id"] for p in posts):
                        posts.append(post)
            except Exception:
                pass
        except (json.JSONDecodeError, KeyError):
            continue
    return posts


import requests

def scrape_once():
    """Single scrape attempt. Returns list of posts or empty list."""
    driver = None
    all_posts = []
    target_headers = {}
    cookies = []
    try:
        driver = make_driver()
        driver.execute_cdp_cmd("Network.enable", {})

    try:
        driver = make_driver()
        driver.set_script_timeout(30)
        lg("Loading builder.aws.com to establish trusted session...")
        driver.get(BASE_URL)
        time.sleep(4)

        # Trigger one random UI scroll to naturalize session
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        lg("Auth session established. Fetching all paginated data via CDP injection...")
        
        # Inject JavaScript to fetch all pages naturally using the browser's own networking
        fetch_js = """
        var done = arguments[0];
        
        async function fetchAll() {
            try {
                // Find token either in localStorage or cookies if needed, though fetch will auto-attach cookies
                let t = localStorage.getItem('builder-session-token');
                if (!t) {
                    let keys = Object.keys(localStorage);
                    for(let k of keys) {
                        if(localStorage[k].includes('eyJ')) t = localStorage[k];
                    }
                }
                
                let headers = {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                };
                if (t) headers['builder-session-token'] = t;

                let all_items = [];
                for (let type of ['article', 'post', 'wish']) {
                    let nextToken = null;
                    while (true) {
                        let payload = { contentType: type, pageSize: 100 };
                        if (nextToken) payload.nextToken = nextToken;
                        
                        let res = await fetch('/cs/content/feed', {
                            method: 'POST',
                            headers: headers,
                            body: JSON.stringify(payload)
                        });
                        
                        if (!res.ok) break;
                        let data = await res.json();
                        let items = data.feedContents || [];
                        all_items.push(...items);
                        
                        nextToken = data.nextToken;
                        if (!nextToken) break;
                        await new Promise(r => setTimeout(r, 600)); // sleep gently
                    }
                }
                done({success: true, data: all_items});
            } catch (e) {
                done({success: false, error: e.toString()});
            }
        }
        
        fetchAll();
        """
        
        res = driver.execute_async_script(fetch_js)
        
        if res and res.get('success'):
            raw_items = res.get('data', [])
            lg(f"JS Fetch complete. Extracted {len(raw_items)} raw objects.")
            
            for item in raw_items:
                cid = item.get("contentId", "")
                uri = item.get("uri", "")
                url_ = f"{BASE_URL}{uri}" if uri else (f"{BASE_URL}/content/{cid.split('/')[-1]}" if cid else BASE_URL)
                
                post = {
                    "id": cid, "title": item.get("title", "Untitled"),
                    "content_type": item.get("contentType", ""),
                    "likes_count": item.get("likesCount", 0),
                    "comments_count": item.get("commentsCount", 0),
                    "views_count": item.get("viewsCount"),
                    "created_at": format_timestamp(item.get("createdAt")),
                    "last_published_at": format_timestamp(item.get("lastPublishedAt")),
                    "uri": uri, "url": url_,
                    "status": item.get("status", ""),
                    "locale": item.get("locale", ""),
                    "author_alias": (item.get("author") or {}).get("alias", "N/A"),
                    "author_name": (item.get("author") or {}).get("preferredName", "N/A"),
                    "follow_count": item.get("followCount", 0),
                }
                if not any(ap["id"] == post["id"] for ap in all_posts):
                    all_posts.append(post)
        else:
            lg(f"JS Fetch failed: {res.get('error') if res else 'Unknown timeout'}")

    except Exception as e:
        lg(f"Chrome error: {type(e).__name__}: {str(e)[:80]}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return all_posts


def run_scraper():
    global scrape_data
    with data_lock:
        if scrape_data["is_scraping"]:
            return
        scrape_data["is_scraping"] = True
        scrape_data["error"] = None

    lg("--- Scrape started ---")
    t0 = time.time()

    # Try up to 3 times with short delays
    posts = []
    for attempt in range(1, 4):
        lg(f"Attempt {attempt}/3...")
        posts = scrape_once()
        if posts:
            break
        if attempt < 3:
            lg(f"Attempt {attempt} failed, retrying in 5s...")
            time.sleep(5)

    if posts:
        sorted_p = sorted(posts, key=lambda x: x.get("likes_count", 0), reverse=True)
        seen = set()
        unique = []
        for p in sorted_p:
            pid = p.get("id", "")
            if pid and pid not in seen:
                p.pop("raw_item", None)
                tag_comp(p)
                seen.add(pid)
                unique.append(p)

        try:
            with open(JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(unique, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        comp_n = sum(1 for p in unique if p.get("is_competition"))
        elapsed = int(time.time() - t0)
        with data_lock:
            scrape_data["posts"] = unique
            scrape_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            scrape_data["error"] = None
        lg(f"Done! {len(unique)} posts ({comp_n} comp) in {elapsed}s. Top: {unique[0]['likes_count']} likes")
    else:
        # NEVER show empty state — keep existing data
        elapsed = int(time.time() - t0)
        err = f"Scrape failed after 3 attempts ({elapsed}s). Using cached data."
        with data_lock:
            scrape_data["error"] = err
            # Don't clear posts — keep old data visible
        lg(err)

    with data_lock:
        scrape_data["is_scraping"] = False


def auto_loop():
    time.sleep(10)
    while True:
        try:
            run_scraper()
        except Exception as e:
            print(f"[AUTO] Error: {e}")
        time.sleep(AUTO_INTERVAL)


# ── Routes ──
@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/data")
def api_data():
    with data_lock:
        posts = list(scrape_data["posts"])
        upd = scrape_data["last_updated"]
        busy = scrape_data["is_scraping"]
        err = scrape_data["error"]
        logs = list(scrape_data["logs"][-12:])

    posts = [tag_comp(p) for p in posts]
    total_likes = sum(p.get("likes_count", 0) for p in posts)
    comp_posts = [p for p in posts if p.get("is_competition")]

    hl_rank = hl_post = hl_comp = None
    nearby = []
    climb = 0

    for idx, p in enumerate(posts, 1):
        pid = (p.get("id") or "").lower()
        puri = (p.get("uri") or "").lower()
        ptitle = (p.get("title") or "").lower()
        hl = HIGHLIGHT_POST_URI.lower() if HIGHLIGHT_POST_URI else ""
        is_hl = (hl and pid and pid in hl) or (hl and puri and puri in hl) or \
                ("aideas" in ptitle and "transforming healthcare" in ptitle)
        if is_hl:
            hl_rank, hl_post = idx, p
            for ci, cp in enumerate(comp_posts, 1):
                if cp.get("id") == p.get("id"):
                    hl_comp = ci; break
            if idx > 1:
                ab = posts[idx-2].copy(); ab["rank"] = idx-1; nearby.append(ab)
                climb = ab.get("likes_count",0) - p.get("likes_count",0) + 1
            if idx < len(posts):
                bl = posts[idx].copy(); bl["rank"] = idx+1; nearby.append(bl)
            break

    return jsonify({
        "posts": posts, "last_updated": upd, "is_scraping": busy,
        "error": err, "logs": logs,
        "highlight_rank": hl_rank, "highlight_post": hl_post,
        "highlight_comp_rank": hl_comp, "nearby_posts": nearby,
        "likes_to_climb": max(0, climb) if hl_rank and hl_rank > 1 else 0,
        "stats": {
            "total_posts": len(posts), "comp_posts": len(comp_posts),
            "total_likes": total_likes,
            "avg_likes": round(total_likes / max(len(posts),1), 1),
            "max_likes": max((p.get("likes_count",0) for p in posts), default=0),
        }
    })


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    with data_lock:
        if scrape_data["is_scraping"]:
            return jsonify({"status": "already_running"})
    threading.Thread(target=run_scraper, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/logs")
def api_logs():
    with data_lock:
        return jsonify({"logs": list(scrape_data["logs"][-30:]),
                        "busy": scrape_data["is_scraping"]})


# ═══════════════════════════════════════════
# HTML Dashboard
# ═══════════════════════════════════════════
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>AWS Builder Rankings</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root{--bg:#050a14;--cd:#111827;--cd2:#1a2236;--a:#ff9900;--gw:rgba(255,153,0,.3);--g:#10b981;--b:#3b82f6;--r:#ef4444;--t:#f3f4f6;--t2:#9ca3af;--t3:#6b7280;--bd:#1f2937;--rd:14px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Outfit',sans-serif;background:var(--bg);color:var(--t);min-height:100vh;line-height:1.5}
.mesh{position:fixed;inset:0;z-index:-1;background:var(--bg);background-image:radial-gradient(at 15% 0%,rgba(255,153,0,.07) 0,transparent 50%),radial-gradient(at 85% 100%,rgba(59,130,246,.05) 0,transparent 50%)}
.w{max-width:940px;margin:0 auto;padding:16px 14px 0;min-height:100vh;display:flex;flex-direction:column}
.hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:10px}
.hdr h1{font-size:20px;font-weight:900;background:linear-gradient(135deg,#fff 20%,var(--a));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.hm{display:flex;align-items:center;gap:6px;margin-top:3px;flex-wrap:wrap}
.dot{width:6px;height:6px;background:var(--g);border-radius:50%;animation:pls 2s infinite}
@keyframes pls{0%,100%{opacity:1}50%{opacity:.4}}
.mt{font-size:10px;color:var(--t3);font-weight:600}
.ubtn{background:linear-gradient(135deg,var(--a),#e68a00);color:#000;border:none;padding:9px 18px;border-radius:11px;font-family:'Outfit';font-size:12px;font-weight:800;cursor:pointer;display:flex;align-items:center;gap:7px;box-shadow:0 4px 18px var(--gw);transition:all .2s}
.ubtn:hover{transform:translateY(-1px)}
.ubtn:active{transform:scale(.97)}
.ubtn:disabled{opacity:.5;cursor:not-allowed;transform:none}
.sp{width:14px;height:14px;border:2px solid rgba(0,0,0,.2);border-top-color:#000;border-radius:50%;animation:s .6s linear infinite;display:inline-block}
@keyframes s{to{transform:rotate(360deg)}}
.sb{background:var(--cd);border:1px solid var(--bd);border-radius:10px;padding:8px 12px;margin-bottom:12px;font-size:11px;display:flex;align-items:center;gap:8px;color:var(--t2)}
.sb.err{border-color:var(--r);color:var(--r)}
.sb.busy{border-color:var(--a);color:var(--a)}
.proj{background:linear-gradient(135deg,var(--cd2),var(--cd));border:1px solid var(--bd);border-radius:var(--rd);padding:14px 16px;margin-bottom:12px;display:flex;align-items:center;gap:14px}
.proj-i{font-size:26px}.proj-b{flex:1;min-width:0}
.proj-n{font-size:14px;font-weight:800;color:#fff}
.proj-d{font-size:10px;color:var(--t2);margin-top:1px;line-height:1.3}
.proj-a{font-size:10px;color:var(--t3);margin-top:2px}
.proj-a strong{color:var(--a);font-weight:700}
.sts{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:12px}
@media(min-width:600px){.sts{grid-template-columns:repeat(5,1fr)}}
.st{background:var(--cd);border:1px solid var(--bd);padding:11px;border-radius:var(--rd);text-align:center}
.sl{font-size:8px;color:var(--t3);text-transform:uppercase;font-weight:800;letter-spacing:.6px}
.sv{font-size:20px;font-weight:800;margin-top:1px}
.hl{background:linear-gradient(145deg,#1a263d,#0f172a);border:2px solid var(--a);border-radius:var(--rd);padding:16px;margin-bottom:12px;box-shadow:0 0 35px var(--gw);position:relative;overflow:hidden}
.hl::before{content:'';position:absolute;top:-50%;right:-20%;width:200px;height:200px;background:radial-gradient(circle,rgba(255,153,0,.08),transparent 70%);pointer-events:none}
.hl-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}
.hl-bg{background:var(--a);color:#000;padding:3px 10px;font-size:9px;font-weight:800;border-radius:6px;text-transform:uppercase}
.hl-rk{font-size:46px;font-weight:900;color:var(--a);line-height:1;text-shadow:0 0 30px var(--gw)}
.hl-ti{font-size:14px;font-weight:700;color:#fff;margin-bottom:10px}
.hl-row{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px}
.hsl{display:block;font-size:8px;color:var(--t3);font-weight:800;text-transform:uppercase}
.hsv{font-size:16px;font-weight:800;color:#fff}
.ctx{border-top:1px solid rgba(255,255,255,.06);padding-top:10px}
.ctx-h{font-size:9px;font-weight:800;color:var(--a);text-transform:uppercase;margin-bottom:5px}
.ctx-r{display:flex;justify-content:space-between;align-items:center;font-size:11px;background:rgba(255,255,255,.03);padding:5px 10px;border-radius:6px;margin-bottom:3px}
.ctx-r span:last-child{font-weight:800;color:var(--a)}
.clmb{background:rgba(16,185,129,.12);color:var(--g);padding:3px 8px;border-radius:5px;font-size:10px;font-weight:700;margin-top:4px;display:inline-block}
.flt{display:flex;gap:6px;margin-bottom:10px}
.fb{background:var(--cd);border:1px solid var(--bd);color:var(--t2);padding:6px 12px;border-radius:9px;font-size:11px;font-weight:700;cursor:pointer;font-family:'Outfit'}
.fb.on{background:var(--a);color:#000;border-color:var(--a)}
.ri{background:var(--cd);border:1px solid var(--bd);border-radius:var(--rd);padding:11px 13px;display:flex;align-items:center;gap:11px;margin-bottom:6px;transition:border-color .2s}
.ri:hover{border-color:rgba(255,255,255,.1)}
.ri.mine{border-color:var(--a);background:rgba(255,153,0,.04)}
.rn{width:30px;font-size:15px;font-weight:900;color:var(--t3);text-align:center;flex-shrink:0}
.rb{flex:1;min-width:0}
.rt{font-size:12px;font-weight:700;color:var(--t);text-decoration:none;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rt:hover{color:var(--a)}
.rm{font-size:9px;color:var(--t3);display:flex;gap:6px;margin-top:1px;align-items:center}
.rc{color:var(--b);font-weight:800;font-size:8px;text-transform:uppercase;background:rgba(59,130,246,.1);padding:1px 4px;border-radius:3px}
.rl{text-align:right;flex-shrink:0}
.rv{font-size:15px;font-weight:800;color:var(--a);display:block;line-height:1}
.rll{font-size:7px;color:var(--t3);text-transform:uppercase;font-weight:700}
.ft{margin-top:auto;padding:18px 0 12px;border-top:1px solid var(--bd);text-align:center}
.ft-by{font-size:11px;color:var(--t3);font-weight:600;margin-bottom:5px}
.ft-by a{color:var(--a);text-decoration:none;font-weight:700}
.ft-by a:hover{text-decoration:underline}
.fl{display:flex;justify-content:center;gap:12px}
.fl a{color:var(--t3);text-decoration:none;font-size:10px;font-weight:600;transition:color .2s;display:flex;align-items:center;gap:3px}
.fl a:hover{color:var(--a)}
.fl svg{width:12px;height:12px;fill:currentColor}
#ov{position:fixed;inset:0;background:var(--bg);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:1000;gap:12px}
.ld{width:28px;height:28px;border:3px solid var(--bd);border-top-color:var(--a);border-radius:50%;animation:s 1s linear infinite}
.ltg{font-size:9px;color:var(--t3);cursor:pointer;text-decoration:underline;margin-top:4px}
.lp{background:#0c1324;border:1px solid var(--bd);border-radius:8px;padding:6px 8px;margin-top:4px;font-size:9px;color:var(--t3);font-family:monospace;max-height:100px;overflow-y:auto;display:none}
.lp.sh{display:block}
</style>
</head>
<body>
<div class="mesh"></div>
<div id="ov"><div class="ld"></div><div style="font-size:12px;font-weight:700;color:var(--t2)">Loading...</div></div>
<div class="w">
<div class="hdr"><div><h1>AWS Builder Rankings</h1><div class="hm"><div class="dot"></div><span class="mt" id="ut">Starting...</span><span class="mt" id="ns"></span></div></div>
<button class="ubtn" id="ub" onclick="doRefresh()"><span id="utx">&#x21bb; Update Now</span></button></div>
<div class="sb" id="sb" style="display:none"></div>
<div class="proj"><div class="proj-i">🏥</div><div class="proj-b"><div class="proj-n">AIdeas: Transforming Healthcare into AI-Powered Wellness Companion</div><div class="proj-d">AI-powered wellness platform leveraging AWS services for proactive, personalized healthcare.</div><div class="proj-a">By <strong>Md. Shafayat Sadat Saad</strong> (@saad30) — AWS Builder Competition 2026</div></div></div>
<div class="sts">
<div class="st"><div class="sl">Posts</div><div class="sv" id="sP">--</div></div>
<div class="st"><div class="sl">Competition</div><div class="sv" id="sC">--</div></div>
<div class="st"><div class="sl">Total Likes</div><div class="sv" id="sL">--</div></div>
<div class="st"><div class="sl">Top Likes</div><div class="sv" id="sM">--</div></div>
<div class="st"><div class="sl">Average</div><div class="sv" id="sA">--</div></div>
</div>
<div id="hlBox"></div>
<div class="flt"><button class="fb on" id="fA" onclick="setF('all')">All Posts</button><button class="fb" id="fC" onclick="setF('comp')">Competition</button></div>
<div id="list"></div>
<div class="ltg" id="lt" onclick="toggleLog()" style="display:none">Show scraper log</div>
<div class="lp" id="lp"></div>
<div class="ft">
<div class="ft-by">Developed by <a href="https://shafayatsaad.vercel.app/" target="_blank">Shafayat Saad</a></div>
<div class="fl">
<a href="https://www.linkedin.com/in/shafayatsaad/" target="_blank"><svg viewBox="0 0 24 24"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>LinkedIn</a>
<a href="https://github.com/shafayatsaad" target="_blank"><svg viewBox="0 0 24 24"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>GitHub</a>
<a href="https://shafayatsaad.vercel.app/" target="_blank"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>Portfolio</a>
</div></div>
</div>
<script>
let f='all',D=null;
function setF(v){f=v;document.querySelectorAll('.fb').forEach(b=>b.classList.remove('on'));document.getElementById(v==='all'?'fA':'fC').classList.add('on');renderList()}
function toggleLog(){const p=document.getElementById('lp');p.classList.toggle('sh');document.getElementById('lt').textContent=p.classList.contains('sh')?'Hide scraper log':'Show scraper log'}
async function loadData(){try{const r=await fetch('/api/data');D=await r.json();document.getElementById('ov').style.display='none';render()}catch(e){console.error(e)}}
function render(){
if(!D)return;
const{stats:s,highlight_post:hp,highlight_rank:hr,highlight_comp_rank:hcr,nearby_posts:nb,likes_to_climb:lc,posts,error,is_scraping,logs}=D;
document.getElementById('sP').textContent=s.total_posts;
document.getElementById('sC').textContent=s.comp_posts;
document.getElementById('sL').textContent=s.total_likes;
document.getElementById('sM').textContent=s.max_likes;
document.getElementById('sA').textContent=s.avg_likes;
if(D.last_updated)document.getElementById('ut').textContent='Scraped: '+D.last_updated;
const sb=document.getElementById('sb');
if(is_scraping){sb.style.display='flex';sb.className='sb busy';sb.innerHTML='<div class="sp"></div> Scraping builder.aws.com (may take ~30s)...'}
else if(error){sb.style.display='flex';sb.className='sb err';sb.textContent='⚠ '+error}
else{sb.style.display='none'}
if(logs&&logs.length>0){document.getElementById('lt').style.display='block';document.getElementById('lp').innerHTML=logs.map(l=>'<div>'+l+'</div>').join('')}
const box=document.getElementById('hlBox');
if(hp&&hr){
const pct=((hr/posts.length)*100).toFixed(1);
let cx='';
if(nb&&nb.length>0){cx=`<div class="ctx"><div class="ctx-h">Rank Neighborhood</div>${nb.map(n=>`<div class="ctx-r"><span>#${n.rank} ${(n.title||'').length>28?(n.title||'').substring(0,25)+'...':n.title||''}</span><span>${n.likes_count} likes</span></div>`).join('')}${lc>0?`<div class="clmb">🚀 ${lc} more like${lc>1?'s':''} to reach #${hr-1}</div>`:''}</div>`}
box.innerHTML=`<div class="hl"><div class="hl-top"><div class="hl-bg">Your Post</div><div class="hl-rk">#${hr}</div></div><div class="hl-ti">${hp.title}</div><div class="hl-row"><div><span class="hsl">Likes</span><span class="hsv">${hp.likes_count}</span></div><div><span class="hsl">Overall</span><span class="hsv">Top ${pct}%</span></div><div><span class="hsl">Comp Rank</span><span class="hsv">#${hcr||'?'}/${s.comp_posts}</span></div></div>${cx}</div>`}
renderList()}
function renderList(){
if(!D)return;
const posts=D.posts,hp=D.highlight_post;
const items=f==='all'?posts:posts.filter(p=>p.is_competition);
if(!items.length){document.getElementById('list').innerHTML='<div style="text-align:center;padding:20px;color:var(--t3)">No posts found.</div>';return}
document.getElementById('list').innerHTML=items.map(p=>{
const r=posts.indexOf(p)+1,me=hp&&p.id===hp.id;
const m=r===1?'🥇':r===2?'🥈':r===3?'🥉':r;
const au=[p.author_alias&&p.author_alias!=='N/A'?'@'+p.author_alias:'',p.author_name&&p.author_name!=='N/A'?p.author_name:''].filter(Boolean).join(' · ');
return`<div class="ri ${me?'mine':''}"><div class="rn" ${r<=3?'style="color:#fff"':''}>${m}</div><div class="rb"><a href="${p.url||'#'}" target="_blank" class="rt">${p.title||'Untitled'}</a><div class="rm"><span>${au}</span>${p.is_competition?'<span class="rc">Competition</span>':''}</div></div><div class="rl"><span class="rv">${p.likes_count}</span><span class="rll">likes</span></div></div>`}).join('')}
async function doRefresh(){
const b=document.getElementById('ub'),t=document.getElementById('utx');
b.disabled=true;t.innerHTML='<div class="sp"></div> Scraping...';
try{await fetch('/api/refresh',{method:'POST'});
let n=0;const iv=setInterval(async()=>{n++;
try{const r=await fetch('/api/data');D=await r.json();render();
if(!D.is_scraping||n>120){clearInterval(iv);b.disabled=false;t.innerHTML=D.error?'⚠ Retry':'&#x21bb; Update Now'}}
catch(e){if(n>120){clearInterval(iv);b.disabled=false;t.innerHTML='&#x21bb; Update Now'}}},2000)}
catch(e){b.disabled=false;t.innerHTML='&#x21bb; Update Now'}}
let cd=300;
setInterval(()=>{cd--;if(cd<=0)cd=300;const m=Math.floor(cd/60),s=cd%60;const e=document.getElementById('ns');if(e)e.textContent='· Auto in '+m+':'+s.toString().padStart(2,'0')},1000);
setInterval(loadData,30000);
loadData();
</script>
</body></html>"""

# ── Startup ──
cached, ct = load_cached()
if cached:
    scrape_data["posts"] = cached
    scrape_data["last_updated"] = ct

threading.Thread(target=auto_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
