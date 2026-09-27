import requests
from .base import BaseExecutor
from . import register

@register("discord")
class DiscordExecutor(BaseExecutor):
    def execute(self, config: dict, context: dict) -> dict:
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            raise ValueError("Discord integration requires a 'webhook_url'")

        content = config.get("content", "")
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

            payload["embeds"] = [{
                "title": title,
                "description": description,
                "color": color_int,
            }]

        resp = requests.post(webhook_url, json=payload)
        resp.raise_for_status()
        
        return {"status": resp.status_code, "delivered": True}