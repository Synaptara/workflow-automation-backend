import requests

from . import register
from .base import BaseExecutor


@register("slack")
class SlackExecutor(BaseExecutor):
    """
    Requires config: {"webhook_url": str, "text": str}
    Variables like {{trigger.budget}} are already parsed by the core engine before reaching here.
    """

    def execute(self, config: dict, context: dict) -> dict:
        webhook_url = config.get("webhook_url")
        # Text is already fully injected with dynamic variables
        message_text = config.get("text", "Workflow triggered!")

        resp = requests.post(webhook_url, json={"text": message_text}, timeout=5)
        resp.raise_for_status()
        return {"status_code": resp.status_code}
