import asyncio
import os
import signal
import sys
from typing import Any, Dict

import aiohttp
import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
INTERNAL_INGRESS = "http://web:8000/api/ingress/discord/"
BASE_URL = (
    os.getenv("BACKEND_INTERNAL_URL")
    or os.getenv("BACKEND_URL")
    or os.getenv("VITE_API_URL")
)

INGRESS_URL = (
    f"{BASE_URL.rstrip('/')}/api/ingress/discord/" if BASE_URL else INTERNAL_INGRESS
)


# Setup Privileged Gateway Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

client = discord.Client(intents=intents)
session: aiohttp.ClientSession | None = None


async def get_http_session() -> aiohttp.ClientSession:
    global session
    if session is None or session.closed:
        connector = aiohttp.TCPConnector(limit=100, keepalive_timeout=30)
        timeout = aiohttp.ClientTimeout(total=4)
        session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    return session


async def dispatch_event(
    event_type: str, event_id: str, payload: Dict[str, Any]
) -> None:
    enriched_payload = {
        "event_type": event_type,
        "event_id": event_id,
        **payload,
    }

    try:
        http_client = await get_http_session()
        async with http_client.post(INGRESS_URL, json=enriched_payload) as response:
            if response.status == 202:
                print(f"✅ Routed [{event_type}] id={event_id} to Celery", flush=True)
            elif response.status == 200:
                print(
                    f"ℹ️ Handled [{event_type}] id={event_id} (Deduplicated)", flush=True
                )
            else:
                body = await response.text()
                print(
                    f"❌ Ingress rejected [{event_type}] ({response.status}): {body}",
                    flush=True,
                )
    except asyncio.TimeoutError:
        print(
            f"⚠️ Handoff timeout: Django failed to respond within limit for {event_id}",
            flush=True,
        )
    except Exception as exc:
        print(f"⚠️ Handoff failed for {event_id}: {exc}", flush=True)


@client.event
async def on_ready():
    print(f"🔥 Orkflo Discord Ingress Online | Logged in as {client.user}", flush=True)
    print(f"📡 Routing events to {INGRESS_URL}", flush=True)


@client.event
async def on_message(message: discord.Message):
    # Prevent bot-to-bot recursion loops
    if message.author.bot:
        return

    payload = {
        "channel_id": str(message.channel.id),
        "author_id": str(message.author.id),
        "author_name": message.author.name,
        "content": message.content,
        "guild_id": str(message.guild.id) if message.guild else None,
        "created_at": message.created_at.isoformat(),
    }
    await dispatch_event("new_message", str(message.id), payload)


@client.event
async def on_member_join(member: discord.Member):
    payload = {
        "author_id": str(member.id),
        "author_name": member.name,
        "guild_id": str(member.guild.id),
        "created_at": member.joined_at.isoformat() if member.joined_at else None,
    }
    # Unique composite hash for member join events
    event_id = f"join_{member.guild.id}_{member.id}"
    await dispatch_event("member_join", event_id, payload)


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # Ignore reactions by the bot itself
    if client.user and payload.user_id == client.user.id:
        return

    data = {
        "channel_id": str(payload.channel_id),
        "message_id": str(payload.message_id),
        "author_id": str(payload.user_id),
        "emoji": str(payload.emoji.name),
        "guild_id": str(payload.guild_id) if payload.guild_id else None,
    }
    event_id = f"reaction_{payload.message_id}_{payload.user_id}_{payload.emoji.name}"
    await dispatch_event("reaction_added", event_id, data)


async def shutdown():
    global session
    if session and not session.closed:
        await session.close()
    await client.close()


if __name__ == "__main__":
    if not TOKEN:
        print("FATAL: DISCORD_BOT_TOKEN missing from environment.", flush=True)
        sys.exit(1)

    try:
        client.run(TOKEN)
    finally:
        if session and not session.closed:
            try:
                asyncio.run(session.close())
            except Exception:
                pass
