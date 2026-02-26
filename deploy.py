"""
AWS Builder - Deployment Suite (Deploy to Netlify)
==================================================
This script prepares a static snapshot of the dashboard for Netlify.

Usage:
1. Run: python deploy.py
2. Drag the 'dist' folder to https://app.netlify.com/drop
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
DATA_FILE = os.path.join(BASE_DIR, "aws_builder_likes.json")
DIST_DATA = os.path.join(DIST_DIR, "data.json")
SCRAPER_SCRIPT = os.path.join(BASE_DIR, "aws_scraper.py")

def print_step(msg):
    print(f"\n[STEP] {msg}...")

def run_scraper():
    print_step("Running AWS Builder Scraper (Latest Data)")
    try:
        # Run the scraper script
        result = subprocess.run([sys.executable, SCRAPER_SCRIPT], capture_output=False)
        if result.returncode == 0:
            print("Successfully scraped latest data.")
            return True
        else:
            print("Scraper failed. Check console output.")
            return False
    except Exception as e:
        print(f"Error running scraper: {e}")
        return False

def prepare_dist():
    print_step("Preparing 'dist' folder for deployment")
    
    if not os.path.exists(DIST_DIR):
        os.makedirs(DIST_DIR)
        print(f"Created {DIST_DIR}")

    if os.path.exists(DATA_FILE):
        # Load, clean, and re-save to ensure is_competition is present
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            posts = json.load(f)
        
        # Strip raw_item (bulky debug data) and ensure is_competition exists
        cleaned = []
        for p in posts:
            p.pop("raw_item", None)
            p.pop("content_id", None)
            if "is_competition" not in p:
                # Fallback detection
                title = (p.get("title", "") or "").lower()
                keywords = ["aideas", "mimamori", "kiro", "healthcare", "wellness"]
                p["is_competition"] = any(kw in title for kw in keywords)
            cleaned.append(p)
        
        with open(DIST_DATA, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2, ensure_ascii=False)
        
        comp_count = sum(1 for p in cleaned if p.get("is_competition"))
        print(f"Synced data: {len(cleaned)} posts ({comp_count} competition) -> {DIST_DATA}")
    else:
        print(f"Error: {DATA_FILE} not found. Run scraper first.")
        return False

    return True

def main():
    print("=" * 60)
    print("  AWS BUILDER - NETLIFY DEPLOYMENT HELPER")
    print("=" * 60)

    # 1. Scrape latest data
    if not run_scraper():
        print("Continuing with cached data...")

    # 2. Prepare dist
    if prepare_dist():
        print("\n" + "!" * 60)
        print("  SUCCESS! Your Netlify-ready folder is ready at:")
        print(f"  {DIST_DIR}")
        print("\n  NEXT STEPS:")
        print("  1. Go to https://app.netlify.com/drop")
        print("  2. Drag the WHOLE 'dist' folder onto the page.")
        print("  3. Your dashboard will be live on the web!")
        print("!" * 60 + "\n")
    else:
        print("\nDeployment preparation failed.")

if __name__ == "__main__":
    main()
