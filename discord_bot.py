#!/usr/bin/env python3
"""
PulseOps Discord Bot
Watches the topics channel for ✅ reactions and fires the pipeline.
Run permanently: python3 discord_bot.py
"""

import os
import re
import subprocess
import discord
import sys
sys.path.insert(0, "/root/pulseops-studio")
from topic_picker import remove_pending_topic

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
TOPICS_CHANNEL_ID = 1484068137547599893

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"PulseOps Bot online as {client.user}")

@client.event
async def on_reaction_add(reaction, user):
    # Ignore bot's own reactions
    if user.bot:
        return

    # Only watch the topics channel
    if reaction.message.channel.id != TOPICS_CHANNEL_ID:
        return

    msg = reaction.message.content

    if str(reaction.emoji) == "✅":
        # Extract topic and why from message format:
        # **Topic Suggestion**\n**<topic>**\n_<why>_
        topic_match = re.search(r'\*\*Topic Suggestion\*\*\n\*\*(.+?)\*\*', msg)
        if not topic_match:
            topic_match = re.search(r'\*\*(.+?)\*\*', msg)

        if not topic_match:
            await reaction.message.channel.send("Couldn't parse the topic from that message.")
            return

        topic = topic_match.group(1).strip()

        # Extract the "why" from italics line
        why_match = re.search(r'\n_(.+?)_\n', msg)
        why = why_match.group(1).strip() if why_match else None

        await reaction.message.channel.send(f"Got it. Running pipeline for: **{topic}**")
        print(f"Approved topic: {topic}")

        # Remove from pending log
        remove_pending_topic(topic)

        # Run pipeline in background, passing --why if available
        cmd = ["python3", "/root/pulseops-studio/pipeline.py", topic]
        if why:
            cmd += ["--why", why]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    elif str(reaction.emoji) == "❌":
        # Extract topic to remove from pending log
        topic_match = re.search(r'\*\*Topic Suggestion\*\*\n\*\*(.+?)\*\*', msg)
        if not topic_match:
            topic_match = re.search(r'\*\*(.+?)\*\*', msg)
        if topic_match:
            remove_pending_topic(topic_match.group(1).strip())
        await reaction.message.channel.send("Skipped.")
        print(f"Skipped topic.")

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set")
        exit(1)
    client.run(BOT_TOKEN)
