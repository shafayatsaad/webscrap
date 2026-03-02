"use client";

import { useState, useEffect, useCallback } from "react";

const HIGHLIGHT_ID = "3AAMRb7l";
const COMPETITION_END = new Date("2026-03-13T23:59:59");
const GITHUB_RAW_URL = "https://raw.githubusercontent.com/shafayatsaad/webscrap/main/dist/aws_builder_likes.json";

interface Post {
  id: string;
  title: string;
  likes_count: number;
  velocity?: number;
  is_competition?: boolean;
  author_alias?: string;
  url?: string;
  created_at?: string;
  last_published_at?: string;
  region?: string;
}

type ScrapeStatus = "idle" | "triggered" | "running" | "done" | "error";

function formatDate(created?: string, published?: string): string {
  if (!created && !published) return "Unknown";
  try {
    let dateObj = new Date(created || "");
    if (published) {
      const pubObj = new Date(published);
      if (!isNaN(pubObj.getTime()) && (isNaN(dateObj.getTime()) || pubObj < dateObj)) {
        dateObj = pubObj;
      }
    }
    if (isNaN(dateObj.getTime())) return "Invalid Date";
    return dateObj.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return created || "Unknown"; }
}

export default function Dashboard() {
  const [allData, setAllData] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentTab, setCurrentTab] = useState<"comp" | "all">("comp");
  const [searchQuery, setSearchQuery] = useState("");
  const [scrapedAt, setScrapedAt] = useState("");
  const [scrapeStatus, setScrapeStatus] = useState<ScrapeStatus>("idle");
  const [scrapeMessage, setScrapeMessage] = useState("");
  const [countdown, setCountdown] = useState("");
  const [deadlineText, setDeadlineText] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${GITHUB_RAW_URL}?_=${Date.now()}`);
      if (!res.ok) throw new Error("Failed to fetch");
      const data = await res.json();
      const posts: Post[] = data.posts || data;
      const seen = new Set<string>();
      const unique = posts.filter((p) => p.id && !seen.has(p.id) && seen.add(p.id));
      setAllData(unique);
      setScrapedAt(data.scraped_at || "");
      setLoading(false);
    } catch (e) {
      console.error("Failed to load data", e);
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Countdown timer
  useEffect(() => {
    const timer = setInterval(() => {
      const now = new Date();
      const diff = COMPETITION_END.getTime() - now.getTime();
      const days = Math.floor(diff / (1000 * 60 * 60 * 24));
      const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
      const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
      const secs = Math.floor((diff % (1000 * 60)) / 1000);
      setDeadlineText(`${days}D ${hours}H ${mins}M ${secs}S REMAINING`);
      setCountdown(`${String(15 - (now.getMinutes() % 15) - (now.getSeconds() > 0 ? 1 : 0)).padStart(2, "0")}:${String((60 - now.getSeconds()) % 60).padStart(2, "0")}`);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const handleScrape = async () => {
    setScrapeStatus("triggered");
    setScrapeMessage("Triggering scraper via GitHub Actions...");
    try {
      const res = await fetch("/api/trigger-scrape", { method: "POST" });
      const data = await res.json();
      if (data.success) {
        setScrapeStatus("running");
        setScrapeMessage("Scraper triggered! Waiting for fresh data (~2 min)...");
        // Poll for new data
        let attempts = 0;
        const pollInterval = setInterval(async () => {
          attempts++;
          await fetchData();
          if (attempts >= 12) {
            clearInterval(pollInterval);
            setScrapeStatus("done");
            setScrapeMessage("Data refreshed! Check the latest results.");
            setTimeout(() => setScrapeStatus("idle"), 5000);
          }
        }, 15000);
      } else {
        setScrapeStatus("error");
        setScrapeMessage(data.error || "Failed to trigger scraper");
        setTimeout(() => setScrapeStatus("idle"), 5000);
      }
    } catch {
      setScrapeStatus("error");
      setScrapeMessage("Failed to connect to scrape API");
      setTimeout(() => setScrapeStatus("idle"), 5000);
    }
  };

  // Computed values
  const compItems = allData.filter((p) => p.is_competition);
  const compLikes = compItems.reduce((s, p) => s + (p.likes_count || 0), 0);
  const maxVelo = allData.length > 0 ? Math.max(...allData.map((p) => p.velocity || 0)) : 0;
  const avgVelo = allData.length > 0 ? allData.reduce((s, p) => s + (p.velocity || 0), 0) / allData.length : 0;
  const uniqueAuthors = new Set(allData.map((p) => p.author_alias)).size;
  const topVelo = [...allData].sort((a, b) => (b.velocity || 0) - (a.velocity || 0)).slice(0, 5);

  // My post
  const meIndex = allData.findIndex((p) => p.id?.includes(HIGHLIGHT_ID));
  const me = meIndex >= 0 ? allData[meIndex] : null;
  const compSorted = [...compItems].sort((a, b) => (b.likes_count || 0) - (a.likes_count || 0));
  const compRank = me ? compSorted.findIndex((p) => p.id?.includes(HIGHLIGHT_ID)) + 1 : 0;

  const daysLeft = Math.max(0.1, (COMPETITION_END.getTime() - Date.now()) / 86400000);
  const forecasted = me ? Math.round(me.likes_count + (me.velocity || 0) * daysLeft) : 0;
  const topPost = compSorted[0];
  const topForecasted = topPost ? Math.round(topPost.likes_count + (topPost.velocity || 0) * daysLeft) : 0;
  const top3 = compSorted.slice(0, 3);
  const top3AvgVelo = top3.reduce((s, p) => s + (p.velocity || 0), 0) / Math.max(1, top3.length);
  const paceStatus = me && me.velocity !== undefined && me.velocity >= top3AvgVelo
    ? { lbl: "ELITE PACE", color: "var(--green)" }
    : { lbl: "BEHIND PACE", color: "var(--accent)" };
  const safetyMargin = Math.max(10, Math.round(topForecasted * 0.05));
  const safeTarget = topForecasted + safetyMargin;
  const safeBufferNeeded = me ? Math.max(0, safeTarget - me.likes_count) : 0;
  const dailySafeAdd = (safeBufferNeeded / daysLeft).toFixed(1);

  let winProb = 50;
  if (me && topPost) {
    const veloRatio = (me.velocity || 0) / (topPost.velocity || 0.1);
    const scoreRatio = me.likes_count / topPost.likes_count;
    winProb = Math.round(veloRatio * 60 + scoreRatio * 30);
    if (compRank === 1) winProb = (me.velocity || 0) >= (topPost.velocity || 0) ? 98 : 85;
    winProb = Math.min(99, Math.max(5, winProb));
  }

  // Filtered & sorted data
  let filteredData = [...allData];
  if (currentTab === "comp") {
    filteredData = filteredData.filter((p) => p.is_competition);
    filteredData.sort((a, b) => (b.likes_count || 0) - (a.likes_count || 0));
  } else {
    filteredData.sort((a, b) => new Date(b.last_published_at || b.created_at || "").getTime() - new Date(a.last_published_at || a.created_at || "").getTime());
  }
  if (searchQuery) {
    filteredData = filteredData.filter((p) => p.title?.toLowerCase().includes(searchQuery) || p.author_alias?.toLowerCase().includes(searchQuery));
  }

  const lastTime = scrapedAt ? formatDate(scrapedAt) : "—";

  if (loading) {
    return (
      <div id="overlay">
        <div className="loader"></div>
        <p style={{ fontWeight: 800, letterSpacing: "0.5px" }}>SYNCING COMPETITION DATA...</p>
        <div style={{ marginTop: 15, textAlign: "center" }}>
          <div style={{ fontSize: 14, fontWeight: 800, color: "#fff", marginBottom: 4 }}>Directed &amp; Developed by Shafayat Saad</div>
          <div style={{ fontSize: 10, color: "var(--text-mute)", fontWeight: 700, textTransform: "uppercase", letterSpacing: "1px" }}>Full Stack Engineer &amp; AI Architect</div>
        </div>
      </div>
    );
  }

  return (
    <div className="container">
      <header>
        <div className="logo-area">
          <h1>AIdeas Analyzer</h1>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 4 }}>
            <p style={{ margin: 0 }}><span className="live-indicator"></span> Tracking AWS 10,000 AIdeas</p>
          </div>
        </div>
        <div className="header-actions">
          <div className="countdown-container">
            <span>NEXT REFRESH:</span>
            <span id="countdown-timer">{countdown}</span>
          </div>
          <button className="refresh-btn" onClick={handleScrape} disabled={scrapeStatus === "triggered" || scrapeStatus === "running"}>
            {scrapeStatus === "triggered" || scrapeStatus === "running" ? (
              <><span className="spinner"></span> SCRAPING...</>
            ) : (
              <>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path></svg>
                LIVE SYNC
              </>
            )}
          </button>
        </div>
      </header>

      {scrapeStatus !== "idle" && (
        <div className={`status-banner ${scrapeStatus === "error" ? "error" : scrapeStatus === "done" ? "success" : "busy"}`}>
          {scrapeStatus === "running" || scrapeStatus === "triggered" ? <span className="spinner"></span> : null}
          {scrapeMessage}
        </div>
      )}

      <div className="comp-banner">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
        <div>
          <strong>COMPETITION DEADLINE:</strong> <span style={{ color: "var(--accent)" }}>March 13, 2026</span> &middot; <span style={{ fontWeight: 900, letterSpacing: "0.5px" }}>{deadlineText}</span>
        </div>
      </div>

      {/* Rank Hero Card */}
      {me && compRank > 0 && (
        <div className="rank-hero">
          <div className="rank-grid">
            <div className="rank-main">
              <div className="rank-badge">
                <span className="lbl">Rank</span>
                <span className="num">#{compRank}</span>
              </div>
              <div className="rank-info">
                <h2>{me.title}</h2>
                <p style={{ color: "var(--accent)", fontWeight: 700 }}>Currently #{compRank} in Competition</p>
                <p style={{ marginTop: 4, fontSize: 13, color: "var(--text-dim)" }}>
                  Speed: <strong style={{ color: "var(--green)" }}>{me.velocity || 0} likes/day</strong> &middot;
                  <span style={{ opacity: 0.8 }}> Submitted: {formatDate(me.created_at, me.last_published_at)}</span>
                </p>
              </div>
            </div>
            <div className="comp-comparison">
              <div className="comp-row"><span className="comp-lbl">📈 Top 3 Avg Pace</span><span className="comp-val" style={{ color: paceStatus.color }}>{top3AvgVelo.toFixed(1)} v/d</span></div>
              <div className="comp-row"><span className="comp-lbl">🔭 Forecasted Final</span><span className="comp-val">~{forecasted} LIKES</span></div>
              <div className="comp-row"><span className="comp-lbl">🛡️ Safe-Win Target</span><span className="comp-val" style={{ color: "var(--green)" }}>+{safeBufferNeeded} LIKES</span></div>
              <div className="comp-row"><span className="comp-lbl">🔥 Win Probability</span><span className="comp-val" style={{ color: winProb > 75 ? "var(--green)" : "var(--accent)" }}>{winProb}%</span></div>
              <div className="climb-tip" style={{ borderTop: "1px solid rgba(255,255,255,0.05)", paddingTop: 10 }}>
                <div style={{ fontSize: 10, fontWeight: 800, color: paceStatus.color, marginBottom: 4 }}>{paceStatus.lbl}</div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 11 }}>Target <strong>{dailySafeAdd} likes/day</strong> to guarantee #1</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="hero-stats">
        <div className="card"><p className="stat-label">Feed Count</p><p className="stat-val">{allData.length}</p><p className="stat-sub">Recent articles</p></div>
        <div className="card"><p className="stat-label">Competition Entries</p><p className="stat-val">{compItems.length}</p><p className="stat-sub">AIdeas matches</p></div>
        <div className="card"><p className="stat-label">Max Velocity</p><p className="stat-val">{maxVelo.toFixed(1)}</p><p className="stat-sub">Likes per day</p></div>
        <div className="card"><p className="stat-label">Last Updated</p><p className="stat-val" style={{ fontSize: 18, paddingTop: 8 }}>{lastTime}</p><p className="stat-sub">Automatic tracking</p></div>
      </div>

      <div className="layout-main">
        <div className="content-area">
          <div className="controls">
            <div className="filter-tabs">
              <button className={`tab-btn ${currentTab === "comp" ? "active" : ""}`} onClick={() => setCurrentTab("comp")}>Competition Leaderboard ({compItems.length})</button>
              <button className={`tab-btn ${currentTab === "all" ? "active" : ""}`} onClick={() => setCurrentTab("all")}>Global Feed ({allData.length})</button>
            </div>
            <div className="search-box">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.3-4.3"></path></svg>
              <input type="text" placeholder="Filter articles..." onChange={(e) => setSearchQuery(e.target.value.toLowerCase())} />
            </div>
          </div>
          <div className="rank-list">
            {filteredData.slice(0, 100).map((p, idx) => {
              const isMe = p.id?.includes(HIGHLIGHT_ID);
              const displayRank = idx + 1;
              const medal = displayRank === 1 ? "🥇" : displayRank === 2 ? "🥈" : displayRank === 3 ? "🥉" : String(displayRank);
              const forecast = Math.round(p.likes_count + (p.velocity || 0) * daysLeft);
              return (
                <a key={p.id} href={p.url || "#"} target="_blank" rel="noopener noreferrer" className={`rank-item ${isMe ? "highlighted" : ""}`}>
                  <div className="item-rank" style={displayRank <= 3 ? { color: "#fff" } : undefined}>{medal}</div>
                  <div className="item-content">
                    <span className="item-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {p.title}
                      <span className="tag-region" style={{ background: "var(--accent)", color: "#000", fontWeight: 900, fontSize: 10, padding: "3px 7px", borderRadius: 4, boxShadow: "0 2px 4px rgba(0,0,0,0.2)" }}>{p.region || "Global"}</span>
                    </span>
                    <div className="item-sub">
                      <span style={{ fontWeight: 700, color: "var(--text-dim)" }}>{p.author_alias ? `@${p.author_alias}` : "Anonymous"}</span>
                      {p.is_competition && <span className="tag-comp">AIdeas</span>}
                      <span className="tag-velocity">⚡ {p.velocity || 0} v/d</span>
                      <span style={{ fontSize: 9, opacity: 0.6 }}>{formatDate(p.created_at, p.last_published_at)}</span>
                    </div>
                  </div>
                  <div className="item-likes">
                    <span className="likes-num">{p.likes_count}</span>
                    <span className="likes-lbl">Likes</span>
                    <span className="forecast-num" style={{ color: "var(--accent)" }}>🔭 ~{forecast}</span>
                  </div>
                </a>
              );
            })}
          </div>
        </div>

        <div className="sidebar">
          <div className="card side-card">
            <h4>Competition Health</h4>
            <div className="side-row"><span>Detected entries</span><span>{compItems.length}</span></div>
            <div className="side-row"><span>Avg likes/entry</span><span>{(compLikes / Math.max(1, compItems.length)).toFixed(1)}</span></div>
            <div className="side-row"><span>Total engagements</span><span>{compLikes}</span></div>
            <div className="side-row"><span>Competition %</span><span>{((compItems.length / Math.max(1, allData.length)) * 100).toFixed(1)}%</span></div>
          </div>
          <div className="card side-card">
            <h4>Builder Activity</h4>
            <div className="side-row"><span>Recent Articles</span><span>{allData.length}</span></div>
            <div className="side-row"><span>Unique Authors</span><span>{uniqueAuthors}</span></div>
            <div className="side-row"><span>Avg Velocity</span><span>{avgVelo.toFixed(2)}</span></div>
          </div>
          <div className="card side-card" style={{ borderStyle: "dashed", opacity: 0.8 }}>
            <h4>Top Velocity Gainers</h4>
            {topVelo.map((p) => (
              <div className="side-row" key={p.id}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 150, fontWeight: 600 }}>{p.title}</span>
                <span style={{ color: "var(--green)", fontWeight: 800 }}>+{p.velocity}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <footer>
        <div style={{ marginBottom: 24 }}>
          <p style={{ fontWeight: 800, fontSize: 14, color: "#fff", marginBottom: 12, letterSpacing: "0.5px" }}>Designed &amp; Developed by Shafayat Saad</p>
          <div style={{ display: "flex", gap: 20, justifyContent: "center", marginBottom: 15 }}>
            <a href="https://shafayatsaad.vercel.app/" target="_blank" rel="noopener noreferrer">Portfolio</a>
            <a href="https://github.com/shafayatsaad" target="_blank" rel="noopener noreferrer">GitHub</a>
            <a href="https://twitter.com/shafayatsaad" target="_blank" rel="noopener noreferrer">Twitter</a>
            <a href="https://linkedin.com/in/shafayatsaad" target="_blank" rel="noopener noreferrer">LinkedIn</a>
          </div>
        </div>
        <p>&copy; 2026 AWS Builder Competition Tracker &middot; API Monitoring Live</p>
      </footer>
    </div>
  );
}
