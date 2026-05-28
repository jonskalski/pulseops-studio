#!/usr/bin/env python3
"""
Backfill alt_text on all published post media attachments where it's missing.
Also fixes inline <img> tags in post content that have blank alt attributes.

Run: python3 backfill_image_alt_text.py [--dry-run]
"""

import sys
import re
import requests
from requests.auth import HTTPBasicAuth

DRY_RUN = "--dry-run" in sys.argv

with open("/root/.claude/settings.json") as f:
    import json
    env = json.load(f)["env"]

WP_URL = env["WP_URL"].rstrip("/")
auth = HTTPBasicAuth(env["WP_USER"], env["WP_APP_PASSWORD"])


def get_all_posts():
    posts = []
    page = 1
    while True:
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/posts", auth=auth, params={
            "per_page": 100, "page": page, "status": "publish",
            "context": "edit", "_fields": "id,title,content,featured_media,slug",
        })
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        posts.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return posts


def fix_media_alt(media_id, post_title):
    r = requests.get(f"{WP_URL}/wp-json/wp/v2/media/{media_id}", auth=auth,
                     params={"_fields": "id,alt_text,title"})
    if r.status_code != 200:
        return False
    media = r.json()
    existing = media.get("alt_text", "").strip()
    if existing:
        return False  # already has alt text
    print(f"  Media {media_id}: blank alt → setting to '{post_title}'")
    if not DRY_RUN:
        requests.post(f"{WP_URL}/wp-json/wp/v2/media/{media_id}", auth=auth,
                      json={"alt_text": post_title, "title": post_title}, timeout=15)
    return True


def fix_content_alts(post_id, content_raw, post_title):
    # Match <img ...> tags with blank or missing alt
    pattern = re.compile(r'<img([^>]*?)alt=""([^>]*?)>', re.IGNORECASE)
    missing_pattern = re.compile(r'<img(?![^>]*\balt\b)[^>]*>', re.IGNORECASE)

    updated = content_raw
    changed = False

    # Replace alt="" with alt="post title"
    def replace_blank(m):
        return f'<img{m.group(1)}alt="{post_title}"{m.group(2)}>'

    new = pattern.sub(replace_blank, updated)
    if new != updated:
        updated = new
        changed = True

    if changed:
        print(f"  Post {post_id}: fixed blank alt in content")
        if not DRY_RUN:
            requests.post(f"{WP_URL}/wp-json/wp/v2/posts/{post_id}", auth=auth,
                          json={"content": updated}, timeout=30)
    return changed


def main():
    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Fetching all published posts...")
    posts = get_all_posts()
    print(f"Found {len(posts)} posts\n")

    media_fixed = 0
    content_fixed = 0

    for post in posts:
        post_id = post["id"]
        title = post["title"]["raw"]
        print(f"Post {post_id}: {title[:60]}")

        # Fix featured image alt
        media_id = post.get("featured_media")
        if media_id:
            if fix_media_alt(media_id, title):
                media_fixed += 1

        # Fix inline image alts in content
        content_raw = post.get("content", {}).get("raw", "")
        if content_raw and fix_content_alts(post_id, content_raw, title):
            content_fixed += 1

    print(f"\nDone. Media attachments updated: {media_fixed} | Post content updated: {content_fixed}")
    if DRY_RUN:
        print("(dry run — no changes written)")


if __name__ == "__main__":
    main()
