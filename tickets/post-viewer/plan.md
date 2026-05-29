# Plan: Post Viewer for PulseOps Dashboard

## Goal
Add a `/posts` route to the Flask dashboard that shows published WordPress posts with their generated social copy, and a Veto/Regenerate button that queues a replacement pipeline run.

## Data model
- Published posts: WordPress REST API (`status=publish`, most recent 20)
- Social copy: run folders at `/root/pulseops-studio/runs/*/published.json` — each contains `id` (WP post ID); sibling files `07_linkedin.json`, `09_bluesky.json`, `10_personal_linkedin.json`, `08_instagram.json` have a `post` key with the copy
- Match posts to run folders by WP post ID in `published.json`

## Files to create/modify

### 1. `/root/pulseops-studio/dashboard/app.py` — add these routes and helpers

**New route:**
```python
@app.route("/posts")
@login_required
def posts():
    posts = _get_published_posts_with_socials()
    metrics = _get_metrics()
    return render_template("posts.html", posts=posts, metrics=metrics, active="posts")

@app.route("/api/post/<int:post_id>/regenerate", methods=["POST"])
@login_required
def api_regenerate(post_id):
    data = request.get_json(silent=True) or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify({"ok": False, "error": "topic required"}), 400
    cmd = ["python3", "/root/pulseops-studio/pipeline.py", topic]
    job_id = queue_db.enqueue_job(
        command=cmd,
        job_type="pipeline_topic",
        label=f"Regenerate: {topic}",
        meta={"source": "post_viewer", "post_id": post_id},
    )
    return jsonify({"ok": True, "job_id": job_id})
```

**New helper — add after `_get_scheduled_posts()`:**
```python
def _get_published_posts_with_socials():
    """Fetch published WP posts and match each to its run folder social copy."""
    import requests as req
    import html as html_module
    from pathlib import Path

    # Build run folder index: wp_post_id (int) -> run_dir Path
    runs_dir = Path("/root/pulseops-studio/runs")
    run_index = {}
    if runs_dir.exists():
        for run_dir in sorted(runs_dir.iterdir(), reverse=True):
            pub = run_dir / "published.json"
            if pub.exists():
                try:
                    d = json.loads(pub.read_text())
                    wp_id = d.get("id")
                    if wp_id and int(wp_id) not in run_index:
                        run_index[int(wp_id)] = run_dir
                except Exception:
                    pass

    # Fetch published posts from WP
    r = req.get(
        os.environ["WP_URL"] + "/wp-json/wp/v2/posts",
        params={
            "status": "publish",
            "per_page": 20,
            "_fields": "id,title,slug,date,link",
            "orderby": "date",
            "order": "desc",
        },
        auth=(os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"]),
        timeout=10,
    )
    r.raise_for_status()

    posts = []
    for p in r.json():
        post_id = p["id"]
        run_dir = run_index.get(post_id)

        socials = {}
        if run_dir:
            for key, filename in [
                ("linkedin_brand", "07_linkedin.json"),
                ("instagram", "08_instagram.json"),
                ("bluesky", "09_bluesky.json"),
                ("linkedin_personal", "10_personal_linkedin.json"),
            ]:
                f = run_dir / filename
                if f.exists():
                    try:
                        d = json.loads(f.read_text())
                        raw = d.get("post", "")
                        # Strip markdown code fences if present
                        raw = re.sub(r'^```[a-z]*\n?', '', raw, flags=re.MULTILINE)
                        raw = re.sub(r'\n?```$', '', raw, flags=re.MULTILINE)
                        # Strip inner JSON wrapper if present (some agents wrap in {"post": ...})
                        try:
                            inner = json.loads(raw.strip())
                            if isinstance(inner, dict) and "post" in inner:
                                raw = inner["post"]
                        except Exception:
                            pass
                        socials[key] = raw.strip()
                    except Exception:
                        pass

        posts.append({
            "id": post_id,
            "title": html_module.unescape(p["title"]["rendered"]),
            "slug": p["slug"],
            "date": p["date"][:10],
            "link": p.get("link", ""),
            "socials": socials,
            "has_socials": bool(socials),
        })

    return posts
```

**Also add the `humandate` filter if not already present** (it was added in the calendar feature, so skip if it already exists).

### 2. `/root/pulseops-studio/dashboard/templates/posts.html` — new template

Create this file. It must extend `base.html`.

**Layout:**
- Header: kicker "Post library", h2 "Posts", subtitle "Published posts and their social copy. Regenerate queues a new pipeline run."
- Metrics row: Published (len posts), Queued (metrics.queued), Running, Needs Review
- One panel per post (use `.panel` class), each containing:
  - Panel head: post title (linked to `post.link` in a new tab), date pill, "Regenerate" button
  - If `post.has_socials`: expandable sections for each available social variant
  - If not `post.has_socials`: a muted note "No social copy found for this post."

**Social variant sections** (only render if the key exists in `post.socials`):
```
LinkedIn (Brand)     — post.socials.linkedin_brand
LinkedIn (Personal)  — post.socials.linkedin_personal
Instagram            — post.socials.instagram
Bluesky              — post.socials.bluesky
```

Each section has:
- A label pill (e.g. `<span class="pill">LinkedIn Brand</span>`)
- The copy in a `<pre>` styled like `.log` but lighter (readable, not monospace terminal)
- A "Copy" button that copies the text to clipboard using `navigator.clipboard.writeText()`

**Regenerate button behavior:**
- Clicking shows a small confirm with the post title
- Calls `POST /api/post/<id>/regenerate` with `{"topic": post.title}`
- On success: toast "Regenerate job queued. Check the Runs page."

**CSS to add (inline in the template `<style>` block):**
```css
.post-copy {
  margin-top: 10px;
  padding: 14px;
  background: var(--surface-2);
  border: 1px solid var(--border-soft);
  border-radius: 2px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--muted);
  white-space: pre-wrap;
  word-break: break-word;
}
.social-block {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-soft);
}
.social-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
```

### 3. Update nav in `/root/pulseops-studio/dashboard/templates/base.html`

Add "Posts" to the sidebar nav after "Calendar":
```html
<a href="/posts" class="{{ 'active' if active == 'posts' }}">Posts</a>
```

Update mobile tabs to include Posts (replace one of the existing 5 if needed — keep Inbox, Write, Calendar, Queue, and swap Health for Posts on mobile since Health is accessible via sidebar):
```html
<a href="/inbox" class="{{ 'active' if active == 'inbox' }}">Inbox</a>
<a href="/write-this" class="{{ 'active' if active == 'write-this' }}">Write</a>
<a href="/calendar" class="{{ 'active' if active == 'calendar' }}">Cal</a>
<a href="/posts" class="{{ 'active' if active == 'posts' }}">Posts</a>
<a href="/queue" class="{{ 'active' if active == 'queue' }}">Queue</a>
```

## Important notes
- Do NOT modify pipeline.py, queue_db.py, queue_worker.py, or any agent files
- Do NOT change existing routes — only add new ones
- The run folder scan should be silent on errors (try/except around all file reads)
- The `json` and `re` modules are already imported in `app.py`
- The `humandate` filter is already registered — do not re-register it
- Social copy from Personal LinkedIn often has a JSON wrapper `{"post": "..."}` or markdown fences — strip both
- No external JS libraries — vanilla JS only
- Verify with `python3 -m py_compile dashboard/app.py` before finishing
