# POPS-CP-002: SQLite Job Queue + Worker
**Assigned to:** Codex  
**Planned by:** Claude  
**Status:** Ready for implementation

---

## Objective

Build the queue foundation for the PulseOps control panel. This replaces direct calls to `pipeline.py` with a job queue pattern: everything creates a job, one worker runs jobs one at a time.

This is Phase 1 of the control panel plan at `/root/pulseops-studio/CONTROL_PANEL_WORKER_PLAN.md`. Read that file for full context. Only implement what is scoped here — nothing else.

---

## What to build

### File 1: `queue_db.py`

Path: `/root/pulseops-studio/queue_db.py`

A SQLite helper module. Creates and manages `pulseops_control.db` in the same directory.

#### Database setup

On import (or when `init_db()` is called), create this table if it doesn't exist:

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    type              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'queued',
    priority          INTEGER DEFAULT 100,

    topic             TEXT,
    why               TEXT,
    pillar            TEXT,
    cluster_id        TEXT,
    run_dir           TEXT,
    publish_days      TEXT,

    payload_json      TEXT,
    command_json      TEXT,

    created_at        TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT,

    attempts          INTEGER DEFAULT 0,
    max_attempts      INTEGER DEFAULT 1,

    log_path          TEXT,
    error_message     TEXT,
    result_url        TEXT,
    result_post_id    TEXT,

    created_by        TEXT,
    source            TEXT
)
```

#### Functions to implement

**`init_db()`**
Creates the database and table if they don't exist. Called at module import.

**`enqueue_job(type, topic=None, why=None, pillar=None, cluster_id=None, run_dir=None, publish_days=None, source='manual', priority=100)`**
Inserts a new job with status `queued` and `created_at` set to UTC ISO timestamp.
Returns the new job's integer `id`.

**`get_next_job()`**
Returns the next job with status `queued`, ordered by `priority ASC, created_at ASC`.
Returns a dict (all columns) or `None` if no jobs are queued.

**`get_job(job_id)`**
Returns a single job dict by id, or `None`.

**`mark_running(job_id)`**
Sets `status='running'`, increments `attempts`, sets `started_at` to UTC now.

**`mark_done(job_id, status, error=None, result_url=None, result_post_id=None)`**
Sets `status` (use `'succeeded'` or `'failed'`), sets `finished_at` to UTC now.
Optionally sets `error_message`, `result_url`, `result_post_id`.

**`list_jobs(status=None, limit=20)`**
Returns list of job dicts. Filters by status if provided. Orders by `created_at DESC`.

**`set_job_log_path(job_id, log_path)`**
Sets `log_path` on a job.

**`set_job_command(job_id, command_json)`**
Sets `command_json` (store as JSON string) on a job.

#### CLI usage (for testing)

When run directly (`python3 queue_db.py`), support these subcommands:

```
python3 queue_db.py enqueue "<topic>" [--why "<why>"] [--publish-days "1,3"]
python3 queue_db.py list [--status queued|running|succeeded|failed]
python3 queue_db.py show <job_id>
```

`enqueue` should print: `Enqueued job #<id>: <topic>`
`list` should print a simple table: id, type, status, topic, created_at
`show` should pretty-print all fields for that job

---

### File 2: `queue_worker.py`

Path: `/root/pulseops-studio/queue_worker.py`

The worker process. Runs the job queue one job at a time.

#### Lock file

Path: `/tmp/pulseops-worker.lock`

Contents (plain text, one value per line):
```
pid=<pid>
started_at=<utc iso timestamp>
job_id=<job_id or 'none'>
```

On startup:
- If lock exists and PID is alive (`os.kill(pid, 0)` does not raise): print warning and exit. Another worker is running.
- If lock exists and PID is dead: remove lock and continue.
- Write new lock file.

On exit (normal or exception): remove lock file.

#### Stale job detection

On startup, after lock check: query for any job with `status='running'` and `started_at` older than 6 hours. Mark those jobs `status='stale'` and log a warning. Do not auto-resume them.

#### Command mapping

Build the command array (never a shell string) for each job type:

**`pipeline_topic`**
```python
cmd = ["python3", "/root/pulseops-studio/pipeline.py", topic]
if job["why"]:
    cmd += ["--why", job["why"]]
if job["publish_days"]:
    cmd += ["--publish-days", job["publish_days"]]
```

**`pipeline_cluster`**
```python
cmd = ["python3", "/root/pulseops-studio/pipeline.py", topic]
if job["pillar"]:
    cmd += ["--pillar", job["pillar"]]
if job["cluster_id"]:
    cmd += ["--cluster-id", job["cluster_id"]]
if job["publish_days"]:
    cmd += ["--publish-days", job["publish_days"]]
```

**`resume_run`**
```python
cmd = ["python3", "/root/pulseops-studio/pipeline.py", "--resume", job["run_dir"]]
```

**`force_publish`**
```python
# payload_json contains {"run_id": "...", "airtable_record_id": "..."}
payload = json.loads(job["payload_json"])
cmd = ["python3", "/root/pulseops-studio/force_publish.py",
       payload["run_id"], payload["airtable_record_id"]]
```

#### Timeouts (seconds)

```python
TIMEOUTS = {
    "pipeline_topic":   4 * 3600,
    "pipeline_cluster": 4 * 3600,
    "resume_run":       2 * 3600,
    "force_publish":    30 * 60,
}
```

#### Worker loop

```
1. Check/write lock file
2. Mark stale running jobs
3. Loop:
   a. Get next queued job
   b. If none: sleep 15 seconds, continue
   c. Mark job running
   d. Build command array
   e. Store command in command_json on the job
   f. Open log file at logs/jobs/<job_id>_<type>.log
   g. Store log path on the job
   h. Run subprocess, stream stdout+stderr into log file AND print to terminal
   i. If process exits 0: check for NEEDS_REVIEW / published.json, mark succeeded or blocked
   j. If process exits nonzero: mark failed, store last 500 chars of output as error_message
   k. If timeout: kill process, mark failed with "Timed out after Xh"
   l. Print summary line: [job_id] type | topic | status | duration
```

#### Result detection (step i above)

After a `pipeline_topic` or `pipeline_cluster` job exits 0:
- Find the most recently modified subdirectory in `/root/pulseops-studio/runs/`
- If `NEEDS_REVIEW.md` exists in that dir: mark job `status='blocked'`
- Else if `published.json` exists: parse it, set `result_url` and `result_post_id` on the job, mark `succeeded`
- Else: mark `failed` with error "pipeline exited 0 but no published.json or NEEDS_REVIEW.md found"

For `resume_run` and `force_publish`: just use exit code. Exit 0 = succeeded, nonzero = failed.

#### `--once` flag

Support `python3 queue_worker.py --once` which processes exactly one job then exits (used for testing).

#### Log directory

Ensure `logs/jobs/` directory exists on startup. Create it if needed.

---

## Constraints

- Do not modify `pipeline.py`, `force_publish.py`, or any existing file
- Do not add dependencies beyond Python stdlib + `queue_db` module
- SQLite is stdlib (`import sqlite3`) — no installs needed
- Do not add Discord/Airtable notifications yet — that is a later ticket
- Do not build a Flask dashboard — that is a later ticket
- The worker should work as a foreground process for now. No systemd service yet.
- Use `subprocess.Popen` with `stdout=PIPE, stderr=STDOUT` for streaming. Do not use `subprocess.run`.

---

## Definition of done

All of these work without errors:

```bash
# Create a test job
python3 queue_db.py enqueue "test topic" --why "testing the queue"

# Verify it shows up
python3 queue_db.py list

# Show full job details
python3 queue_db.py show 1
```

The worker can be started:
```bash
python3 queue_worker.py --once
```
(It will find the test job, attempt to run pipeline.py, stream output, and mark the job succeeded or failed depending on pipeline result.)

Both files exist and have no syntax errors (`python3 -c "import queue_db; import queue_worker"`).

---

## Questions

If you have a question before or during implementation, append it here and stop. Do not guess. Claude will answer and confirm you should continue.

Format:
```
Q1: <your question>
```
