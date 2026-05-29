#!/usr/bin/env python3
"""Foreground worker for the PulseOps SQLite job queue."""

from __future__ import annotations

import argparse
import json
import os
import select
import signal
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import queue_db


ROOT = Path(__file__).resolve().parent
LOCK_PATH = Path("/tmp/pulseops-worker.lock")
LOG_DIR = ROOT / "logs" / "jobs"
RUNS_DIR = ROOT / "runs"

TIMEOUTS = {
    "pipeline_topic": 4 * 3600,
    "pipeline_cluster": 4 * 3600,
    "resume_run": 2 * 3600,
    "force_publish": 30 * 60,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


WORKER_STARTED_AT = utc_now_iso()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock_pid() -> int | None:
    try:
        lines = LOCK_PATH.read_text().splitlines()
    except FileNotFoundError:
        return None

    for line in lines:
        if line.startswith("pid="):
            try:
                return int(line.split("=", 1)[1])
            except ValueError:
                return None
    return None


def write_lock(job_id: int | str = "none") -> None:
    LOCK_PATH.write_text(
        f"pid={os.getpid()}\nstarted_at={WORKER_STARTED_AT}\njob_id={job_id}\n"
    )


def acquire_lock() -> bool:
    if LOCK_PATH.exists():
        pid = read_lock_pid()
        if pid and pid_is_alive(pid):
            print(f"Warning: another worker is already running with PID {pid}")
            return False
        print("Warning: removing stale worker lock")
        LOCK_PATH.unlink(missing_ok=True)

    write_lock("none")
    return True


def release_lock() -> None:
    try:
        pid = read_lock_pid()
        if pid == os.getpid():
            LOCK_PATH.unlink(missing_ok=True)
    except FileNotFoundError:
        pass


def mark_stale_running_jobs() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    stale_jobs: list[dict[str, Any]] = []

    with queue_db._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = 'running'"
        ).fetchall()
        for row in rows:
            job = dict(row)
            started_at = parse_iso(job.get("started_at"))
            if started_at and started_at < cutoff:
                stale_jobs.append(job)

        for job in stale_jobs:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'stale',
                    finished_at = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (
                    utc_now_iso(),
                    "Marked stale after running for more than 6 hours",
                    job["id"],
                ),
            )

    for job in stale_jobs:
        print(f"Warning: marked stale job #{job['id']} ({job['type']})")


def build_command(job: dict[str, Any]) -> list[str]:
    job_type = job["type"]
    topic = job.get("topic")

    if job_type == "pipeline_topic":
        cmd = ["python3", str(ROOT / "pipeline.py"), topic]
        if job.get("why"):
            cmd += ["--why", job["why"]]
        if job.get("publish_days"):
            cmd += ["--publish-days", job["publish_days"]]
        return cmd

    if job_type == "pipeline_cluster":
        cmd = ["python3", str(ROOT / "pipeline.py"), topic]
        if job.get("pillar"):
            cmd += ["--pillar", job["pillar"]]
        if job.get("cluster_id"):
            cmd += ["--cluster-id", job["cluster_id"]]
        if job.get("publish_days"):
            cmd += ["--publish-days", job["publish_days"]]
        return cmd

    if job_type == "resume_run":
        return ["python3", str(ROOT / "pipeline.py"), "--resume", job["run_dir"]]

    if job_type == "force_publish":
        payload = json.loads(job["payload_json"])
        return [
            "python3",
            str(ROOT / "force_publish.py"),
            payload["run_id"],
            payload["airtable_record_id"],
        ]

    raise ValueError(f"Unknown job type: {job_type}")


def latest_run_dir() -> Path | None:
    if not RUNS_DIR.exists():
        return None

    dirs = [path for path in RUNS_DIR.iterdir() if path.is_dir()]
    if not dirs:
        return None

    return max(dirs, key=lambda path: path.stat().st_mtime)


def detect_pipeline_result(job_id: int) -> tuple[str, str | None, str | None, str | None]:
    run_dir = latest_run_dir()
    if run_dir is None:
        return "failed", "pipeline exited 0 but no published.json or NEEDS_REVIEW.md found", None, None

    if (run_dir / "NEEDS_REVIEW.md").exists():
        return "blocked", None, None, None

    published_path = run_dir / "published.json"
    if published_path.exists():
        try:
            published = json.loads(published_path.read_text())
        except json.JSONDecodeError as exc:
            return "failed", f"published.json could not be parsed: {exc}", None, None

        result_url = published.get("link")
        result_post_id = published.get("id")
        if result_post_id is not None:
            result_post_id = str(result_post_id)
        return "succeeded", None, result_url, result_post_id

    return "failed", "pipeline exited 0 but no published.json or NEEDS_REVIEW.md found", None, None


def timeout_message(timeout_seconds: int) -> str:
    hours = timeout_seconds / 3600
    if hours.is_integer():
        return f"Timed out after {int(hours)}h"
    return f"Timed out after {timeout_seconds}s"


def run_command(
    job: dict[str, Any],
    cmd: list[str],
    log_path: Path,
    timeout_seconds: int,
) -> tuple[int | None, str | None, str]:
    start_monotonic = time.monotonic()
    output_tail = ""

    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"job id: {job['id']}\n")
        log_file.write(f"job type: {job['type']}\n")
        log_file.write(f"created_at: {job.get('created_at')}\n")
        log_file.write(f"started_at: {utc_now_iso()}\n")
        log_file.write(f"command: {json.dumps(cmd)}\n")
        log_file.write("\n--- output ---\n")
        log_file.flush()

        env = os.environ.copy()
        env["PULSEOPS_JOB_ID"] = str(job["id"])

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            cwd=str(ROOT),
            env=env,
        )

        timed_out = False
        assert process.stdout is not None

        stdout_fd = process.stdout.fileno()
        os.set_blocking(stdout_fd, False)

        def drain_output() -> None:
            nonlocal output_tail
            while True:
                try:
                    chunk = os.read(stdout_fd, 4096)
                except BlockingIOError:
                    break
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                print(text, end="")
                log_file.write(text)
                log_file.flush()
                output_tail = (output_tail + text)[-500:]

        while True:
            readable, _, _ = select.select([stdout_fd], [], [], 1)
            if readable:
                drain_output()

            if process.poll() is not None:
                drain_output()
                break

            if time.monotonic() - start_monotonic > timeout_seconds:
                timed_out = True
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                drain_output()
                break

        exit_code = process.returncode
        finished_at = utc_now_iso()
        if timed_out:
            message = timeout_message(timeout_seconds)
            log_file.write(f"\n--- timeout ---\n{message}\n")
            log_file.write(f"finished_at: {finished_at}\n")
            log_file.flush()
            return None, message, output_tail

        log_file.write(f"\n--- exit code ---\n{exit_code}\n")
        log_file.write(f"finished_at: {finished_at}\n")
        log_file.flush()
        return exit_code, None, output_tail


def process_job(job: dict[str, Any]) -> str:
    job_id = job["id"]
    start_time = time.monotonic()
    status = "failed"

    write_lock(job_id)
    queue_db.mark_running(job_id)

    try:
        cmd = build_command(job)
        queue_db.set_job_command(job_id, cmd)
    except Exception as exc:
        queue_db.mark_done(job_id, "failed", error=str(exc))
        print_summary(job, "failed", start_time)
        write_lock("none")
        return "failed"

    log_path = LOG_DIR / f"{job_id}_{job['type']}.log"
    queue_db.set_job_log_path(job_id, str(log_path))

    timeout_seconds = TIMEOUTS.get(job["type"], 3600)
    try:
        exit_code, timeout_error, output_tail = run_command(
            job, cmd, log_path, timeout_seconds
        )
    except Exception as exc:
        status = "failed"
        queue_db.mark_done(job_id, status, error=str(exc))
        print_summary(job, status, start_time)
        write_lock("none")
        return status

    if timeout_error:
        status = "failed"
        queue_db.mark_done(job_id, status, error=timeout_error)
    elif exit_code == 0:
        if job["type"] in {"pipeline_topic", "pipeline_cluster"}:
            status, error, result_url, result_post_id = detect_pipeline_result(job_id)
            queue_db.mark_done(
                job_id,
                status,
                error=error,
                result_url=result_url,
                result_post_id=result_post_id,
            )
        else:
            status = "succeeded"
            queue_db.mark_done(job_id, status)
    else:
        status = "failed"
        queue_db.mark_done(job_id, status, error=output_tail)

    print_summary(job, status, start_time)
    write_lock("none")
    return status


def print_summary(job: dict[str, Any], status: str, start_time: float) -> None:
    duration = int(time.monotonic() - start_time)
    topic = job.get("topic") or ""
    print(f"[{job['id']}] {job['type']} | {topic} | {status} | {duration}s")


def worker_loop(once: bool = False) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if not acquire_lock():
        return

    try:
        mark_stale_running_jobs()

        while True:
            job = queue_db.get_next_job()
            if job is None:
                if once:
                    return
                time.sleep(15)
                continue

            process_job(job)

            if once:
                return
    finally:
        release_lock()


def handle_signal(signum: int, _frame: Any) -> None:
    release_lock()
    raise SystemExit(128 + signum)


def main() -> int:
    parser = argparse.ArgumentParser(description="PulseOps queue worker")
    parser.add_argument("--once", action="store_true", help="Process one job then exit")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    worker_loop(once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
