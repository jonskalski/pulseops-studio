#!/usr/bin/env python3
"""
PulseOps Discord Bot
Watches the topics channel for reactions and POSTs to n8n webhook.
Run permanently: python3 discord_bot.py
"""

import os
import re
import json
import requests
import discord
import sys
from bs4 import BeautifulSoup
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
WRITE_THIS_CHANNEL_ID = 1484742781514682368
N8N_WEBHOOK_URL = "https://n8n.srv1491199.hstgr.cloud/webhook/pulseops-reaction"

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"PulseOps Bot online as {client.user}")

@client.event
async def on_raw_reaction_add(payload):
    if payload.user_id == client.user.id:
        return
    if payload.channel_id != TOPICS_CHANNEL_ID:
        return

    channel = client.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)
    user = await client.fetch_user(payload.user_id)

    if user.bot:
        return

    msg = message.content
    emoji = str(payload.emoji)

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
        await message.channel.send("Couldn't parse the topic from that message.")
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
    await message.channel.send(confirms[action])

    if action == "approve":
        import subprocess
        if is_pillar:
            cmd = ["python3", "/root/pulseops-studio/pillar_planner.py", topic]
        else:
            cmd = ["python3", "/root/pulseops-studio/pipeline.py", topic, "--publish-days", "1,3"]
            if why:
                cmd += ["--why", why]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def extract_topic_from_url(url, extra_context=""):
    resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(resp.text, "html.parser")

    title = soup.find("title")
    title_text = title.text.strip() if title else ""
    meta = soup.find("meta", {"name": "description"})
    desc_text = meta.get("content", "") if meta else ""
    paragraphs = " ".join(p.get_text() for p in soup.find_all("p")[:5])

    page_content = f"Title: {title_text}\nDescription: {desc_text}\nContent: {paragraphs[:1000]}"
    if extra_context:
        page_content += f"\nUser note: {extra_context}"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 200,
            "messages": [{
                "role": "user",
                "content": f"Given this article, suggest a blog post topic for an SMB audience and a 1-2 sentence why-this-matters context.\n\nRespond in JSON only: {{\"topic\": \"...\", \"why\": \"...\"}}\n\n{page_content}"
            }]
        }
    )
    text = response.json()["content"][0]["text"]
    data = json.loads(re.search(r'\{.*\}', text, re.DOTALL).group(0))
    return data["topic"], data["why"]


@client.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id != WRITE_THIS_CHANNEL_ID:
        return

    content = message.content.strip()
    if not content:
        return

    import subprocess
    url_match = re.match(r'https?://\S+', content)

    if url_match:
        url = url_match.group(0)
        extra = content[len(url):].strip()
        await message.channel.send(f"Scraping <{url}>...")
        try:
            topic, why = extract_topic_from_url(url, extra)
        except Exception as e:
            await message.channel.send(f"Couldn't scrape that URL: {e}")
            return
    else:
        topic = content
        why = None

    await message.channel.send(f"Got it. Running pipeline for: **{topic}**")
    cmd = ["python3", "/root/pulseops-studio/pipeline.py", topic, "--publish-days", "1,3"]
    if why:
        cmd += ["--why", why]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        import threading
        def log_stderr(p):
            out = p.stderr.read()
            if out:
                print(f"[pipeline stderr] {out.decode()}", flush=True)
        threading.Thread(target=log_stderr, args=(proc,), daemon=True).start()
    except Exception as e:
        await message.channel.send(f"Failed to start pipeline: {e}")
        print(f"[pipeline launch error] {e}", flush=True)


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set")
        exit(1)
    client.run(BOT_TOKEN)
