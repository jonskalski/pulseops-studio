# Changelog

## 2026-04-23 — Pipeline retry logic, --resume flag, run_meta.json, TODO updates

### pipeline.py
- Added `import time` for retry sleeps
- `call_claude()` now retries up to 3x on ReadTimeout (45s/90s backoff) and 529/503/502 (30s/60s/120s backoff) — previously a single timeout silently killed the run
- New `resume_pipeline()` function resumes any incomplete or NEEDS_REVIEW run from its last completed step; injects prior approver feedback for NEEDS_REVIEW runs
- New `--resume RUN_DIR` CLI flag; `topic` arg is now optional when `--resume` is used
- New runs save `run_meta.json` (topic, why, pillar, cluster_id, allowed_days) so context survives a crash
- Added `run_meta.json` write at pipeline start

### TODO.md
- Added: Build pipeline job queue (pipeline_queue.jsonl + queue_worker.py)
- Restored: Rebuild cluster_writer.py for full pillar batch mode (updated description to reference queue)

## 2026-04-20 — New beginner pillars, cluster ID fix, Airtable fields, Discord log split

### pillar_planner.py
- Ran for 2 new pillars: "Local Marketing Systems for Small Businesses" (20 clusters) and "Email and Inbox Systems for SMB Owners" (20 clusters)

### cluster_writer.py
- Switched `get_next_cluster()` from oldest-first sort to `random.choice()` — spreads writes across all active pillars instead of draining one at a time
- Now passes `--cluster-id` (Airtable record ID) to pipeline.py so publish tracking no longer relies on title matching

### pipeline.py
- Added `--cluster-id` CLI arg, threaded through `run_pipeline()` to `mark_cluster_published()`
- Added `detect_schema_type()` and `count_words()` helpers (extracted from `generate_schema_markup`)
- `mark_cluster_published()` call now passes 6 new fields: Published Title, Keyword, WP Slug, Meta Description, Schema Type, Word Count
- Added `DISCORD_PIPELINE_LOG_URL` env var and `discord_log()` function — all step-level progress (Steps 1–6, polish attempts, LinkedIn) now routes to #pipeline-logs; #drafts only gets Started, Scheduled, Needs Review

### airtable/client.py
- `mark_cluster_published()` now accepts `cluster_id` for direct record update (bypasses title match), plus 6 new optional fields

### backfill_cluster_fields.py (new)
- Backfill script that matches published cluster records to runs/ JSON files and populates all 6 new fields; handles "In Queue" records via slug fuzzy-matching

### .env
- Added `DISCORD_PIPELINE_LOG_WEBHOOK_URL` for #pipeline-logs channel

## 2026-04-19 — Pipeline rejection audit + measurement fixes

### pipeline.py
- Added `count_post_words()` helper — strips HTML tags and entities, returns exact word count via `len(split())`
- Added `validate_and_repolish()` — runs after every Polish step, before Approver; measures word count and meta description `len()` exactly; if either is out of spec (1500-2000 words, 150-160 chars), re-prompts Polish with exact delta, up to 2 correction rounds
- `polish_and_approve()` now calls `validate_and_repolish()` between Polish and Approver, and logs final measurements to Discord

### agents/05_polish.md
- Removed "Estimate the word count" instruction — replaced with "write to 1,700–1,900 words, pipeline measures after you return"
- Added explicit meta description instruction: 150–160 chars, count before returning, do not estimate

### agents/06_approver.md
- Added "finalize verdict before writing" rule — stops Approver from reasoning out loud in comments and walking back pass/fail decisions mid-response
- Updated word count and meta description criteria to note pipeline pre-validates both

### agents/04_edit.md
- Removed "verify it's 150-160 characters" from meta description check — exact count is enforced by pipeline after Polish

### TODO.md
- Added 13 new items covering: scenario mode drift, keyword-in-title programmatic gate, Draft word count bias, draft/polish target misalignment, stale outline hardcoded links, Research agent stat hallucination, attempt 3 escalation rethink, force_publish.py missing measurement fixes, rewrite Polish feedback gap, weekly recurring review process

## 2026-04-19 — Fix Discord topics webhook pointing to wrong channel

### .env
- Updated DISCORD_TOPICS_WEBHOOK_URL to correct Suggestions Bot webhook (was pointing to Spidey Bot channel)

### discord_bot.py
- Updated TOPICS_CHANNEL_ID from 1484068137547599893 to 1487257451664244777 to match new webhook channel

### TODO.md
- Added PulseOps Control Panel webapp item (Flask replacement for Discord approval flow)
- Added Discord platform evaluation item

## 2026-04-19 — Fix duplicate featured images in sitemap

### pipeline.py
- Changed in-content image injection from raw `<figure>` tag to Gutenberg block format (`<!-- wp:image {"id":N} -->`) with attachment ID; Yoast deduplicates by attachment ID rather than URL, fixing the issue where WP.com's Photon CDN created different URLs for the featured image vs the content image

## 2026-04-12 — LinkedIn post generation

### agents/07_linkedin.md (new)
- LinkedIn agent prompt: dry PulseOps voice, short-line format, hook + body + soft CTA, no hashtags/emojis, 100-180 words

### pipeline.py
- Added `DISCORD_LINKEDIN_WEBHOOK_URL` env var
- Post-publish step: runs 07_linkedin agent on polished content, logs to Airtable Social Posts, posts draft to Discord #linkedin

### airtable/client.py
- Added `log_social_post()` — creates record in Social Posts table with platform, copy, status, date, WP URL

### .env
- Added `DISCORD_LINKEDIN_WEBHOOK_URL=` (needs Discord #linkedin webhook URL to activate)

## 2026-04-12 — Pillar voice consistency for cluster posts

### pipeline.py
- Added `get_pillar_voice_context(pillar_name)` — queries Airtable for published sibling clusters, reads their `05_polish.json`, extracts intro paragraph (~300 chars) as voice/terminology reference
- Added `--pillar` CLI argument; when set, voice context is injected into Draft agent input
- `mark_cluster_published()` now called at publish time when `--pillar` is set, writing run_id to Clusters table

### airtable/client.py
- Added `run_id` param to `mark_cluster_published()` — writes Run ID field to Clusters record on publish
- Added `get_published_clusters_for_pillar(pillar_name)` — returns published cluster records for a pillar, sorted newest first

### cluster_writer.py
- Now passes `--pillar pillar_name` to pipeline.py so every cluster post gets sibling voice context

## 2026-04-12 — Rejected post backfill + Rewrite trigger

### backfill_rejected.py (new)
- One-off script to log 6 historical NEEDS_REVIEW runs (pre-Apr-2) into Airtable Rejected Posts table
- Reads NEEDS_REVIEW.md for rejection reason, 01_outline.json for topic, 05_polish.json for post copy

### airtable/client.py
- Added `get_rewrite_records()` — returns Rejected Posts records with Status = "Rewrite"
- Added `typecast: True` to all `_update()` calls so new single-select options auto-create on write

### force_publish.py
- Added `rewrite_run()` — loads original outline/research from run folder, creates new run dir, re-runs Draft→Edit→Polish→Approve with rejection feedback injected, publishes on approval, flips back to Needs Review on 3-attempt failure
- Updated `poll()` to handle both Force Publish and Rewrite records from Airtable in same cron cycle

## 2026-04-09 — Uptime Kuma heartbeat added to Discord bot

### discord_bot.py
- Added `asyncio` import and `heartbeat()` async task that pings Uptime Kuma push URL every 60 seconds
- Heartbeat starts on `on_ready` via `client.loop.create_task(heartbeat())`
- Added `UPTIME_KUMA_PUSH_URL` constant for the push monitor endpoint
- Bot restarted to pick up changes

### TODO.md
- Added: wire Uptime Kuma pipeline monitor (Push, 1440min interval) into pipeline.py end-of-run

## 2026-04-03 — Cluster cadence, publish day routing, morning briefing fix, Pexels key

### morning_briefing.py (sandbox)
- Fixed jolt/weird fact always showing fallback — Claude API returns JSON in markdown code blocks, broke json.loads(). Fixed with regex extraction.

### pipeline.py
- next_publish_slot() now accepts allowed_days param to restrict scheduling to specific weekdays
- publish_to_wordpress() and run_pipeline() thread allowed_days through
- Added --publish-days CLI arg (e.g. "1,3" for Tue/Thu)

### discord_bot.py
- Topic approvals and #write-this posts now pass --publish-days 1,3 (Tue/Thu only for trending topics)

### cluster_writer.py (new)
- Created cluster_writer.py — pulls next Suggested cluster from Airtable, fires pipeline with Mon/Wed/Fri scheduling
- NOTE: needs rebuild for full batch mode next session

### .env
- Added PEXELS_API_KEY so featured images work when pipeline runs via Discord bot

### crontab
- Added cluster_writer.py cron: Sat/Mon/Wed at 7am UTC (0 7 * * 1,3,6)

## 2026-04-03 — Voice/snark rule, FAQ removed, Discord bot raw reaction fix

### CLAUDE.md
- Added Snark Rule section with concrete before/after example ("Congratulations, apparently.")

### agents/03_draft.md
- Added Snark Rule with pattern example above the voice target examples
- Removed FAQ section instruction entirely

### agents/05_polish.md
- Added Snark Rule with pattern example

### pipeline.py
- Removed FAQPage schema detection — no longer generates FAQPage JSON-LD

### discord_bot.py
- Switched from `on_reaction_add` to `on_raw_reaction_add` — reactions on cached messages now work for all messages regardless of age

## 2026-04-02 — Discord channel routing, rejected post workflow, Polish feedback fix

### pipeline.py
- `DISCORD_WEBHOOK_URL` now prefers `DISCORD_DRAFTS_WEBHOOK_URL` — publish notifications go to #drafts
- `polish_and_approve()` now accepts `approver_feedback` param — passes rejection comments to Polish agent on attempts 2 and 3
- On 3-attempt failure: logs to Airtable Rejected Posts table via `log_rejected_post()`, posts Discord prompt to flip "Force Publish"

### pillar_suggester.py / pillar_planner.py
- `DISCORD_WEBHOOK_URL` now prefers `DISCORD_PILLAR_WEBHOOK_URL` — pillar suggestions/plans go to #pillar-post-suggestions

### airtable/client.py
- Added `TABLE_REJECTED` — new Rejected Posts table
- Added `log_rejected_post()`, `get_force_publish_records()`, `update_rejected_status()`

### force_publish.py (new)
- Polls Airtable for "Force Publish" status records, publishes last polished run to WordPress, updates status to "Published (Forced)", notifies #drafts

### .env
- Added `DISCORD_PILLAR_WEBHOOK_URL`, `DISCORD_DRAFTS_WEBHOOK_URL`, `AIRTABLE_REJECTED_POSTS_TABLE_ID`

### crontab
- Added `*/5 * * * *` poller for `force_publish.py --poll`

## 2026-03-31 — Added 9 SEO behaviors to content pipeline

### pipeline.py
- Added `POSTS_INDEX_FILE`, `load_posts_index()`, `update_posts_index()` — maintains published_posts_index.json with title/url/slug/topic per post
- Added `generate_schema_markup()` — auto-detects Article/HowTo/FAQPage schema, appends JSON-LD to post content before WP publish
- Updated internal linking section to use local posts index (topic-aware) merged with WP API
- Changed image alt text from post title to keyword string
- Added keyword cannibalization check before pipeline starts — posts Discord warning if overlap found
- `update_posts_index()` called after each successful publish

### agents/01_outline.md
- Added Title Optimization section: first-person/emotional hooks, no list titles, 60-char limit, natural keyphrase placement

### agents/02_research.md
- Added `semantic_keywords` deliverable (8-10 LSI/related terms) to research task and output JSON schema

### agents/03_draft.md
- Added Title Optimization section (same rules as outline)
- Added EEAT Signals requirement: at least one specific scenario with real numbers, before/after outcome, or practitioner insight per post
- Added SEO instructions for semantic keyword weaving, featured snippet paragraph (40-60 word direct answer after intro), and FAQ section (3-4 H3 Q&As near conclusion)

### agents/06_approver.md
- Added title checks to SEO Basics: 60-char limit, no generic list titles
- Added EEAT approval criterion with pass/fail scoring
- Added `eeat` to scores output JSON

## 2026-03-31 — Added date tracking fields to all Airtable tables

### airtable/client.py
- Added `Suggested Date` (today's date) to `create_suggested()` and `create_cluster()`
- Added `Published Date` (today's date) to `mark_published()` and `mark_cluster_published()`
- Backfilled all 85 existing records: Suggested Date from Airtable createdTime, Published Date from WordPress API for 15 published posts

### pillar_suggester.py
- Added `Suggested Date` to pillar creation in `save_to_airtable()`

### Airtable (via API)
- Added `Suggested Date` and `Published Date` Date fields to Content Ideas table
- Added `Suggested Date` to Pillars table
- Added `Suggested Date` and `Published Date` to Clusters table

## 2026-03-28 — Fixed Discord topic posting, overhauled RSS feeds

### .env
- Added `DISCORD_TOPICS_WEBHOOK_URL` — was missing, causing daily topics to generate silently with no Discord delivery

### topic_picker.py
- Replaced broken feeds (Zapier malformed XML, Beehiiv empty) and AI-heavy feeds (Ars Technica, Verge) with SMB-focused sources: Search Engine Land, Inc.com, Moz, Convince & Convert
- Added prompt guardrail: no more than 2 AI topics per batch, at least 3 must be non-AI SMB topics

## 2026-03-27 — Rejected post workflow spec written

### SPEC-rejected-post-workflow.md
- New spec created: documents the rejected post Airtable logging flow and post-mortem agent design

## 2026-03-21 — Pillar system, Airtable fields, GitHub setup

### pillar_planner.py
- Added `load_dotenv(override=True)` to fix stale env var issue where old API key was cached in shell
- Added `sync_pillar_stats()` call after cluster creation to update Clusters Created/Published counts
- First successful run: CRMs for Small Business Beginners — 21 clusters generated

### pillar_suggester.py (new)
- Asks Claude to suggest 5 content pillars, avoids existing ones, posts to Discord as Pillar Suggestions, saves to Airtable as Suggested with Summary field

### discord_bot.py
- Added Pillar Suggestion detection — ✅ fires pillar_planner.py and sets status to Planning, ❌ sets status to Rejected

### airtable/client.py
- Added `sync_pillar_stats(pillar_name)` — counts clusters total + published, updates Pillars record
- `mark_cluster_published()` now calls `sync_pillar_stats()` automatically
- New Airtable fields: Clusters Created, Clusters Published, Summary
- Pillars Status options expanded: added Suggested, Rejected

### Git + /summarize skill
- Initialized repo, pushed to github.com/jonskalski/pulseops-studio
- /summarize skill updated to auto-push at end of every session (Step 7c)

### ROADMAP.md
- Updated Current State checklist, Pillars schema, and Pillar Brief Flow to reflect live state

## 2026-03-19

### agents/04_edit.md + agents/06_approver.md — Scenario thread rule relaxed
- **Problem:** The original threaded scenario rule required the scenario to appear in at least 3 sections, with no distinction between intro/conclusion and middle body sections. A post with a scenario in the intro, 5 of 6 body sections, and the conclusion was DENIED because one middle body section used generic second-person framing. That's a false failure — the thread was clearly present throughout.
- **Fix (04_edit.md):** Scenario thread check now requires the scenario in the intro, at least 2 body sections where it fits naturally, and the conclusion. Absence from a single middle section is explicitly allowed.
- **Fix (06_approver.md):** Scenario pass/fail now FAILS only if the scenario is absent from the intro, absent from the conclusion, or appears fewer than 2 times total in the body. A middle section in generic second-person is no longer a failure condition. The approver is instructed not to fail a post for one generic middle section.



### topic_picker.py
- **Post all 5 topics to Discord** — `post_to_discord()` now loops through all 5 Claude-ranked topics and posts each as a separate Discord message with ✅/❌ react instructions.
- **Save topics to file before posting** — All 5 topics saved to `runs/topic_picks/YYYY-MM-DD_topics.json` immediately after Claude responds, so picks aren't lost if Discord fails.
- **Pending topics deduplication** — Added `runs/pending_topics.txt` log. After posting to Discord, each topic is appended to this file. At run start, pending topics are loaded and passed to Claude alongside published posts to avoid suggesting duplicates.
- **SMB-first RSS feeds** — Added Zapier Blog, HubSpot Marketing, Small Biz Trends, and Search Engine Journal. These are listed first in `RSS_FEEDS` so Claude sees SMB-native headlines with higher weight. Existing enterprise/developer feeds retained but moved lower.

### pipeline.py
- **`--why` argument** — Accepts optional `--why "..."` flag. When provided, the context is appended to the Draft agent input as `Topic context: {why}` so the Draft agent understands why the topic is timely and what the SMB angle is.
- Switched argument parsing from `sys.argv` to `argparse` to cleanly support the new flag.

### discord_bot.py
- **Extracts `why` from Discord message** — On ✅ react, parses the italics line from the topic message and passes it to `pipeline.py` as `--why "..."`.
- **Removes topic from pending log on reaction** — Both ✅ (approved) and ❌ (skipped) reactions now call `remove_pending_topic()` to keep `pending_topics.txt` clean.
- Imports `remove_pending_topic` directly from `topic_picker.py` to avoid duplicating file logic.

---

## 2026-03-19 — Agent Quality Overhaul

Root cause: a published post came out competent but generic. Voice ceiling wasn't defined, headers were bland, a threaded scenario disappeared after the intro, and the approver passed it anyway because its checks were too loose.

### agents/01_outline.md
- Added concrete bad vs good H2 header examples showing the target register.
- Added the HubSpot listicle test: if a header could appear on a generic marketing blog unchanged, rewrite it. Requires at least 3 H2s to have genuine personality.

### agents/02_research.md
- Added scenario_mode decision at the top of the task: agent must choose "threaded" (one recurring SMB scenario, no named people, appears in 3+ sections) or "hypothetical" (second-person only).
- Added scenario_seed to JSON output (1-2 sentence scenario description, or null).
- Added scenario_details field: concrete moments from the scenario the Draft agent can use.
- Removed "fictional SMBs are fine" language that contradicted the no-fake-characters rule.

### agents/03_draft.md
- Added voice ceiling section with explicit too-cold and too-hot examples defining the target range.
- Added scenario handling section: threaded mode must use scenario_seed across 3+ sections (no named people); hypothetical mode uses second-person only.
- Fixed length target from 1,200-1,800 to 1,500-2,000 words.
- Removed "NO FAKE CASE STUDIES" rule; replaced with scenario_mode system above.

### agents/04_edit.md
- Added scenario thread check: if threaded scenario appears in fewer than 3 sections, reintroduce it naturally in later sections.
- Fixed length target from implied to explicit 1,500-2,000 words.

### agents/05_polish.md
- Added voice ceiling section with too-cold and too-hot examples mirroring Draft agent.
- Added HubSpot listicle test for headers: at least 3 H2s must have personality; rewrite any that fail.

### agents/06_approver.md
- Added "headers" check to scores: at least 3 H2s must pass the HubSpot listicle test; failing headers named explicitly.
- Added "scenario" check to scores: threaded mode must appear in 3+ sections; hypothetical mode must have no named fictional characters.
- Changed word count gate to 1,500-2,000 words (hard fail outside range).
- Added voice ceiling check in both directions (too cold and too hot both fail).
- Expanded scores object to include "headers" and "scenario" fields.
- Required DENY feedback to name the exact section header or quote the specific sentence.

### pipeline.py
- Replaced 2-attempt Polish loop with 3-attempt escalating retry:
  1. Polish → Approve
  2. (denied) Polish again → Approve
  3. (denied again) Rerun Draft with original outline + research + approver feedback → Polish → Approve
  - Still denied: write NEEDS_REVIEW.md and stop

---

## 2026-03-19 — TODO system and /summarize updates

### /summarize skill (SKILL.md)
- Added Step 7b: load or create TODO.md per project, Claude marks completed items from session, adds new pending items, posts two Discord messages (completed + pending) to DISCORD_TODO_WEBHOOK_URL with discord_sent tracking so completed items only post once.
- Updated Step 9 confirmation to include TODO.md status.

### ~/.claude/settings.json
- Added DISCORD_TODO_WEBHOOK_URL env var pointing to the dedicated #todo Discord channel (channel ID 1481878060344020992).

---

## 2026-03-19 — Voice target examples expanded

### agents/03_draft.md + agents/05_polish.md
- Voice target (pass) examples expanded from 3-5 to 10 to better define the warmer, more absurdist register matching established brand tone. New examples cover the "slightly tired knowledgeable friend" end of the spectrum — self-deprecating, a little absurd, still genuinely useful. Reference post: /ai-automation-smb-guide/.
- Added test sentence after examples: "The test: would a slightly tired, knowledgeable friend say this over coffee? If it sounds like a press release or a pep talk, rewrite it."
- **05_polish.md only:** Polish agent task instructions updated to flag competent-but-bland as an explicit fail condition. "Warm and a little absurdist beats dry and restrained."

## 2026-03-21 — Removed threaded scenario system

Removed the threaded scenario system from all agents. Second-person is now the only mode. Brief one-sentence unnamed examples replace the threaded scenario approach.

**Changed files:** 02_research.md, 03_draft.md, 04_edit.md, 06_approver.md, CLAUDE.md

**Reason:** Threaded scenarios created distance between the reader and the advice. The setup felt performative. Second-person direct address is more confident and reads faster. The fake-case-study problem is solved by keeping examples to one sentence with no names or biography, not by building a narrative thread.

## 2026-03-21 — #write-this channel, .env fixes, agent overhaul

### discord_bot.py
- Added on_message listener watching WRITE_THIS_CHANNEL_ID (1484742781514682368)
- Added extract_topic_from_url() — scrapes URL, asks Claude for SMB topic + why context
- Added stderr logging for pipeline subprocess (was silently failing)
- Installed beautifulsoup4 for URL scraping
- Killed old tmux bot instance (was competing with systemd bot, stealing events)

### .env
- Added DISCORD_WEBHOOK_URL (was missing — caused silent pipeline failures)
- Added WP_USER, WP_APP_PASSWORD, WP_URL (were missing — caused all WP publishes to fail silently)

### agents/02_research.md
- Removed scenario_mode decision system entirely
- Removed scenario_mode, scenario_seed, scenario_details from output JSON
- Added ## Examples section: brief unnamed one-sentence grounding examples only

### agents/03_draft.md
- Removed ## Scenario Handling section
- Added ## Examples and Grounding: second-person throughout, brief unnamed examples
- Banned &mdash; HTML entity alongside — character
- Raised target length to 1,700-2,000 words (was 1,500-2,000)

### agents/04_edit.md
- Replaced scenario thread check with simple examples check (one sentence, unnamed, grounding)

### agents/05_polish.md
- Added &mdash; HTML entity to em dash ban
- Added word count check: expand if under 1,550 words before passing to Approver

### agents/06_approver.md
- Removed scenario from scores object
- Moved examples check under Structure criteria

### pipeline.py
- Bumped note truncation from 100 to 200 chars (Polish and Edit notes)

## 2026-04-29 — Voice overhaul: deadpan/sardonic/dark as baseline register

### agents/03_draft.md
- Rewrote voice ceiling: changed from "knowledgeable, dry, occasionally sarcastic" to "deadpan, sarcastic, occasionally dark"
- Changed snark rule from "1-2 moments max" to sarcasm-as-baseline with ceiling on escalation/stacking only
- Updated target examples: added Kevin, CRM setup, pipeline failure, software demo examples
- Updated voice rules: "deadpan, sardonic, occasionally dark" replaces "dry, sardonic, a little tired"

### agents/05_polish.md
- Mirrored all voice ceiling changes from 03_draft.md
- Updated "The Voice" section to make sarcasm the baseline register, not occasional
- Rewrote task description: "deadpan and dark beats warm and restrained"

### agents/07_linkedin.md
- Updated voice section to match new register: deadpan, sardonic, occasionally dark
- Added Kevin example to pass/fail section
