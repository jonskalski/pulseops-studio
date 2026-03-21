#!/usr/bin/env python3
"""
PulseOps Studio — Pillar Suggester
Asks Claude to suggest new content pillars based on the site niche and existing pillars.
Posts suggestions to Discord for approval. React ✅ to trigger pillar_planner.py.

Usage: python3 pillar_suggester.py
"""

import os
import json
import re
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
SONNET = "claude-sonnet-4-6"


def get_existing_pillars():
    """Fetch pillar names already in Airtable."""
    try:
        from airtable.client import _get, TABLE_PILLARS
        records = _get(TABLE_PILLARS)
        return [r["fields"].get("Name", "") for r in records if r["fields"].get("Name")]
    except Exception as e:
        print(f"  Could not fetch existing pillars: {e}")
        return []


def call_claude(prompt):
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": SONNET,
            "max_tokens": 2000,
            "system": """You are a content strategist for PulseOps, a blog about AI, automation, workflow tools, and practical technology for small business owners.

Audience: SMB owners and operators (5–50 employees), non-technical, trying to run better businesses with less chaos.

A content pillar is a broad topic area that supports 15–25 cluster posts. Good pillars are:
- Specific enough to own (not "AI" — too broad)
- Broad enough for 20 posts (not "Zapier Zap for Gmail" — too narrow)
- Evergreen with search demand
- Clearly relevant to the SMB audience""",
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def suggest_pillars(existing):
    existing_str = "\n".join(f"- {p}" for p in existing) if existing else "None yet."
    prompt = f"""Suggest 5 new content pillars for PulseOps.

Existing pillars (do not duplicate or overlap):
{existing_str}

For each pillar, provide:
- A clear pillar name (4–8 words, specific and ownable)
- A 1–2 sentence explanation of why it's a strong pillar for our audience

Return as JSON:
[
  {{"pillar": "<pillar name>", "why": "<why this works>"}},
  ...
]

Only return valid JSON, no other text."""

    raw = call_claude(prompt)
    match = re.search(r'\[[\s\S]*\]', raw)
    if not match:
        raise ValueError(f"Could not parse JSON from response:\n{raw}")
    return json.loads(match.group(0))


def post_to_discord(suggestions):
    if not DISCORD_WEBHOOK_URL:
        print("  No DISCORD_WEBHOOK_URL set, skipping Discord.")
        return
    for s in suggestions:
        msg = f"**Pillar Suggestion**\n**{s['pillar']}**\n_{s['why']}_\n\nReact ✅ to build clusters, ❌ to skip."
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=10)
        print(f"  Posted: {s['pillar']}")


def save_to_airtable(suggestions):
    try:
        from airtable.client import _create, _get, TABLE_PILLARS
        existing_names = {r["fields"].get("Name", "").lower() for r in _get(TABLE_PILLARS)}
        created = 0
        for s in suggestions:
            if s["pillar"].lower() in existing_names:
                print(f"  Skipped (exists): {s['pillar']}")
                continue
            _create(TABLE_PILLARS, {"Name": s["pillar"], "Status": "Suggested", "Summary": s["why"]})
            print(f"  Saved to Airtable: {s['pillar']}")
            created += 1
        return created
    except Exception as e:
        print(f"  Airtable write failed: {e}")
        return 0


def main():
    print("\nPulseOps Pillar Suggester")
    print("Fetching existing pillars...")
    existing = get_existing_pillars()
    print(f"  {len(existing)} existing pillars found")

    print("Asking Claude for suggestions...")
    suggestions = suggest_pillars(existing)

    print(f"\n{len(suggestions)} suggestions:")
    for i, s in enumerate(suggestions, 1):
        print(f"  {i}. {s['pillar']}")
        print(f"     {s['why']}")

    print("\nSaving to Airtable...")
    save_to_airtable(suggestions)

    print("Posting to Discord...")
    post_to_discord(suggestions)

    print("\nDone.")


if __name__ == "__main__":
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set")
        exit(1)
    main()
