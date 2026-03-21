#!/usr/bin/env python3
"""
PulseOps Discord Bot
Watches the topics channel for reactions and POSTs to n8n webhook.
Run permanently: python3 discord_bot.py
"""

import os
import re
import requests
import discord
import sys
sys.path.insert(0, "/root/pulseops-studio")
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
from topic_picker import remove_pending_topic
try:
    from airtable.client import mark_approved, mark_skipped, mark_regenerate
    airtable_enabled = True
except Exception:
    airtable_enabled = False

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
TOPICS_CHANNEL_ID = 1484068137547599893
N8N_WEBHOOK_URL = "https://n8n.srv1491199.hstgr.cloud/webhook/pulseops-reaction"

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"PulseOps Bot online as {client.user}")

@client.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    if reaction.message.channel.id != TOPICS_CHANNEL_ID:
        return

    msg = reaction.message.content
    emoji = str(reaction.emoji)

    if emoji not in ("✅", "❌", "🔁"):
        return

    is_pillar = "**Pillar Suggestion**" in msg

    if is_pillar:
        name_match = re.search(r'\*\*Pillar Suggestion\*\*\n\*\*(.+?)\*\*', msg)
    else:
        name_match = re.search(r'\*\*Topic Suggestion\*\*\n\*\*(.+?)\*\*', msg)
        if not name_match:
            name_match = re.search(r'\*\*(.+?)\*\*', msg)

    if not name_match:
        await reaction.message.channel.send("Couldn't parse the topic from that message.")
        return

    topic = name_match.group(1).strip()
    why_match = re.search(r'\n_(.+?)_\n', msg)
    why = why_match.group(1).strip() if why_match else None

    action_map = {"✅": "approve", "❌": "skip", "🔁": "regenerate"}
    action = action_map[emoji]

    if not is_pillar and action in ("skip", "regenerate"):
        remove_pending_topic(topic)

    if airtable_enabled:
        try:
            if is_pillar:
                from airtable.client import _get, _update, TABLE_PILLARS
                records = _get(TABLE_PILLARS, {"filterByFormula": f'LOWER({{Name}}) = LOWER("{topic}")'})
                if records:
                    if action == "approve":
                        _update(TABLE_PILLARS, records[0]["id"], {"Status": "Planning"})
                    elif action == "skip":
                        _update(TABLE_PILLARS, records[0]["id"], {"Status": "Rejected"})
            else:
                if action == "approve":
                    mark_approved(topic)
                elif action == "skip":
                    mark_skipped(topic)
                elif action == "regenerate":
                    mark_regenerate(topic)
        except Exception as e:
            print(f"Airtable update failed: {e}")

    if is_pillar:
        confirms = {"approve": f"Got it. Building cluster map for: **{topic}**", "skip": "Skipped.", "regenerate": "Skipped."}
    else:
        confirms = {"approve": f"Got it. Running pipeline for: **{topic}**", "skip": "Skipped.", "regenerate": f"Requeued: **{topic}**"}
    await reaction.message.channel.send(confirms[action])

    if action == "approve":
        import subprocess
        if is_pillar:
            cmd = ["python3", "/root/pulseops-studio/pillar_planner.py", topic]
        else:
            cmd = ["python3", "/root/pulseops-studio/pipeline.py", topic]
            if why:
                cmd += ["--why", why]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set")
        exit(1)
    client.run(BOT_TOKEN)
