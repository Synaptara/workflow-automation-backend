import requests

from . import register
from .base import BaseExecutor


@register("discord")
class DiscordExecutor(BaseExecutor):
    def execute(self, config: dict, context: dict) -> dict:
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            raise ValueError("Discord requires a 'webhook_url'")

        # In standard config, the key is usually 'text', but handle both based on your frontend
        content = config.get("text", config.get("content", ""))
        title = config.get("embed_title", "")
        description = config.get("embed_description", "")
        color_hex = config.get("embed_color", "000000").replace("#", "")

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
            raise ValueError(
                "Discord node failed: No content, title, or description provided."
            )

        resp = requests.post(webhook_url, json=payload, timeout=10)

        # Catch the specific API error and extract the JSON response for the UI
        if not resp.ok:
            error_message = resp.text
            try:
                error_message = resp.json().get("message", resp.text)
            except Exception:
                pass
            raise ValueError(f"Discord API Error ({resp.status_code}): {error_message}")

        return {"status": resp.status_code, "delivered": True}
