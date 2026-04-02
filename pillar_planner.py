#!/usr/bin/env python3
"""
PulseOps Studio — Pillar Planner
Given a pillar topic, generates a cluster map (20 post titles + angles)
and writes them to Airtable + Discord.

Usage: python3 pillar_planner.py "CRM Basics for Small Business"
"""

import sys
import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_PILLAR_WEBHOOK_URL") or os.getenv("DISCORD_WEBHOOK_URL")
SONNET = "claude-sonnet-4-6"


def call_claude(prompt):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": SONNET,
            "max_tokens": 4000,
            "system": """You are a content strategist for PulseOps, a blog about AI, automation, workflow tools, and practical technology for small business owners.

Your audience: SMB owners and operators (5-50 employees), not technical, trying to run better businesses with less chaos.

Voice: knowledgeable friend who's tired of the hype. Dry, direct, occasionally sardonic. No fake case studies. No corporate speak.""",
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def generate_clusters(pillar):
    prompt = f"""I'm building a content pillar around: "{pillar}"

Generate 20 cluster post titles for this pillar. Group them into 4-5 angles (e.g. "Getting Started", "Picking the Right Tool", "Common Mistakes", "Advanced Use", etc.).

For each post, give:
- A specific, opinionated title (not generic — pass the HubSpot listicle test)
- A one-line angle (what's the specific hook or pain point this addresses)

Return as JSON:
{{
  "pillar": "<pillar name>",
  "angles": [
    {{
      "angle": "<angle name>",
      "clusters": [
        {{"title": "<post title>", "angle": "<one-line hook>"}},
        ...
      ]
    }},
    ...
  ]
}}

Only return valid JSON, no other text."""

    raw = call_claude(prompt)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def post_to_discord(pillar, data):
    if not DISCORD_WEBHOOK_URL:
        return
    lines = [f"📐 **Pillar Brief: {pillar}**\n"]
    for angle in data.get("angles", []):
        lines.append(f"**{angle['angle']}**")
        for c in angle["clusters"]:
            lines.append(f"  • {c['title']}")
        lines.append("")
    lines.append("_Clusters written to Airtable. Approve individually there._")
    msg = "\n".join(lines)
    chunks = [msg[i:i+1900] for i in range(0, len(msg), 1900)]
    for chunk in chunks:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=10)


def write_to_airtable(pillar, data):
    try:
        from airtable.client import create_cluster, _create, TABLE_PILLARS
        # Create pillar record
        _create(TABLE_PILLARS, {"Name": pillar, "Status": "Planning", "Target Clusters": 20})
        print(f"  Created Pillar: {pillar}")
    except Exception as e:
        print(f"  Pillar record failed: {e}")

    total = 0
    try:
        from airtable.client import create_cluster
        for angle in data.get("angles", []):
            for c in angle["clusters"]:
                create_cluster(c["title"], pillar, angle=c.get("angle"))
                total += 1
        print(f"  Created {total} cluster records in Airtable")
    except Exception as e:
        print(f"  Cluster write failed: {e}")
    return total


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 pillar_planner.py \"Pillar Topic Here\"")
        sys.exit(1)

    pillar = " ".join(sys.argv[1:])
    print(f"\nGenerating cluster map for: {pillar}")
    print("Calling Claude...")

    data = generate_clusters(pillar)

    print(f"\n=== {data['pillar']} ===")
    total = 0
    for angle in data.get("angles", []):
        print(f"\n  [{angle['angle']}]")
        for c in angle["clusters"]:
            print(f"    • {c['title']}")
            print(f"      {c['angle']}")
            total += 1
    print(f"\nTotal clusters: {total}")

    print("\nWriting to Airtable...")
    write_to_airtable(pillar, data)

    print("Syncing pillar stats...")
    from airtable.client import sync_pillar_stats
    sync_pillar_stats(pillar)

    print("Posting to Discord...")
    post_to_discord(pillar, data)

    print("\nDone.")


if __name__ == "__main__":
    main()
