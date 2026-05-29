import os
import json
import re
import sys
from functools import wraps
from datetime import datetime, timezone

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import queue_db

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=True)

app = Flask(__name__)
app.secret_key = os.environ["DASHBOARD_SECRET_KEY"]

DASHBOARD_USER = os.environ["DASHBOARD_USER"]
DASHBOARD_PASSWORD = os.environ["DASHBOARD_PASSWORD"]


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (request.form.get("username") == DASHBOARD_USER and
                request.form.get("password") == DASHBOARD_PASSWORD):
            session["logged_in"] = True
            return redirect(url_for("inbox"))
        flash("Invalid credentials.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return redirect(url_for("inbox"))


@app.route("/inbox")
@login_required
def inbox():
    topics = _get_inbox_topics()
    metrics = _get_metrics()
    return render_template("inbox.html", topics=topics, metrics=metrics, active="inbox")


@app.route("/queue")
@login_required
def queue():
    jobs = queue_db.list_jobs(limit=30)
    metrics = _get_metrics()
    return render_template("queue.html", jobs=jobs, metrics=metrics, active="queue")


@app.route("/runs")
@login_required
def runs():
    jobs = queue_db.list_jobs(limit=50)
    metrics = _get_metrics()
    return render_template("runs.html", jobs=jobs, metrics=metrics, active="runs")


@app.route("/write-this")
@login_required
def write_this():
    metrics = _get_metrics()
    return render_template("write_this.html", metrics=metrics, active="write-this")


@app.route("/calendar")
@login_required
def calendar():
    posts = _get_scheduled_posts()
    metrics = _get_metrics()
    return render_template("calendar.html", posts=posts, metrics=metrics, active="calendar")


@app.route("/posts")
@login_required
def posts():
    posts = _get_published_posts_with_socials()
    metrics = _get_metrics()
    return render_template("posts.html", posts=posts, metrics=metrics, active="posts")


@app.route("/rejected")
@login_required
def rejected():
    posts = _get_rejected_posts()
    metrics = _get_metrics()
    return render_template("rejected.html", posts=posts, metrics=metrics, active="rejected")


@app.route("/health")
@login_required
def health():
    status = _get_health_status()
    metrics = _get_metrics()
    return render_template("health.html", status=status, metrics=metrics, active="health")


# --- API actions ---

@app.route("/api/topic/approve", methods=["POST"])
@login_required
def api_topic_approve():
    data = request.get_json()
    topic = data.get("topic", "").strip()
    why = data.get("why", "").strip()
    if not topic:
        return jsonify({"ok": False, "error": "No topic provided"}), 400
    cmd = ["python3", "/root/pulseops-studio/pipeline.py", topic]
    if why:
        cmd += ["--why", why]
    job_id = queue_db.enqueue_job(
        command=cmd,
        job_type="pipeline_topic",
        label=topic,
        meta={"source": "inbox", "why": why},
    )
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/topic/deny", methods=["POST"])
@login_required
def api_topic_deny():
    data = request.get_json()
    record_id = data.get("record_id", "").strip()
    reason = data.get("reason", "").strip()
    if not record_id or not reason:
        return jsonify({"ok": False, "error": "record_id and reason required"}), 400
    try:
        _deny_airtable_topic(record_id, reason)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/topic/wait", methods=["POST"])
@login_required
def api_topic_wait():
    data = request.get_json()
    record_id = data.get("record_id", "").strip()
    if not record_id:
        return jsonify({"ok": False, "error": "record_id required"}), 400
    try:
        _wait_airtable_topic(record_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/write-this", methods=["POST"])
@login_required
def api_write_this():
    data = request.get_json()
    topic = data.get("topic", "").strip()
    why = data.get("why", "").strip()
    if not topic:
        return jsonify({"ok": False, "error": "No topic provided"}), 400
    cmd = ["python3", "/root/pulseops-studio/pipeline.py", topic]
    if why:
        cmd += ["--why", why]
    job_id = queue_db.enqueue_job(
        command=cmd,
        job_type="pipeline_topic",
        label=topic,
        meta={"source": "write_this", "why": why},
    )
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/job/<int:job_id>/events")
@login_required
def api_job_events(job_id):
    after_id = request.args.get("after", 0, type=int)
    events = queue_db.get_job_events(job_id, after_id=after_id)
    job = queue_db.get_job(job_id)
    return jsonify({
        "events": events,
        "job_status": job["status"] if job else "unknown",
    })


@app.route("/api/job/<int:job_id>/cancel", methods=["POST"])
@login_required
def api_job_cancel(job_id):
    job = queue_db.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job not found"}), 404
    if job["status"] != "queued":
        return jsonify({"ok": False, "error": "Only queued jobs can be cancelled"}), 400
    queue_db.mark_done(job_id, "cancelled")
    return jsonify({"ok": True})


@app.route("/api/run/<int:job_id>/resume", methods=["POST"])
@login_required
def api_run_resume(job_id):
    job = queue_db.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job not found"}), 404
    label = job.get("label", "unknown")
    cmd = ["python3", "/root/pulseops-studio/pipeline.py", "--resume", str(job_id)]
    new_id = queue_db.enqueue_job(
        command=cmd,
        job_type="resume_run",
        label=f"Resume: {label}",
        meta={"original_job_id": job_id},
    )
    return jsonify({"ok": True, "job_id": new_id})


@app.route("/api/rejected/<record_id>/force-publish", methods=["POST"])
@login_required
def api_force_publish(record_id):
    cmd = ["python3", "/root/pulseops-studio/force_publish.py", "--record-id", record_id]
    job_id = queue_db.enqueue_job(
        command=cmd,
        job_type="force_publish",
        label=f"Force publish: {record_id}",
        meta={"record_id": record_id},
    )
    return jsonify({"ok": True, "job_id": job_id})


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


@app.route("/api/run-image/<path:rel_path>")
@login_required
def api_run_image(rel_path):
    from flask import send_file, abort
    import pathlib
    runs_root = pathlib.Path("/root/pulseops-studio/runs").resolve()
    target = (runs_root / rel_path).resolve()
    if not str(target).startswith(str(runs_root)):
        abort(403)
    if target.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        abort(403)
    if not target.exists():
        abort(404)
    return send_file(target, mimetype="image/png")


@app.route("/api/post/<int:post_id>/reschedule", methods=["POST"])
@login_required
def api_reschedule(post_id):
    data = request.get_json(silent=True) or {}
    date_value = data.get("date") or ""
    if not isinstance(date_value, str):
        return jsonify({"ok": False, "error": "valid date required"}), 400
    new_date = date_value.strip()
    if not new_date:
        return jsonify({"ok": False, "error": "date required"}), 400
    try:
        parsed_date = datetime.strptime(new_date, "%Y-%m-%d")
        if parsed_date.strftime("%Y-%m-%d") != new_date:
            raise ValueError()
    except ValueError:
        return jsonify({"ok": False, "error": "valid date required"}), 400
    try:
        _reschedule_wp_post(post_id, new_date)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# --- Data helpers ---

@app.template_filter("humandate")
def humandate_filter(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%A, %b %-d")
    except (TypeError, ValueError):
        return d


def _get_inbox_topics():
    try:
        from pyairtable import Api
        api = Api(os.environ["AIRTABLE_API_KEY"])
        table = api.table(os.environ["AIRTABLE_BASE_ID"], os.environ["AIRTABLE_CONTENT_IDEAS_TABLE_ID"])
        records = table.all(formula="{Status}='Suggested'", max_records=20, sort=["-Suggested Date"])
        topics = []
        for r in records:
            f = r["fields"]
            topics.append({
                "record_id": r["id"],
                "topic": f.get("Topic", f.get("Name", "")),
                "why": f.get("Why", ""),
                "suggested_date": f.get("Suggested Date", ""),
            })
        return topics
    except Exception:
        return []


def _get_rejected_posts():
    try:
        from pyairtable import Api
        api = Api(os.environ["AIRTABLE_API_KEY"])
        table = api.table(os.environ["AIRTABLE_BASE_ID"], os.environ["AIRTABLE_REJECTED_POSTS_TABLE_ID"])
        records = table.all(formula="{Status}='Needs Review'", max_records=10)
        posts = []
        for r in records:
            f = r["fields"]
            posts.append({
                "record_id": r["id"],
                "topic": f.get("Topic", ""),
                "reason": f.get("Rejection Reason", ""),
                "date": f.get("Date", ""),
                "run_id": f.get("Run ID", ""),
            })
        return posts
    except Exception:
        return []


def _get_scheduled_posts():
    """Fetch scheduled (future) posts from WordPress REST API."""
    import html
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
            "title": html.unescape(p["title"]["rendered"]),
            "slug": p["slug"],
            "date": p["date"][:10],
            "time": p["date"][11:16],
            "link": p.get("link", ""),
        })
    return posts


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
            "status": "future",
            "per_page": 20,
            "_fields": "id,title,slug,date,link",
            "orderby": "date",
            "order": "asc",
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
                        raw = d.get("post", "") or d.get("caption", "")
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

        instagram_image_url = None
        if run_dir and (run_dir / "instagram.png").exists():
            rel = (run_dir / "instagram.png").relative_to(Path("/root/pulseops-studio/runs"))
            instagram_image_url = f"/api/run-image/{rel}"

        posts.append({
            "id": post_id,
            "title": html_module.unescape(p["title"]["rendered"]),
            "slug": p["slug"],
            "date": p["date"][:10],
            "link": p.get("link", ""),
            "socials": socials,
            "has_socials": bool(socials),
            "instagram_image_url": instagram_image_url,
        })

    return posts


def _get_metrics():
    try:
        queued = len(queue_db.list_jobs(status="queued", limit=100))
        running = len(queue_db.list_jobs(status="running", limit=10))
        failed = len(queue_db.list_jobs(status="failed", limit=100))

        from pyairtable import Api
        api = Api(os.environ["AIRTABLE_API_KEY"])
        table = api.table(os.environ["AIRTABLE_BASE_ID"], os.environ["AIRTABLE_REJECTED_POSTS_TABLE_ID"])
        needs_review = len(table.all(formula="{Status}='Needs Review'", max_records=50))

        return {
            "queued": queued,
            "running": running,
            "failed": failed,
            "needs_review": needs_review,
        }
    except Exception:
        return {"queued": 0, "running": 0, "failed": 0, "needs_review": 0}


def _get_health_status():
    import subprocess
    worker_running = False
    try:
        result = subprocess.run(["pgrep", "-f", "queue_worker.py"], capture_output=True)
        worker_running = result.returncode == 0
    except Exception:
        pass

    lock_info = "none"
    lock_path = "/tmp/pulseops-worker.lock"
    if os.path.exists(lock_path):
        try:
            with open(lock_path) as f:
                lock_info = f.read().strip() or "locked"
        except Exception:
            lock_info = "locked"

    airtable_ok = False
    try:
        from pyairtable import Api
        api = Api(os.environ["AIRTABLE_API_KEY"])
        table = api.table(os.environ["AIRTABLE_BASE_ID"], os.environ["AIRTABLE_CONTENT_IDEAS_TABLE_ID"])
        table.all(max_records=1)
        airtable_ok = True
    except Exception:
        pass

    wp_ok = False
    try:
        import requests as req
        r = req.get(f"{os.environ['WP_URL']}/wp-json/wp/v2/posts?per_page=1", timeout=5)
        wp_ok = r.status_code == 200
    except Exception:
        pass

    stale = len(queue_db.list_jobs(status="running", limit=20))

    return {
        "worker": "online" if worker_running else "offline",
        "lock": lock_info,
        "airtable": "ok" if airtable_ok else "error",
        "wordpress": "ok" if wp_ok else "error",
        "stale_jobs": stale,
    }


def _deny_airtable_topic(record_id, reason):
    from pyairtable import Api
    api = Api(os.environ["AIRTABLE_API_KEY"])
    table = api.table(os.environ["AIRTABLE_BASE_ID"], os.environ["AIRTABLE_CONTENT_IDEAS_TABLE_ID"])
    table.update(record_id, {"Status": "Rejected", "Rejection Reason": reason})


def _wait_airtable_topic(record_id):
    from pyairtable import Api
    api = Api(os.environ["AIRTABLE_API_KEY"])
    table = api.table(os.environ["AIRTABLE_BASE_ID"], os.environ["AIRTABLE_CONTENT_IDEAS_TABLE_ID"])
    table.update(record_id, {"Status": "On Hold"})


def _reschedule_wp_post(post_id: int, new_date: str):
    """Update a WordPress post's scheduled date. new_date is YYYY-MM-DD."""
    import requests as req
    new_datetime = new_date + "T09:00:00"
    r = req.post(
        os.environ["WP_URL"] + f"/wp-json/wp/v2/posts/{post_id}",
        json={"date": new_datetime, "status": "future"},
        auth=(os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"]),
        timeout=10,
    )
    r.raise_for_status()


if __name__ == "__main__":
    queue_db.init_db()
    app.run(host="0.0.0.0", port=5050, debug=False)
