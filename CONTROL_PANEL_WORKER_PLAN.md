# PulseOps Control Panel + Worker Plan

**Created:** 2026-05-07  
**Status:** Planning  
**Purpose:** Replace Discord as the control surface for PulseOps Studio with a private, phone-friendly dashboard and a reliable one-job-at-a-time worker.

---

## Why This Exists

Discord was a good starting point because it made approvals fast from a phone. It is now carrying too much responsibility.

Current problems:

- Discord reactions are brittle.
- Webhooks can point to the wrong channel.
- Bot duplication can silently start multiple workflows.
- Pipeline jobs can be started from several places with no central queue.
- Background subprocesses can fail without a clean status record.
- Airtable timeouts can break polling flows.
- There is no simple phone dashboard showing what is waiting, running, failed, or done.

The goal is not to rewrite the content pipeline. The goal is to stabilize the control layer around it.

Keep:

- `pipeline.py`
- agent prompts in `agents/`
- Airtable as the content/state database for topics, pillars, clusters, rejected posts, and social posts
- WordPress as the publishing target
- existing run folders under `runs/`

Replace:

- Discord as the main approval/control interface
- direct background calls to `pipeline.py`
- cron jobs that start long-running workflows directly

---

## Core Rule

Only the worker should run `pipeline.py`.

Everything else creates a job.

```text
dashboard button     -> creates job
cluster_writer cron  -> creates job
topic approval       -> creates job
manual topic input   -> creates job
rewrite request      -> creates job
force publish        -> creates job

queue_worker.py      -> runs the actual command
```

This is the main architectural change.

The worker should be boring. It should not make content decisions. It should not interpret strategy. It should only:

1. Pick the next queued job.
2. Mark it running.
3. Run the correct command.
4. Capture logs.
5. Mark the result.
6. Notify Jon.

---

## Proposed Folder Structure

```text
/root/pulseops-studio/
├── control_app.py                  # private dashboard
├── queue_worker.py                 # one-job-at-a-time worker
├── queue_db.py                     # small SQLite helper module
├── pulseops_control.db             # local SQLite database
├── templates/                      # dashboard HTML templates
│   ├── layout.html
│   ├── inbox.html
│   ├── queue.html
│   ├── runs.html
│   ├── rejected.html
│   ├── social.html
│   └── health.html
├── static/
│   └── control.css
├── logs/
│   └── jobs/
│       └── <job_id>.log
└── CONTROL_PANEL_WORKER_PLAN.md
```

Flask is enough. Do not start with React. This needs to be reliable and easy to debug from the VPS.

---

## Data Store Choice

Use SQLite for execution state.

Airtable remains the content database. SQLite becomes the local job database.

Why SQLite:

- It is local and fast.
- It handles safe updates better than a JSON file.
- It survives restarts.
- It is simple enough for this VPS.
- It avoids making Airtable the only source of truth for whether something is running.

Do not use a JSONL queue as the final version. JSONL is fine for a quick prototype, but SQLite is better for this system because jobs need status updates, attempts, logs, failure reasons, and dashboard filtering.

---

## Job Statuses

Use a small, strict set of statuses:

```text
queued
running
succeeded
failed
blocked
cancelled
stale
```

Meaning:

- `queued`: waiting to run
- `running`: currently being processed by the worker
- `succeeded`: command finished successfully and produced expected result
- `failed`: command failed, crashed, timed out, or exited with error
- `blocked`: job cannot continue without human input
- `cancelled`: manually cancelled before running
- `stale`: was running, but the worker or VPS died and the job is too old to trust

---

## First Job Types

Build only these first:

```text
pipeline_topic
pipeline_cluster
resume_run
force_publish
```

Add these later:

```text
rewrite_run
pillar_plan
topic_pick
social_generation
buffer_topup
```

Start small. The first goal is to stop direct pipeline execution and make runs visible.

---

## Job Schema

SQLite table: `jobs`

Recommended fields:

```text
id                  integer primary key
type                text not null
status              text not null
priority            integer default 100

topic               text
why                 text
pillar              text
cluster_id          text
run_dir             text
publish_days        text

payload_json        text
command_json        text

created_at          text not null
started_at          text
finished_at         text

attempts            integer default 0
max_attempts        integer default 1

log_path            text
error_message       text
result_url          text
result_post_id      text

created_by          text
source              text
```

Notes:

- `payload_json` stores extra data for future job types.
- `command_json` stores the exact command the worker generated.
- `source` can be `dashboard`, `cron`, `cluster_writer`, `manual`, or `airtable`.
- `priority` allows urgent jobs later, but do not overuse it at first.

---

## Command Mapping

The dashboard should create structured jobs. The worker should convert jobs into known command arrays.

Never store one giant shell string and run it with `shell=True`.

Use command arrays.

### `pipeline_topic`

Input:

```text
topic
why optional
publish_days optional
```

Command:

```text
python3 /root/pulseops-studio/pipeline.py "<topic>" --why "<why>" --publish-days "1,3"
```

If `why` is empty, omit `--why`.

If `publish_days` is empty, omit `--publish-days`.

### `pipeline_cluster`

Input:

```text
topic
pillar
cluster_id
publish_days usually "0,2,4"
```

Command:

```text
python3 /root/pulseops-studio/pipeline.py "<topic>" --pillar "<pillar>" --cluster-id "<cluster_id>" --publish-days "0,2,4"
```

### `resume_run`

Input:

```text
run_dir
```

Command:

```text
python3 /root/pulseops-studio/pipeline.py --resume "<run_dir>"
```

### `force_publish`

Input:

```text
run_id
airtable_record_id
```

Command:

```text
python3 /root/pulseops-studio/force_publish.py "<run_id>" "<airtable_record_id>"
```

Long term, consider moving force publish into shared pipeline functions so `force_publish.py` does not drift from `pipeline.py`.

---

## Worker Behavior

The worker should run one job at a time.

Basic loop:

```text
1. Start worker.
2. Check for stale running jobs.
3. If another worker lock exists, exit or wait.
4. Get oldest queued job by priority then created_at.
5. If no job exists, sleep.
6. Mark job running.
7. Build command from job type.
8. Write command to command_json.
9. Open job log file.
10. Run command with subprocess.
11. Stream stdout/stderr into the log file.
12. If process exits 0, mark succeeded.
13. If process exits nonzero, mark failed.
14. If timeout, mark failed.
15. Send phone notification.
16. Move to next job.
```

The worker should not auto-retry full pipeline jobs at first.

`pipeline.py` already has internal Claude/API retries. Worker-level automatic retries can create confusing duplicate posts. Failed jobs should be visible and manually resumed.

---

## Locking

Use a lock file plus SQLite status.

Lock file:

```text
/tmp/pulseops-worker.lock
```

The lock should contain:

```text
pid
started_at
job_id
```

Startup behavior:

- If lock exists and PID is alive, do not start another worker.
- If lock exists and PID is dead, remove stale lock.
- If a job is marked `running` but started more than 6 hours ago, mark it `stale`.

Do not auto-resume stale jobs in v1. Show them in the dashboard and let Jon choose what to do.

---

## Timeouts

Set generous but finite timeouts.

Initial recommendation:

```text
pipeline_topic:   4 hours
pipeline_cluster: 4 hours
resume_run:       2 hours
force_publish:    30 minutes
pillar_plan:      30 minutes
topic_pick:       20 minutes
```

If a job times out:

- terminate process
- mark job `failed`
- save timeout message
- send phone alert
- show it on dashboard

---

## Logs

Every job gets a dedicated log.

Path:

```text
/root/pulseops-studio/logs/jobs/<job_id>_<type>.log
```

The log should include:

```text
job id
job type
created_at
started_at
command
stdout
stderr
exit code
finished_at
```

The dashboard should show:

- last 50 lines
- full log view
- failure reason
- link to run folder if known

Do not rely only on Discord/phone notifications for logs.

---

## Result Detection

The worker should not parse the whole pipeline deeply in v1.

Simple result detection:

- process exit code `0` means command-level success
- for `pipeline_*`, scan the newest run folder or job log for scheduled URL if practical
- if `published.json` exists in the run folder, store `result_url` and `result_post_id`
- if `NEEDS_REVIEW.md` exists, mark job `blocked` instead of `failed`

Suggested behavior:

```text
pipeline exits 0 + published.json exists       -> succeeded
pipeline exits 0 + NEEDS_REVIEW.md exists      -> blocked
pipeline exits 0 + no published.json           -> failed or blocked, inspect log
pipeline exits nonzero                         -> failed
```

Later, `pipeline.py` can write a small `run_result.json` file to make this cleaner.

Future `run_result.json`:

```json
{
  "status": "scheduled",
  "topic": "...",
  "run_dir": "...",
  "wp_post_id": "...",
  "wp_url": "...",
  "publish_date": "...",
  "needs_review": false,
  "error": null
}
```

---

## Dashboard Purpose

The dashboard replaces Discord as the control panel.

It should be designed for phone use first.

Do not overbuild. The dashboard is not the product. It is the cockpit.

---

## Dashboard Pages

### 1. Inbox

Things waiting for a human decision.

Show:

- topic suggestions
- pillar suggestions
- rejected posts
- stale jobs
- failed jobs
- social drafts waiting for manual posting

Actions:

- approve
- reject
- regenerate
- rewrite
- force publish
- cancel

### 2. Write This

Replacement for Discord `#write-this`.

Fields:

```text
topic or URL
optional context
content type: hot topic / standalone / cluster
publish days
```

Submit creates a `pipeline_topic` job.

If URL extraction is needed, keep it separate:

```text
URL -> extract topic suggestion -> show preview -> Jon confirms -> create job
```

Do not immediately run a URL scrape into the pipeline without showing the extracted topic first.

### 3. Queue

Shows:

- queued jobs
- running job
- failed jobs
- stale jobs
- recently completed jobs

Actions:

- cancel queued job
- retry failed job
- resume stale job
- view log

### 4. Runs

Shows recent `runs/` folders with:

- run id
- topic
- status
- WordPress URL if scheduled/published
- date
- whether `NEEDS_REVIEW.md` exists
- links to key files

Important files:

```text
run_meta.json
01_outline.json
03_draft.json
05_polish.json
06_approver.json
published.json
NEEDS_REVIEW.md
```

### 5. Rejected

Replacement for Airtable-only Force Publish / Rewrite workflow.

Show rejected posts from Airtable and/or local runs.

Actions:

- rewrite
- force publish
- discard
- open run
- view rejection reason

`rewrite` should create a job. It should not run immediately inside the web request.

### 6. Social Drafts

Shows generated social posts:

- LinkedIn
- Personal LinkedIn
- Instagram caption
- Bluesky

Actions:

- copy text
- mark posted
- regenerate later
- send to Buffer later

This can initially read from Airtable Social Posts.

### 7. Health

Show:

- worker running or stopped
- current lock file
- last successful job
- last failed job
- last Airtable check
- last WordPress publish
- queue length
- stale jobs
- `.env` presence without showing values

Do not expose secrets in the dashboard.

---

## Authentication

This dashboard must be private.

Simple v1:

- bind to localhost only
- access through SSH tunnel

Example usage:

```text
ssh -L 8080:localhost:8080 root@vps
open http://localhost:8080
```

If phone access needs direct URL:

- put behind nginx
- require strong basic auth
- use HTTPS
- consider Cloudflare Access or Tailscale

Do not expose an unauthenticated dashboard to the public internet.

---

## Phone Notifications

Use `ntfy.sh` or self-hosted ntfy for phone alerts.

Notifications:

```text
job started
job succeeded
job failed
job blocked / needs review
worker down
stale job detected
```

Discord can remain as a temporary backup notification channel, but should not be required.

---

## Migration Plan Away From Discord

### Phase 1: Queue Foundation

Build:

- SQLite job table
- `queue_worker.py`
- helper function `enqueue_job()`
- job logs
- manual CLI enqueue command

Do not change Discord yet.

Goal: manually enqueue one test job and watch worker run it.

### Phase 2: Dashboard Read-Only

Build dashboard pages:

- Queue
- Runs
- Health

No mutation yet except maybe cancelling queued jobs.

Goal: see what is happening from phone.

### Phase 3: Dashboard Creates Jobs

Add:

- Write This form
- Resume Run button
- Force Publish button

Goal: dashboard can create jobs, worker runs them.

### Phase 4: Convert Existing Scripts To Enqueue

Change later, carefully:

- `cluster_writer.py` should enqueue `pipeline_cluster`, not start `pipeline.py`.
- `discord_bot.py` can temporarily enqueue instead of directly starting `pipeline.py`.
- cron jobs should enqueue work, not run long jobs directly.

Goal: no workflow starts `pipeline.py` except the worker.

### Phase 5: Replace Discord Approvals

Add dashboard inbox for:

- topic suggestions
- pillar suggestions
- rejected posts

Once stable:

- stop using Discord reactions for approvals
- keep Discord alerts only if useful

### Phase 6: Remove Discord Bot

After the dashboard is trusted:

- disable persistent `discord_bot.py`
- remove reaction-based triggers
- keep webhook notifications only if desired

---

## What Not To Change Casually

Do not rewrite `pipeline.py` while building the dashboard.

Do not change agent prompts as part of the queue/dashboard work unless the task is specifically about content quality.

Do not remove Airtable from the system in the first version.

Do not make the dashboard directly publish or run long commands inside HTTP requests.

Do not let multiple workers run at once.

Do not auto-retry full content pipeline jobs until the queue has proven stable.

Do not expose the dashboard publicly without authentication.

---

## First Build Target

The smallest useful version:

```text
1. SQLite jobs table exists.
2. A helper can enqueue `pipeline_topic`.
3. `queue_worker.py` runs one queued job.
4. Job output is captured to `logs/jobs/`.
5. Job status changes from queued -> running -> succeeded/failed.
6. A simple dashboard shows Queue, Runs, and Health.
```

After that works, move `cluster_writer.py` onto the queue.

That is the moment the system becomes materially safer.

---

## Design Principle

The agents are the creative layer.

`pipeline.py` is the production layer.

The dashboard and worker are the control layer.

The control layer should be plain, predictable, and hard to confuse.

No cleverness belongs there.
