#!/usr/bin/env python3
"""
cluster_writer.py — Pull the next unwritten cluster from Airtable and run the pipeline.

Runs on Sat/Mon/Wed (cron) to generate cluster posts that publish Mon/Wed/Fri.
Posts land as WP drafts and notify Discord #drafts for approval before scheduling.
"""

import os
import sys
import subprocess
import requests
sys.path.insert(0, "/root/pulseops-studio")
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
from airtable.client import _get, _update, TABLE_CLUSTERS

DISCORD_WEBHOOK = os.environ.get("DISCORD_DRAFTS_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_URL")


def get_next_cluster():
    """Return the next Suggested cluster record, ordered by creation time."""
    records = _get(TABLE_CLUSTERS, {"filterByFormula": "{Status} = 'Suggested'"})
    if not records:
        return None
    # Sort by created time (earliest first)
    records.sort(key=lambda r: r.get("createdTime", ""))
    return records[0]


def notify_discord(message):
    if DISCORD_WEBHOOK:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)


def main():
    cluster = get_next_cluster()

    if not cluster:
        print("No Suggested clusters found in Airtable.")
        notify_discord("cluster_writer: No Suggested clusters to write. Add more via pillar_planner.")
        return

    title = cluster["fields"].get("Title", "").strip()
    pillar = cluster["fields"].get("Parent Pillar", "").strip()
    record_id = cluster["id"]

    if not title:
        print("Cluster record has no title, skipping.")
        return

    print(f"Writing cluster: {title} (Pillar: {pillar})")

    # Mark as In Queue so it doesn't get picked again if this runs twice
    _update(TABLE_CLUSTERS, record_id, {"Status": "In Queue"})

    why = f"This is a cluster post for the '{pillar}' pillar. Write it as a standalone post that supports the pillar topic."

    cmd = [
        "python3", "/root/pulseops-studio/pipeline.py",
        title,
        "--why", why,
        "--publish-days", "0,2,4"  # Mon/Wed/Fri only
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        out = proc.stderr.read()
        if out:
            print(f"[pipeline stderr] {out.decode()}", flush=True)
        notify_discord(f"cluster_writer: Started pipeline for cluster post **{title}** (Pillar: {pillar}). Check #drafts when done.")
    except Exception as e:
        # Revert status if pipeline failed to launch
        _update(TABLE_CLUSTERS, record_id, {"Status": "Suggested"})
        print(f"Failed to launch pipeline: {e}")
        notify_discord(f"cluster_writer: Failed to launch pipeline for **{title}**: {e}")


if __name__ == "__main__":
    main()
