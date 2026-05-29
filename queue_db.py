#!/usr/bin/env python3
"""SQLite job queue helpers for the PulseOps control panel."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "pulseops_control.db"

CREATE_RUN_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS run_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL,
    ts         TEXT NOT NULL,
    step       TEXT NOT NULL,
    message    TEXT NOT NULL
)
"""

CREATE_JOBS_TABLE_SQL = """
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
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def init_db() -> None:
    """Create tables if they do not exist."""
    with _connect() as conn:
        conn.execute(CREATE_JOBS_TABLE_SQL)
        conn.execute(CREATE_RUN_EVENTS_TABLE_SQL)


def log_step(job_id: int, step: str, message: str) -> None:
    """Append a step event for a running job."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO run_events (job_id, ts, step, message) VALUES (?, ?, ?, ?)",
            (job_id, utc_now_iso(), step, message),
        )


def get_job_events(job_id: int, after_id: int = 0) -> list[dict[str, Any]]:
    """Return run events for a job, optionally after a given event id."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM run_events WHERE job_id = ? AND id > ? ORDER BY id ASC",
            (job_id, after_id),
        ).fetchall()
    return [dict(row) for row in rows]


def enqueue_job(
    type: str,
    topic: str | None = None,
    why: str | None = None,
    pillar: str | None = None,
    cluster_id: str | None = None,
    run_dir: str | None = None,
    publish_days: str | None = None,
    source: str = "manual",
    priority: int = 100,
) -> int:
    """Insert a queued job and return its id."""
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO jobs (
                type, status, priority, topic, why, pillar, cluster_id,
                run_dir, publish_days, created_at, source
            )
            VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                type,
                priority,
                topic,
                why,
                pillar,
                cluster_id,
                run_dir,
                publish_days,
                utc_now_iso(),
                source,
            ),
        )
        return int(cursor.lastrowid)


def get_next_job() -> dict[str, Any] | None:
    """Return the next queued job by priority then creation time."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE status = 'queued'
            ORDER BY priority ASC, created_at ASC
            LIMIT 1
            """
        ).fetchone()
    return _row_to_dict(row)


def get_job(job_id: int) -> dict[str, Any] | None:
    """Return one job by id."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row)


def mark_running(job_id: int) -> None:
    """Mark a job running, incrementing its attempt count."""
    with _connect() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'running',
                attempts = COALESCE(attempts, 0) + 1,
                started_at = ?
            WHERE id = ?
            """,
            (utc_now_iso(), job_id),
        )


def mark_done(
    job_id: int,
    status: str,
    error: str | None = None,
    result_url: str | None = None,
    result_post_id: str | None = None,
) -> None:
    """Mark a job finished with its terminal status and optional result fields."""
    with _connect() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = ?,
                finished_at = ?,
                error_message = ?,
                result_url = ?,
                result_post_id = ?
            WHERE id = ?
            """,
            (status, utc_now_iso(), error, result_url, result_post_id, job_id),
        )


def list_jobs(status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent jobs, optionally filtered by status."""
    with _connect() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT *
                FROM jobs
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def set_job_log_path(job_id: int, log_path: str) -> None:
    """Store the log path for a job."""
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET log_path = ? WHERE id = ?",
            (log_path, job_id),
        )


def set_job_command(job_id: int, command_json: Any) -> None:
    """Store the generated command as JSON text."""
    if isinstance(command_json, str):
        value = command_json
    else:
        value = json.dumps(command_json)

    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET command_json = ? WHERE id = ?",
            (value, job_id),
        )


def _print_job_table(jobs: list[dict[str, Any]]) -> None:
    print(f"{'id':>4}  {'type':<18}  {'status':<10}  {'topic':<50}  created_at")
    print(f"{'-' * 4}  {'-' * 18}  {'-' * 10}  {'-' * 50}  {'-' * 20}")
    for job in jobs:
        topic = (job.get("topic") or "")[:50]
        print(
            f"{job['id']:>4}  {job['type']:<18}  {job['status']:<10}  "
            f"{topic:<50}  {job['created_at']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="PulseOps SQLite job queue")
    subparsers = parser.add_subparsers(dest="command", required=True)

    enqueue_parser = subparsers.add_parser("enqueue")
    enqueue_parser.add_argument("topic")
    enqueue_parser.add_argument("--why", default=None)
    enqueue_parser.add_argument("--publish-days", default=None)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument(
        "--status",
        choices=["queued", "running", "succeeded", "failed"],
        default=None,
    )

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("job_id", type=int)

    args = parser.parse_args()

    if args.command == "enqueue":
        job_id = enqueue_job(
            "pipeline_topic",
            topic=args.topic,
            why=args.why,
            publish_days=args.publish_days,
            source="manual",
        )
        print(f"Enqueued job #{job_id}: {args.topic}")
        return 0

    if args.command == "list":
        _print_job_table(list_jobs(status=args.status))
        return 0

    if args.command == "show":
        job = get_job(args.job_id)
        if job is None:
            print(f"Job #{args.job_id} not found")
            return 1
        print(json.dumps(job, indent=2))
        return 0

    return 1


init_db()


if __name__ == "__main__":
    raise SystemExit(main())
