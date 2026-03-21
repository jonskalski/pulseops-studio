# TODO

## Pending
- [ ] Install glow for terminal markdown rendering
- [ ] Set up filebrowser for web-based file browsing (accessible from any device)
- [ ] Build pillar_planner.py — given a pillar topic, output cluster map (5-8 titles + keywords), feed each into pipeline.py
- [ ] Set up AdSense account (need ~6-8 weeks of consistent publishing first)
- [ ] Run topic_picker.py end-to-end to test all 5 topics posting + pending_topics.txt dedup
- [ ] Test full pipeline with --why flag passed from Discord bot
- [ ] Set up Notion databases: Pillars table + Content Ideas table (per ROADMAP.md schema)
- [ ] Create Discord #drafts channel + get webhook URL
- [ ] Create Discord #pillar-topics channel + get webhook URL
- [ ] Provide n8n URL + API key for workflow setup
- [ ] Set up rclone + Google Drive sync + cron
- [ ] Schedule topic_picker.py cron (3am EST)
- [ ] Schedule blog pipeline cron (7am EST)
- [ ] Build buffer system (10 evergreen safety posts, auto-refill logic)
- [ ] Build draft review flow (WP draft → Discord notify → ✅/❌/🔁 → publish or fallback)
- [ ] Build 8pm approval reminder (n8n)
- [ ] Build pillar brief flow (#pillar-topics → Claude brief → ✅ → Notion)

## Completed
- [x] Expand voice target examples in 03_draft.md and 05_polish.md to 10 examples, add coffee-test sentence, flag competent-but-bland as fail in Polish agent | completed: 2026-03-19 | discord_sent: true
- [x] Post all 5 topics to Discord from topic_picker.py | completed: 2026-03-19 | discord_sent: true
- [x] Save all 5 topic picks to runs/topic_picks/ JSON | completed: 2026-03-19 | discord_sent: true
- [x] Add pending_topics.txt dedup log | completed: 2026-03-19 | discord_sent: true
- [x] Add SMB-first RSS feeds to topic_picker.py | completed: 2026-03-19 | discord_sent: true
- [x] Add --why flag to pipeline.py | completed: 2026-03-19 | discord_sent: true
- [x] 3-attempt escalating retry logic in pipeline.py | completed: 2026-03-19 | discord_sent: true
- [x] Overhaul all 6 agent prompts (scenario system, voice ceiling, header quality, approver checks) | completed: 2026-03-19 | discord_sent: true
- [x] Add CHANGELOG.md step to /summarize skill | completed: 2026-03-19 | discord_sent: true
- [x] Add TODO.md + Discord TODO channel to /summarize skill | completed: 2026-03-19 | discord_sent: true
- [x] Wire DISCORD_TODO_WEBHOOK_URL to settings.json | completed: 2026-03-19 | discord_sent: true
