#!/usr/bin/env python3
"""
cluster_writer.py — Pull the next unwritten cluster from Airtable and run the pipeline.

Runs on Sat/Mon/Wed (cron) to generate cluster posts that publish Mon/Wed/Fri.
Posts land as WP drafts and notify Discord #drafts for approval before scheduling.
"""

import os
import sys
import random
import subprocess
import requests
import glob
sys.path.insert(0, "/root/pulseops-studio")
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
from airtable.client import _get, _update, TABLE_CLUSTERS

RUNS_DIR = os.path.join(os.path.dirname(__file__), "runs")

DISCORD_WEBHOOK = os.environ.get("DISCORD_DRAFTS_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_URL")


def get_next_cluster():
    """Return a random Suggested cluster record to spread writes across pillars."""
    records = _get(TABLE_CLUSTERS, {"filterByFormula": "{Status} = 'Suggested'"})
    if not records:
        return None
    return random.choice(records)


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
        "--publish-days", "0,2,4",  # Mon/Wed/Fri only
        "--pillar", pillar,
        "--cluster-id", record_id,
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        out = proc.stderr.read()
        returncode = proc.wait()
        if out:
            print(f"[pipeline stderr] {out.decode()}", flush=True)
    except Exception as e:
        _update(TABLE_CLUSTERS, record_id, {"Status": "Suggested"})
        print(f"Failed to launch pipeline: {e}", flush=True)
        notify_discord(f"cluster_writer: Failed to launch pipeline for **{title}**: {e}")
        return

    # Find the run dir for this cluster and check if it published successfully
    published_date = None
    for meta_path in glob.glob(os.path.join(RUNS_DIR, "*/run_meta.json")):
        try:
            import json
            meta = json.load(open(meta_path))
            if meta.get("cluster_id") == record_id:
                pub_path = os.path.join(os.path.dirname(meta_path), "published.json")
                if os.path.exists(pub_path):
                    pub = json.load(open(pub_path))
                    published_date = pub.get("date", "")[:10]
                break
        except Exception:
            continue

    if published_date:
        _update(TABLE_CLUSTERS, record_id, {"Status": "Published", "Published Date": published_date})
        print(f"  Published: {title} ({published_date})", flush=True)
        notify_discord(f"cluster_writer: Published cluster post **{title}** (Pillar: {pillar}). Check #drafts when done.")
    else:
        _update(TABLE_CLUSTERS, record_id, {"Status": "Suggested"})
        print(f"  Pipeline failed, reverted to Suggested: {title}", flush=True)
        notify_discord(f"cluster_writer: Pipeline failed for **{title}** — reverted to Suggested for retry.")


if __name__ == "__main__":
    main()
