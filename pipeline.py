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
import time
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
POSTS_INDEX_FILE = BASE_DIR / "published_posts_index.json"
WP_USER = os.environ.get("WP_USER")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_DRAFTS_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK_URL")
DISCORD_PIPELINE_LOG_URL = os.environ.get("DISCORD_PIPELINE_LOG_WEBHOOK_URL")
DISCORD_LINKEDIN_WEBHOOK_URL = os.environ.get("DISCORD_LINKEDIN_WEBHOOK_URL")
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

# ── Posts Index ─────────────────────────────────────────────────────────────

def get_pillar_voice_context(pillar_name, runs_dir=None):
    """
    Find up to 3 published sibling posts in the same pillar and extract their
    intro paragraph + title as a voice/terminology reference for the Draft agent.
    Returns a formatted string, or empty string if nothing useful found.
    """
    if runs_dir is None:
        runs_dir = RUNS_DIR
    try:
        from airtable.client import get_published_clusters_for_pillar
        siblings = get_published_clusters_for_pillar(pillar_name)
    except Exception:
        return ""

    samples = []
    for rec in siblings[:3]:
        fields = rec.get("fields", {})
        run_id = fields.get("Run ID", "")
        title = fields.get("Title", "")
        if not run_id:
            continue
        polish_file = runs_dir / run_id / "05_polish.json"
        if not polish_file.exists():
            continue
        try:
            post = json.loads(polish_file.read_text())
            content = post.get("content", "")
            # Strip HTML tags and grab first ~300 chars (intro paragraph)
            import re as _re
            plain = _re.sub(r'<[^>]+>', '', content).strip()
            intro = plain[:300].rsplit(' ', 1)[0] + '…' if len(plain) > 300 else plain
            if intro:
                samples.append(f'- **{title}**: "{intro}"')
        except Exception:
            continue

    if not samples:
        return ""

    return (
        f"\n\nVoice consistency — existing published posts in the '{pillar_name}' pillar "
        f"(match their tone, terminology, and sentence rhythm):\n"
        + "\n".join(samples)
    )


def load_posts_index():
    """Load local published posts index (title, url, slug, topic)."""
    if POSTS_INDEX_FILE.exists():
        try:
            return json.loads(POSTS_INDEX_FILE.read_text())
        except Exception:
            return []
    return []

def update_posts_index(title, url, slug, topic):
    """Add a newly published post to the local index."""
    index = load_posts_index()
    index = [p for p in index if p.get("slug") != slug]  # remove if exists
    index.append({
        "title": title,
        "url": url,
        "slug": slug,
        "topic": topic,
        "published_date": datetime.now().strftime("%Y-%m-%d"),
    })
    POSTS_INDEX_FILE.write_text(json.dumps(index, indent=2))

# ── Schema Markup ────────────────────────────────────────────────────────────

def detect_schema_type(post_data):
    """Return the schema type string that would be used for this post."""
    title_lower = post_data.get("title", "").lower()
    content = post_data.get("content", "")
    howto_signals = ["how to ", "step-by-step", "steps to ", "guide to "]
    if any(s in title_lower for s in howto_signals):
        steps = re.findall(r'<li[^>]*>(.*?)</li>', content, re.IGNORECASE | re.DOTALL)
        valid_steps = [s for s in steps if len(re.sub(r'<[^>]+>', '', s).strip()) > 20]
        if valid_steps:
            return "HowTo"
    return "Article"


def count_words(html_content):
    """Strip HTML tags and return word count."""
    text = re.sub(r'<[^>]+>', ' ', html_content)
    return len(text.split())


def generate_schema_markup(post_data, pub_date_str=""):
    """Generate JSON-LD schema. Defaults to Article, upgrades to HowTo."""
    content = post_data.get("content", "")
    title = post_data.get("title", "")
    date_str = pub_date_str[:10] if pub_date_str else datetime.now().strftime("%Y-%m-%d")
    schema_type = detect_schema_type(post_data)

    if schema_type == "HowTo":
        steps = []
        for i, m in enumerate(
            re.finditer(r'<li[^>]*>(.*?)</li>', content, re.IGNORECASE | re.DOTALL), 1
        ):
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if text and len(text) > 20:
                steps.append({"@type": "HowToStep", "position": i, "text": text[:200]})
            if len(steps) >= 10:
                break
        if steps:
            schema = {
                "@context": "https://schema.org",
                "@type": "HowTo",
                "name": title,
                "step": steps,
            }
            return f'\n<script type="application/ld+json">\n{json.dumps(schema, indent=2)}\n</script>'

    # Default: Article
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "author": {"@type": "Organization", "name": "PulseOps"},
        "datePublished": date_str,
        "publisher": {"@type": "Organization", "name": "PulseOps", "url": WP_URL},
    }
    return f'\n<script type="application/ld+json">\n{json.dumps(schema, indent=2)}\n</script>'

# ── Scheduling ──────────────────────────────────────────────────────────────

def next_publish_slot(allowed_days=None):
    """Find next available 9am EST slot on allowed_days not already taken in WP.

    allowed_days: list of weekday ints (0=Mon ... 6=Sun). Defaults to PUBLISH_DAYS.
    """
    if allowed_days is None:
        allowed_days = PUBLISH_DAYS

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
        if candidate.weekday() in allowed_days and date_str not in taken and date_str not in SKIP_DATES:
            return candidate.strftime("%Y-%m-%dT%H:%M:%S")
        candidate += timedelta(days=1)

    return candidate.strftime("%Y-%m-%dT%H:%M:%S")

# ── Helpers ─────────────────────────────────────────────────────────────────

def _post_webhook(url, msg):
    try:
        for chunk in [msg[i:i+1900] for i in range(0, len(msg), 1900)]:
            requests.post(url, json={"content": chunk}, timeout=5)
    except Exception:
        pass

def discord(msg):
    """Post a key event to #drafts."""
    if DISCORD_WEBHOOK_URL:
        _post_webhook(DISCORD_WEBHOOK_URL, msg)

def discord_log(msg):
    """Post a step-level progress update to #pipeline-logs (falls back to #drafts)."""
    url = DISCORD_PIPELINE_LOG_URL or DISCORD_WEBHOOK_URL
    if url:
        _post_webhook(url, msg)

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
    last_exc = None
    for attempt in range(3):
        try:
            r = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=120)
            if r.status_code in (529, 503, 502):
                wait = 30 * (2 ** attempt)
                print(f"  API overloaded {r.status_code} (attempt {attempt+1}/3), retrying in {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()["content"][0]["text"]
        except requests.exceptions.ReadTimeout as e:
            last_exc = e
            if attempt < 2:
                wait = 45 * (2 ** attempt)
                print(f"  API timeout (attempt {attempt+1}/3), retrying in {wait}s...")
                time.sleep(wait)
        except requests.exceptions.ConnectionError as e:
            last_exc = e
            if attempt < 2:
                wait = 15 * (2 ** attempt)
                print(f"  API connection error (attempt {attempt+1}/3), retrying in {wait}s...")
                time.sleep(wait)
    raise last_exc or Exception("API failed after 3 attempts")

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

def count_post_words(html_content):
    """Strip HTML tags and entities, return word count."""
    plain = re.sub(r'<[^>]+>', ' ', html_content)
    plain = re.sub(r'&[a-zA-Z]+;', ' ', plain)
    return len(plain.split())


def validate_and_repolish(polished, attempt_label, run_dir, approver_feedback=None):
    """
    Measure word count and meta description length after Polish.
    If either is out of spec, re-prompt Polish with exact numbers (up to 2 correction rounds).
    Returns the corrected polished dict.
    """
    WORD_MIN, WORD_MAX = 1500, 2000
    META_MIN, META_MAX = 150, 160

    for correction in range(2):
        if not isinstance(polished, dict):
            break
        content  = polished.get("content", "")
        meta     = polished.get("meta_description", "")
        words    = count_post_words(content)
        meta_len = len(meta)

        issues = []
        if words < WORD_MIN:
            issues.append(
                f"Word count is {words} — must be at least {WORD_MIN}. "
                f"Add {WORD_MIN - words + 50}+ words to the thinnest section(s)."
            )
        elif words > WORD_MAX:
            issues.append(
                f"Word count is {words} — must be under {WORD_MAX}. "
                f"Cut {words - WORD_MAX + 20}+ words from the longest section."
            )

        if meta_len < META_MIN:
            issues.append(
                f"Meta description is {meta_len} characters — must be {META_MIN}-{META_MAX}. "
                f"Add {META_MIN - meta_len}–{META_MAX - meta_len} characters of specific detail. "
                f"Current meta: \"{meta}\""
            )
        elif meta_len > META_MAX:
            issues.append(
                f"Meta description is {meta_len} characters — must be {META_MIN}-{META_MAX}. "
                f"Trim {meta_len - META_MAX} characters. "
                f"Current meta: \"{meta}\""
            )

        if not issues:
            break

        fix_note = "\n".join(f"- {i}" for i in issues)
        discord(
            f"🔧 **Auto-fix** ({attempt_label}, correction {correction+1}/2) — "
            + "; ".join(issues)
        )
        print(f"  Auto-fix ({correction+1}/2): " + "; ".join(issues))
        polish_input = (
            f"Post:\n{json.dumps(polished, indent=2)}\n\n"
            f"PIPELINE MEASUREMENT — fix these before returning (these are exact counts, not estimates):\n"
            f"{fix_note}"
        )
        if approver_feedback:
            polish_input += f"\n\nApprover feedback from previous attempt:\n{approver_feedback}"
        polished = run_agent("05_polish", polish_input, run_dir)

    return polished


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

def publish_to_wordpress(post_data, keyword=None, allowed_days=None):
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

    # Inject image into content after first paragraph.
    # Use Gutenberg block format with attachment ID so Yoast deduplicates against
    # the featured image in the sitemap (WP.com serves featured images via Photon CDN,
    # making the URL differ from the raw upload URL — block ID is the dedup key).
    content = post_data["content"]
    alt_text = keyword or search_term  # keyword-descriptive alt text, not post title
    if uploaded_image_url and featured_media_id and "</p>" in content:
        img_html = (
            f'\n<!-- wp:image {{"id":{featured_media_id},"sizeSlug":"large","linkDestination":"none"}} -->\n'
            f'<figure class="wp-block-image size-large">'
            f'<img src="{uploaded_image_url}" alt="{alt_text}" class="wp-image-{featured_media_id}" />'
            f'</figure>\n'
            f'<!-- /wp:image -->\n'
        )
        insert_at = content.index("</p>") + 4
        content = content[:insert_at] + img_html + content[insert_at:]

    # Append JSON-LD schema markup
    pub_date = next_publish_slot(allowed_days=allowed_days)
    content = content + generate_schema_markup(post_data, pub_date)

    endpoint = f"{WP_URL}/wp-json/wp/v2/posts"
    payload = {
        "title": post_data["title"],
        "slug": post_data["slug"],
        "content": content,
        "excerpt": post_data.get("meta_description", ""),
        "status": "future",
        "date": pub_date,
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
    post = r.json()

    # Apply Astra page-builder meta so the dark Elementor post template renders correctly
    astra_meta = {
        "site-sidebar-layout": "no-sidebar",
        "site-content-layout": "page-builder",
        "ast-site-content-layout": "full-width-container",
        "site-content-style": "unboxed",
        "theme-transparent-header-meta": "enabled",
        "site-post-title": "disabled",
        "ast-featured-img": "disabled",
    }
    requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post['id']}",
        auth=(WP_USER, WP_APP_PASSWORD),
        json={"meta": astra_meta},
        timeout=15,
    )

    return post

# ── Resume Pipeline ──────────────────────────────────────────────────────────

def resume_pipeline(run_dir_path):
    """Resume an incomplete or NEEDS_REVIEW run from its last completed step."""
    run_dir = Path(run_dir_path)
    if not run_dir.exists():
        print(f"ERROR: run directory not found: {run_dir}")
        sys.exit(1)

    meta_file = run_dir / "run_meta.json"
    meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
    topic       = meta.get("topic", run_dir.name.split("_", 2)[-1].replace("-", " "))
    why         = meta.get("why")
    pillar      = meta.get("pillar")
    cluster_id  = meta.get("cluster_id")
    allowed_days = meta.get("allowed_days")

    def load_json(name):
        f = run_dir / f"{name}.json"
        return json.loads(f.read_text()) if f.exists() else None

    outline  = load_json("01_outline")
    research = load_json("02_research")
    edited   = load_json("04_edit")

    needs_review_file = run_dir / "NEEDS_REVIEW.md"
    initial_feedback = None
    if needs_review_file.exists():
        raw = needs_review_file.read_text()
        initial_feedback = raw.replace("# Needs Manual Review\n\nApprover feedback (all 3 attempts failed):\n", "").strip()
        needs_review_file.unlink()
        print(f"  Resuming NEEDS_REVIEW run with prior feedback injected")
    else:
        print(f"  Resuming incomplete run from 04_edit")

    if edited is None:
        print("ERROR: 04_edit.json not found — cannot resume from this point")
        sys.exit(1)

    print(f"\n🔄 Resuming pipeline: {run_dir.name}")
    print(f"   Topic: {topic}\n")
    discord(f"🔄 **Pipeline Resumed**\n**Topic:** {topic}\n**Run:** {run_dir.name}")

    linking_note = ""
    why_note = f"\n\nTopic context: {why}" if why else ""

    # ── Polish + Approve (3-attempt loop, same as run_pipeline) ─────────────
    approved = False
    polished = None
    last_comments = initial_feedback or ""

    def polish_and_approve(post_input, attempt_label, approver_feedback=None):
        discord_log(f"⏳ Polish — {attempt_label}...")
        polish_input = f"Post:\n{json.dumps(post_input, indent=2)}"
        if approver_feedback:
            polish_input += f"\n\nApprover feedback from previous attempt (fix these issues):\n{approver_feedback}"
        p = run_agent("05_polish", polish_input, run_dir)
        polish_notes = p.get('polish_notes', []) if isinstance(p, dict) else []
        notes_preview = "\n".join(f"  - {n}" for n in polish_notes) if polish_notes else "  (no notes)"
        discord_log(f"✅ Polish complete — {attempt_label}\n{notes_preview}")
        p = validate_and_repolish(p, attempt_label, run_dir, approver_feedback=approver_feedback)
        if isinstance(p, dict):
            words    = count_post_words(p.get("content", ""))
            meta_len = len(p.get("meta_description", ""))
            discord_log(f"📏 Measurements — words: {words}, meta: {meta_len} chars")
        discord_log(f"🔍 Approver reviewing — {attempt_label}...")
        a = run_agent("06_approver", f"Post:\n{json.dumps(p, indent=2)}", run_dir)
        return p, a

    polished, approval = polish_and_approve(edited, "attempt 1/3", approver_feedback=last_comments if last_comments else None)
    if isinstance(approval, dict) and approval.get("decision") == "APPROVED":
        discord_log(f"✅ **APPROVED** on attempt 1")
        approved = True
    else:
        last_comments = approval.get("comments", "No specific feedback") if isinstance(approval, dict) else str(approval)
        scores = approval.get("scores", {}) if isinstance(approval, dict) else {}
        failed = [k for k, v in scores.items() if v == "fail"]
        discord_log(f"❌ **DENIED** (attempt 1) — Failed: {', '.join(failed) or 'unknown'}")

    if not approved:
        polished, approval = polish_and_approve(polished, "attempt 2/3", approver_feedback=last_comments)
        if isinstance(approval, dict) and approval.get("decision") == "APPROVED":
            discord_log(f"✅ **APPROVED** on attempt 2")
            approved = True
        else:
            last_comments = approval.get("comments", "No specific feedback") if isinstance(approval, dict) else str(approval)
            scores = approval.get("scores", {}) if isinstance(approval, dict) else {}
            failed = [k for k, v in scores.items() if v == "fail"]
            discord_log(f"❌ **DENIED** (attempt 2) — Failed: {', '.join(failed) or 'unknown'}")

    if not approved and outline and research:
        discord_log(f"🔄 Rerunning Draft with approver feedback (attempt 3/3)...")
        draft_retry_input = (
            f"Outline:\n{json.dumps(outline, indent=2)}\n\n"
            f"Research:\n{json.dumps(research, indent=2)}\n\n"
            f"Approver feedback from previous attempt (fix these issues):\n{last_comments}"
        )
        if why:
            draft_retry_input += f"\n\nTopic context: {why}"
        redraft = run_agent("03_draft", draft_retry_input, run_dir)
        discord_log(f"✅ Draft rerun complete")
        polished, approval = polish_and_approve(redraft, "attempt 3/3", approver_feedback=last_comments)
        if isinstance(approval, dict) and approval.get("decision") == "APPROVED":
            discord_log(f"✅ **APPROVED** on attempt 3")
            approved = True
        else:
            last_comments = approval.get("comments", "No specific feedback") if isinstance(approval, dict) else str(approval)
            scores = approval.get("scores", {}) if isinstance(approval, dict) else {}
            failed = [k for k, v in scores.items() if v == "fail"]
            discord(f"❌ **NEEDS REVIEW** (all 3 attempts failed)\nFailed: {', '.join(failed) or 'unknown'}\n{last_comments}")
            (run_dir / "NEEDS_REVIEW.md").write_text(f"# Needs Manual Review\n\nApprover feedback (all 3 attempts failed):\n{last_comments}\n")

    if not approved:
        print(f"\n⚠️  Post still needs manual review: {run_dir}")
        return

    # ── Publish ──────────────────────────────────────────────────────────────
    discord_log(f"📤 Scheduling to WordPress...")
    try:
        keyword = outline.get("target_keyword", "") if isinstance(outline, dict) else ""
        result = publish_to_wordpress(polished, keyword=keyword, allowed_days=allowed_days)
        post_url = result.get("link", "unknown")
        post_id  = result.get("id", "")
        pub_date = result.get("date", "")
        discord(f"🎉 **Scheduled!**\n**URL:** {post_url}\n**Title:** {polished.get('title')}\n**Publishes:** {pub_date[:10]}")
        print(f"\n✅ Scheduled: {post_url}")
        (run_dir / "published.json").write_text(json.dumps(result, indent=2))
        update_posts_index(polished.get("title", topic), post_url, polished.get("slug", ""), keyword)
        try:
            from airtable.client import mark_published, mark_cluster_published
            mark_published(topic, post_id, post_url)
            if pillar:
                mark_cluster_published(
                    polished.get("title", topic), post_id, post_url,
                    run_id=run_dir.name, cluster_id=cluster_id,
                    published_title=polished.get("title", ""),
                    keyword=keyword, wp_slug=polished.get("slug", ""),
                    meta_description=polished.get("meta_description", ""),
                    schema_type=detect_schema_type(polished),
                    word_count=count_words(polished.get("content", "")),
                )
        except Exception as ae:
            print(f"  Airtable update failed: {ae}")
    except Exception as e:
        discord(f"❌ **WordPress publish failed:** {str(e)}")
        print(f"\n❌ Publish failed: {e}")

# ── Main Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(topic, why=None, allowed_days=None, pillar=None, cluster_id=None):
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

    # Save metadata so --resume can recover context
    (run_dir / "run_meta.json").write_text(json.dumps({
        "topic": topic, "why": why, "pillar": pillar,
        "cluster_id": cluster_id,
        "allowed_days": allowed_days,
    }, indent=2))

    # ── Keyword cannibalization check ─────────────────────────────────────
    existing_index = load_posts_index()
    topic_lower = topic.lower()
    conflicts = [
        p for p in existing_index
        if p.get("topic") and p["topic"].lower() in topic_lower or topic_lower in p.get("topic", "").lower()
        or any(word in p["title"].lower() for word in topic_lower.split() if len(word) > 4)
    ]
    if conflicts:
        conflict_list = "\n".join(f"  - {p['title']} [{p.get('topic','')}] → {p.get('url','')}" for p in conflicts[:3])
        discord(f"⚠️ **Cannibalization warning** — existing posts may target the same keyword:\n{conflict_list}\nContinuing anyway.")

    # ── Fetch existing posts for internal linking ─────────────────────────
    # Local index has topic/keyword data; WP API fills in any gaps
    local_index = load_posts_index()
    local_slugs = {p["slug"] for p in local_index}
    try:
        wp_posts = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"per_page": 100, "status": "publish", "_fields": "title,slug"},
            timeout=15,
        ).json()
        for p in wp_posts:
            if p["slug"] not in local_slugs:
                local_index.append({"title": p["title"]["rendered"], "slug": p["slug"], "topic": ""})
    except Exception:
        pass
    if local_index:
        posts_context = "\n".join([
            f"- {p['title']}" + (f" [{p['topic']}]" if p.get("topic") else "") + f" → /{p['slug']}/"
            for p in local_index
        ])
    else:
        posts_context = ""

    # ── Step 1: Outline ──────────────────────────────────────────────────
    discord_log(f"⏳ Step 1/6 — Outline Agent running...")
    outline = run_agent("01_outline", f"Topic: {topic}", run_dir)
    sections = outline.get("sections", [])
    section_list = "\n".join(f"  {i+1}. {s.get('header','?')}" for i, s in enumerate(sections))
    discord_log(f"✅ Step 1/6 — Outline complete\n**Title:** {outline.get('title', '?')}\n**Keyword:** {outline.get('target_keyword', '?')}\n**Sections:**\n{section_list}")

    # ── Step 2: Research ─────────────────────────────────────────────────
    discord_log(f"⏳ Step 2/6 — Research Agent running...")
    research = run_agent("02_research", f"Outline:\n{json.dumps(outline, indent=2)}", run_dir)
    hook_angles = research.get("hook_angles", []) if isinstance(research, dict) else []
    pain_points = research.get("pain_points", []) if isinstance(research, dict) else []
    angle_preview = hook_angles[0][:120] if hook_angles else "none"
    pain_preview = pain_points[0][:100] if pain_points else "none"
    discord_log(f"✅ Step 2/6 — Research complete\n**Top angle:** {angle_preview}\n**Top pain point:** {pain_preview}")

    # ── Step 3: Draft ────────────────────────────────────────────────────
    discord_log(f"⏳ Step 3/6 — Draft Agent running...")
    linking_note = f"\n\nExisting posts (use sparingly — 1-2 max, only mid-sentence where naturally relevant, never at the end of a section as a habit):\n{posts_context}" if posts_context else ""
    why_note = f"\n\nTopic context: {why}" if why else ""
    pillar_note = get_pillar_voice_context(pillar) if pillar else ""
    draft_input = f"Outline:\n{json.dumps(outline, indent=2)}\n\nResearch:\n{json.dumps(research, indent=2)}{linking_note}{why_note}{pillar_note}"
    draft = run_agent("03_draft", draft_input, run_dir)
    draft_content = draft.get('content', '') if isinstance(draft, dict) else ''
    word_count = len(draft_content.split())
    first_sentence = draft_content[:200].strip().split('. ')[0] + '.' if draft_content else '?'
    discord_log(f"✅ Step 3/6 — Draft complete (~{word_count} words)\n**Intro:** {first_sentence}")

    # ── Step 4: Edit ─────────────────────────────────────────────────────
    discord_log(f"⏳ Step 4/6 — Edit Agent running...")
    edited = run_agent("04_edit", f"Draft:\n{json.dumps(draft, indent=2)}", run_dir)
    edit_notes = edited.get('edit_notes', []) if isinstance(edited, dict) else []
    notes_preview = "\n".join(f"  - {n}" for n in edit_notes)
    discord_log(f"✅ Step 4/6 — Edit complete ({len(edit_notes)} edits)\n{notes_preview}")

    # ── Step 5 & 6: Polish + Approve — 3-attempt escalating retry ────────
    # Attempt 1: Polish → Approve
    # Attempt 2 (denied): Polish again → Approve
    # Attempt 3 (denied again): Rerun Draft with approver feedback → Polish → Approve
    # Still denied: flag for manual review
    approved = False
    polished = None
    last_comments = ""

    def polish_and_approve(post_input, attempt_label, run_dir, approver_feedback=None):
        discord_log(f"⏳ Polish — {attempt_label}...")
        polish_input = f"Post:\n{json.dumps(post_input, indent=2)}"
        if approver_feedback:
            polish_input += f"\n\nApprover feedback from previous attempt (fix these issues):\n{approver_feedback}"
        p = run_agent("05_polish", polish_input, run_dir)
        polish_notes = p.get('polish_notes', []) if isinstance(p, dict) else []
        notes_preview = "\n".join(f"  - {n}" for n in polish_notes) if polish_notes else "  (no notes)"
        discord_log(f"✅ Polish complete — {attempt_label}\n{notes_preview}")
        # Measure word count and meta desc length; auto-correct before Approver sees it
        p = validate_and_repolish(p, attempt_label, run_dir, approver_feedback=approver_feedback)
        if isinstance(p, dict):
            words    = count_post_words(p.get("content", ""))
            meta_len = len(p.get("meta_description", ""))
            discord_log(f"📏 Measurements — words: {words}, meta: {meta_len} chars")
        discord_log(f"🔍 Approver reviewing — {attempt_label}...")
        a = run_agent("06_approver", f"Post:\n{json.dumps(p, indent=2)}", run_dir)
        return p, a

    # Attempt 1: Polish → Approve
    polished, approval = polish_and_approve(edited, "attempt 1/3", run_dir)
    if isinstance(approval, dict) and approval.get("decision") == "APPROVED":
        scores = approval.get("scores", {})
        scores_str = "  " + "  ".join(f"{k}: {v}" for k, v in scores.items())
        discord_log(f"✅ **APPROVED** on attempt 1\n{scores_str}")
        approved = True
    else:
        last_comments = approval.get("comments", "No specific feedback") if isinstance(approval, dict) else str(approval)
        scores = approval.get("scores", {}) if isinstance(approval, dict) else {}
        failed = [k for k, v in scores.items() if v == "fail"]
        passed = [k for k, v in scores.items() if v == "pass"]
        score_summary = f"**Failed:** {', '.join(failed) or 'unknown'}  |  **Passed:** {', '.join(passed) or 'none'}"
        discord_log(f"❌ **DENIED** (attempt 1)\n{score_summary}\n**Reason:** {last_comments}")

    # Attempt 2: Polish again → Approve
    if not approved:
        discord_log(f"🔄 Sending back to Polish (attempt 2/3)...")
        polished, approval = polish_and_approve(polished, "attempt 2/3", run_dir, approver_feedback=last_comments)
        if isinstance(approval, dict) and approval.get("decision") == "APPROVED":
            scores = approval.get("scores", {})
            scores_str = "  " + "  ".join(f"{k}: {v}" for k, v in scores.items())
            discord_log(f"✅ **APPROVED** on attempt 2\n{scores_str}")
            approved = True
        else:
            last_comments = approval.get("comments", "No specific feedback") if isinstance(approval, dict) else str(approval)
            scores = approval.get("scores", {}) if isinstance(approval, dict) else {}
            failed = [k for k, v in scores.items() if v == "fail"]
            passed = [k for k, v in scores.items() if v == "pass"]
            score_summary = f"**Failed:** {', '.join(failed) or 'unknown'}  |  **Passed:** {', '.join(passed) or 'none'}"
            discord_log(f"❌ **DENIED** (attempt 2)\n{score_summary}\n**Reason:** {last_comments}")

    # Attempt 3: Rerun Draft with approver feedback → Polish → Approve
    if not approved:
        discord_log(f"🔄 Rerunning Draft with approver feedback (attempt 3/3)...")
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
        discord_log(f"✅ Draft rerun complete")
        polished, approval = polish_and_approve(redraft, "attempt 3/3", run_dir, approver_feedback=last_comments)
        if isinstance(approval, dict) and approval.get("decision") == "APPROVED":
            scores = approval.get("scores", {})
            scores_str = "  " + "  ".join(f"{k}: {v}" for k, v in scores.items())
            discord_log(f"✅ **APPROVED** on attempt 3\n{scores_str}")
            approved = True
        else:
            last_comments = approval.get("comments", "No specific feedback") if isinstance(approval, dict) else str(approval)
            scores = approval.get("scores", {}) if isinstance(approval, dict) else {}
            failed = [k for k, v in scores.items() if v == "fail"]
            passed = [k for k, v in scores.items() if v == "pass"]
            score_summary = f"**Failed:** {', '.join(failed) or 'unknown'}  |  **Passed:** {', '.join(passed) or 'none'}"
            discord(f"❌ **NEEDS REVIEW** (all 3 attempts failed)\n{score_summary}\n**Reason:** {last_comments}")
            (run_dir / "NEEDS_REVIEW.md").write_text(f"# Needs Manual Review\n\nApprover feedback (all 3 attempts failed):\n{last_comments}\n")

    if not approved:
        print(f"\n⚠️  Post needs manual review. Check: {run_dir}")
        try:
            from airtable.client import log_rejected_post
            post_copy = json.dumps(polished, indent=2) if isinstance(polished, dict) else str(polished)
            scores = approval.get("scores", {}) if isinstance(approval, dict) else {}
            score_str = "\n".join(f"  {k}: {v}" for k, v in scores.items())
            log_rejected_post(
                topic=topic,
                run_id=run_dir.name,
                rejection_reason=last_comments,
                score_breakdown=score_str,
                post_copy=post_copy,
            )
            discord(f"📋 Logged to Airtable Rejected Posts — flip to **Force Publish** to override.")
        except Exception as e:
            print(f"  Warning: could not log to Airtable: {e}")
        return

    # ── Publish ──────────────────────────────────────────────────────────
    discord_log(f"📤 Scheduling to WordPress...")
    try:
        keyword = outline.get("target_keyword", "") if isinstance(outline, dict) else ""
        result = publish_to_wordpress(polished, keyword=keyword, allowed_days=allowed_days)
        post_url = result.get("link", "unknown")
        post_id  = result.get("id", "")
        pub_date = result.get("date", "")
        discord(f"🎉 **Scheduled!**\n**URL:** {post_url}\n**Title:** {polished.get('title')}\n**Publishes:** {pub_date[:10]}")
        print(f"\n✅ Scheduled: {post_url}")
        (run_dir / "published.json").write_text(json.dumps(result, indent=2))
        # ── Update posts index ────────────────────────────────────────────
        update_posts_index(
            polished.get("title", topic),
            post_url,
            polished.get("slug", ""),
            keyword,
        )
        # ── Airtable update ──────────────────────────────────────────────
        try:
            from airtable.client import mark_published, mark_cluster_published
            mark_published(topic, post_id, post_url)
            if pillar:
                mark_cluster_published(
                    polished.get("title", topic), post_id, post_url,
                    run_id=run_dir.name,
                    cluster_id=cluster_id,
                    published_title=polished.get("title", ""),
                    keyword=keyword,
                    wp_slug=polished.get("slug", ""),
                    meta_description=polished.get("meta_description", ""),
                    schema_type=detect_schema_type(polished),
                    word_count=count_words(polished.get("content", "")),
                )
        except Exception as ae:
            print(f"  Airtable update failed: {ae}")

        # ── LinkedIn post generation ─────────────────────────────────────
        try:
            discord_log(f"✍️ Generating LinkedIn post...")
            import re as _re
            plain_content = _re.sub(r'<[^>]+>', '', polished.get("content", "")).strip()
            linkedin_input = (
                f"Title: {polished.get('title', topic)}\n"
                f"Meta description: {polished.get('meta_description', '')}\n"
                f"Post excerpt:\n{plain_content[:1500]}"
            )
            linkedin_result = run_agent("07_linkedin", linkedin_input, run_dir)
            post_copy = linkedin_result.get("post", "") if isinstance(linkedin_result, dict) else str(linkedin_result)

            if post_copy:
                # Log to Airtable Social Posts
                try:
                    from airtable.client import log_social_post
                    log_social_post(polished.get("title", topic), "LinkedIn", post_copy, wp_post_url=post_url)
                except Exception:
                    pass

                # Post to Discord #linkedin for approval
                if DISCORD_LINKEDIN_WEBHOOK_URL:
                    preview = post_copy.replace("\\n", "\n")
                    msg = (
                        f"**LinkedIn Draft** — {polished.get('title', topic)}\n"
                        f"**Blog URL:** {post_url}\n\n"
                        f"```\n{preview}\n```\n"
                        f"_Copy and post manually when ready._"
                    )
                    chunks = [msg[i:i+1900] for i in range(0, len(msg), 1900)]
                    for chunk in chunks:
                        requests.post(DISCORD_LINKEDIN_WEBHOOK_URL, json={"content": chunk}, timeout=5)
                    discord_log(f"✅ LinkedIn draft posted to #linkedin")
                else:
                    discord_log(f"⚠️ LinkedIn draft generated but DISCORD_LINKEDIN_WEBHOOK_URL not set — saved to Airtable Social Posts only.")
        except Exception as le:
            discord_log(f"⚠️ LinkedIn generation failed: {le}")
            print(f"  LinkedIn generation failed: {le}")
    except Exception as e:
        discord(f"❌ **WordPress publish failed:** {str(e)}")
        print(f"\n❌ Publish failed: {e}")
        print(f"   Post saved at: {run_dir}/05_polish.json")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("topic", nargs="*", help="Topic to write about (omit when using --resume)")
    parser.add_argument("--why", default=None, help="Context: why this topic is timely and the SMB angle")
    parser.add_argument("--publish-days", default=None, help="Comma-separated weekday ints to restrict scheduling (e.g. '1,3' for Tue/Thu)")
    parser.add_argument("--pillar", default=None, help="Parent pillar name — enables voice consistency context from sibling posts")
    parser.add_argument("--cluster-id", default=None, help="Airtable cluster record ID for reliable publish tracking")
    parser.add_argument("--resume", default=None, metavar="RUN_DIR", help="Resume an incomplete or NEEDS_REVIEW run from its last completed step")
    args = parser.parse_args()

    if args.resume:
        resume_pipeline(args.resume)
    else:
        if not args.topic:
            parser.error("topic is required unless --resume is used")
        topic = " ".join(args.topic)
        allowed_days = [int(d) for d in args.publish_days.split(",")] if args.publish_days else None
        run_pipeline(topic, why=args.why, allowed_days=allowed_days, pillar=args.pillar, cluster_id=args.cluster_id)
