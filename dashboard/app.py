import os
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


# --- Data helpers ---

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


if __name__ == "__main__":
    queue_db.init_db()
    app.run(host="0.0.0.0", port=5050, debug=False)
