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


def rewrite_run(run_id, record_id, rejection_feedback):
    """Re-run the pipeline from Draft stage using existing outline/research + rejection feedback."""
    import json
    import re
    from datetime import datetime

    run_dir = RUNS_DIR / run_id
    outline_file = run_dir / "01_outline.json"
    research_file = run_dir / "02_research.json"

    if not outline_file.exists() or not research_file.exists():
        discord(f"❌ Rewrite failed — outline or research not found for run: `{run_id}`")
        print(f"ERROR: Missing outline/research in {run_dir}")
        from airtable.client import update_rejected_status
        update_rejected_status(record_id, "Needs Review")
        return False

    outline = json.loads(outline_file.read_text())
    research = json.loads(research_file.read_text())
    topic = outline.get("title") or outline.get("topic") or run_id

    # New run dir for the rewrite
    slug = re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    new_run_dir = RUNS_DIR / f"{timestamp}_{slug}"
    new_run_dir.mkdir(parents=True, exist_ok=True)

    discord(f"🔄 **Rewriting** (injecting approver feedback)\n**Topic:** {topic}\n**Original run:** {run_id}\n**New run:** {new_run_dir.name}")

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from pipeline import run_agent, discord as pipe_discord, publish_to_wordpress, load_posts_index, update_posts_index, RUNS_DIR as _

        # Build draft input with rejection feedback + internal linking context
        local_index = load_posts_index()
        posts_context = "\n".join([
            f"- {p['title']}" + (f" [{p['topic']}]" if p.get("topic") else "") + f" → /{p['slug']}/"
            for p in local_index
        ]) if local_index else ""
        linking_note = f"\n\nExisting posts (use sparingly — 1-2 max, only mid-sentence where naturally relevant):\n{posts_context}" if posts_context else ""

        draft_input = (
            f"Outline:\n{json.dumps(outline, indent=2)}\n\n"
            f"Research:\n{json.dumps(research, indent=2)}\n\n"
            f"Approver feedback from previous attempt (fix these issues):\n{rejection_feedback}"
            f"{linking_note}"
        )

        # Draft
        discord("⏳ Rewrite — Draft Agent running...")
        draft = run_agent("03_draft", draft_input, new_run_dir)

        # Edit
        discord("⏳ Rewrite — Edit Agent running...")
        edited = run_agent("04_edit", f"Draft:\n{json.dumps(draft, indent=2)}", new_run_dir)

        # Polish + Approve — 3 attempts
        approved = False
        polished = None
        last_comments = rejection_feedback

        def polish_and_approve(post_input, attempt_label, approver_feedback=None):
            discord(f"⏳ Rewrite Polish — {attempt_label}...")
            polish_input = f"Post:\n{json.dumps(post_input, indent=2)}"
            if approver_feedback:
                polish_input += f"\n\nApprover feedback from previous attempt (fix these issues):\n{approver_feedback}"
            p = run_agent("05_polish", polish_input, new_run_dir)
            discord(f"🔍 Rewrite Approver reviewing — {attempt_label}...")
            a = run_agent("06_approver", f"Post:\n{json.dumps(p, indent=2)}", new_run_dir)
            return p, a

        for attempt in range(1, 4):
            polished, approval = polish_and_approve(
                edited if attempt == 1 else polished,
                f"attempt {attempt}/3",
                approver_feedback=last_comments if attempt > 1 else None,
            )
            if isinstance(approval, dict) and approval.get("decision") == "APPROVED":
                scores = approval.get("scores", {})
                scores_str = "  ".join(f"{k}: {v}" for k, v in scores.items())
                discord(f"✅ **Rewrite APPROVED** on attempt {attempt}\n{scores_str}")
                approved = True
                break
            else:
                last_comments = approval.get("comments", "No specific feedback") if isinstance(approval, dict) else str(approval)
                discord(f"❌ Rewrite DENIED (attempt {attempt})\n**Reason:** {last_comments[:300]}")

        if not approved:
            (new_run_dir / "NEEDS_REVIEW.md").write_text(
                f"# Needs Manual Review\n\nApprover feedback (all 3 rewrite attempts failed):\n{last_comments}\n"
            )
            from airtable.client import update_rejected_status
            update_rejected_status(record_id, "Needs Review")
            discord(f"⚠️ **Rewrite failed** all 3 attempts — flipped back to Needs Review in Airtable.\nNew run: `{new_run_dir.name}`")
            return False

        # Publish
        discord("📤 Scheduling rewritten post to WordPress...")
        keyword = outline.get("target_keyword", "") if isinstance(outline, dict) else ""
        result = publish_to_wordpress(polished, keyword=keyword)
        wp_url = result.get("link", "")
        wp_id = result.get("id", "")
        pub_date = result.get("date", "")
        discord(f"🎉 **Rewrite Scheduled!**\n**URL:** {wp_url}\n**Publishes:** {pub_date[:10]}")
        (new_run_dir / "published.json").write_text(json.dumps(result, indent=2))

        update_posts_index(polished.get("title", topic), wp_url, polished.get("slug", ""), keyword)

        from airtable.client import update_rejected_status, mark_published
        update_rejected_status(record_id, "Published (Rewrite)")
        try:
            mark_published(topic, str(wp_id), wp_url)
        except Exception:
            pass

        return True

    except Exception as e:
        discord(f"❌ Rewrite failed for `{run_id}`: {e}")
        print(f"ERROR: {e}")
        from airtable.client import update_rejected_status
        update_rejected_status(record_id, "Needs Review")
        return False


def poll():
    """Check Airtable for Force Publish and Rewrite records and process them."""
    sys.path.insert(0, str(Path(__file__).parent))
    from airtable.client import get_force_publish_records, get_rewrite_records, update_rejected_status

    # Handle Force Publish
    records = get_force_publish_records()
    if records:
        print(f"Found {len(records)} Force Publish record(s)")
    for rec in records:
        record_id = rec["id"]
        fields = rec.get("fields", {})
        run_id = fields.get("Run ID", "")
        topic = fields.get("Topic", run_id)

        if not run_id:
            print(f"  Skipping {record_id} — no Run ID")
            continue

        print(f"  Force publishing: {topic}")
        update_rejected_status(record_id, "Publishing...")
        publish_run(run_id, record_id)

    # Handle Rewrite
    rewrite_records = get_rewrite_records()
    if rewrite_records:
        print(f"Found {len(rewrite_records)} Rewrite record(s)")
    for rec in rewrite_records:
        record_id = rec["id"]
        fields = rec.get("fields", {})
        run_id = fields.get("Run ID", "")
        topic = fields.get("Topic", run_id)
        rejection_feedback = fields.get("Rejection Reason", "")

        if not run_id:
            print(f"  Skipping {record_id} — no Run ID")
            continue

        print(f"  Rewriting: {topic}")
        update_rejected_status(record_id, "Rewriting...")
        rewrite_run(run_id, record_id, rejection_feedback)


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
