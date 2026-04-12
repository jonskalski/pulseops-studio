# PulseOps Studio — System Map

_How the whole thing works: what runs, when, where, and why._

---

## Overview

```
RSS Feeds ──► topic_picker.py ──► Discord #topics ──► discord_bot.py ──► pipeline.py ──► WordPress
                                                                      └──► pillar_planner.py ──► Airtable Clusters

You (phone/Discord) ──► #write-this (topic or URL) ──► discord_bot.py ──► pipeline.py ──► WordPress

pillar_suggester.py ──► Discord #topics ──► discord_bot.py ──► pillar_planner.py ──► Airtable Clusters
```

---

## Scripts

### `topic_picker.py`
| | |
|---|---|
| **What** | Scrapes RSS feeds, asks Claude to pick 5 strong blog topics, posts to Discord for approval |
| **When** | Manual or cron (3am EST — not yet scheduled) |
| **Trigger** | Manual: `python3 topic_picker.py` |
| **Reads** | 10 RSS feeds (Zapier, HubSpot, SmallBizTrends, SEJ, VentureBeat, TechCrunch, etc.) |
| **Reads** | WordPress published posts (dedup) |
| **Reads** | `runs/pending_topics.txt` (dedup against already-pending suggestions) |
| **Writes** | `runs/topic_picks/YYYY-MM-DD_topics.json` (all 5 picks saved) |
| **Writes** | `runs/pending_topics.txt` (appends each topic to track pending) |
| **Writes** | Discord `#topics` via `DISCORD_TOPICS_WEBHOOK_URL` (5 separate messages) |
| **Writes** | Airtable Content Ideas (Status: Suggested) |
| **Why** | Keeps a fresh queue of relevant, non-duplicate topics without manual research |

---

### `discord_bot.py`
| | |
|---|---|
| **What** | Persistent bot: watches reactions in #topics + messages in #write-this |
| **When** | Always running as background process (logged to /var/log/pulseops-bot.log) |
| **Heartbeat** | Pings Uptime Kuma push monitor every 60s — monitor at status.srv1491199.hstgr.cloud |
| **Trigger 1** | ✅ / ❌ / 🔁 reactions in `#topics` channel |
| **Trigger 2** | Any message in `#write-this` channel (channel ID: 1484742781514682368) |
| **Reads** | Discord message content (parses topic/pillar name + why from message format) |
| **Writes** | Fires `pipeline.py <topic> --why "..."` on ✅ Topic Suggestion or #write-this message |
| **Writes** | Fires `pillar_planner.py "<pillar>"` on ✅ Pillar Suggestion |
| **Writes** | Airtable Content Ideas: mark_approved / mark_skipped / mark_regenerate |
| **Writes** | Airtable Pillars: Planning (on ✅) / Rejected (on ❌) |
| **Writes** | `runs/pending_topics.txt` (removes topic on ❌ or 🔁) |
| **Why** | Mobile-first: react to suggestions or drop a topic/URL in #write-this from your phone |
| **#write-this** | Plain text = topic. URL = bot scrapes page, Claude extracts SMB topic + why, fires pipeline. Optional note after URL adds context. |

---

### `pipeline.py`
| | |
|---|---|
| **What** | 6-agent Claude pipeline: outline → research → draft → edit → polish → approve → publish |
| **When** | Triggered by discord_bot.py on ✅ reaction, or manual |
| **Trigger** | `python3 pipeline.py "Topic Here" [--why "context"] [--pillar "Pillar Name"] [--publish-days "0,2,4"]` |
| **Reads** | All 6 agent prompt files in `agents/` |
| **Reads** | `published_posts_index.json` (local topic-aware index for internal linking) |
| **Reads** | WordPress published posts (supplemental, fills gaps not in local index) |
| **Reads** | Pexels API (featured image) |
| **Writes** | WordPress: creates post as `future` status, scheduled to next open 9am EST slot on allowed days |
| **Writes** | WordPress content includes JSON-LD schema markup (Article/HowTo/FAQPage auto-detected) |
| **Writes** | Airtable Content Ideas: mark_published (Status: Published, WP Post ID, WP Post URL) |
| **Writes** | `published_posts_index.json`: appends entry (title, url, slug, topic, date) after each publish |
| **Writes** | Discord `DISCORD_WEBHOOK_URL`: step-by-step progress + cannibalization warnings |
| **Writes** | `runs/NEEDS_REVIEW.md` if all 3 attempts fail approval |
| **Pillar mode** | `--pillar` flag enables voice consistency: queries Airtable for published sibling clusters, reads their `05_polish.json` intros, injects as voice/terminology reference into Draft agent |
| **Why** | Core content engine — turns a topic into a published WordPress post |

**Retry logic:** Attempt 1 (Polish→Approve) → Attempt 2 (Polish again→Approve) → Attempt 3 (Rerun Draft with feedback→Polish→Approve) → NEEDS_REVIEW

**Model strategy:** Haiku for steps 1-4 (cheap/fast), Sonnet for steps 5-6 (quality)

---

### `pillar_suggester.py`
| | |
|---|---|
| **What** | Asks Claude to suggest 5 new content pillars based on site niche and existing pillars |
| **When** | Manual or cron (weekly — not yet scheduled) |
| **Trigger** | `python3 pillar_suggester.py` |
| **Reads** | Airtable Pillars table (existing pillar names — avoids duplicates) |
| **Writes** | Discord `DISCORD_WEBHOOK_URL` (5 Pillar Suggestion messages) |
| **Writes** | Airtable Pillars (Status: Suggested, with Summary) |
| **Why** | Keeps a pipeline of new content territory without manual brainstorming |

---

### `pillar_planner.py`
| | |
|---|---|
| **What** | Given a pillar topic, generates 20+ cluster post titles grouped by angle |
| **When** | Triggered by discord_bot.py on ✅ Pillar Suggestion, or manual |
| **Trigger** | `python3 pillar_planner.py "Pillar Topic Here"` |
| **Reads** | Nothing (Claude generates from topic + system prompt) |
| **Writes** | Airtable Pillars: creates Pillar record (Status: Planning) |
| **Writes** | Airtable Clusters: creates 20+ Cluster records (Status: Suggested) |
| **Writes** | Airtable Pillars: updates Clusters Created count via sync_pillar_stats() |
| **Writes** | Discord `DISCORD_WEBHOOK_URL` (pillar brief with all cluster titles) |
| **Why** | Builds out the content map for a pillar in one shot — 20 posts planned instantly |

---

### `airtable/client.py`
| | |
|---|---|
| **What** | Shared Airtable client used by all scripts |
| **Tables** | Content Ideas, Pillars, Clusters, Social Posts, Rejected Posts |
| **Key functions** | `create_suggested`, `mark_approved`, `mark_skipped`, `mark_regenerate`, `mark_published` |
| **Key functions** | `create_cluster`, `mark_cluster_published`, `sync_pillar_stats` |
| **Key functions** | `log_rejected_post`, `get_force_publish_records`, `get_rewrite_records`, `update_rejected_status` |
| **Key functions** | `get_published_clusters_for_pillar` — returns published cluster records for a pillar (used by pipeline voice context) |
| **Why** | Single source of truth for all Airtable reads/writes — no duplication across scripts |

---

## Airtable Tables

| Table | Purpose | Key Status Values |
|---|---|---|
| **Content Ideas** | All blog post topics (hot, standalone, cluster) | Suggested → Approved → In Queue → Published / Rejected / Regenerate |
| **Pillars** | Top-level content pillars | Suggested → Planning → Active → Ready → Published / Rejected |
| **Clusters** | Individual posts under a pillar | Suggested → Approved → Published |
| **Social Posts** | Social variants after publish | Scheduled → Posted _(not yet built)_ |
| **Rejected Posts** | Posts that failed all 3 approval attempts | Needs Review → Force Publish → Published (Forced) / Rewrite → Rewriting... → Published (Rewrite) |

---

## Discord Channels & Webhooks

| Channel | Webhook Env Var | What posts there |
|---|---|---|
| `#daily-topics` | `DISCORD_TOPICS_WEBHOOK_URL` | Topic suggestions (topic_picker.py) |
| `#pillar-post-suggestions` | `DISCORD_PILLAR_WEBHOOK_URL` | Pillar suggestions + cluster maps (pillar_suggester.py, pillar_planner.py) |
| `#drafts` | `DISCORD_DRAFTS_WEBHOOK_URL` | Pipeline publish notifications, Force Publish confirmations |
| `#general` or main | `DISCORD_WEBHOOK_URL` | Errors, alerts, fallback |
| `#todo` | `DISCORD_TODO_WEBHOOK_URL` | Completed + pending TODO items (from /summarize) |

**Bot token:** `DISCORD_BOT_TOKEN` — watches `#topics` (channel ID: `1484068137547599893`) for reactions

---

## Cron Schedule

| Job | Schedule | Status |
|---|---|---|
| `topic_picker.py` | `0 7 * * *` | Active (7am UTC = 3am EST) — posts to Discord for Tue/Thu approval |
| `pillar_suggester.py` | `0 13 * * 1` | Active (1pm UTC = 9am EST Mon) |
| `force_publish.py --poll` | `*/5 * * * *` | Active (every 5 min) |
| `cluster_writer.py` | `0 7 * * 1,3,6` | Active (Sat/Mon/Wed 7am UTC — publishes Mon/Wed/Fri) |
| Buffer top-up | `0 7 * * 1-5` | Not built |
| Approval reminder | `0 20 * * 1-5` | Not built |

---

## Data Flow: Topic → Published Post

```
1. topic_picker.py scrapes RSS → Claude picks 5 topics
2. Topics posted to Discord #topics + saved to Airtable (Suggested)
3. You react ✅ on Discord (from phone or desktop)
4. discord_bot.py catches reaction → fires pipeline.py
5. pipeline.py checks published_posts_index.json for keyword cannibalization — warns Discord if overlap
6. pipeline.py runs 6-agent chain → generates post (includes featured snippet, semantic keywords, FAQ section, schema markup)
7. Post auto-scheduled to next open 9am EST slot on WordPress (with JSON-LD schema appended)
8. published_posts_index.json updated with new post entry
9. Airtable Content Ideas updated: Published + WP URL
10. Discord notified with post link
```

## Data Flow: Pillar → Cluster Map

```
1. pillar_suggester.py asks Claude for 5 pillar ideas
2. Pillar Suggestions posted to Discord + saved to Airtable (Suggested)
3. You react ✅ on Discord
4. discord_bot.py catches reaction → fires pillar_planner.py
5. pillar_planner.py generates 20+ cluster titles grouped by angle
6. Pillar record created in Airtable (Planning) + 20 Cluster records (Suggested)
7. Pillar brief posted to Discord
8. cluster_writer.py runs Sat/Mon/Wed at 7am UTC — pulls next Suggested cluster, fires pipeline with --pillar and --publish-days 0,2,4 (Mon/Wed/Fri)
8a. pipeline.py loads published sibling clusters from Airtable → reads their 05_polish.json → injects voice/terminology reference into Draft agent
9. Post lands as WP draft, Discord notifies #drafts for review
10. NOTE: cluster_writer.py needs rebuild for full batch mode (write all pillar clusters at once)
```

---

## File Structure

```
/root/pulseops-studio/
├── pipeline.py              # Core content pipeline
├── topic_picker.py          # Topic suggestion + Discord posting
├── pillar_planner.py        # Cluster map generator
├── pillar_suggester.py      # Pillar suggestion + Discord posting
├── discord_bot.py           # Reaction-based approval bot
├── agents/
│   ├── 01_outline.md        # Outline agent prompt
│   ├── 02_research.md       # Research agent prompt
│   ├── 03_draft.md          # Draft agent prompt
│   ├── 04_edit.md           # Edit agent prompt
│   ├── 05_polish.md         # Polish agent prompt
│   └── 06_approver.md       # Approver agent prompt
├── airtable/
│   └── client.py            # Shared Airtable client
├── published_posts_index.json  # Local index: title/url/slug/topic per published post
├── runs/                    # Runtime outputs (gitignored)
│   ├── pending_topics.txt   # Topics currently pending in Discord
│   └── topic_picks/         # Daily topic pick JSON files
├── .env                     # All secrets (gitignored)
├── SYSTEM.md                # This file
├── ROADMAP.md               # Strategic decisions + future plans
├── CHANGELOG.md             # Human-readable change log
└── TODO.md                  # Pending + completed task list
```

---

## Environment Variables (stored in `.env`)

| Variable | Used By | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | pipeline.py, pillar_planner.py, pillar_suggester.py, topic_picker.py | Claude API calls |
| `AIRTABLE_API_KEY` | airtable/client.py | Airtable access |
| `AIRTABLE_BASE_ID` | airtable/client.py | Which Airtable base |
| `AIRTABLE_CONTENT_IDEAS_TABLE_ID` | airtable/client.py | Content Ideas table |
| `AIRTABLE_PILLARS_TABLE_ID` | airtable/client.py | Pillars table |
| `AIRTABLE_CLUSTERS_TABLE_ID` | airtable/client.py | Clusters table |
| `AIRTABLE_SOCIAL_POSTS_TABLE_ID` | airtable/client.py | Social Posts table |
| `WP_URL` | pipeline.py | WordPress site URL |
| `WP_USER` | pipeline.py | WordPress username |
| `WP_APP_PASSWORD` | pipeline.py | WordPress Application Password |
| `PEXELS_API_KEY` | pipeline.py | Featured image fetching |
| `DISCORD_BOT_TOKEN` | discord_bot.py | Bot authentication |
| `DISCORD_WEBHOOK_URL` | pipeline.py, pillar_planner.py, pillar_suggester.py | General Discord channel |
| `DISCORD_TOPICS_WEBHOOK_URL` | topic_picker.py | Topics channel |
| `DISCORD_TODO_WEBHOOK_URL` | /summarize skill | TODO channel |
| `NOTION_API_KEY` | /summarize skill | Session logging |
