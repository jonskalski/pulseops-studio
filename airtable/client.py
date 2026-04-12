#!/usr/bin/env python3
"""
Airtable client for PulseOps Studio.
Handles all reads/writes to Content Ideas, Pillars, and Social Posts tables.
"""

import os
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY  = os.getenv("AIRTABLE_API_KEY")
BASE_ID  = os.getenv("AIRTABLE_BASE_ID")
TABLE_CONTENT  = os.getenv("AIRTABLE_CONTENT_IDEAS_TABLE_ID")
TABLE_PILLARS  = os.getenv("AIRTABLE_PILLARS_TABLE_ID")
TABLE_CLUSTERS = os.getenv("AIRTABLE_CLUSTERS_TABLE_ID")
TABLE_SOCIAL   = os.getenv("AIRTABLE_SOCIAL_POSTS_TABLE_ID")
TABLE_REJECTED = os.getenv("AIRTABLE_REJECTED_POSTS_TABLE_ID")

BASE_URL = f"https://api.airtable.com/v0/{BASE_ID}"
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def _get(table, params=None):
    records = []
    offset = None
    while True:
        p = params.copy() if params else {}
        if offset:
            p["offset"] = offset
        r = requests.get(f"{BASE_URL}/{table}", headers=HEADERS, params=p, timeout=15)
        r.raise_for_status()
        data = r.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
    return records


def _create(table, fields):
    r = requests.post(f"{BASE_URL}/{table}", headers=HEADERS, json={"fields": fields}, timeout=15)
    r.raise_for_status()
    return r.json()


def _update(table, record_id, fields):
    r = requests.patch(f"{BASE_URL}/{table}/{record_id}", headers=HEADERS, json={"fields": fields, "typecast": True}, timeout=15)
    r.raise_for_status()
    return r.json()


def _find_by_topic(topic):
    """Find a Content Ideas record by topic name."""
    records = _get(TABLE_CONTENT, {"filterByFormula": f'LOWER({{Topic}}) = LOWER("{topic}")'})
    return records[0] if records else None


# ── Public API ───────────────────────────────────────────────────────────────

def create_suggested(topic, why=None, post_type="Standalone"):
    """Called by topic_picker.py when a topic is posted to Discord."""
    from datetime import date
    existing = _find_by_topic(topic)
    if existing:
        return existing
    return _create(TABLE_CONTENT, {
        "Topic": topic,
        "Type": post_type,
        "Status": "Suggested",
        "Priority": "Normal",
        "Suggested Date": date.today().isoformat(),
        **({"Why": why} if why else {}),
    })


def mark_approved(topic):
    """Called by discord_bot.py when ✅ reaction."""
    rec = _find_by_topic(topic)
    if rec:
        return _update(TABLE_CONTENT, rec["id"], {"Status": "In Queue"})


def mark_skipped(topic):
    """Called by discord_bot.py when ❌ reaction."""
    rec = _find_by_topic(topic)
    if rec:
        return _update(TABLE_CONTENT, rec["id"], {"Status": "Rejected"})


def mark_regenerate(topic):
    """Called by discord_bot.py when 🔁 reaction."""
    rec = _find_by_topic(topic)
    if rec:
        return _update(TABLE_CONTENT, rec["id"], {"Status": "Regenerate"})


def mark_published(topic, wp_post_id, wp_post_url):
    """Called by pipeline.py after successful WP publish."""
    from datetime import date
    rec = _find_by_topic(topic)
    if rec:
        return _update(TABLE_CONTENT, rec["id"], {
            "Status": "Published",
            "WP Post ID": str(wp_post_id),
            "WP Post URL": wp_post_url,
            "Published Date": date.today().isoformat(),
        })


def sync_pillar_stats(pillar_name):
    """Update Clusters Created and Clusters Published counts on the pillar record."""
    pillars = _get(TABLE_PILLARS, {"filterByFormula": f'LOWER({{Name}}) = LOWER("{pillar_name}")'})
    if not pillars:
        return
    pillar_id = pillars[0]["id"]
    clusters = _get(TABLE_CLUSTERS, {"filterByFormula": f'LOWER({{Parent Pillar}}) = LOWER("{pillar_name}")'})
    total = len(clusters)
    published = sum(1 for c in clusters if c["fields"].get("Status") == "Published")
    _update(TABLE_PILLARS, pillar_id, {"Clusters Created": total, "Clusters Published": published})


def create_cluster(title, pillar_name, angle=None, priority="Normal"):
    """Create a cluster post under a pillar."""
    from datetime import date
    return _create(TABLE_CLUSTERS, {
        "Title": title,
        "Parent Pillar": pillar_name,
        "Status": "Suggested",
        "Priority": priority,
        "Suggested Date": date.today().isoformat(),
        **({"Angle": angle} if angle else {}),
    })


def mark_cluster_published(title, wp_post_id, wp_post_url, run_id=None):
    """Flip cluster status to Published after WP post goes live."""
    from datetime import date
    records = _get(TABLE_CLUSTERS, {"filterByFormula": f'LOWER({{Title}}) = LOWER("{title}")'})
    if records:
        rec = records[0]
        fields = {
            "Status": "Published",
            "WP Post ID": str(wp_post_id),
            "WP Post URL": wp_post_url,
            "Published Date": date.today().isoformat(),
        }
        if run_id:
            fields["Run ID"] = run_id
        _update(TABLE_CLUSTERS, rec["id"], fields)
        pillar_name = rec["fields"].get("Parent Pillar")
        if pillar_name:
            sync_pillar_stats(pillar_name)


def get_published_clusters_for_pillar(pillar_name):
    """Return published cluster records for a pillar, most recent first."""
    records = _get(TABLE_CLUSTERS, {
        "filterByFormula": f'AND(LOWER({{Parent Pillar}}) = LOWER("{pillar_name}"), {{Status}} = "Published")'
    })
    records.sort(key=lambda r: r["fields"].get("Published Date", ""), reverse=True)
    return records


def backfill_published(posts):
    """
    Import existing WP published posts into Airtable.
    posts: list of dicts with keys: title, wp_id, url, date
    """
    existing = _get(TABLE_CONTENT)
    existing_urls = {r["fields"].get("WP Post URL") for r in existing}
    created = 0
    for p in posts:
        if p["url"] in existing_urls:
            continue
        _create(TABLE_CONTENT, {
            "Topic": p["title"],
            "Type": "Standalone",
            "Status": "Published",
            "WP Post ID": str(p["wp_id"]),
            "WP Post URL": p["url"],
        })
        created += 1
    return created


def log_rejected_post(topic, run_id, rejection_reason, score_breakdown, post_copy):
    """Log a post that failed all 3 approval attempts to the Rejected Posts table."""
    from datetime import date
    return _create(TABLE_REJECTED, {
        "Topic": topic,
        "Run ID": run_id,
        "Date": date.today().isoformat(),
        "Rejection Reason": rejection_reason,
        "Score Breakdown": score_breakdown,
        "Post Copy": post_copy[:100000],  # Airtable field limit
        "Status": "Needs Review",
    })


def get_force_publish_records():
    """Return all Rejected Posts records with Status = Force Publish."""
    return _get(TABLE_REJECTED, {"filterByFormula": "{Status} = 'Force Publish'"})


def get_rewrite_records():
    """Return all Rejected Posts records with Status = Rewrite."""
    return _get(TABLE_REJECTED, {"filterByFormula": "{Status} = 'Rewrite'"})


def update_rejected_status(record_id, status):
    """Update the Status field on a Rejected Posts record."""
    return _update(TABLE_REJECTED, record_id, {"Status": status})
