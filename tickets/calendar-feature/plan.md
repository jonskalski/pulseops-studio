# Plan: Calendar Feature for PulseOps Dashboard

## Goal
Add a `/calendar` route to the Flask dashboard at `/root/pulseops-studio/dashboard/app.py` that shows scheduled WordPress posts in a 1-2 week view and allows date reassignment.

## Files to create/modify

### 1. `/root/pulseops-studio/dashboard/app.py` — add these routes:

```python
@app.route("/calendar")
@login_required
def calendar():
    posts = _get_scheduled_posts()
    metrics = _get_metrics()
    return render_template("calendar.html", posts=posts, metrics=metrics, active="calendar")

@app.route("/api/post/<int:post_id>/reschedule", methods=["POST"])
@login_required
def api_reschedule(post_id):
    data = request.get_json()
    new_date = data.get("date", "").strip()  # expects "YYYY-MM-DD"
    if not new_date:
        return jsonify({"ok": False, "error": "date required"}), 400
    try:
        _reschedule_wp_post(post_id, new_date)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
```

Also add these helper functions to `app.py`:

```python
def _get_scheduled_posts():
    """Fetch scheduled (future) posts from WordPress REST API."""
    import requests as req
    r = req.get(
        os.environ["WP_URL"] + "/wp-json/wp/v2/posts",
        params={
            "status": "future",
            "per_page": 30,
            "_fields": "id,title,slug,date,link,categories",
            "orderby": "date",
            "order": "asc",
        },
        auth=(os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"]),
        timeout=10,
    )
    r.raise_for_status()
    posts = []
    for p in r.json():
        posts.append({
            "id": p["id"],
            "title": p["title"]["rendered"],
            "slug": p["slug"],
            "date": p["date"][:10],   # YYYY-MM-DD
            "time": p["date"][11:16], # HH:MM
            "link": p.get("link", ""),
        })
    return posts

def _reschedule_wp_post(post_id: int, new_date: str):
    """Update a WordPress post's scheduled date. new_date is YYYY-MM-DD."""
    import requests as req
    # Keep 9am EST publish time
    new_datetime = new_date + "T09:00:00"
    r = req.post(
        os.environ["WP_URL"] + f"/wp-json/wp/v2/posts/{post_id}",
        json={"date": new_datetime, "status": "future"},
        auth=(os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"]),
        timeout=10,
    )
    r.raise_for_status()
```

### 2. `/root/pulseops-studio/dashboard/templates/calendar.html` — new template

Create this file. It must extend `base.html`.

The calendar shows:
- A header with "Calendar" title and a subtitle "What's scheduled for the next two weeks."
- A metrics row (reuse the same 4-metric pattern from other pages): Queued, Scheduled (len of posts), Running, Needs Review
- A list of scheduled posts as cards, grouped by date (one group per day)
- Each group has a date header (e.g. "Monday, Jun 2") and the posts for that day listed beneath
- Each post card shows: title, slug as a muted pill, time (e.g. "9:00 AM"), and a "Reschedule" button
- Clicking "Reschedule" shows a small inline date picker (`<input type="date">`) and a "Save" button
- "Save" calls `POST /api/post/<id>/reschedule` with `{"date": "YYYY-MM-DD"}`
- On success, update the displayed date and collapse the picker; show a toast

Use the existing CSS classes from base.html: `panel`, `panel-head`, `inbox-item`, `item-title`, `item-copy`, `pills`, `pill`, `btn`, `mini`, `primary`, `field`, `toast`.

Add a new CSS class `.cal-date-header` styled as:
```css
padding: 10px 20px 4px;
color: var(--accent);
font-size: 11px;
font-weight: 800;
letter-spacing: 0.13em;
text-transform: uppercase;
border-bottom: 1px solid var(--border-soft);
```

Group posts by date in the Jinja2 template using `groupby`:
```jinja2
{% for date, day_posts in posts | groupby('date') %}
  ...
{% endfor %}
```

Format date as human-readable in the template using a filter — add this to `app.py`:
```python
@app.template_filter('humandate')
def humandate_filter(d):
    from datetime import datetime
    return datetime.strptime(d, "%Y-%m-%d").strftime("%A, %b %-d")
```

### 3. Update nav in `/root/pulseops-studio/dashboard/templates/base.html`

Add "Calendar" to the sidebar nav and mobile tabs. Insert after "Write This":

In `.nav`:
```html
<a href="/calendar" class="{{ 'active' if active == 'calendar' }}">Calendar</a>
```

In `.mobile-tabs`, replace the 5 items with these 5 (replacing "Runs" with "Calendar" since it fits better on mobile):
```html
<a href="/inbox" class="{{ 'active' if active == 'inbox' }}">Inbox</a>
<a href="/write-this" class="{{ 'active' if active == 'write-this' }}">Write</a>
<a href="/calendar" class="{{ 'active' if active == 'calendar' }}">Calendar</a>
<a href="/queue" class="{{ 'active' if active == 'queue' }}">Queue</a>
<a href="/health" class="{{ 'active' if active == 'health' }}">Health</a>
```

## Important notes
- Do NOT modify pipeline.py, queue_db.py, queue_worker.py, or any agent files
- Do NOT change existing routes in app.py — only add new ones
- All existing templates must continue to work unchanged
- The reschedule API must validate the date format before calling WordPress
- Use `html.unescape()` or Jinja2's `| striptags` to clean WordPress HTML entities in titles
- The `humandate` filter must handle ValueError gracefully (return the raw date string as fallback)
- No external JS libraries — vanilla JS only
