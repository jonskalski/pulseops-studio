#!/usr/bin/env python3
"""
Backfill Published Title, Keyword, WP Slug, Meta Description, Schema Type, Word Count
on all Published cluster records in Airtable, sourced from runs/ JSON files.
"""
import os
import re
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

import sys
sys.path.insert(0, str(Path(__file__).parent))
from airtable.client import _get, _update, TABLE_CLUSTERS


def strip_html(html):
    return re.sub(r'<[^>]+>', ' ', html)


def count_words(html):
    return len(strip_html(html).split())


def detect_schema_type(title, content):
    howto_signals = ["how to ", "step-by-step", "steps to ", "guide to "]
    if any(s in title.lower() for s in howto_signals):
        steps = re.findall(r'<li[^>]*>(.*?)</li>', content, re.IGNORECASE | re.DOTALL)
        valid = [s for s in steps if len(re.sub(r'<[^>]+>', '', s).strip()) > 20]
        if valid:
            return "HowTo"
    return "Article"


def load_run_data(run_dir):
    """Extract the fields we need from a run directory."""
    polish_file = run_dir / "05_polish.json"
    outline_file = run_dir / "01_outline.json"
    published_file = run_dir / "published.json"

    if not all(f.exists() for f in [polish_file, outline_file, published_file]):
        return None

    polish = json.loads(polish_file.read_text())
    outline = json.loads(outline_file.read_text())
    published = json.loads(published_file.read_text())

    title = polish.get("title", "")
    content = polish.get("content", "")
    slug = polish.get("slug", "") or published.get("slug", "")
    wp_id = str(published.get("id", ""))
    wp_url = published.get("link", "") or published.get("guid", {}).get("rendered", "")

    return {
        "wp_id": wp_id,
        "wp_url": wp_url,
        "published_title": title,
        "keyword": outline.get("target_keyword", ""),
        "wp_slug": slug,
        "meta_description": polish.get("meta_description", ""),
        "schema_type": detect_schema_type(title, content),
        "word_count": count_words(content),
    }


def slugify(text):
    """Convert title to a slug-like string for fuzzy matching."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def main():
    runs_dir = Path(__file__).parent / "runs"
    print("Loading cluster records from Airtable (Published + In Queue)...")
    clusters = _get(TABLE_CLUSTERS, {
        "filterByFormula": "OR({Status} = 'Published', {Status} = 'In Queue')"
    })
    print(f"  {len(clusters)} clusters found")

    # Build lookups: by WP Post ID and by title slug
    by_wp_id = {}
    by_title_slug = {}
    for c in clusters:
        wp_id = c["fields"].get("WP Post ID", "").strip()
        if wp_id:
            by_wp_id[wp_id] = c
        title_slug = slugify(c["fields"].get("Title", ""))
        if title_slug:
            by_title_slug[title_slug] = c

    print(f"\nScanning runs/ for published.json files...")
    run_dirs = sorted([d for d in runs_dir.iterdir() if d.is_dir()])
    print(f"  {len(run_dirs)} run directories found\n")

    updated = 0
    skipped = 0
    unmatched = 0

    for run_dir in run_dirs:
        data = load_run_data(run_dir)
        if not data:
            continue

        # Match by WP Post ID first, then fall back to run dir slug
        cluster = by_wp_id.get(data["wp_id"])
        if not cluster:
            run_slug = re.sub(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_', '', run_dir.name)
            # Try matching against title slug (allow partial overlap)
            for title_slug, c in by_title_slug.items():
                # Check if the slugs share significant overlap
                ts_words = set(title_slug.split("-"))
                rs_words = set(run_slug.split("-"))
                if len(ts_words & rs_words) >= max(3, len(ts_words) // 2):
                    cluster = c
                    break

        if not cluster:
            unmatched += 1
            continue

        existing = cluster["fields"]
        # Skip if all new fields already populated
        if all([
            existing.get("Published Title"),
            existing.get("Keyword"),
            existing.get("WP Slug"),
            existing.get("Meta Description"),
            existing.get("Schema Type"),
            existing.get("Word Count"),
        ]):
            skipped += 1
            continue

        fields = {"Status": "Published"}
        if not existing.get("WP Post ID") and data["wp_id"]:
            fields["WP Post ID"] = data["wp_id"]
        if not existing.get("WP Post URL") and data["wp_url"]:
            fields["WP Post URL"] = data["wp_url"]
        if not existing.get("Published Title") and data["published_title"]:
            fields["Published Title"] = data["published_title"]
        if not existing.get("Keyword") and data["keyword"]:
            fields["Keyword"] = data["keyword"]
        if not existing.get("WP Slug") and data["wp_slug"]:
            fields["WP Slug"] = data["wp_slug"]
        if not existing.get("Meta Description") and data["meta_description"]:
            fields["Meta Description"] = data["meta_description"]
        if not existing.get("Schema Type") and data["schema_type"]:
            fields["Schema Type"] = data["schema_type"]
        if not existing.get("Word Count") and data["word_count"]:
            fields["Word Count"] = data["word_count"]

        _update(TABLE_CLUSTERS, cluster["id"], fields)
        title = existing.get("Title", run_dir.name)
        print(f"  Updated: {title[:65]}")
        updated += 1

    print(f"\nDone. Updated: {updated} | Already complete: {skipped} | No match: {unmatched}")


if __name__ == "__main__":
    main()
