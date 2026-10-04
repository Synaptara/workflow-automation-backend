import os

import requests
from django.core.cache import cache

from .models import Credential


def get_decrypted_token(user_id, service_name):
    """
    Fetches integration tokens from Redis memory.
    Only hits the DB for decryption if the cache has expired.
    """
    cache_key = f"token_{service_name}_{user_id}"
    token_data = cache.get(cache_key)

    if not token_data:
        try:
            # The database pull and decryption tax happens here
            cred = Credential.objects.get(owner_id=user_id, service=service_name)
            token_data = cred.data  # Automatically decrypted by your EncryptedJSONField

            # Cache the decrypted dictionary for 1 hour
            cache.set(cache_key, token_data, timeout=3600)
        except Credential.DoesNotExist:
            return None

    return token_data


def execute_discord_message(channel_id, message_text, embed_title=None):
    """Sends a message to a Discord channel using the bot token."""
    bot_token = os.getenv("DISCORD_BOT_TOKEN")

    if not bot_token:
        raise ValueError("Missing DISCORD_BOT_TOKEN in .env")

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"

    headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}

    # Build the payload based on your UI fields
    payload = {"content": message_text}

    if embed_title:
        payload["embeds"] = [{"title": embed_title}]

    # Fire the action!
    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 200:
        return response.json()
    else:
        raise RuntimeError(f"Discord API Error {response.status_code}: {response.text}")
