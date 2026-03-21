# PulseOps Studio — Roadmap

_Living planning doc. Update freely._

---

## Content Strategy

### Content Types
| Type | Description | Expiration |
|---|---|---|
| Hot Topic | Timely, news-hooked post | 48-72 hrs from suggestion |
| Cluster | Evergreen post under a Pillar | None |
| Pillar | Anchor post, generated after clusters are ready | None |
| Buffer | Standalone evergreen fallback post, no pillar dependency | None |
| Standalone | One-off post, no parent pillar | None |

### Content Status Flow
```
Suggested → Approved → In Queue → Draft Ready → Published
                                              ↘ Rejected (topic killed)
                                              ↘ Regenerate → In Queue → Draft Ready → ...
                                              ↘ Expired (hot topics only, after 48-72hrs)
```

- **Rejected** — topic killed, won't run again
- **Regenerate** — topic is fine, execution failed. Requeued for a fresh pipeline run. Triggered by:
  - 🔁 react on Discord draft notification
  - Manual status flip in Airtable
  - Automatic: if post hits NEEDS_REVIEW after all retries, auto-flip to Regenerate
- **Expired** — hot topics only, window closed

### Pillar → Cluster Model
- You inject a Pillar topic via `#pillar-topics` Discord channel
- System generates a brief + 20 cluster topic suggestions (grouped by angle)
- You react ✅ to approve the pillar → written to Airtable
- You approve individual clusters in Airtable
- Clusters publish on cadence (2-3/week per pillar, rotate between active pillars)
- You manually flip `Generate Pillar` checkbox when cluster set feels complete
- Pillar post drops, interlinks all published clusters
- _Future: tie pillar trigger to cluster performance metrics_

### Buffer System
- Target: **10 approved WP drafts** in buffer at all times
- Buffer posts are simple, standalone evergreen SMB topics — no pillar, no trend dependency
- Morning pipeline checks buffer count → auto-generates to top back up to 10 if below
- When a scheduled post is rejected or times out unapproved → oldest buffer post slots in for tomorrow, Discord notified
- Buffer topics generated from a standing evergreen prompt pool, e.g.:
  - "5 things to automate this week"
  - "Why your follow-up emails aren't getting replies"
  - "How to write an SOP in an afternoon"
  - "What to track in your first CRM"
  - "When to hire vs. automate"

### Suggested Pillar Topics (seed list)
- CRM Basics (what is a CRM, what is a lead, what is a contact, HubSpot basics, Salesforce basics, how to pick a CRM...)
- Sales Pipeline Basics
- Business Automation 101
- Email Marketing for SMBs
- Hiring & Onboarding
- Finance & Invoicing Automation
- Customer Support Automation
- Reporting & Dashboards for SMBs

---

## Airtable Schema

### Pillars Table
| Field | Type | Notes |
|---|---|---|
| Name | Text | e.g. "CRM Basics" |
| Status | Select | Planning → Active → Ready → Published |
| Target Clusters | Number | Default 20 |
| Clusters Published | Rollup | Count from Clusters table |
| Generate Pillar | Checkbox | You flip when ready |
| Pillar Post URL | Text | WP URL after publish |

### Content Ideas Table
| Field | Type | Notes |
|---|---|---|
| Topic | Text | |
| Type | Select | Hot / Cluster / Pillar / Buffer / Standalone |
| Parent Pillar | Link → Pillars | Null for Hot/Buffer/Standalone |
| Status | Select | Suggested → Approved → In Queue → Draft Ready → Published / Rejected / Regenerate / Expired |
| Priority | Select | High / Normal / Low |
| Publish Date | Date | Date only — pipeline runs morning of |
| Expires At | Date | Hot topics only — auto-flip to Expired after 48-72hrs |
| Why | Text | Timeliness hook (hot topics) or angle note |
| WP Post ID | Text | After publish |
| WP Post URL | Text | After publish |
| Regen Count | Number | How many times regenerated — flag if > 2 |

---

## Pipeline & Automation

### Current State
- [x] Blog pipeline working (01_outline → 02_research → 03_draft → 04_edit → 05_polish → 06_approver)
- [x] Hot topic picker (topic_picker.py) — manual trigger
- [x] Discord bot watching ✅/❌ reactions → fires pipeline
- [x] 3-attempt escalating retry logic
- [x] NEEDS_REVIEW.md fallback

### Scheduling (all times EST)
| Job | Cron | Notes |
|---|---|---|
| topic_picker.py | `0 3 * * *` | 3am EST — topics ready when you wake up |
| Blog pipeline (generate) | `0 7 * * *` | 7am EST — generates posts for Publish Date = tomorrow, saves to WP as draft |
| Blog pipeline (publish) | `0 7 * * *` | 7am EST — publishes approved posts where Publish Date = today |
| Buffer top-up check | `0 7 * * *` | 7am EST — if buffer < 10, generate to refill |
| Approval reminder | `0 20 * * *` | 8pm EST — ping Discord if draft still unapproved |
| Hot topic expiration check | `0 3 * * *` | 3am EST — flip Suggested → Expired after 48-72hrs |

### Draft Review Flow
1. Pipeline generates post day before Publish Date → saves to WordPress as **draft**
2. Discord notification to `#drafts`: title, slug, intro preview + ✅ approve / ❌ reject / 🔁 regenerate
3. ✅ → status `Draft Ready` → morning pipeline publishes
4. ❌ → status `Rejected` → slot filled from buffer, Discord notified
5. 🔁 → status `Regenerate` → requeued for fresh pipeline run
6. No react by 8pm → reminder sent: "[title] publishes tomorrow. Still needs approval."
7. No react by publish time → slot filled from buffer silently

### Buffer Fallback Logic
1. Scheduled post rejected or unapproved at publish time → pull oldest Buffer post
2. Slot it in for tomorrow
3. Discord: "[original title] skipped. [buffer title] queued for tomorrow — needs approval by 8pm."
4. Morning pipeline checks buffer count → auto-generates to refill to 10

### n8n Migration (replace discord_bot.py)
- Discord reaction trigger node (watches topic + drafts channels)
- Switch on ✅ / ❌ / 🔁
- Execute Command node → SSH → `pipeline.py <topic> --why "..."`
- Discord node posts result back
- _Benefit: modify trigger logic without touching Python_

### Pillar Brief Flow (`#pillar-topics` channel)
1. You post a pillar idea in Discord
2. n8n catches it → calls Claude → generates brief (pitch + 20 cluster suggestions grouped by angle)
3. Brief posted back to Discord — tight enough to read in 30 seconds on mobile
4. ✅ → pillar + clusters written to Airtable as Suggested
5. You approve/trim clusters in Airtable
6. Pipeline picks up Approved clusters on cadence

---

## Social (Planned — Not Built)

### Trigger
Post-publish: `Published` status → generate social variants → schedule drip

### Platform Voices
| Platform | Register |
|---|---|
| LinkedIn | Thoughtful, professional, slightly opinionated |
| Twitter/X | Punchy, blunt, one strong point |
| Facebook | Warmer, conversational, community-focused |

### Social Post Fields (future Airtable table)
- Parent Blog Post (link)
- Platform
- Copy
- Link
- Scheduled DateTime (full timestamp — platform timing matters)
- Status (Scheduled / Posted)

### Social Scheduler
n8n workflow on hourly cron — checks for social posts where `Scheduled DateTime <= now`, fires to platform APIs.

---

## Metrics (Future)

### Blog
- Impressions, clicks, avg position (Search Console)
- Time on page

### Social
- Reach, engagement rate, click-throughs back to post

### DNA Signal
- Which platform drives most blog traffic per post
- Which voice traits correlate with engagement
- Feeds back into Content DNA evolution
- _Future: tie pillar generation trigger to cluster performance thresholds_

---

## Infrastructure & Ops

### Backup (Pending)
- [ ] Install and configure rclone on VPS
- [ ] Authenticate with Google Drive
- [ ] Set up daily sync: `/root/pulseops-studio`, `/root/megabrain`, `/root/.claude` → Google Drive
- [ ] Cron it (run after overnight jobs complete)

---

## Open Questions
_None currently. Social platform decisions deferred until social layer is built._

## Decisions Made
- Max concurrent active pillars: **3**. Add a 4th when the first pillar nears completion.
- Social rollout order: decided when social is built.
- Database: **Airtable**. Setup script written and deployed by Claude via API — no manual table creation. Jon provides API key + Base ID.
- Database setup checklist:
  - [ ] Jon creates empty Airtable base, provides Base ID (`appXXXXXXXXXXXXXX`)
  - [ ] Jon provides Airtable API key (Personal Access Token)
  - [ ] Claude runs setup script → creates Pillars + Content Ideas tables with all fields
  - [ ] Script outputs table IDs → stored in settings.json for pipeline use
