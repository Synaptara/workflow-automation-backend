import requests
from decouple import config

from . import register
from .base import BaseExecutor


@register("discord")
class DiscordExecutor(BaseExecutor):
    def execute(self, app_event: str, step_config: dict, context: dict) -> dict:

        # Discord requires a BOT TOKEN to send messages, not a user OAuth token
        bot_token = config("DISCORD_BOT_TOKEN", default=None)
        if not bot_token:
            raise ValueError(
                "DISCORD_BOT_TOKEN is missing in the backend environment variables."
            )

        # Notice it says "Bot", not "Bearer"
        headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }

        if app_event == "send_message":
            channel_id = step_config.get("channel_id")
            if not channel_id:
                raise ValueError("Channel ID is required for sending a message.")

            content = step_config.get("content", "")
            title = step_config.get("embed_title", "")
            description = step_config.get("embed_description", "")
            color_hex = step_config.get("embed_color", "000000").replace("#", "")

            payload = {}
            if content:
                payload["content"] = content

            if title or description:
                try:
                    color_int = int(color_hex, 16) if color_hex else 0
                except ValueError:
                    color_int = 0

                payload["embeds"] = [
                    {
                        "title": title,
                        "description": description,
                        "color": color_int,
                    }
                ]

            if not payload:
                raise ValueError("Discord failed: No content or embed provided.")

            # Make the API call using the Bot token
            resp = requests.post(
                f"https://discord.com/api/v10/channels/{channel_id}/messages",
                headers=headers,
                json=payload,
                timeout=10,
            )

            if not resp.ok:
                error_message = resp.text
                try:
                    error_message = resp.json().get("message", resp.text)
                except Exception:
                    pass
                raise ValueError(
                    f"Discord API Error ({resp.status_code}): {error_message}"
                )

            return {
                "status": resp.status_code,
                "delivered": True,
                "message_id": resp.json().get("id"),
            }

        else:
            raise ValueError(f"Unsupported Discord event: {app_event}")
