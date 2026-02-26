"""
AWS Builder Center - Live Dynamic Dashboard (v8 - Final)
=========================================================
Fully dynamic Flask dashboard with real-time scraping.
- Auto-scrape every 5 minutes.
- Manual "Update Now" button for immediate refresh.
- Competition detection always applied.
- Error reporting in UI.

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

# Fix Windows encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from flask import Flask, jsonify, render_template_string

# Import scraper
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aws_scraper import (
    get_session_token_selenium,
    create_session,
    fetch_all_posts,
    scrape_via_selenium_direct,
    CONTENT_TYPES,
    HIGHLIGHT_POST_URI,
    BASE_URL,
    is_competition_post,
)

app = Flask(__name__)

# Global state
scrape_data = {
    "posts": [],
    "last_updated": None,
    "is_scraping": False,
    "error": None,
    "scrape_log": [],  # Last N log messages for debugging
}
data_lock = threading.Lock()
AUTO_SCRAPE_INTERVAL = 300  # 5 minutes

JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aws_builder_likes.json")

# Competition keywords (inline for cached data without is_competition)
COMP_KEYWORDS = ["aideas", "ai ideas", "healthcare", "wellness", "competition",
                 "kiro", "mimamori", "wellness companion", "ai-powered wellness",
                 "wellness avatar", "health ai", "medical ai", "satya",
                 "mindbridge", "fitlens", "vantedge", "preflight", "anukriti",
                 "orpheus", "studybuddy", "renew", "nova", "serverless"]


def detect_competition(post):
    """Ensure is_competition flag is set on a post."""
    if "is_competition" in post and post["is_competition"] is not None:
        return post
    title = (post.get("title") or "").lower()
    post["is_competition"] = any(kw in title for kw in COMP_KEYWORDS)
    return post


def load_cached_data():
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                posts = json.load(f)
            # ALWAYS apply competition detection to cached data
            posts = [detect_competition(p) for p in posts]
            mod_time = os.path.getmtime(JSON_PATH)
            return posts, datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return [], None


def add_log(msg):
    with data_lock:
        scrape_data["scrape_log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(scrape_data["scrape_log"]) > 20:
            scrape_data["scrape_log"] = scrape_data["scrape_log"][-20:]
    print(f"[SCRAPE] {msg}")


def run_scraper():
    """Run the scraper — called by auto-loop or manual button."""
    global scrape_data
    with data_lock:
        if scrape_data["is_scraping"]:
            return
        scrape_data["is_scraping"] = True
        scrape_data["error"] = None

    add_log("Starting scrape...")
    try:
        all_posts = []

        # Step 1: Get session token
        add_log("Launching Chrome to get session token...")
        session_token, cookies = get_session_token_selenium()
        add_log(f"Got session token: {session_token[:20]}..." if session_token else "No token found, using fallback")

        # Step 2: Fetch posts via API
        session = create_session(session_token, cookies)
        for content_type in CONTENT_TYPES:
            add_log(f"Fetching '{content_type}' posts...")
            posts = fetch_all_posts(session, content_type)
            if posts:
                all_posts.extend(posts)
                add_log(f"  Got {len(posts)} {content_type} posts")

        # Step 3: Fallback to direct scraping if API failed
        if not all_posts:
            add_log("API returned no posts. Trying Selenium direct scrape...")
            selenium_posts = scrape_via_selenium_direct()
            all_posts.extend(selenium_posts)
            add_log(f"Selenium fallback got {len(selenium_posts)} posts")

        if all_posts:
            sorted_posts = sorted(all_posts, key=lambda x: x.get("likes_count", 0), reverse=True)
            seen = set()
            unique = []
            for p in sorted_posts:
                pid = p.get("id", "")
                if pid and pid not in seen:
                    p["is_competition"] = is_competition_post(p)
                    p.pop("raw_item", None)
                    seen.add(pid)
                    unique.append(p)

            # Also apply broad keyword detection
            unique = [detect_competition(p) for p in unique]

            try:
                with open(JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump(unique, f, indent=2, ensure_ascii=False)
            except Exception as e:
                add_log(f"Warning: couldn't save JSON: {e}")

            comp_count = sum(1 for p in unique if p.get("is_competition"))
            with data_lock:
                scrape_data["posts"] = unique
                scrape_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                scrape_data["error"] = None
            add_log(f"Done! {len(unique)} posts ({comp_count} competition). Top: {unique[0]['likes_count']} likes")
        else:
            with data_lock:
                scrape_data["error"] = "Scraper returned no posts. The site might be temporarily unavailable."
            add_log("Failed: no posts returned")

    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)}"
        with data_lock:
            scrape_data["error"] = err_msg
        add_log(f"Error: {err_msg}")
        traceback.print_exc()
    finally:
        with data_lock:
            scrape_data["is_scraping"] = False


def auto_scrape_loop():
    """Background loop: scrape every 5 minutes."""
    time.sleep(10)
    while True:
        try:
            run_scraper()
        except Exception as e:
            print(f"[AUTO-SCRAPE] Unexpected error: {e}")
        time.sleep(AUTO_SCRAPE_INTERVAL)


# ── Routes ──
@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/data")
def api_data():
    with data_lock:
        posts = list(scrape_data["posts"])
        last_updated = scrape_data["last_updated"]
        is_scraping = scrape_data["is_scraping"]
        error = scrape_data["error"]
        logs = list(scrape_data["scrape_log"][-10:])

    # Ensure competition flags
    posts = [detect_competition(p) for p in posts]

    total_likes = sum(p.get("likes_count", 0) for p in posts)
    avg_likes = total_likes / len(posts) if posts else 0
    max_likes = max((p.get("likes_count", 0) for p in posts), default=0)

    comp_posts = [p for p in posts if p.get("is_competition")]

    highlight_rank = None
    highlight_post = None
    highlight_comp_rank = None
    nearby_posts = []
    likes_to_climb = 0

    for idx, post in enumerate(posts, 1):
        pid = post.get("id", "")
        puri = post.get("uri", "")
        title_lc = (post.get("title") or "").lower()
        is_hl = False
        if HIGHLIGHT_POST_URI:
            hl_lower = HIGHLIGHT_POST_URI.lower()
            if pid and pid.lower() in hl_lower:
                is_hl = True
            elif puri and puri.lower() in hl_lower:
                is_hl = True
            elif "aideas" in title_lc and "transforming healthcare" in title_lc:
                is_hl = True

        if is_hl:
            highlight_rank = idx
            highlight_post = post

            for ci, cp in enumerate(comp_posts, 1):
                if cp.get("id") == pid:
                    highlight_comp_rank = ci
                    break

            if idx > 1:
                above = posts[idx - 2].copy()
                above["rank"] = idx - 1
                nearby_posts.append(above)
                likes_to_climb = above.get("likes_count", 0) - post.get("likes_count", 0) + 1

            if idx < len(posts):
                below = posts[idx].copy()
                below["rank"] = idx + 1
                nearby_posts.append(below)
            break

    return jsonify({
        "posts": posts,
        "last_updated": last_updated,
        "is_scraping": is_scraping,
        "error": error,
        "logs": logs,
        "highlight_rank": highlight_rank,
        "highlight_post": highlight_post,
        "highlight_comp_rank": highlight_comp_rank,
        "nearby_posts": nearby_posts,
        "likes_to_climb": max(0, likes_to_climb) if highlight_rank and highlight_rank > 1 else 0,
        "stats": {
            "total_posts": len(posts),
            "comp_posts": len(comp_posts),
            "total_likes": total_likes,
            "avg_likes": round(avg_likes, 1),
            "max_likes": max_likes,
        }
    })


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    with data_lock:
        if scrape_data["is_scraping"]:
            return jsonify({"status": "already_running"})

    thread = threading.Thread(target=run_scraper, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/logs")
def api_logs():
    with data_lock:
        return jsonify({
            "logs": list(scrape_data["scrape_log"][-20:]),
            "is_scraping": scrape_data["is_scraping"],
            "error": scrape_data["error"],
        })


# ── Dashboard HTML ──
DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>AWS Builder Rankings — Live Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #050a14;
            --bg2: #0c1324;
            --card: #111827;
            --card2: #1a2236;
            --accent: #ff9900;
            --accent2: #ffb84d;
            --glow: rgba(255,153,0,0.3);
            --green: #10b981;
            --blue: #3b82f6;
            --red: #ef4444;
            --txt: #f3f4f6;
            --txt2: #9ca3af;
            --txt3: #6b7280;
            --border: #1f2937;
            --r: 14px;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family:'Outfit',sans-serif; background:var(--bg); color:var(--txt); min-height:100vh; line-height:1.5; }
        .mesh { position:fixed; inset:0; z-index:-1;
            background: var(--bg);
            background-image:
                radial-gradient(at 15% 0%, rgba(255,153,0,0.07) 0, transparent 50%),
                radial-gradient(at 85% 100%, rgba(59,130,246,0.05) 0, transparent 50%);
        }
        .wrap { max-width:940px; margin:0 auto; padding:16px 14px 0; min-height:100vh; display:flex; flex-direction:column; }

        /* Header */
        .hdr { display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; flex-wrap:wrap; gap:10px; }
        .hdr-left h1 { font-size:20px; font-weight:900; background:linear-gradient(135deg,#fff 20%,var(--accent)); -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }
        .hdr-meta { display:flex; align-items:center; gap:6px; margin-top:3px; flex-wrap:wrap; }
        .dot { width:6px; height:6px; background:var(--green); border-radius:50%; animation:pulse 2s infinite; }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        .meta-txt { font-size:10px; color:var(--txt3); font-weight:600; }

        .ubtn {
            background:linear-gradient(135deg, var(--accent), #e68a00); color:#000; border:none;
            padding:9px 20px; border-radius:11px; font-family:'Outfit'; font-size:12px; font-weight:800;
            cursor:pointer; display:flex; align-items:center; gap:7px;
            box-shadow:0 4px 18px var(--glow); transition:all .2s;
        }
        .ubtn:hover { transform:translateY(-1px); box-shadow:0 6px 24px var(--glow); }
        .ubtn:active { transform:scale(.97); }
        .ubtn:disabled { opacity:.5; cursor:not-allowed; transform:none; }
        .spin { width:14px; height:14px; border:2px solid rgba(0,0,0,.2); border-top-color:#000; border-radius:50%; animation:sp .6s linear infinite; display:inline-block; }
        @keyframes sp { to{transform:rotate(360deg)} }

        /* Status Bar */
        .status-bar { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:8px 14px; margin-bottom:14px; font-size:11px; display:flex; align-items:center; gap:8px; color:var(--txt2); }
        .status-bar.error { border-color:var(--red); color:var(--red); }
        .status-bar.scraping { border-color:var(--accent); color:var(--accent); }

        /* Project Info */
        .proj { background:linear-gradient(135deg,var(--card2),var(--card)); border:1px solid var(--border); border-radius:var(--r); padding:14px 16px; margin-bottom:14px; display:flex; align-items:center; gap:14px; }
        .proj-icon { font-size:28px; }
        .proj-body { flex:1; min-width:0; }
        .proj-title { font-size:14px; font-weight:800; color:#fff; }
        .proj-desc { font-size:11px; color:var(--txt2); margin-top:1px; line-height:1.3; }
        .proj-auth { font-size:10px; color:var(--txt3); margin-top:3px; }
        .proj-auth strong { color:var(--accent); font-weight:700; }

        /* Stats */
        .stats { display:grid; grid-template-columns:repeat(2,1fr); gap:8px; margin-bottom:14px; }
        @media(min-width:600px) { .stats { grid-template-columns:repeat(5,1fr); } }
        .st { background:var(--card); border:1px solid var(--border); padding:12px; border-radius:var(--r); text-align:center; }
        .st-l { font-size:8px; color:var(--txt3); text-transform:uppercase; font-weight:800; letter-spacing:.6px; }
        .st-v { font-size:20px; font-weight:800; margin-top:1px; }

        /* Highlight */
        .hl { background:linear-gradient(145deg,#1a263d,#0f172a); border:2px solid var(--accent); border-radius:var(--r); padding:18px; margin-bottom:14px; box-shadow:0 0 35px var(--glow); position:relative; overflow:hidden; }
        .hl::before { content:''; position:absolute; top:-50%; right:-20%; width:200px; height:200px; background:radial-gradient(circle,rgba(255,153,0,0.08),transparent 70%); pointer-events:none; }
        .hl-top { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px; }
        .hl-badge { background:var(--accent); color:#000; padding:3px 10px; font-size:9px; font-weight:800; border-radius:6px; text-transform:uppercase; letter-spacing:.5px; }
        .hl-rank { font-size:48px; font-weight:900; color:var(--accent); line-height:1; text-shadow:0 0 30px var(--glow); }
        .hl-title { font-size:15px; font-weight:700; color:#fff; margin-bottom:12px; }
        .hl-row { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:12px; }
        .hl-sl { display:block; font-size:8px; color:var(--txt3); font-weight:800; text-transform:uppercase; }
        .hl-sv { font-size:17px; font-weight:800; color:#fff; }
        .ctx { border-top:1px solid rgba(255,255,255,.06); padding-top:12px; }
        .ctx-h { font-size:9px; font-weight:800; color:var(--accent); text-transform:uppercase; margin-bottom:6px; letter-spacing:.5px; }
        .ctx-r { display:flex; justify-content:space-between; align-items:center; font-size:11px; background:rgba(255,255,255,.03); padding:6px 10px; border-radius:7px; margin-bottom:4px; }
        .ctx-r span:last-child { font-weight:800; color:var(--accent); font-size:12px; }
        .climb { background:rgba(16,185,129,.12); color:var(--green); padding:3px 9px; border-radius:5px; font-size:10px; font-weight:700; margin-top:5px; display:inline-block; }

        /* Filters */
        .filters { display:flex; gap:6px; margin-bottom:12px; }
        .fb { background:var(--card); border:1px solid var(--border); color:var(--txt2); padding:6px 13px; border-radius:9px; font-size:11px; font-weight:700; cursor:pointer; transition:all .15s; font-family:'Outfit'; }
        .fb.on { background:var(--accent); color:#000; border-color:var(--accent); }

        /* Rankings List */
        .ri { background:var(--card); border:1px solid var(--border); border-radius:var(--r); padding:12px 14px; display:flex; align-items:center; gap:12px; margin-bottom:7px; transition:border-color .2s; }
        .ri:hover { border-color:rgba(255,255,255,.1); }
        .ri.mine { border-color:var(--accent); background:rgba(255,153,0,.04); }
        .ri-rank { width:32px; font-size:16px; font-weight:900; color:var(--txt3); text-align:center; flex-shrink:0; }
        .ri-body { flex:1; min-width:0; }
        .ri-t { font-size:12px; font-weight:700; color:var(--txt); text-decoration:none; display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .ri-t:hover { color:var(--accent); }
        .ri-meta { font-size:9px; color:var(--txt3); display:flex; gap:6px; margin-top:1px; align-items:center; }
        .ri-comp { color:var(--blue); font-weight:800; font-size:8px; text-transform:uppercase; background:rgba(59,130,246,.1); padding:1px 5px; border-radius:4px; }
        .ri-likes { text-align:right; flex-shrink:0; }
        .ri-lv { font-size:16px; font-weight:800; color:var(--accent); display:block; line-height:1; }
        .ri-ll { font-size:7px; color:var(--txt3); text-transform:uppercase; font-weight:700; }

        /* Footer */
        .footer { margin-top:auto; padding:20px 0 14px; border-top:1px solid var(--border); text-align:center; }
        .footer-by { font-size:11px; color:var(--txt3); font-weight:600; margin-bottom:6px; }
        .footer-by a { color:var(--accent); text-decoration:none; font-weight:700; }
        .footer-by a:hover { text-decoration:underline; }
        .f-links { display:flex; justify-content:center; gap:14px; }
        .f-links a { color:var(--txt3); text-decoration:none; font-size:10px; font-weight:600; transition:color .2s; display:flex; align-items:center; gap:3px; }
        .f-links a:hover { color:var(--accent); }
        .f-links svg { width:13px; height:13px; fill:currentColor; }

        /* Overlay */
        #ov { position:fixed; inset:0; background:var(--bg); display:flex; flex-direction:column; align-items:center; justify-content:center; z-index:1000; gap:12px; }
        .ld { width:28px; height:28px; border:3px solid var(--border); border-top-color:var(--accent); border-radius:50%; animation:sp 1s linear infinite; }

        /* Log panel */
        .log-toggle { font-size:10px; color:var(--txt3); cursor:pointer; text-decoration:underline; margin-top:4px; }
        .log-panel { background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:8px 10px; margin-top:6px; font-size:10px; color:var(--txt3); font-family:monospace; max-height:120px; overflow-y:auto; display:none; }
        .log-panel.show { display:block; }
    </style>
</head>
<body>
    <div class="mesh"></div>
    <div id="ov"><div class="ld"></div><div style="font-size:12px;font-weight:700;color:var(--txt2)">Loading Dashboard...</div></div>

    <div class="wrap">
        <!-- Header -->
        <div class="hdr">
            <div class="hdr-left">
                <h1>AWS Builder Rankings</h1>
                <div class="hdr-meta">
                    <div class="dot"></div>
                    <span class="meta-txt" id="updTime">Starting up...</span>
                    <span class="meta-txt" id="nextScrape"></span>
                </div>
            </div>
            <button class="ubtn" id="ubtn" onclick="doRefresh()">
                <span id="utext">&#x21bb; Update Now</span>
            </button>
        </div>

        <!-- Status bar (shows scraper errors/status) -->
        <div class="status-bar" id="statusBar" style="display:none"></div>

        <!-- Project Info -->
        <div class="proj">
            <div class="proj-icon">🏥</div>
            <div class="proj-body">
                <div class="proj-title">AIdeas: Transforming Healthcare into AI-Powered Wellness Companion</div>
                <div class="proj-desc">An AI-powered wellness platform leveraging AWS services for proactive, personalized healthcare.</div>
                <div class="proj-auth">By <strong>Md. Shafayat Sadat Saad</strong> (@saad30) — AWS Builder Competition 2026</div>
            </div>
        </div>

        <!-- Stats -->
        <div class="stats">
            <div class="st"><div class="st-l">Posts</div><div class="st-v" id="sP">--</div></div>
            <div class="st"><div class="st-l">Competition</div><div class="st-v" id="sC">--</div></div>
            <div class="st"><div class="st-l">Total Likes</div><div class="st-v" id="sL">--</div></div>
            <div class="st"><div class="st-l">Top Likes</div><div class="st-v" id="sM">--</div></div>
            <div class="st"><div class="st-l">Average</div><div class="st-v" id="sA">--</div></div>
        </div>

        <!-- Highlight Card -->
        <div id="hlBox"></div>

        <!-- Filters -->
        <div class="filters">
            <button class="fb on" id="fAll" onclick="setF('all')">All Posts</button>
            <button class="fb" id="fComp" onclick="setF('comp')">Competition</button>
        </div>

        <!-- Rankings List -->
        <div id="list"></div>

        <!-- Debug Log -->
        <div class="log-toggle" id="logToggle" onclick="toggleLog()" style="display:none">Show scraper log</div>
        <div class="log-panel" id="logPanel"></div>

        <!-- Footer -->
        <div class="footer">
            <div class="footer-by">Developed by <a href="https://shafayatsaad.vercel.app/" target="_blank">Shafayat Saad</a></div>
            <div class="f-links">
                <a href="https://www.linkedin.com/in/shafayatsaad/" target="_blank">
                    <svg viewBox="0 0 24 24"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>
                    LinkedIn
                </a>
                <a href="https://github.com/shafayatsaad" target="_blank">
                    <svg viewBox="0 0 24 24"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>
                    GitHub
                </a>
                <a href="https://shafayatsaad.vercel.app/" target="_blank">
                    <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>
                    Portfolio
                </a>
            </div>
        </div>
    </div>

    <script>
        let filter = 'all';
        let D = null;

        function setF(f) {
            filter = f;
            document.querySelectorAll('.fb').forEach(b => b.classList.remove('on'));
            document.getElementById(f==='all'?'fAll':'fComp').classList.add('on');
            renderList();
        }

        function toggleLog() {
            const p = document.getElementById('logPanel');
            p.classList.toggle('show');
            document.getElementById('logToggle').textContent = p.classList.contains('show') ? 'Hide scraper log' : 'Show scraper log';
        }

        async function loadData() {
            try {
                const r = await fetch('/api/data');
                D = await r.json();
                document.getElementById('ov').style.display = 'none';
                render();
            } catch(e) { console.error('Load error:', e); }
        }

        function render() {
            if (!D) return;
            const { stats:s, highlight_post:hp, highlight_rank:hr, highlight_comp_rank:hcr, nearby_posts:nb, likes_to_climb:lc, posts, error, is_scraping, logs } = D;

            // Stats
            document.getElementById('sP').textContent = s.total_posts;
            document.getElementById('sC').textContent = s.comp_posts;
            document.getElementById('sL').textContent = s.total_likes;
            document.getElementById('sM').textContent = s.max_likes;
            document.getElementById('sA').textContent = s.avg_likes;

            // Update time
            if (D.last_updated) {
                document.getElementById('updTime').textContent = 'Last scraped: ' + D.last_updated;
            }

            // Status bar
            const sb = document.getElementById('statusBar');
            if (is_scraping) {
                sb.style.display = 'flex';
                sb.className = 'status-bar scraping';
                sb.innerHTML = '<div class="spin"></div> Scraping builder.aws.com...';
            } else if (error) {
                sb.style.display = 'flex';
                sb.className = 'status-bar error';
                sb.textContent = '⚠ ' + error;
            } else {
                sb.style.display = 'none';
            }

            // Logs
            if (logs && logs.length > 0) {
                document.getElementById('logToggle').style.display = 'block';
                document.getElementById('logPanel').innerHTML = logs.map(l => `<div>${l}</div>`).join('');
            }

            // Highlight
            const box = document.getElementById('hlBox');
            if (hp && hr) {
                const pct = ((hr / posts.length) * 100).toFixed(1);
                let ctxHTML = '';
                if (nb && nb.length > 0) {
                    ctxHTML = `<div class="ctx"><div class="ctx-h">Rank Neighborhood</div>${nb.map(n =>
                        `<div class="ctx-r"><span>#${n.rank} ${(n.title||'').length>30?(n.title||'').substring(0,27)+'...':n.title||''}</span><span>${n.likes_count} likes</span></div>`
                    ).join('')}${lc > 0 ? `<div class="climb">🚀 ${lc} more like${lc>1?'s':''} to reach #${hr-1}</div>` : ''}</div>`;
                }
                box.innerHTML = `<div class="hl">
                    <div class="hl-top"><div class="hl-badge">Your Post</div><div class="hl-rank">#${hr}</div></div>
                    <div class="hl-title">${hp.title}</div>
                    <div class="hl-row">
                        <div><span class="hl-sl">Likes</span><span class="hl-sv">${hp.likes_count}</span></div>
                        <div><span class="hl-sl">Overall</span><span class="hl-sv">Top ${pct}%</span></div>
                        <div><span class="hl-sl">Comp Rank</span><span class="hl-sv">#${hcr||'?'}/${s.comp_posts}</span></div>
                    </div>${ctxHTML}</div>`;
            }

            renderList();
        }

        function renderList() {
            if (!D) return;
            const posts = D.posts;
            const hp = D.highlight_post;
            const items = filter === 'all' ? posts : posts.filter(p => p.is_competition);

            if (items.length === 0) {
                document.getElementById('list').innerHTML = '<div style="text-align:center;padding:24px;color:var(--txt3);font-size:13px">No posts found for this filter.</div>';
                return;
            }

            document.getElementById('list').innerHTML = items.map(p => {
                const r = posts.indexOf(p) + 1;
                const isMe = hp && p.id === hp.id;
                const medal = r===1?'🥇':r===2?'🥈':r===3?'🥉':r;
                const author = [p.author_alias ? '@'+p.author_alias : '', p.author_name && p.author_name !== 'N/A' ? p.author_name : ''].filter(Boolean).join(' · ');
                return `<div class="ri ${isMe?'mine':''}">
                    <div class="ri-rank" ${r<=3?'style="color:#fff;font-size:18px"':''}>${medal}</div>
                    <div class="ri-body">
                        <a href="${p.url||'#'}" target="_blank" class="ri-t">${p.title||'Untitled'}</a>
                        <div class="ri-meta">
                            <span>${author}</span>
                            ${p.is_competition?'<span class="ri-comp">Competition</span>':''}
                        </div>
                    </div>
                    <div class="ri-likes"><span class="ri-lv">${p.likes_count}</span><span class="ri-ll">likes</span></div>
                </div>`;
            }).join('');
        }

        async function doRefresh() {
            const btn = document.getElementById('ubtn');
            const txt = document.getElementById('utext');
            btn.disabled = true;
            txt.innerHTML = '<div class="spin"></div> Scraping...';

            try {
                const res = await fetch('/api/refresh', { method:'POST' });
                const r = await res.json();

                // Poll until scrape completes
                let tries = 0;
                const poll = setInterval(async () => {
                    tries++;
                    try {
                        const dr = await fetch('/api/data');
                        const dd = await dr.json();
                        D = dd;
                        render();

                        if (!dd.is_scraping || tries > 90) {
                            clearInterval(poll);
                            btn.disabled = false;
                            txt.innerHTML = dd.error
                                ? '⚠ Retry'
                                : '&#x21bb; Update Now';
                        }
                    } catch(e) {
                        if (tries > 90) {
                            clearInterval(poll);
                            btn.disabled = false;
                            txt.innerHTML = '&#x21bb; Update Now';
                        }
                    }
                }, 2000);
            } catch(e) {
                btn.disabled = false;
                txt.innerHTML = '&#x21bb; Update Now';
            }
        }

        // Countdown to next auto-scrape
        let cd = 300;
        setInterval(() => {
            cd--;
            if (cd <= 0) cd = 300;
            const m = Math.floor(cd/60), s = cd%60;
            const el = document.getElementById('nextScrape');
            if (el) el.textContent = `· Auto-scrape in ${m}:${s.toString().padStart(2,'0')}`;
        }, 1000);

        // Refresh UI every 30s
        setInterval(loadData, 30000);
        loadData();
    </script>
</body>
</html>
"""

# ── Startup ──
cached_posts, cached_time = load_cached_data()
if cached_posts:
    scrape_data["posts"] = cached_posts
    scrape_data["last_updated"] = cached_time

_scrape_thread = threading.Thread(target=auto_scrape_loop, daemon=True)
_scrape_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
