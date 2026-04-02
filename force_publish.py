#!/usr/bin/env python3
"""
PulseOps Studio — Force Publish
Reads the last polished post from a run folder and publishes it to WordPress,
bypassing the Approver.

Usage:
  python3 force_publish.py --poll                         # poll Airtable for Force Publish records
  python3 force_publish.py <run_id> <airtable_record_id>  # publish a specific run directly
"""

import sys
import json
import requests
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

RUNS_DIR = Path(__file__).parent / "runs"
WP_URL = os.environ.get("WP_URL", "https://pulseops.us")
WP_USER = os.environ.get("WP_USER")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_DRAFTS_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_URL")


def discord(msg):
    if DISCORD_WEBHOOK_URL:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": msg}, timeout=5)
        except Exception:
            pass


def publish_run(run_id, record_id):
    run_dir = RUNS_DIR / run_id
    polish_file = run_dir / "05_polish.json"

    if not polish_file.exists():
        discord(f"❌ Force Publish failed — polish file not found for run: `{run_id}`")
        print(f"ERROR: {polish_file} not found")
        return False

    post_data = json.loads(polish_file.read_text())
    topic = post_data.get("title", run_id)

    discord(f"🚀 **Force Publishing** (bypassing Approver)\n**Topic:** {topic}\n**Run:** {run_id}")

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from pipeline import publish_to_wordpress
        result = publish_to_wordpress(post_data)
        wp_url = result.get("link", "")
        wp_id = result.get("id", "")
        discord(f"✅ **Force Published**\n**Title:** {topic}\n**URL:** {wp_url}")

        from airtable.client import update_rejected_status, mark_published
        update_rejected_status(record_id, "Published (Forced)")
        try:
            mark_published(topic, wp_post_id=str(wp_id), wp_post_url=wp_url)
        except Exception:
            pass

        print(f"Published: {wp_url}")
        return True
    except Exception as e:
        discord(f"❌ Force Publish failed for `{run_id}`: {e}")
        print(f"ERROR: {e}")
        return False


def poll():
    """Check Airtable for Force Publish records and process them."""
    sys.path.insert(0, str(Path(__file__).parent))
    from airtable.client import get_force_publish_records, update_rejected_status

    records = get_force_publish_records()
    if not records:
        return

    print(f"Found {len(records)} Force Publish record(s)")
    for rec in records:
        record_id = rec["id"]
        fields = rec.get("fields", {})
        run_id = fields.get("Run ID", "")
        topic = fields.get("Topic", run_id)

        if not run_id:
            print(f"  Skipping {record_id} — no Run ID")
            continue

        print(f"  Processing: {topic}")
        # Mark in-progress to prevent double-processing on next poll
        update_rejected_status(record_id, "Publishing...")
        publish_run(run_id, record_id)


def main():
    os.chdir(Path(__file__).parent)

    if len(sys.argv) == 2 and sys.argv[1] == "--poll":
        poll()
    elif len(sys.argv) == 3:
        run_id = sys.argv[1]
        record_id = sys.argv[2]
        publish_run(run_id, record_id)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
