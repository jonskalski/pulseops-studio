# Changelog

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
