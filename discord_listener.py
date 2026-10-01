import os

import discord
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# The internal URL of your Django Universal Ingress endpoint
INGRESS_URL = "http://127.0.0.1:8000/api/ingress/discord/"

# Intents dictate which Gateway events Discord sends to your app
intents = discord.Intents.default()
intents.message_content = True  # Required to read the actual text of messages

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"Orkflo Bot connected as {client.user}")


@client.event
async def on_message(message):
    # Ignore messages sent by the bot itself to prevent infinite loops
    if message.author == client.user:
        return

    # Construct the payload to send to your Django universal ingress funnel
    payload = {
        "id": str(message.id),
        "channel_id": str(message.channel.id),
        "author_id": str(message.author.id),
        "author_name": message.author.name,
        "content": message.content,
        "guild_id": str(message.guild.id) if message.guild else None,
    }

    try:
        # Fire and forget: Push to Django in milliseconds
        response = requests.post(INGRESS_URL, json=payload, timeout=2)
        if response.status_code == 202:
            print(
                f"Successfully queued message {message.id} from channel {message.channel.id}"
            )
    except requests.RequestException as e:
        print(f"Failed to hand off event to Django: {e}")


if __name__ == "__main__":
    client.run(TOKEN)
