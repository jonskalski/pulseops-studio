#!/usr/bin/env python3
"""
Creates the PulseOps Studio tables in Airtable:
- Pillars
- Content Ideas
- Social Posts

Run once. Safe to re-run — skips tables that already exist.
"""

import os
import sys
import json
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

API_KEY = os.getenv("AIRTABLE_API_KEY")
BASE_ID = "appPC6RbZ95SgzgIM"

if not API_KEY:
    print("ERROR: AIRTABLE_API_KEY not set in .env")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

def get_existing_tables():
    r = requests.get(f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables", headers=HEADERS)
    r.raise_for_status()
    return {t["name"]: t["id"] for t in r.json()["tables"]}

def create_table(name, fields):
    r = requests.post(
        f"https://api.airtable.com/v0/meta/bases/{BASE_ID}/tables",
        headers=HEADERS,
        json={"name": name, "fields": fields},
    )
    if not r.ok:
        print(f"    API error: {r.text}")
    r.raise_for_status()
    return r.json()["id"]

# ── Table definitions ────────────────────────────────────────────────────────

PILLARS_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    {"name": "Status", "type": "singleSelect", "options": {"choices": [
        {"name": "Planning"},
        {"name": "Active"},
        {"name": "Ready"},
        {"name": "Published"},
    ]}},
    {"name": "Target Clusters", "type": "number", "options": {"precision": 0}},
    {"name": "Generate Pillar", "type": "checkbox", "options": {"icon": "check", "color": "greenBright"}},
    {"name": "Pillar Post URL", "type": "url"},
    {"name": "Notes", "type": "multilineText"},
]

CONTENT_IDEAS_FIELDS = [
    {"name": "Topic", "type": "singleLineText"},
    {"name": "Type", "type": "singleSelect", "options": {"choices": [
        {"name": "Hot"},
        {"name": "Cluster"},
        {"name": "Pillar"},
        {"name": "Buffer"},
        {"name": "Standalone"},
    ]}},
    {"name": "Status", "type": "singleSelect", "options": {"choices": [
        {"name": "Suggested"},
        {"name": "Approved"},
        {"name": "In Queue"},
        {"name": "Draft Ready"},
        {"name": "Published"},
        {"name": "Rejected"},
        {"name": "Regenerate"},
        {"name": "Expired"},
    ]}},
    {"name": "Priority", "type": "singleSelect", "options": {"choices": [
        {"name": "High"},
        {"name": "Normal"},
        {"name": "Low"},
    ]}},
    {"name": "Publish Date", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
    {"name": "Expires At", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
    {"name": "Why", "type": "multilineText"},
    {"name": "WP Post ID", "type": "singleLineText"},
    {"name": "WP Post URL", "type": "url"},
    {"name": "Regen Count", "type": "number", "options": {"precision": 0}},
    {"name": "Parent Pillar Name", "type": "singleLineText"},
]

SOCIAL_POSTS_FIELDS = [
    {"name": "Name", "type": "singleLineText"},
    {"name": "Platform", "type": "singleSelect", "options": {"choices": [
        {"name": "LinkedIn"},
        {"name": "Twitter/X"},
        {"name": "Facebook"},
    ]}},
    {"name": "Copy", "type": "multilineText"},
    {"name": "Link", "type": "url"},
    {"name": "Scheduled DateTime", "type": "dateTime", "options": {
        "dateFormat": {"name": "friendly"},
        "timeFormat": {"name": "12hour"},
        "timeZone": "America/New_York",
    }},
    {"name": "Status", "type": "singleSelect", "options": {"choices": [
        {"name": "Scheduled"},
        {"name": "Posted"},
    ]}},
    {"name": "Parent Blog Topic", "type": "singleLineText"},
]

# ── Run ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Connecting to base {BASE_ID}...")
    existing = get_existing_tables()
    print(f"Existing tables: {list(existing.keys()) or 'none'}\n")

    table_ids = {}

    for name, fields in [
        ("Pillars", PILLARS_FIELDS),
        ("Content Ideas", CONTENT_IDEAS_FIELDS),
        ("Social Posts", SOCIAL_POSTS_FIELDS),
    ]:
        if name in existing:
            print(f"  SKIP: '{name}' already exists (id: {existing[name]})")
            table_ids[name] = existing[name]
        else:
            print(f"  CREATE: '{name}'...")
            tid = create_table(name, fields)
            table_ids[name] = tid
            print(f"    Done. id: {tid}")

    print("\n=== Table IDs ===")
    for name, tid in table_ids.items():
        print(f"  {name}: {tid}")

    # Write IDs to .env additions file for easy copy-paste
    env_lines = [
        f"AIRTABLE_BASE_ID={BASE_ID}",
        f"AIRTABLE_PILLARS_TABLE_ID={table_ids.get('Pillars', '')}",
        f"AIRTABLE_CONTENT_IDEAS_TABLE_ID={table_ids.get('Content Ideas', '')}",
        f"AIRTABLE_SOCIAL_POSTS_TABLE_ID={table_ids.get('Social Posts', '')}",
    ]
    out_path = os.path.join(os.path.dirname(__file__), "table_ids.env")
    with open(out_path, "w") as f:
        f.write("\n".join(env_lines) + "\n")
    print(f"\nTable IDs saved to airtable/table_ids.env")
    print("Add those lines to your .env file.")

if __name__ == "__main__":
    main()
