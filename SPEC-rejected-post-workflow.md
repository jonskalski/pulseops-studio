# SPEC: Rejected Post Workflow

**Created:** 2026-03-27
**Status:** Draft

---

## Problem
When the Approver agent rejects a post after all 3 attempts, the rejection reason is posted to Discord and written to a local `NEEDS_REVIEW.md` file — but never logged to Airtable, never acted on, and never used to improve the pipeline. Rejected posts and their reasons sit in limbo.

## Goal
Rejected posts are logged to Airtable with full context. A post-mortem agent can be manually triggered from Airtable to analyze the rejection and recommend specific prompt changes. Recommendations appear in Airtable and Discord. Over time, rejections become less frequent as patterns are identified and prompts are improved.

## Audience
Internal only — just Jon.

## What Already Exists
- `pipeline.py` — runs the 6-agent pipeline, handles 3 retry attempts, posts rejection reason to Discord, writes `NEEDS_REVIEW.md` to the run folder
- `agents/06_approver.md` — outputs structured JSON with pass/fail per criteria and a `comments` field with specific feedback
- Airtable — already has Content Ideas, Pillars, Clusters, Social Posts tables with working Python client (`airtable/client.py`)
- Discord webhook — already wired for pipeline notifications

## Tech Stack & Constraints
- Python on VPS (Ubuntu 24.04)
- Airtable API (existing client)
- Claude API (existing usage in pipeline)
- Webhook endpoint needed on VPS to receive trigger from Airtable button
- n8n already running — webhook trigger will use n8n webhook node to call post-mortem script on VPS

## Integrations
- Airtable: new "Rejected Posts" table, button automation triggers webhook
- Discord: post-mortem recommendations posted to existing pipeline webhook
- Claude API: post-mortem agent call
- Local filesystem: reads `NEEDS_REVIEW.md` and agent prompt files from run folder

## Scope

### In Scope
- Log rejected posts to Airtable "Rejected Posts" table automatically when pipeline hits 3-attempt failure
- Fields: Topic, Date, Run ID, Post Copy (full text), Rejection Reason (full comments), Score Breakdown (per-criteria pass/fail), Status (Pending Review / Reviewed)
- Post-mortem agent: reads the rejection record + relevant agent prompts, outputs specific recommended prompt changes
- Recommendations written back to Airtable record (new field: "Prompt Recommendations")
- Recommendations posted to Discord
- Webhook endpoint on VPS to receive trigger from Airtable button

### Out of Scope
- Auto-applying prompt changes
- Auto-retry after logging
- Logging intermediate rejections (attempts 1 and 2) — only final 3-attempt failures
- Any UI beyond Airtable

## Minimum Viable Version
A post fails all 3 attempts → gets logged to Airtable "Rejected Posts" table with reason and copy → Jon clicks a button in Airtable → post-mortem recommendations appear in the record and Discord.

## Open Questions
- Need n8n URL + API key to set up the webhook workflow (already on TODO)

## Risks
- n8n webhook node needs to be able to SSH into VPS or call a script — confirm n8n has VPS access configured
- Post-mortem agent needs access to the original run folder to read the full post copy — run IDs must be stored in Airtable to look up the right folder

## Priority
Low — pipeline publishes fine without it. Build after buffer system and draft review flow.
