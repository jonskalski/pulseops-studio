#!/usr/bin/env python3
"""
One-off script: backfill NEEDS_REVIEW runs into Airtable Rejected Posts table.
Only logs runs that were created before the Rejected Posts table existed (pre-Apr-2).
"""

import json
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

RUNS_DIR = Path(__file__).parent / "runs"

BACKFILL_RUNS = [
    "2026-03-19_16-28_salesforce-agentforce-for-small-business-what-it-actually-does-and-whether-it-s-worth-it",
    "2026-03-21_02-41_how-small-businesses-can-use-ai-to-save-time",
    "2026-03-21_02-59_what-does-a-sales-pipeline-do-for-your-business",
    "2026-03-21_03-14_5-quick-wins-to-streamline-your-sales-operations-without-breaking-the-budget",
    "2026-04-02_22-36_5-quick-wins-how-ai-can-immediately-improve-your-sales-team-s-productivity",
    "2026-04-09_19-27_conflict-at-work-is-costing-you-more-than-you-think-a-small-business-owner-s-guide-to-managing-team-disputes",
]

def main():
    sys.path.insert(0, str(Path(__file__).parent))
    from airtable.client import log_rejected_post

    for run_id in BACKFILL_RUNS:
        run_dir = RUNS_DIR / run_id
        needs_review = run_dir / "NEEDS_REVIEW.md"

        if not needs_review.exists():
            print(f"  SKIP (no NEEDS_REVIEW.md): {run_id}")
            continue

        # Extract rejection reason (everything after the header lines)
        text = needs_review.read_text()
        lines = text.strip().splitlines()
        reason_lines = []
        skip = True
        for line in lines:
            if skip and (line.startswith("#") or line.startswith("Approver feedback")):
                if line.startswith("Approver feedback"):
                    reason_lines.append(line)
                    skip = False
                continue
            reason_lines.append(line)
        rejection_reason = "\n".join(reason_lines).strip()

        # Get topic from outline if available
        outline_file = run_dir / "01_outline.json"
        topic = None
        if outline_file.exists():
            try:
                outline = json.loads(outline_file.read_text())
                topic = outline.get("title") or outline.get("topic")
            except Exception:
                pass
        if not topic:
            # Derive from folder name: strip timestamp prefix
            parts = run_id.split("_", 2)
            topic = parts[2].replace("-", " ").title() if len(parts) >= 3 else run_id

        # Get post copy from last polish file
        post_copy = ""
        polish_file = run_dir / "05_polish.json"
        if polish_file.exists():
            try:
                post_copy = polish_file.read_text()
            except Exception:
                pass

        print(f"  Logging: {topic[:60]}...")
        try:
            log_rejected_post(
                topic=topic,
                run_id=run_id,
                rejection_reason=rejection_reason,
                score_breakdown="(backfilled — see Rejection Reason)",
                post_copy=post_copy,
            )
            print(f"    ✓ Done")
        except Exception as e:
            print(f"    ✗ Error: {e}")

    print("\nBackfill complete.")

if __name__ == "__main__":
    main()
