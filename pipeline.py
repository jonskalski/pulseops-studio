#!/usr/bin/env python3
"""
PulseOps Studio — Content Pipeline
Usage: python3 pipeline.py "topic here" [--why "context"]
"""

import sys
import os
import json
import re
import argparse
import subprocess
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import load_dotenv

# ── Config ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
AGENTS_DIR = BASE_DIR / "agents"
RUNS_DIR = BASE_DIR / "runs"
RUNS_DIR.mkdir(exist_ok=True)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
WP_URL = os.environ.get("WP_URL", "https://pulseops.us")
WP_USER = os.environ.get("WP_USER")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

# ── Publish Schedule ────────────────────────────────────────────────────────
# Days to publish: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
PUBLISH_DAYS = [0, 1, 2, 3, 4]  # Mon-Fri
PUBLISH_HOUR = 9                  # 9am EST
SKIP_DATES = [                    # "YYYY-MM-DD" dates to never publish on
    # "2026-07-04",               # Example: July 4th
    # "2026-11-27",               # Example: Thanksgiving
]
# ────────────────────────────────────────────────────────────────────────────

# Models: use Haiku for cheap steps, Sonnet for quality steps
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"

AGENT_MODELS = {
    "01_outline": HAIKU,
    "02_research": HAIKU,
    "03_draft": SONNET,
    "04_edit": HAIKU,
    "05_polish": SONNET,
    "06_approver": SONNET,
}

# ── Scheduling ──────────────────────────────────────────────────────────────

def next_publish_slot():
    """Find next available Mon-Fri 9am EST slot not already taken in WP."""
    est = ZoneInfo("America/New_York")
    now = datetime.now(est)

    # Fetch already-scheduled future post dates from WP
    try:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"status": "future,draft", "per_page": 50, "_fields": "date"},
            auth=(WP_USER, WP_APP_PASSWORD),
            timeout=10,
        )
        taken = set()
        for p in r.json():
            try:
                d = datetime.fromisoformat(p["date"]).strftime("%Y-%m-%d")
                taken.add(d)
            except Exception:
                pass
    except Exception:
        taken = set()

    candidate = now.replace(hour=PUBLISH_HOUR, minute=0, second=0, microsecond=0)
    if now.hour >= PUBLISH_HOUR:
        candidate += timedelta(days=1)

    for _ in range(90):
        date_str = candidate.strftime("%Y-%m-%d")
        if candidate.weekday() in PUBLISH_DAYS and date_str not in taken and date_str not in SKIP_DATES:
            return candidate.strftime("%Y-%m-%dT%H:%M:%S")
        candidate += timedelta(days=1)

    return candidate.strftime("%Y-%m-%dT%H:%M:%S")

# ── Helpers ─────────────────────────────────────────────────────────────────

def discord(msg):
    if DISCORD_WEBHOOK_URL:
        try:
            chunks = [msg[i:i+1900] for i in range(0, len(msg), 1900)]
            for chunk in chunks:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=5)
        except Exception:
            pass

def call_claude(system_prompt, user_message, model=SONNET):
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 8192,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
    r = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["content"][0]["text"]

def extract_json(text):
    """Extract JSON from Claude response, handling markdown code blocks."""
    # Try to find JSON in code blocks first
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    candidate = match.group(1) if match else text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Try finding the outermost { } block and parsing that
        brace_match = re.search(r'(\{[\s\S]*\})', candidate)
        if brace_match:
            return json.loads(brace_match.group(1))
        raise

def run_agent(name, user_message, run_dir):
    prompt_file = AGENTS_DIR / f"{name}.md"
    system_prompt = prompt_file.read_text()
    model = AGENT_MODELS.get(name, SONNET)

    print(f"  Running {name} [{model}]...")
    result_text = call_claude(system_prompt, user_message, model)

    # Save raw output
    (run_dir / f"{name}_raw.txt").write_text(result_text)

    try:
        result_json = extract_json(result_text)
        (run_dir / f"{name}.json").write_text(json.dumps(result_json, indent=2))
        return result_json
    except json.JSONDecodeError:
        # Save as text if not valid JSON
        (run_dir / f"{name}.txt").write_text(result_text)
        return result_text

def fetch_pexels_image(keyword):
    """Search Pexels and return (image_url, photographer, pexels_url)."""
    if not PEXELS_API_KEY:
        return None, None, None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": keyword, "per_page": 5, "orientation": "landscape"},
            timeout=10,
        )
        photos = r.json().get("photos", [])
        if not photos:
            return None, None, None
        photo = photos[0]
        return photo["src"]["large2x"], photo["photographer"], photo["url"]
    except Exception as e:
        print(f"  Pexels fetch failed: {e}")
        return None, None, None

def upload_image_to_wordpress(image_url, title, slug):
    """Download image and upload to WordPress media library. Returns media ID."""
    try:
        img_data = requests.get(image_url, timeout=30).content
        filename = f"{slug}.jpg"
        r = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            auth=(WP_USER, WP_APP_PASSWORD),
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "image/jpeg",
            },
            data=img_data,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        return data["id"], data.get("source_url", "")
    except Exception as e:
        print(f"  Image upload failed: {e}")
        return None, None

def publish_to_wordpress(post_data, keyword=None):
    # Fetch and upload featured image
    featured_media_id = None
    uploaded_image_url = None
    search_term = keyword or post_data.get("slug", "technology automation").replace("-", " ")
    image_url, photographer, pexels_url = fetch_pexels_image(search_term)
    if image_url:
        print(f"  Fetching image: {pexels_url}")
        featured_media_id, uploaded_image_url = upload_image_to_wordpress(image_url, post_data["title"], post_data["slug"])
        if featured_media_id:
            print(f"  Image uploaded (ID: {featured_media_id}, photo by {photographer})")

    # Inject image into content after first paragraph
    content = post_data["content"]
    if uploaded_image_url and "</p>" in content:
        img_html = (
            f'<figure class="wp-block-image size-large">'
            f'<img src="{uploaded_image_url}" alt="{post_data["title"]}" />'
            f'</figure>'
        )
        insert_at = content.index("</p>") + 4
        content = content[:insert_at] + "\n" + img_html + "\n" + content[insert_at:]

    endpoint = f"{WP_URL}/wp-json/wp/v2/posts"
    payload = {
        "title": post_data["title"],
        "slug": post_data["slug"],
        "content": content,
        "excerpt": post_data.get("meta_description", ""),
        "status": "future",
        "date": next_publish_slot(),
        "author": 257061572,
    }
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    r = requests.post(
        endpoint,
        auth=(WP_USER, WP_APP_PASSWORD),
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

# ── Main Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(topic, why=None):
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    # Create run directory
    slug = re.sub(r'[^a-z0-9]+', '-', topic.lower()).strip('-')
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    run_dir = RUNS_DIR / f"{timestamp}_{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🚀 PulseOps Studio Pipeline")
    print(f"   Topic: {topic}")
    if why:
        print(f"   Why:   {why}")
    print(f"   Run:   {run_dir.name}\n")

    discord(f"🚀 **Studio Pipeline Started**\n**Topic:** {topic}\n**Run:** {run_dir.name}")

    # ── Fetch existing posts for internal linking ─────────────────────────
    try:
        wp_posts = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"per_page": 100, "status": "publish", "_fields": "title,slug"},
            timeout=15,
        ).json()
        existing_posts = [{"title": p["title"]["rendered"], "slug": p["slug"]} for p in wp_posts]
        posts_context = "\n".join([f"- {p['title']} → /{p['slug']}/" for p in existing_posts])
    except Exception:
        posts_context = ""

    # ── Step 1: Outline ──────────────────────────────────────────────────
    discord(f"⏳ Step 1/6 — Outline Agent running...")
    outline = run_agent("01_outline", f"Topic: {topic}", run_dir)
    sections = outline.get("sections", [])
    section_list = "\n".join(f"  {i+1}. {s.get('header','?')}" for i, s in enumerate(sections))
    discord(f"✅ Step 1/6 — Outline complete\n**Title:** {outline.get('title', '?')}\n**Keyword:** {outline.get('target_keyword', '?')}\n**Sections:**\n{section_list}")

    # ── Step 2: Research ─────────────────────────────────────────────────
    discord(f"⏳ Step 2/6 — Research Agent running...")
    research = run_agent("02_research", f"Outline:\n{json.dumps(outline, indent=2)}", run_dir)
    hook_angles = research.get("hook_angles", []) if isinstance(research, dict) else []
    pain_points = research.get("pain_points", []) if isinstance(research, dict) else []
    angle_preview = hook_angles[0][:120] if hook_angles else "none"
    pain_preview = pain_points[0][:100] if pain_points else "none"
    discord(f"✅ Step 2/6 — Research complete\n**Top angle:** {angle_preview}\n**Top pain point:** {pain_preview}")

    # ── Step 3: Draft ────────────────────────────────────────────────────
    discord(f"⏳ Step 3/6 — Draft Agent running...")
    linking_note = f"\n\nExisting posts (use sparingly — 1-2 max, only mid-sentence where naturally relevant, never at the end of a section as a habit):\n{posts_context}" if posts_context else ""
    why_note = f"\n\nTopic context: {why}" if why else ""
    draft_input = f"Outline:\n{json.dumps(outline, indent=2)}\n\nResearch:\n{json.dumps(research, indent=2)}{linking_note}{why_note}"
    draft = run_agent("03_draft", draft_input, run_dir)
    draft_content = draft.get('content', '') if isinstance(draft, dict) else ''
    word_count = len(draft_content.split())
    first_sentence = draft_content[:200].strip().split('. ')[0] + '.' if draft_content else '?'
    discord(f"✅ Step 3/6 — Draft complete (~{word_count} words)\n**Intro:** {first_sentence}")

    # ── Step 4: Edit ─────────────────────────────────────────────────────
    discord(f"⏳ Step 4/6 — Edit Agent running...")
    edited = run_agent("04_edit", f"Draft:\n{json.dumps(draft, indent=2)}", run_dir)
    edit_notes = edited.get('edit_notes', []) if isinstance(edited, dict) else []
    notes_preview = "\n".join(f"  - {n}" for n in edit_notes)
    discord(f"✅ Step 4/6 — Edit complete ({len(edit_notes)} edits)\n{notes_preview}")

    # ── Step 5 & 6: Polish + Approve — 3-attempt escalating retry ────────
    # Attempt 1: Polish → Approve
    # Attempt 2 (denied): Polish again → Approve
    # Attempt 3 (denied again): Rerun Draft with approver feedback → Polish → Approve
    # Still denied: flag for manual review
    approved = False
    polished = None
    last_comments = ""

    def polish_and_approve(post_input, attempt_label, run_dir):
        discord(f"⏳ Polish — {attempt_label}...")
        p = run_agent("05_polish", f"Post:\n{json.dumps(post_input, indent=2)}", run_dir)
        polish_notes = p.get('polish_notes', []) if isinstance(p, dict) else []
        notes_preview = "\n".join(f"  - {n}" for n in polish_notes) if polish_notes else "  (no notes)"
        discord(f"✅ Polish complete — {attempt_label}\n{notes_preview}")
        discord(f"🔍 Approver reviewing — {attempt_label}...")
        a = run_agent("06_approver", f"Post:\n{json.dumps(p, indent=2)}", run_dir)
        return p, a

    # Attempt 1: Polish → Approve
    polished, approval = polish_and_approve(edited, "attempt 1/3", run_dir)
    if isinstance(approval, dict) and approval.get("decision") == "APPROVED":
        scores = approval.get("scores", {})
        scores_str = "  " + "  ".join(f"{k}: {v}" for k, v in scores.items())
        discord(f"✅ **APPROVED** on attempt 1\n{scores_str}")
        approved = True
    else:
        last_comments = approval.get("comments", "No specific feedback") if isinstance(approval, dict) else str(approval)
        scores = approval.get("scores", {}) if isinstance(approval, dict) else {}
        failed = [k for k, v in scores.items() if v == "fail"]
        passed = [k for k, v in scores.items() if v == "pass"]
        score_summary = f"**Failed:** {', '.join(failed) or 'unknown'}  |  **Passed:** {', '.join(passed) or 'none'}"
        discord(f"❌ **DENIED** (attempt 1)\n{score_summary}\n**Reason:** {last_comments}")

    # Attempt 2: Polish again → Approve
    if not approved:
        discord(f"🔄 Sending back to Polish (attempt 2/3)...")
        polished, approval = polish_and_approve(polished, "attempt 2/3", run_dir)
        if isinstance(approval, dict) and approval.get("decision") == "APPROVED":
            scores = approval.get("scores", {})
            scores_str = "  " + "  ".join(f"{k}: {v}" for k, v in scores.items())
            discord(f"✅ **APPROVED** on attempt 2\n{scores_str}")
            approved = True
        else:
            last_comments = approval.get("comments", "No specific feedback") if isinstance(approval, dict) else str(approval)
            scores = approval.get("scores", {}) if isinstance(approval, dict) else {}
            failed = [k for k, v in scores.items() if v == "fail"]
            passed = [k for k, v in scores.items() if v == "pass"]
            score_summary = f"**Failed:** {', '.join(failed) or 'unknown'}  |  **Passed:** {', '.join(passed) or 'none'}"
            discord(f"❌ **DENIED** (attempt 2)\n{score_summary}\n**Reason:** {last_comments}")

    # Attempt 3: Rerun Draft with approver feedback → Polish → Approve
    if not approved:
        discord(f"🔄 Rerunning Draft with approver feedback (attempt 3/3)...")
        draft_retry_input = (
            f"Outline:\n{json.dumps(outline, indent=2)}\n\n"
            f"Research:\n{json.dumps(research, indent=2)}\n\n"
            f"Approver feedback from previous attempt (fix these issues):\n{last_comments}"
        )
        if linking_note:
            draft_retry_input += linking_note
        if why:
            draft_retry_input += f"\n\nTopic context: {why}"
        redraft = run_agent("03_draft", draft_retry_input, run_dir)
        discord(f"✅ Draft rerun complete")
        polished, approval = polish_and_approve(redraft, "attempt 3/3", run_dir)
        if isinstance(approval, dict) and approval.get("decision") == "APPROVED":
            scores = approval.get("scores", {})
            scores_str = "  " + "  ".join(f"{k}: {v}" for k, v in scores.items())
            discord(f"✅ **APPROVED** on attempt 3\n{scores_str}")
            approved = True
        else:
            last_comments = approval.get("comments", "No specific feedback") if isinstance(approval, dict) else str(approval)
            scores = approval.get("scores", {}) if isinstance(approval, dict) else {}
            failed = [k for k, v in scores.items() if v == "fail"]
            passed = [k for k, v in scores.items() if v == "pass"]
            score_summary = f"**Failed:** {', '.join(failed) or 'unknown'}  |  **Passed:** {', '.join(passed) or 'none'}"
            discord(f"❌ **DENIED** (attempt 3) — flagging for manual review\n{score_summary}\n**Reason:** {last_comments}")
            (run_dir / "NEEDS_REVIEW.md").write_text(f"# Needs Manual Review\n\nApprover feedback (all 3 attempts failed):\n{last_comments}\n")

    if not approved:
        print(f"\n⚠️  Post needs manual review. Check: {run_dir}")
        return

    # ── Publish ──────────────────────────────────────────────────────────
    discord(f"📤 Scheduling to WordPress...")
    try:
        keyword = outline.get("target_keyword", "") if isinstance(outline, dict) else ""
        result = publish_to_wordpress(polished, keyword=keyword)
        post_url = result.get("link", "unknown")
        post_id  = result.get("id", "")
        pub_date = result.get("date", "")
        discord(f"🎉 **Scheduled!**\n**URL:** {post_url}\n**Title:** {polished.get('title')}\n**Publishes:** {pub_date[:10]}")
        print(f"\n✅ Scheduled: {post_url}")
        (run_dir / "published.json").write_text(json.dumps(result, indent=2))
        # ── Airtable update ──────────────────────────────────────────────
        try:
            from airtable.client import mark_published
            mark_published(topic, post_id, post_url)
        except Exception as ae:
            print(f"  Airtable update failed: {ae}")
    except Exception as e:
        discord(f"❌ **WordPress publish failed:** {str(e)}")
        print(f"\n❌ Publish failed: {e}")
        print(f"   Post saved at: {run_dir}/05_polish.json")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("topic", nargs="+", help="Topic to write about")
    parser.add_argument("--why", default=None, help="Context: why this topic is timely and the SMB angle")
    args = parser.parse_args()
    topic = " ".join(args.topic)
    run_pipeline(topic, why=args.why)
