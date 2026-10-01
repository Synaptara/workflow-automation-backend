import asyncio
import os

import aiohttp
import discord
from dotenv import load_dotenv

# Load your local .env file
load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# Routing to your local Django server
INGRESS_URL = "http://127.0.0.1:8000/api/ingress/discord/"

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"🔥 Orkflo Discord Ingress Online | Logged in as {client.user}")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    payload = {
        "event_id": str(message.id),
        "channel_id": str(message.channel.id),
        "author_id": str(message.author.id),
        "author_name": message.author.name,
        "content": message.content,
        "guild_id": str(message.guild.id) if message.guild else None,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(INGRESS_URL, json=payload, timeout=2) as response:
                if response.status == 202:
                    print(f"✅ Routed msg {message.id} to Celery queue")
                else:
                    text = await response.text()
                    print(f"❌ Ingress rejected: {response.status} - {text}")
    except asyncio.TimeoutError:
        print(f"⚠️ Handoff timeout: Django took too long to acknowledge {message.id}")
    except Exception as e:
        print(f"⚠️ Handoff failed: {e}")


if __name__ == "__main__":
    if not TOKEN:
        print("FATAL: DISCORD_BOT_TOKEN missing from local .env")
    else:
        client.run(TOKEN)
