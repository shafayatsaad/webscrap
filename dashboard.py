"""
AWS Builder Center - Live Dynamic Dashboard (v6)
=================================================
Fully dynamic Flask dashboard with on-demand scraping.
No auto-refresh — uses manual Refresh button.
Designed for Render.com free tier deployment.

Run locally:  python dashboard.py
Deploy:       gunicorn dashboard:app --bind 0.0.0.0:$PORT
"""

import json
import os
import sys
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
}
data_lock = threading.Lock()

JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aws_builder_likes.json")


def load_cached_data():
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
    """Run the scraper — called on-demand by Refresh button."""
    global scrape_data
    with data_lock:
        if scrape_data["is_scraping"]:
            return
        scrape_data["is_scraping"] = True
        scrape_data["error"] = None

    print(f"\n[SCRAPE] Starting at {datetime.now().strftime('%H:%M:%S')}...")
    try:
        all_posts = []
        session_token, cookies = get_session_token_selenium()
        session = create_session(session_token, cookies)

        for content_type in CONTENT_TYPES:
            posts = fetch_all_posts(session, content_type)
            if posts:
                all_posts.extend(posts)

        if not all_posts:
            selenium_posts = scrape_via_selenium_direct()
            all_posts.extend(selenium_posts)

        if all_posts:
            sorted_posts = sorted(all_posts, key=lambda x: x.get("likes_count", 0), reverse=True)
            seen = set()
            unique = []
            for p in sorted_posts:
                if p["id"] not in seen:
                    p["is_competition"] = is_competition_post(p)
                    p.pop("raw_item", None)
                    seen.add(p["id"])
                    unique.append(p)

            try:
                with open(JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump(unique, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

            with data_lock:
                scrape_data["posts"] = unique
                scrape_data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[SCRAPE] Done: {len(unique)} posts")
        else:
            with data_lock:
                scrape_data["error"] = "No posts found"
            print("[SCRAPE] Failed: no posts")

    except Exception as e:
        with data_lock:
            scrape_data["error"] = str(e)
        print(f"[SCRAPE] Error: {e}")
    finally:
        with data_lock:
            scrape_data["is_scraping"] = False


# ── Routes ──
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

    total_likes = sum(p.get("likes_count", 0) for p in posts)
    avg_likes = total_likes / len(posts) if posts else 0
    max_likes = max((p.get("likes_count", 0) for p in posts), default=0)

    comp_posts = [p for p in posts if p.get("is_competition")]
    comp_count = len(comp_posts)

    highlight_rank = None
    highlight_post = None
    highlight_comp_rank = None
    nearby_posts = []
    likes_to_climb = 0

    for idx, post in enumerate(posts, 1):
        pid = post.get("id", "")
        puri = post.get("uri", "")
        if HIGHLIGHT_POST_URI and (pid in HIGHLIGHT_POST_URI or (puri and puri in HIGHLIGHT_POST_URI)):
            highlight_rank = idx
            highlight_post = post

            # Competition rank
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
        "highlight_id": HIGHLIGHT_POST_URI,
        "highlight_rank": highlight_rank,
        "highlight_post": highlight_post,
        "highlight_comp_rank": highlight_comp_rank,
        "nearby_posts": nearby_posts,
        "likes_to_climb": max(0, likes_to_climb) if highlight_rank and highlight_rank > 1 else 0,
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
    <title>AWS Builder Rankings — Live</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #060a14;
            --bg-card: #111827;
            --bg-card-alt: #1a2236;
            --accent: #ff9900;
            --accent-glow: rgba(255,153,0,0.35);
            --green: #10b981;
            --blue: #3b82f6;
            --red: #ef4444;
            --text: #f3f4f6;
            --text2: #9ca3af;
            --text3: #6b7280;
            --border: #1f2937;
            --r: 16px;
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family:'Outfit',sans-serif; background:var(--bg); color:var(--text); min-height:100vh; overflow-x:hidden; }

        /* Mesh BG */
        .mesh { position:fixed; inset:0; z-index:-1; background:var(--bg);
            background-image:
                radial-gradient(at 20% 0%, rgba(255,153,0,0.06) 0, transparent 50%),
                radial-gradient(at 80% 100%, rgba(59,130,246,0.04) 0, transparent 50%);
        }

        .container { max-width:960px; margin:0 auto; padding:20px 16px 0; min-height:100vh; display:flex; flex-direction:column; }

        /* ── Header ── */
        .header { display:flex; align-items:center; justify-content:space-between; margin-bottom:20px; flex-wrap:wrap; gap:12px; }
        .header-left h1 { font-size:22px; font-weight:900; background:linear-gradient(135deg,#fff,var(--accent)); -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }
        .header-meta { display:flex; align-items:center; gap:8px; margin-top:4px; }
        .live-dot { width:7px; height:7px; background:var(--green); border-radius:50%; }
        .update-txt { font-size:11px; color:var(--text3); font-weight:600; }

        .refresh-btn {
            background:var(--accent); color:#000; border:none; padding:10px 22px; border-radius:12px;
            font-family:'Outfit',sans-serif; font-size:13px; font-weight:800; cursor:pointer;
            display:flex; align-items:center; gap:8px;
            box-shadow:0 4px 20px var(--accent-glow); transition:all .2s;
        }
        .refresh-btn:hover { transform:translateY(-1px); box-shadow:0 6px 25px var(--accent-glow); }
        .refresh-btn:active { transform:scale(.97); }
        .refresh-btn:disabled { opacity:.6; cursor:not-allowed; transform:none; }
        .spin { width:16px; height:16px; border:2px solid rgba(0,0,0,.2); border-top-color:#000; border-radius:50%; animation:spin .7s linear infinite; }
        @keyframes spin { to { transform:rotate(360deg) } }

        /* ── Project Info ── */
        .project-info {
            background:linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border:1px solid var(--border); border-radius:var(--r); padding:16px 20px;
            margin-bottom:16px; display:flex; align-items:center; gap:16px; flex-wrap:wrap;
        }
        .project-icon { font-size:32px; }
        .project-details { flex:1; min-width:200px; }
        .project-name { font-size:16px; font-weight:800; color:#fff; }
        .project-desc { font-size:12px; color:var(--text2); margin-top:2px; line-height:1.4; }
        .project-author { font-size:11px; color:var(--text3); margin-top:4px; }
        .project-author strong { color:var(--accent); }

        /* ── Stats ── */
        .stats { display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin-bottom:16px; }
        @media(min-width:640px) { .stats { grid-template-columns:repeat(4,1fr); } }
        .stat { background:var(--bg-card); border:1px solid var(--border); padding:14px; border-radius:var(--r); text-align:center; }
        .stat-l { font-size:9px; color:var(--text3); text-transform:uppercase; font-weight:800; letter-spacing:.5px; }
        .stat-v { font-size:22px; font-weight:800; margin-top:2px; }

        /* ── Highlight ── */
        .hl { background:linear-gradient(145deg,#1e293b,#0f172a); border:2px solid var(--accent); border-radius:var(--r); padding:20px; margin-bottom:16px; box-shadow:0 0 40px var(--accent-glow); }
        .hl-top { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px; }
        .hl-badge { background:var(--accent); color:#000; padding:4px 12px; font-size:10px; font-weight:800; border-radius:8px; text-transform:uppercase; }
        .hl-rank { font-size:52px; font-weight:900; color:var(--accent); line-height:1; }
        .hl-title { font-size:17px; font-weight:700; color:#fff; margin-bottom:14px; }
        .hl-stats { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-bottom:14px; }
        .hl-s-l { display:block; font-size:9px; color:var(--text3); font-weight:800; text-transform:uppercase; }
        .hl-s-v { font-size:18px; font-weight:800; color:#fff; }
        .ctx { border-top:1px solid rgba(255,255,255,.08); padding-top:14px; }
        .ctx-h { font-size:10px; font-weight:800; color:var(--accent); text-transform:uppercase; margin-bottom:8px; }
        .ctx-row { display:flex; justify-content:space-between; align-items:center; font-size:12px; background:rgba(255,255,255,.03); padding:7px 12px; border-radius:8px; margin-bottom:5px; }
        .ctx-row span:last-child { font-weight:800; color:var(--accent); }
        .climb { background:rgba(16,185,129,.12); color:var(--green); padding:4px 10px; border-radius:6px; font-size:11px; font-weight:700; margin-top:6px; display:inline-block; }

        /* ── Filters ── */
        .filters { display:flex; gap:8px; margin-bottom:14px; }
        .fbtn { background:var(--bg-card); border:1px solid var(--border); color:var(--text2); padding:7px 14px; border-radius:10px; font-size:12px; font-weight:700; cursor:pointer; transition:all .15s; font-family:'Outfit',sans-serif; }
        .fbtn.active { background:var(--accent); color:#000; border-color:var(--accent); }

        /* ── List ── */
        .item { background:var(--bg-card); border:1px solid var(--border); border-radius:var(--r); padding:14px; display:flex; align-items:center; gap:14px; margin-bottom:8px; transition:border-color .2s; }
        .item:hover { border-color:rgba(255,255,255,.12); }
        .item.hl-item { border-color:var(--accent); background:rgba(255,153,0,.04); }
        .i-rank { width:36px; font-size:18px; font-weight:900; color:var(--text3); text-align:center; flex-shrink:0; }
        .i-body { flex:1; min-width:0; }
        .i-title { font-size:13px; font-weight:700; color:var(--text); text-decoration:none; display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .i-title:hover { color:var(--accent); }
        .i-meta { font-size:10px; color:var(--text3); display:flex; gap:8px; margin-top:2px; }
        .i-comp { color:var(--blue); font-weight:800; font-size:9px; text-transform:uppercase; }
        .i-likes { text-align:right; flex-shrink:0; }
        .i-likes-v { font-size:18px; font-weight:800; color:var(--accent); display:block; line-height:1; }
        .i-likes-l { font-size:8px; color:var(--text3); text-transform:uppercase; font-weight:700; }

        /* ── Footer ── */
        .footer { margin-top:auto; padding:24px 0 16px; border-top:1px solid var(--border); text-align:center; }
        .footer-dev { font-size:12px; color:var(--text3); font-weight:600; margin-bottom:8px; }
        .footer-dev a { color:var(--accent); text-decoration:none; font-weight:700; }
        .footer-dev a:hover { text-decoration:underline; }
        .footer-links { display:flex; justify-content:center; gap:16px; }
        .footer-links a { color:var(--text3); text-decoration:none; font-size:11px; font-weight:600; transition:color .2s; display:flex; align-items:center; gap:4px; }
        .footer-links a:hover { color:var(--accent); }
        .footer-links svg { width:14px; height:14px; fill:currentColor; }

        /* ── Loading ── */
        #overlay { position:fixed; inset:0; background:var(--bg); display:flex; flex-direction:column; align-items:center; justify-content:center; z-index:1000; gap:14px; }
        .loader { width:32px; height:32px; border:3px solid var(--border); border-top-color:var(--accent); border-radius:50%; animation:spin 1s linear infinite; }
    </style>
</head>
<body>
    <div class="mesh"></div>
    <div id="overlay"><div class="loader"></div><div style="font-size:13px;font-weight:700;color:var(--text2)">Loading Rankings...</div></div>

    <div class="container">
        <!-- Header -->
        <div class="header">
            <div class="header-left">
                <h1>AWS Builder Rankings</h1>
                <div class="header-meta">
                    <div class="live-dot"></div>
                    <span class="update-txt" id="lastUpdated">Click Refresh to update</span>
                </div>
            </div>
            <button class="refresh-btn" id="refreshBtn" onclick="doRefresh()">
                <span id="refreshText">&#x21bb; Update Now</span>
            </button>
        </div>

        <!-- Project Info -->
        <div class="project-info">
            <div class="project-icon">🏥</div>
            <div class="project-details">
                <div class="project-name">AIdeas: Transforming Healthcare into AI-Powered Wellness Companion</div>
                <div class="project-desc">An AI-powered wellness platform leveraging AWS services to transform reactive healthcare into proactive, personalized wellness management.</div>
                <div class="project-author">By <strong>Md. Shafayat Sadat Saad</strong> (@saad30) — AWS Builder Competition 2026</div>
            </div>
        </div>

        <!-- Stats -->
        <div class="stats">
            <div class="stat"><div class="stat-l">Total Posts</div><div class="stat-v" id="sP">--</div></div>
            <div class="stat"><div class="stat-l">Competition</div><div class="stat-v" id="sC">--</div></div>
            <div class="stat"><div class="stat-l">Total Likes</div><div class="stat-v" id="sL">--</div></div>
            <div class="stat"><div class="stat-l">Top Likes</div><div class="stat-v" id="sM">--</div></div>
        </div>

        <!-- Highlight -->
        <div id="hlBox"></div>

        <!-- Filters -->
        <div class="filters">
            <button class="fbtn active" id="fAll" onclick="setF('all')">All Posts</button>
            <button class="fbtn" id="fComp" onclick="setF('comp')">Competition</button>
        </div>

        <!-- Rankings -->
        <div id="list"></div>

        <!-- Footer -->
        <div class="footer">
            <div class="footer-dev">Developed by <a href="https://shafayatsaad.vercel.app/" target="_blank">Shafayat Saad</a></div>
            <div class="footer-links">
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
        let data = null;

        function setF(f) {
            filter = f;
            document.querySelectorAll('.fbtn').forEach(b => b.classList.remove('active'));
            document.getElementById(f === 'all' ? 'fAll' : 'fComp').classList.add('active');
            renderList();
        }

        async function loadData() {
            try {
                const r = await fetch('/api/data');
                data = await r.json();
                document.getElementById('overlay').style.display = 'none';
                render();
            } catch(e) { console.error(e); }
        }

        function render() {
            if (!data) return;
            const { stats, highlight_post: hp, highlight_rank: hr, highlight_comp_rank: hcr, nearby_posts: nb, likes_to_climb: lc, posts } = data;

            // Stats
            document.getElementById('sP').textContent = stats.total_posts;
            document.getElementById('sC').textContent = stats.comp_posts;
            document.getElementById('sL').textContent = stats.total_likes;
            document.getElementById('sM').textContent = stats.max_likes;

            // Updated time
            if (data.last_updated) {
                const t = data.last_updated.split(' ')[1] || data.last_updated;
                document.getElementById('lastUpdated').textContent = `Last scraped: ${t}`;
            }

            // Highlight card
            const box = document.getElementById('hlBox');
            if (hp && hr) {
                const pct = ((hr / posts.length) * 100).toFixed(1);
                let ctxHTML = '';
                if (nb && nb.length > 0) {
                    ctxHTML = `<div class="ctx"><div class="ctx-h">Rank Neighborhood</div>${nb.map(n =>
                        `<div class="ctx-row"><span>#${n.rank} ${n.title.length > 32 ? n.title.substring(0,29)+'...' : n.title}</span><span>${n.likes_count} likes</span></div>`
                    ).join('')}${lc > 0 ? `<div class="climb">🚀 ${lc} more like${lc>1?'s':''} to climb to #${hr-1}!</div>` : ''}</div>`;
                }
                box.innerHTML = `<div class="hl">
                    <div class="hl-top"><div class="hl-badge">Your Post</div><div class="hl-rank">#${hr}</div></div>
                    <div class="hl-title">${hp.title}</div>
                    <div class="hl-stats">
                        <div><span class="hl-s-l">Likes</span><span class="hl-s-v">${hp.likes_count}</span></div>
                        <div><span class="hl-s-l">Overall</span><span class="hl-s-v">Top ${pct}%</span></div>
                        <div><span class="hl-s-l">Comp Rank</span><span class="hl-s-v">#${hcr || '?'}/${stats.comp_posts}</span></div>
                    </div>${ctxHTML}</div>`;
            }

            renderList();
        }

        function renderList() {
            if (!data) return;
            const posts = data.posts;
            const filtered = filter === 'all' ? posts : posts.filter(p => p.is_competition);
            const hp = data.highlight_post;

            document.getElementById('list').innerHTML = filtered.length === 0
                ? '<div style="text-align:center;padding:30px;color:var(--text3)">No posts found.</div>'
                : filtered.map(p => {
                    const r = posts.indexOf(p) + 1;
                    const isHL = hp && p.id === hp.id;
                    const medal = r===1?'🥇':r===2?'🥈':r===3?'🥉':r;
                    return `<div class="item ${isHL?'hl-item':''}">
                        <div class="i-rank" ${r<=3?'style="color:#fff"':''}>${medal}</div>
                        <div class="i-body">
                            <a href="${p.url||'#'}" target="_blank" class="i-title">${p.title}</a>
                            <div class="i-meta">
                                <span>@${p.author_alias||'?'}</span>
                                <span>${p.author_name&&p.author_name!=='N/A'?p.author_name:''}</span>
                                ${p.is_competition?'<span class="i-comp">Competition</span>':''}
                            </div>
                        </div>
                        <div class="i-likes"><span class="i-likes-v">${p.likes_count}</span><span class="i-likes-l">Likes</span></div>
                    </div>`;
                }).join('');
        }

        async function doRefresh() {
            const btn = document.getElementById('refreshBtn');
            const txt = document.getElementById('refreshText');
            btn.disabled = true;
            txt.innerHTML = '<div class="spin"></div> Scraping...';

            try {
                await fetch('/api/refresh', { method: 'POST' });
                // Poll until done
                let tries = 0;
                const poll = setInterval(async () => {
                    tries++;
                    const r = await fetch('/api/data');
                    const d = await r.json();
                    if (!d.is_scraping || tries > 60) {
                        clearInterval(poll);
                        data = d;
                        render();
                        btn.disabled = false;
                        txt.innerHTML = '&#x21bb; Update Now';
                    }
                }, 3000);
            } catch(e) {
                btn.disabled = false;
                txt.innerHTML = '&#x21bb; Update Now';
            }
        }

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
