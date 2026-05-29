# SPEC: PulseOps Studio Control Panel

**Created:** 2026-05-29
**Status:** Draft

---

## Problem

Discord is the current control surface for PulseOps Studio. It handles topic approvals via reactions, pipeline status via webhooks, and job triggers via bot commands. It is failing at all three:

- Reactions are brittle and frequently missed
- Topic suggestions accumulate for months with no cleanup
- Pipeline status is scattered across multiple channels
- No single view of what is queued, running, or scheduled
- Checking publish schedule requires opening WordPress directly

## Goal

A private, phone-friendly web dashboard that replaces Discord as the control surface. Success means: open it in the morning, approve a few topics, check nothing is broken, close it. No Discord required.

## Audience

Jon only. Single user, internal tool.

## What Already Exists

- `queue_db.py` — SQLite job queue helper, full jobs schema, CLI enqueue/list/show
- `queue_worker.py` — one-job-at-a-time worker, lock file, stale detection, log streaming to `logs/jobs/`, `--once` flag
- `pulseops_control.db` — SQLite database at `/root/pulseops-studio/pulseops_control.db`
- `control_panel_mockup.html` — full visual mockup of the dashboard UI
- `pipeline.py` — the content pipeline (must not be called directly except by the worker)
- Airtable — content state database (Content Ideas, Clusters, Rejected Posts, Social Posts)
- WordPress REST API — scheduled posts and publish status
- Traefik — reverse proxy already handling `skalski.cloud` subdomains with SSL

## Tech Stack & Constraints

- **Server:** Flask (Python), runs on the VPS as a systemd service
- **Database:** SQLite (`pulseops_control.db`) for job queue; Airtable and WordPress REST API for content data
- **Domain:** `studio.skalski.cloud` via Traefik
- **Auth:** Username/password login (Flask session-based)
- **Constraint:** All pipeline actions must go through `queue_worker.py` — no Flask route may call `pipeline.py` directly or spawn long-running subprocesses inline

## Integrations

- **SQLite** (`pulseops_control.db`) — job queue read/write
- **Airtable** — read topic suggestions, cluster status, rejected posts, social posts
- **WordPress REST API** — read scheduled posts, reassign publish dates
- **`queue_worker.py`** — all write actions enqueue a job here

## Scope

### In Scope

- Username/password login with Flask session
- **Inbox** — pending topic suggestions with Approve / Deny (requires reason) / Wait actions; Approve queues a `pipeline_topic` job and suggests a publish date
- **Write This** — URL or freetext topic input; fires immediately as a `pipeline_topic` job and suggests a publish date; bypasses inbox
- **Calendar** — 1-2 week view of scheduled WordPress posts; drag or reassign publish dates; pipeline fullness indicator (posts queued, socials ready)
- **Post Viewer** — read-only view of generated blog copy and social variants (LinkedIn brand, LinkedIn personal, Instagram, Bluesky) per post; Veto/Regenerate button that queues a replacement run
- **Pipeline Health** — stuck runs with Resume button; rejected posts (NEEDS_REVIEW) with reason and Force Publish button
- **Run Log** — step-by-step pipeline progress per run (mirrors what Discord `#drafts` was outputting); current runs in progress + history with outcomes
- Traefik routing for `studio.skalski.cloud` with SSL

### Out of Scope (V1)

- Editing post copy directly in the dashboard
- Denial reasons feeding back into topic suggestions (V2)
- Pillar and cluster management
- LinkedIn automation controls
- Multi-user or client access
- Mobile-native app (responsive web only)
- Real-time push notifications (polling acceptable for V1)

## Minimum Viable Version

Login works. Inbox shows today's topics and you can approve or deny one. Approving it creates a job visible in the Run Log. Run Log shows the job moving through steps. Everything else can be stubbed.

## Open Questions

- Username/password to be provided by Jon at build time — stored in `.env` as `DASHBOARD_USER` and `DASHBOARD_PASSWORD`, never hardcoded.

## Resolved Decisions

- **Calendar data source:** WordPress REST API for publish dates (authoritative), Airtable for topic/pillar context. Join on slug.
- **Run log data source:** `pipeline.py` will write step events to a `run_events` SQLite table via a `log_step(job_id, step_name, message)` function. Dashboard polls this table. Replaces Discord step-by-step output. Discord webhook calls can remain in parallel until the dashboard is trusted.

## Risks

- `pipeline.py` writes step progress to Discord, not to a structured store — the Run Log needs a clean data source; may require adding a step-event table to SQLite
- WordPress date reassignment via REST API requires testing against the scheduled post status flow
- Airtable rate limits (5 req/sec) could cause sluggishness if the dashboard polls too aggressively
- Traefik label config must match the pattern already used by other services (`skalski.cloud`) — wrong label format will silently fail to route

## Priority

High. Discord failures are causing missed pipeline runs and stale inboxes. No hard blockers -- all dependencies exist. Build can start immediately.
