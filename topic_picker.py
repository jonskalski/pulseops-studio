#!/usr/bin/env python3
"""
PulseOps Studio — Topic Picker
Scrapes RSS feeds for trending topics, asks Claude to pick the best ones,
posts suggestions with "why?" to Discord for approval.

Usage: python3 topic_picker.py
"""

import os
import json
import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
DISCORD_TOPICS_WEBHOOK_URL = os.environ.get("DISCORD_TOPICS_WEBHOOK_URL")
WP_URL = os.environ.get("WP_URL", "https://pulseops.us")
WP_USER = os.environ.get("WP_USER")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD")

SONNET = "claude-sonnet-4-6"

# ── RSS Feeds ────────────────────────────────────────────────────────────────
# SMB-native sources listed first so they get weighted first in headlines Claude sees
RSS_FEEDS = [
    "https://blog.hubspot.com/marketing/rss.xml",            # HubSpot Marketing
    "https://www.smallbiztrends.com/feed",                   # Small Biz Trends
    "https://www.searchenginejournal.com/feed/",             # Search Engine Journal
    "https://searchengineland.com/feed",                     # Search Engine Land
    "https://www.inc.com/rss",                               # Inc.com
    "https://moz.com/blog/feed",                             # Moz (SEO/marketing)
    "https://www.convinceandconvert.com/feed/",              # Convince & Convert (marketing)
    "https://neilpatel.com/blog/feed/",                      # Neil Patel (SEO/marketing)
    "https://www.socialmediaexaminer.com/feed/",             # Social Media Examiner
    "https://feeds.feedburner.com/venturebeat/SZYF",        # VentureBeat AI
    "https://techcrunch.com/feed/",                          # TechCrunch
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def fetch_feed(url):
    """Fetch RSS feed and return list of (title, description) tuples."""
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
        items = []
        # Handle both RSS and Atom
        for item in root.findall(".//item")[:10]:
            title = item.findtext("title", "").strip()
            desc = item.findtext("description", "").strip()
            desc = re.sub(r"<[^>]+>", "", desc)[:200]
            if title:
                items.append(f"- {title}: {desc}")
        for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry")[:10]:
            title = entry.findtext("{http://www.w3.org/2005/Atom}title", "").strip()
            summary = entry.findtext("{http://www.w3.org/2005/Atom}summary", "").strip()
            summary = re.sub(r"<[^>]+>", "", summary)[:200]
            if title:
                items.append(f"- {title}: {summary}")
        return items
    except Exception as e:
        print(f"  Feed failed ({url[:50]}...): {e}")
        return []

def fetch_existing_posts():
    """Get titles of already-published posts to avoid duplicates."""
    try:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"per_page": 100, "status": "publish", "_fields": "title"},
            timeout=15,
        )
        return [p["title"]["rendered"] for p in r.json()]
    except Exception:
        return []

def call_claude(system_prompt, user_message):
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": SONNET,
        "max_tokens": 2048,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]

PENDING_TOPICS_FILE = Path(__file__).parent / "runs" / "pending_topics.txt"

def load_pending_topics():
    """Load topics already pending in Discord."""
    if PENDING_TOPICS_FILE.exists():
        return [line.strip() for line in PENDING_TOPICS_FILE.read_text().splitlines() if line.strip()]
    return []

def append_pending_topic(topic_str):
    """Add a topic to the pending topics log."""
    PENDING_TOPICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PENDING_TOPICS_FILE.open("a") as f:
        f.write(topic_str + "\n")

def remove_pending_topic(topic_str):
    """Remove a topic from the pending topics log (called when pipeline fires)."""
    if not PENDING_TOPICS_FILE.exists():
        return
    lines = [l.strip() for l in PENDING_TOPICS_FILE.read_text().splitlines()]
    lines = [l for l in lines if l and l != topic_str.strip()]
    PENDING_TOPICS_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))

def post_to_discord(topics):
    """Post all topic suggestions to Discord as separate messages."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from airtable.client import create_suggested
        airtable_enabled = True
    except Exception as e:
        print(f"  Airtable unavailable: {e}")
        airtable_enabled = False

    if not DISCORD_TOPICS_WEBHOOK_URL:
        print("  No DISCORD_TOPICS_WEBHOOK_URL set, skipping Discord.")
        return

    for topic in topics:
        msg = f"**Topic Suggestion**\n**{topic['topic']}**\n_{topic['why']}_\n\nReact ✅ to publish, ❌ to skip."
        requests.post(DISCORD_TOPICS_WEBHOOK_URL, json={"content": msg}, timeout=10)
        append_pending_topic(topic["topic"])
        if airtable_enabled:
            try:
                create_suggested(topic["topic"], why=topic.get("why"))
            except Exception as e:
                print(f"  Airtable write failed for '{topic['topic']}': {e}")
        print(f"  Posted: {topic['topic']}")

# ── Main ─────────────────────────────────────────────────────────────────────

def pick_topics():
    print("\nPulseOps Topic Picker")
    print("Fetching RSS feeds...")

    all_headlines = []
    for feed_url in RSS_FEEDS:
        items = fetch_feed(feed_url)
        all_headlines.extend(items)
        print(f"  {len(items)} items from {feed_url[:50]}...")

    print(f"\nTotal headlines: {len(all_headlines)}")

    existing = fetch_existing_posts()
    existing_context = "\n".join(f"- {t}" for t in existing) if existing else "None yet."

    system_prompt = """You are the Topic Picker for PulseOps, a blog about AI, automation, workflow tools, and practical technology for small business owners.

Your job: given a list of recent headlines, pick 5 strong blog post topics that:
- Are relevant to AI, automation, business workflows, productivity, or emerging tech
- Would genuinely interest small/medium business owners
- Haven't been covered by the existing posts
- Are specific enough to write a focused 1,500-word post about
- Have some search intent behind them (people would actually Google this)

Avoid:
- Pure consumer tech (gaming, phones, social media drama)
- Highly technical developer topics (unless there's a clear SMB angle)
- Topics already covered in the existing posts list

Important: No more than 2 of the 5 topics should be AI-focused. At least 3 must cover non-AI areas like marketing, operations, sales, finance, hiring, productivity, or tools for SMBs.

Return ONLY valid JSON — an array of 5 objects:
[
  {
    "topic": "The exact topic/title angle to write about",
    "why": "1-2 sentences: why this is timely, what the SMB angle is, and why it will get search traffic"
  }
]"""

    user_message = f"""Recent headlines:
{chr(10).join(all_headlines[:60])}

Already published (avoid duplicates):
{existing_context}"""

    # Load pending topics and add to dedup context
    pending = load_pending_topics()
    pending_context = "\n".join(f"- {t}" for t in pending) if pending else "None."
    user_message += f"\n\nAlready pending in Discord (avoid duplicates):\n{pending_context}"

    print("Asking Claude to pick topics...")
    response = call_claude(system_prompt, user_message)

    # Extract JSON
    match = re.search(r'\[[\s\S]*\]', response)
    if not match:
        print("Failed to parse Claude response:")
        print(response)
        return

    topics = json.loads(match.group(0))

    # Save all 5 topics to runs/topic_picks/
    picks_dir = Path(__file__).parent / "runs" / "topic_picks"
    picks_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    picks_file = picks_dir / f"{date_str}_topics.json"
    picks_file.write_text(json.dumps(topics, indent=2))
    print(f"\nSaved {len(topics)} topics to {picks_file}")

    for i, t in enumerate(topics, 1):
        print(f"  {i}. {t['topic']}")

    post_to_discord(topics)

if __name__ == "__main__":
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set")
        exit(1)
    pick_topics()
