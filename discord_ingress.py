import asyncio
import os
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


class OrkfloDiscordIngress(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self):
        """Fired automatically when the bot starts. Binds the HTTP session to the correct event loop."""
        connector = aiohttp.TCPConnector(limit=100, keepalive_timeout=30)
        timeout = aiohttp.ClientTimeout(total=5)
        self.http_session = aiohttp.ClientSession(connector=connector, timeout=timeout)

    async def close(self):
        """Fired automatically on shutdown. Gracefully cleans up the HTTP session."""
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        await super().close()


client = OrkfloDiscordIngress(intents=intents)


async def dispatch_event(
    event_type: str, event_id: str, payload: Dict[str, Any], retries: int = 3
) -> None:
    """Dispatches payload to Django with exponential backoff for fault tolerance."""
    enriched_payload = {
        "event_type": event_type,
        "event_id": event_id,
        **payload,
    }

    for attempt in range(1, retries + 1):
        try:
            async with client.http_session.post(
                INGRESS_URL, json=enriched_payload
            ) as response:
                if response.status == 202:
                    print(
                        f"✅ Routed [{event_type}] id={event_id} to Celery", flush=True
                    )
                    return
                elif response.status == 200:
                    print(
                        f"ℹ️ Handled [{event_type}] id={event_id} (Deduplicated)",
                        flush=True,
                    )
                    return
                else:
                    body = await response.text()
                    print(
                        f"❌ Ingress rejected [{event_type}] ({response.status}): {body}",
                        flush=True,
                    )
                    # Do not retry on 4xx client errors (e.g. malformed JSON)
                    if 400 <= response.status < 500:
                        return

        except asyncio.TimeoutError:
            print(
                f"⚠️ Handoff timeout (Attempt {attempt}/{retries}) for {event_id}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"⚠️ Handoff failed (Attempt {attempt}/{retries}) for {event_id}: {exc}",
                flush=True,
            )

        if attempt < retries:
            await asyncio.sleep(2**attempt)  # Exponential backoff: 2s, 4s, 8s

    print(
        f"🛑 FATAL: Dropped event {event_id} after {retries} failed attempts.",
        flush=True,
    )


@client.event
async def on_ready():
    print(f"🔥 Orkflo Discord Ingress Online | Logged in as {client.user}", flush=True)
    print(f"📡 Routing events to {INGRESS_URL}", flush=True)


@client.event
async def on_message(message: discord.Message):
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
    event_id = f"join_{member.guild.id}_{member.id}"
    await dispatch_event("member_join", event_id, payload)


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
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


if __name__ == "__main__":
    if not TOKEN:
        print("FATAL: DISCORD_BOT_TOKEN missing from environment.", flush=True)
        sys.exit(1)

    # discord.py's client.run() automatically handles asyncio event loop setup and teardown
    client.run(TOKEN)
