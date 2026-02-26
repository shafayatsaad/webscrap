"""
AWS Builder Center - Live Dashboard (v3 - Featured)
==================================================
- Real-time web dashboard with auto-scraping (every 2.5 mins).
- Fixed Header Refresh (no obstruction).
- Competition Comparison (Nearby posts + Likes to climb).
- Direct Content Links (Fixed broken navigation).

Run: python dashboard.py
"""

import json
import os
import sys
import time
import threading
from datetime import datetime

# Fix Windows encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from flask import Flask, jsonify, render_template_string

# ── Import scraper functions ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aws_scraper import (
    get_session_token_selenium,
    create_session,
    fetch_all_posts,
    scrape_via_selenium_direct,
    CONTENT_TYPES,
    HIGHLIGHT_POST_URI,
    BASE_URL,
)

app = Flask(__name__)

# Global state
scrape_data = {
    "posts": [],
    "last_updated": None,
    "is_scraping": False,
    "error": None,
}
data_lock = threading.Lock()
AUTO_SCRAPE_INTERVAL = 150  # 2.5 minutes

JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aws_builder_likes.json")


def load_cached_data():
    """Load previously scraped data from JSON file."""
    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                posts = json.load(f)
            mod_time = os.path.getmtime(JSON_PATH)
            return posts, datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return [], None


def run_scraper():
    """Run the scraper in background thread."""
    global scrape_data
    with data_lock:
        if scrape_data["is_scraping"]:
            return
        scrape_data["is_scraping"] = True
        scrape_data["error"] = None

    print(f"\n[AUTO] Starting background scrape at {datetime.now().strftime('%H:%M:%S')}...")
    try:
        all_posts = []

        # Method 1: Try API
        session_token, cookies = get_session_token_selenium()
        session = create_session(session_token, cookies)

        api_success = False
        for content_type in CONTENT_TYPES:
            posts = fetch_all_posts(session, content_type)
            if posts:
                all_posts.extend(posts)
                api_success = True

        # Method 2: Fallback
        if not api_success:
            selenium_posts = scrape_via_selenium_direct()
            all_posts.extend(selenium_posts)

        if all_posts:
            from aws_scraper import is_competition_post
            
            # Deduplicate by ID and Preserve Sort Order (Highest Likes First)
            sorted_posts = sorted(all_posts, key=lambda x: x.get("likes_count", 0), reverse=True)
            seen = set()
            unique = []
            for p in sorted_posts:
                if p["id"] not in seen:
                    p["is_competition"] = is_competition_post(p)
                    seen.add(p["id"])
                    unique.append(p)

            # Save to JSON
            try:
                with open(JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump(unique, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

            with data_lock:
                scrape_data["posts"] = unique
                scrape_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[AUTO] Scrape successful: {len(unique)} posts found.")
        else:
            with data_lock:
                scrape_data["error"] = "No posts retrieved."
            print(f"[AUTO] Scrape failed: No posts found.")

    except Exception as e:
        with data_lock:
            scrape_data["error"] = str(e)
        print(f"[AUTO] Scrape error: {e}")
    finally:
        with data_lock:
            scrape_data["is_scraping"] = False


def auto_scrape_loop():
    """Background loop to scrape every interval."""
    time.sleep(10)
    while True:
        run_scraper()
        time.sleep(AUTO_SCRAPE_INTERVAL)


# ── API Endpoints ──
@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/data")
def api_data():
    with data_lock:
        posts = scrape_data["posts"]
        last_updated = scrape_data["last_updated"]
        is_scraping = scrape_data["is_scraping"]
        error = scrape_data["error"]

    # Calculate stats
    total_likes = sum(p.get("likes_count", 0) for p in posts)
    avg_likes = total_likes / len(posts) if posts else 0
    max_likes = max((p.get("likes_count", 0) for p in posts), default=0)

    # Competition-specific stats
    comp_posts = [p for p in posts if p.get("is_competition", False)]
    comp_count = len(comp_posts)
    
    # Find highlight rank in all posts
    highlight_rank = None
    highlight_post = None
    nearby_posts = []
    likes_to_climb = 0
    
    for idx, post in enumerate(posts, 1):
        pid = post.get("id", "")
        puri = post.get("uri", "")
        if HIGHLIGHT_POST_URI and (pid in HIGHLIGHT_POST_URI or (puri and puri in HIGHLIGHT_POST_URI)):
            highlight_rank = idx
            highlight_post = post
            
            # Find nearby posts (1 above, 1 below)
            if idx > 1:
                above = posts[idx-2].copy()
                above["rank"] = idx - 1
                nearby_posts.append(above)
                likes_to_climb = above.get("likes_count", 0) - post.get("likes_count", 0)
            
            # The current post itself for UI context if needed
            
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
        "highlight_id": HIGHLIGHT_POST_URI,
        "highlight_rank": highlight_rank,
        "highlight_post": highlight_post,
        "nearby_posts": nearby_posts,
        "likes_to_climb": max(0, likes_to_climb + 1) if highlight_rank and highlight_rank > 1 else 0,
        "stats": {
            "total_posts": len(posts),
            "comp_posts": comp_count,
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


# ── Dashboard HTML ──
DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>AWS Builder - Leaderboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #050810;
            --bg-secondary: #0d111d;
            --bg-card: #151b2d;
            --bg-card-hover: #1c243a;
            --accent: #ff9900;
            --accent-glow: rgba(255, 153, 0, 0.4);
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --text-dim: #6b7280;
            --green: #10b981;
            --red: #ef4444;
            --gold: #ffb800;
            --silver: #cbd5e1;
            --bronze: #cd7f32;
            --border: #232d45;
            --radius: 16px;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }

        body {
            font-family: 'Outfit', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
            line-height: 1.5;
        }

        .bg-mesh {
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            z-index: -1;
            background-color: var(--bg-primary);
            background-image: 
                radial-gradient(at 0% 0%, rgba(255, 153, 0, 0.05) 0px, transparent 50%),
                radial-gradient(at 100% 0%, rgba(59, 130, 246, 0.05) 0px, transparent 50%);
        }

        .container {
            max-width: 1000px;
            margin: 0 auto;
            padding: 24px 16px 60px;
        }

        /* ── Header ── */
        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 16px;
        }

        .header-left {
            display: flex;
            flex-direction: column;
        }

        .header-title {
            font-size: 26px;
            font-weight: 800;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #fff 0%, var(--accent) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .header-meta {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-top: 4px;
        }

        .live-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(16, 185, 129, 0.1);
            color: var(--green);
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
        }

        .update-time {
            font-size: 11px;
            color: var(--text-dim);
            font-weight: 500;
        }

        .refresh-btn {
            background: var(--accent);
            color: #000;
            border: none;
            padding: 10px 20px;
            border-radius: 12px;
            font-size: 13px;
            font-weight: 800;
            cursor: pointer;
            box-shadow: 0 4px 15px var(--accent-glow);
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .refresh-btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }

        /* ── Custom Cards ── */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            box-shadow: 0 4px 20px rgba(0,0,0,0.2);
            padding: 16px;
            margin-bottom: 16px;
        }

        /* ── Stats ── */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
            margin-bottom: 24px;
        }

        @media (min-width: 768px) {
            .stats-grid { grid-template-columns: repeat(4, 1fr); }
        }

        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            padding: 16px;
            border-radius: var(--radius);
            text-align: center;
        }

        .stat-label {
            font-size: 10px;
            color: var(--text-dim);
            text-transform: uppercase;
            font-weight: 800;
            margin-bottom: 4px;
        }

        .stat-value {
            font-size: 24px;
            font-weight: 800;
            color: var(--text-primary);
        }

        /* ── Highlight Card ── */
        .highlight-card {
            background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%);
            border: 2px solid var(--accent);
            border-radius: var(--radius);
            padding: 24px;
            margin-bottom: 24px;
            position: relative;
            box-shadow: 0 0 30px var(--accent-glow);
        }

        .hl-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 16px;
        }

        .hl-badge {
            background: var(--accent);
            color: #000;
            padding: 4px 12px;
            font-size: 11px;
            font-weight: 800;
            border-radius: 8px;
        }

        .hl-rank-lg {
            font-size: 64px;
            font-weight: 900;
            color: var(--accent);
            line-height: 1;
        }

        .hl-title {
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 20px;
            color: #fff;
        }

        .hl-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
            margin-bottom: 24px;
        }

        .hl-box span:first-child {
            display: block;
            font-size: 10px;
            color: var(--text-dim);
            text-transform: uppercase;
            font-weight: 800;
            letter-spacing: 0.5px;
        }

        .hl-box span:last-child {
            font-size: 20px;
            font-weight: 800;
            color: #fff;
        }

        /* ── Context ── */
        .ctx-section {
            border-top: 1px solid rgba(255,255,255,0.1);
            padding-top: 20px;
        }

        .ctx-title {
            font-size: 11px;
            font-weight: 800;
            color: var(--accent);
            text-transform: uppercase;
            margin-bottom: 12px;
        }

        .ctx-comparison {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .ctx-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 13px;
            background: rgba(255,255,255,0.03);
            padding: 8px 12px;
            border-radius: 8px;
        }

        .climb-badge {
            background: rgba(16, 185, 129, 0.15);
            color: var(--green);
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 700;
            margin-top: 12px;
            display: inline-block;
        }

        /* ── Filters ── */
        .controls {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }

        .filter-btn {
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            padding: 8px 16px;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
        }

        .filter-btn.active {
            background: var(--accent);
            color: #000;
            border-color: var(--accent);
        }

        /* ── Rankings ── */
        .rankings-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .rank-item {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 16px;
            display: flex;
            align-items: center;
            gap: 16px;
            transition: all 0.2s;
        }

        .rank-item.highlighted {
            border-color: var(--accent);
            background: rgba(255, 153, 0, 0.05);
        }

        .rank-num {
            width: 40px;
            font-size: 22px;
            font-weight: 900;
            color: var(--text-dim);
            text-align: center;
            flex-shrink: 0;
        }

        .rank-info {
            flex-grow: 1;
            min-width: 0;
        }

        .item-title {
            font-size: 15px;
            font-weight: 700;
            color: var(--text-primary);
            text-decoration: none;
            display: block;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 2px;
        }

        .item-title:hover { color: var(--accent); }

        .item-meta {
            font-size: 12px;
            color: var(--text-dim);
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .comp-tag {
            color: #3b82f6;
            font-weight: 800;
            font-size: 9px;
            text-transform: uppercase;
        }

        .item-stats {
            text-align: right;
            flex-shrink: 0;
        }

        .likes-val {
            font-size: 20px;
            font-weight: 800;
            color: var(--accent);
            display: block;
            line-height: 1;
        }

        .likes-lbl { font-size: 9px; color: var(--text-dim); text-transform: uppercase; font-weight: 800; }

        .spinner {
            width: 18px; height: 18px;
            border: 3px solid rgba(0,0,0,0.2);
            border-top-color: #000;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin { to { transform: rotate(360deg); } }

        #loadingOverlay {
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: var(--bg-primary);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
    </style>
</head>
<body>
    <div class="bg-mesh"></div>

    <div id="loadingOverlay">
        <div class="loader-content" style="text-align:center">
            <div class="spinner" style="width:40px; height:40px; border-width:4px; border-top-color:var(--accent)"></div>
            <p style="margin-top:20px; font-weight:700; color:var(--text-secondary)">Syncing Rankings...</p>
        </div>
    </div>

    <div class="container">
        <!-- Header -->
        <div class="header">
            <div class="header-left">
                <h1 class="header-title">AWS Builder</h1>
                <div class="header-meta">
                    <div class="live-badge"><div style="width:8px; height:8px; background:var(--green); border-radius:50%"></div>Live</div>
                    <div class="update-time" id="lastUpdated">Updating...</div>
                </div>
            </div>
            <button class="refresh-btn" id="refreshBtn" onclick="refreshManual()">
                <div id="refreshLoader" class="spinner" style="display:none"></div>
                <span id="refreshIcon">&#x21bb;</span>
                <span id="btnText">Refresh Data</span>
            </button>
        </div>

        <!-- Stats -->
        <div class="stats-grid">
            <div class="stat-card"><div class="stat-label">Posts</div><div class="stat-value" id="statPosts">--</div></div>
            <div class="stat-card"><div class="stat-label">Competition</div><div class="stat-value" id="statComp">--</div></div>
            <div class="stat-card"><div class="stat-label">Total Likes</div><div class="stat-value" id="statLikes">--</div></div>
            <div class="stat-card"><div class="stat-label">Avg Likes</div><div class="stat-value" id="statAvg">--</div></div>
        </div>

        <!-- Highlight Card -->
        <div id="highlightContainer"></div>

        <!-- Controls -->
        <div class="controls">
            <button class="filter-btn active" id="btnAll" onclick="setFilter('all')">All</button>
            <button class="filter-btn" id="btnComp" onclick="setFilter('comp')">Competition</button>
        </div>

        <!-- List -->
        <div class="rankings-list" id="rankingsList"></div>
    </div>

    <script>
        let currentFilter = 'all';
        let fullData = null;

        function setFilter(filter) {
            currentFilter = filter;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(filter === 'all' ? 'btnAll' : 'btnComp').classList.add('active');
            renderData();
        }

        async function fetchData() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();
                fullData = data;
                
                document.getElementById('loadingOverlay').style.display = 'none';
                
                updateHeader(data);
                updateStats(data);
                renderData();
            } catch (e) { console.error(e); }
        }

        function updateHeader(data) {
            const timeStr = data.last_updated ? data.last_updated.split(' ')[1] : '--:--';
            document.getElementById('lastUpdated').textContent = `Last Checked: ${timeStr}`;
            
            const btn = document.getElementById('refreshBtn');
            const loader = document.getElementById('refreshLoader');
            const icon = document.getElementById('refreshIcon');
            const text = document.getElementById('btnText');

            if (data.is_scraping) {
                btn.disabled = true;
                loader.style.display = 'block';
                icon.style.display = 'none';
                text.textContent = 'Scraping...';
            } else {
                btn.disabled = false;
                loader.style.display = 'none';
                icon.style.display = 'inline';
                text.textContent = 'Refresh Data';
            }
        }

        function updateStats(data) {
            const s = data.stats;
            document.getElementById('statPosts').textContent = s.total_posts;
            document.getElementById('statComp').textContent = s.comp_posts;
            document.getElementById('statLikes').textContent = s.total_likes;
            document.getElementById('statAvg').textContent = s.avg_likes;
        }

        function renderData() {
            if (!fullData) return;
            const { posts, highlight_post, highlight_rank, nearby_posts, likes_to_climb } = fullData;

            // Highlight Section
            const hlContainer = document.getElementById('highlightContainer');
            if (highlight_post && highlight_rank) {
                const pct = ((highlight_rank / posts.length) * 100).toFixed(1);
                let nearbyHTML = '';
                if (nearby_posts && nearby_posts.length > 0) {
                    nearbyHTML = `
                        <div class="ctx-section">
                            <div class="ctx-title">Rank Neighborhood</div>
                            <div class="ctx-comparison">
                                ${nearby_posts.map(p => `
                                    <div class="ctx-item">
                                        <span>#${p.rank} ${p.title.length > 30 ? p.title.substring(0,27)+'...' : p.title}</span>
                                        <span style="font-weight:800; color:var(--accent)">${p.likes_count} likes</span>
                                    </div>
                                `).join('')}
                            </div>
                            <div class="climb-badge">Need ${likes_to_climb} more likes to climb!</div>
                        </div>
                    `;
                }

                hlContainer.innerHTML = `
                    <div class="highlight-card">
                        <div class="hl-header">
                            <div class="hl-badge">YOUR POST</div>
                            <div class="hl-rank-lg">#${highlight_rank}</div>
                        </div>
                        <h2 class="hl-title">${highlight_post.title}</h2>
                        <div class="hl-grid">
                            <div class="hl-box"><span>LIKES</span><span>${highlight_post.likes_count}</span></div>
                            <div class="hl-box"><span>PERCENTILE</span><span>Top ${pct}%</span></div>
                        </div>
                        ${nearbyHTML}
                    </div>
                `;
            }

            // List Section
            const list = document.getElementById('rankingsList');
            const filtered = currentFilter === 'all' ? posts : posts.filter(p => p.is_competition);
            
            list.innerHTML = filtered.map((p, idx) => {
                const rank = posts.indexOf(p) + 1;
                const isHL = highlight_post && p.id === highlight_post.id;
                const medal = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : rank;
                
                return `
                    <div class="rank-item ${isHL ? 'highlighted' : ''}">
                        <div class="rank-num" style="${rank<=3?'color:white':''}">${medal}</div>
                        <div class="rank-info">
                            <a href="${p.url}" target="_blank" class="item-title">${p.title}</a>
                            <div class="item-meta">
                                <span>@${p.author_alias}</span>
                                ${p.is_competition ? '<span class="comp-tag">Competition</span>' : ''}
                            </div>
                        </div>
                        <div class="item-stats">
                            <span class="likes-val">${p.likes_count}</span>
                            <span class="likes-lbl">Likes</span>
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function refreshManual() {
            fetch('/api/refresh', { method: 'POST' });
            setTimeout(fetchData, 1000);
        }

        // Auto Refresh
        setInterval(fetchData, 30000);
        fetchData();
    </script>
</body>
</html>
"""

# ── Auto-start background scraper (works with both gunicorn and local) ──
cached_posts, cached_time = load_cached_data()
if cached_posts:
    scrape_data["posts"] = cached_posts
    scrape_data["last_updated"] = cached_time

# Start auto-scrape thread (daemon so it dies with the process)
_scrape_thread = threading.Thread(target=auto_scrape_loop, daemon=True)
_scrape_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
