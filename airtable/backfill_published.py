#!/usr/bin/env python3
"""Import all published WP posts into Airtable Content Ideas table."""

import os, requests, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent))
from client import backfill_published

WP_URL = os.getenv("WP_URL")
WP_USER = os.getenv("WP_USER")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD")

print("Fetching published posts from WordPress...")
r = requests.get(
    f"{WP_URL}/wp-json/wp/v2/posts",
    params={"per_page": 100, "status": "publish", "_fields": "id,title,link,date"},
    auth=(WP_USER, WP_APP_PASSWORD),
    timeout=15,
)
r.raise_for_status()
wp_posts = r.json()
print(f"Found {len(wp_posts)} published posts.")

posts = [{"title": p["title"]["rendered"], "wp_id": p["id"], "url": p["link"]} for p in wp_posts]

created = backfill_published(posts)
print(f"Done. {created} new records added to Airtable ({len(posts) - created} already existed).")
