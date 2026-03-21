# PulseOps Studio

An AI-powered content automation and optimization platform for SMBs. Not a content generator — a self-evolving content engine.

## One-Line Summary
Self-improving content automation system that generates, publishes, and optimizes marketing content using performance-driven trait evolution (DNA) unique to each client.

## Core Purpose
Automate the full content lifecycle:
- Idea generation
- Content creation (blogs, social posts, newsletters)
- Publishing + scheduling
- Performance tracking
- Continuous optimization based on results

Goals: drive traffic, increase engagement, improve conversions, reduce manual effort to near zero.

## Stack
- **Airtable** — source of truth / database
- **n8n** — orchestration + automation engine
- **Claude API (via OpenRouter)** — content generation
- **WordPress** — publishing layer (CMS)
- **Social platforms** — distribution layer

## Content Hierarchy
1. **Pillar Content** — long-form, high-value anchor topic (e.g. "CRM Automation for Small Businesses")
2. **Cluster Content** — 5+ supporting posts per pillar, SEO-focused, interlinked
3. **Social Posts** — derived from pillar + cluster, drip-scheduled
4. **Newsletters** — sent after full pillar+cluster set is published, always tied to current pillar

## Content Engine Flow
1. Topic generation → stored in Content Ideas / Backlog table
2. Pillar approved (manual or automated trigger)
3. Cluster expansion — 5+ topics generated
4. Content creation — Claude generates blog, social, newsletter; all stored in Airtable, linked to parent
5. AI quality check — pass/fail or scoring; failed content rewritten or flagged
6. Publishing — blogs → CMS, social → drip schedule, newsletter → post-pillar send
7. Performance tracking — clicks, impressions, engagement collected

## The Evolution Engine (Core Differentiator)

### Initial Phase
First ~10 posts generated WITHOUT optimization traits (baseline data collection)

### Trait Detection
After publishing, system analyzes each post for traits:
- Tone
- CTA style
- Length
- Structure
- Hook style

### DNA Formation
Top-performing traits identified → become the client's **Content DNA**

### Ongoing Evolution
Future content uses DNA traits as constraints, continuously updated based on performance

## DNA System
Each client has 10–30 content traits (depending on tier):
- **Locked** — proven high-performing
- **Flexible** — experimental

System reinforces what works, experiments with what might work better.

## Tier System

| Tier | DNA Traits | Volume | Platforms |
|------|-----------|--------|-----------|
| Studio One | 10 | Lower | Single |
| Studio Pro | 20 | Multi-platform | Multi |
| Studio Max | 30 | Full automation | All + client overrides |

## Automation Triggers
- Monthly planning automation
- Manual approval (Airtable checkbox)
- Client input (email → parsed by AI)
- Immediate post trigger (Post Immediately = true)

## Repurposing Logic
High-performing posts flagged → system can rewrite, repost, or expand into new content using top DNA traits.

## Key Design Principles
- Not static → learns over time
- Not manual → automation-first
- Not generic → client-specific DNA
- Not linear → feedback-driven loop

## End Goal
Scalable, sellable product (SaaS or acquisition target) that produces high-performing content automatically and improves itself without human intervention.

## Relationship to PulseOps Consulting
PulseOps Studio is a productized offering under GH&P Business Solutions LLC, distinct from the hourly consulting work. MyChaosStudio serves as a live data collection experiment to inform Studio's social automation logic.

## Agent Architecture

### Agent Chain
`01_outline` → `02_research` → `03_draft` → `04_edit` → `05_polish` → `06_approver`

Models: Outline/Research/Edit use Haiku (cost). Draft/Polish/Approver use Sonnet (quality).

### Scenario System
Research agent decides the example mode for each post:
- **threaded**: One recurring SMB scenario (business type + situation, no named people, no named businesses) that appears in 3+ sections. Grounding for abstract advice.
- **hypothetical**: Second-person only ("if you're in this situation"). No recurring scenario.

Research outputs `scenario_mode` and `scenario_seed`. Draft, Edit, and Approver all enforce the chosen mode.

### Voice Ceiling
Target register: knowledgeable, dry, occasionally sarcastic, always useful. Client-safe but not corporate.
- **Too cold** (fail): McKinsey-speak, passive voice everywhere, no opinions — "Organizations should consider implementing..."
- **Too hot** (fail): All-caps, stacked hyperbole, exclamation clusters — "This will CHANGE EVERYTHING."
- **Target** (pass): "This isn't a productivity revolution. It's 20 minutes back on a Tuesday. That's still worth it."

Draft, Polish, and Approver all enforce this ceiling in both directions.

### Header Quality Rule
Every H2 must pass the HubSpot listicle test: if it could appear unchanged on a generic marketing blog, it fails. At least 3 H2s per post must have genuine personality (specific angle, subtle opinion, or counterintuitive framing). Enforced by Outline, Polish, and Approver.

### Hard Rules Across All Agents
- No em dashes. Ever.
- No named fictional people or businesses.
- Word count: 1,500-2,000 words (hard fail outside range).
- Internal links: 1-2 max, mid-sentence only, never forced.
- Approver DENY feedback must name the exact section or quote the specific sentence.

### Retry Logic (pipeline.py)
1. Polish → Approve
2. (denied) Polish again → Approve
3. (denied again) Rerun Draft with outline + research + approver feedback → Polish → Approve
4. (still denied) Write NEEDS_REVIEW.md and stop

## Topic Picker Pipeline (topic_picker.py → discord_bot.py → pipeline.py)
1. `topic_picker.py` fetches RSS feeds (SMB-native feeds first), asks Claude for 5 ranked topics, saves them to `runs/topic_picks/YYYY-MM-DD_topics.json`, and posts all 5 to Discord.
2. Pending topics tracked in `runs/pending_topics.txt` — loaded each run and passed to Claude to avoid duplicate suggestions. Entries removed on ✅ or ❌ react.
3. `discord_bot.py` watches for ✅ react, extracts topic + why from the message, removes topic from pending log, and fires `pipeline.py <topic> --why "<why>"`.
4. `pipeline.py` accepts `--why` and appends it to the Draft agent input as `Topic context: {why}` so the agent knows the timeliness/SMB angle.
